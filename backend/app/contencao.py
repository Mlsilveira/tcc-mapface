"""Quanto esforço a porta da frente aceita gastar: tentativas e trabalho em voo.

Como `app/presenca.py` e `app/sessoes.py`, este módulo não conhece HTTP: ele
conta e responde sim ou não. Quem traduz o "não" em 429 é
`app/routers/auth.py` — a mesma divisão que mantém as regras testáveis sem
subir um cliente.

**Os dois problemas são diferentes e por isso são dois mecanismos.**

*Adivinhação de senha* é um problema por conta: mil tentativas contra uma conta,
espalhadas ao longo do dia, não derrubam nada e ainda assim entram. O que o
limita é contar tentativas **por e-mail** dentro de uma janela
(`JanelaDeTentativas`).

*Esgotamento de CPU* é um problema por instante: os endpoints de login e
registro são `def` síncronos, então rodam no threadpool de 40 threads do
FastAPI, e cada um paga um bcrypt cost 12 (~300 ms de CPU) antes de responder.
Algumas dezenas de chamadas simultâneas ocupam as threads; `/pronto` é síncrono
e divide o mesmo pool, fica na fila, estoura o timeout da sonda — e o
orquestrador recicla uma task **sã**, derrubando a sessão de estudo de todo
mundo ao mesmo tempo, inclusive no meio da apresentação. O que limita isso é um
teto de trabalho **em voo** (`TrabalhoSimultaneo`), e ele precisa recusar na
hora em vez de esperar por vaga: esperar seguraria a thread, que é exatamente o
recurso que se está tentando preservar.

**Por que em memória, e não `slowapi` ou Redis.** Duas razões, e a segunda é uma
condição, não uma preferência:

1. `slowapi` resolveria o primeiro problema e não o segundo, traria `limits` e
   um middleware novo a poucos dias da defesa, e ainda assim deixaria a decisão
   difícil na nossa mão — a chave. O default dele é o IP do cliente, e atrás de
   um balanceador o IP de toda a turma é o mesmo IP: um limite por IP ou pune a
   turma junta ou depende de confiar num cabeçalho `X-Forwarded-For` que, sem
   proxy configurado, qualquer cliente escreve. Nada disso é culpa da
   biblioteca; é que a parte difícil não é contar.
2. **Estado em memória só é correto porque a topologia é de uma instância.** É a
   mesma premissa que o README declara em "Limites conhecidos" para a baseline
   de `app/analista.py`, e vale aqui pelo mesmo motivo: com duas tasks, cada uma
   conta metade das tentativas e o limite efetivo dobra silenciosamente, sem
   nada quebrar de um jeito visível. **No dia em que houver duas instâncias,
   este módulo precisa de um contador compartilhado** (Redis, ou uma tabela) —
   não é uma otimização adiada, é uma condição de corretude anotada.
"""
import threading
from contextlib import contextmanager
from datetime import timedelta
from typing import Dict, Iterator, List

from app.config import settings
from app.tempo import agora_utc

#: A partir de quantas chaves distintas a janela varre as expiradas. Existe
#: porque a chave é escolhida por quem chama de fora: uma varredura com e-mails
#: inventados criaria uma entrada por e-mail, e um dicionário que só cresce é um
#: vazamento de memória com outro nome. Varrer a cada chamada seria O(n) por
#: requisição; varrer quando o dicionário passa do teto é O(n) a cada n
#: inserções, que é o mesmo trabalho diluído.
CHAVES_ANTES_DA_LIMPEZA = 2048


class JanelaDeTentativas:
    """Conta tentativas por chave dentro de uma janela deslizante.

    **Janela deslizante com os instantes guardados**, e não um contador que zera
    de tempos em tempos. O contador com reset periódico é mais barato e tem um
    defeito conhecido: nos segundos em volta do reset cabem duas janelas cheias
    de tentativas seguidas, que é o dobro do limite que alguém leu na
    configuração. Guardar os instantes custa uma lista curta por chave — o
    limite é dez — e faz o número configurado ser verdade em qualquer recorte de
    cinco minutos.

    A trava existe porque os endpoints são síncronos e rodam em threads
    diferentes do mesmo pool: sem ela, duas tentativas simultâneas leem a mesma
    lista e as duas passam.
    """

    def __init__(self, chaves_antes_da_limpeza: int = CHAVES_ANTES_DA_LIMPEZA) -> None:
        self._instantes: Dict[str, List[float]] = {}
        self._trava = threading.Lock()
        self._chaves_antes_da_limpeza = chaves_antes_da_limpeza

    def _janela(self) -> timedelta:
        return timedelta(minutes=settings.janela_de_tentativas_minutos)

    def cobrar(self, chave: str) -> bool:
        """Registra uma tentativa desta chave e diz se ela ainda cabe no limite.

        A tentativa é contada **mesmo quando é recusada**: quem está varrendo não
        ganha a janela de volta por insistir, e é isso que impede que o limite
        vire um teto de 10 a cada 5 minutos *bem-sucedidos* com quantas
        recusadas o atacante quiser no meio.
        """
        agora = agora_utc().timestamp()
        piso = agora - self._janela().total_seconds()

        with self._trava:
            if len(self._instantes) > self._chaves_antes_da_limpeza:
                self._esquecer_expiradas(piso)

            recentes = [
                instante for instante in self._instantes.get(chave, []) if instante > piso
            ]
            recentes.append(agora)
            self._instantes[chave] = recentes
            return len(recentes) <= settings.tentativas_de_autenticacao

    def perdoar(self, chave: str) -> None:
        """Apaga o histórico desta chave — usado quando a autenticação dá certo.

        Sem isto o aluno que erra a senha algumas vezes ao longo da manhã, acerta
        e volta a errar à tarde acumularia as tentativas de um dia inteiro e
        levaria 429 no meio de uma sessão de estudo. O limite existe contra quem
        **não** consegue entrar; acertar a senha é a prova de que não é o caso.
        """
        with self._trava:
            self._instantes.pop(chave, None)

    def esquecer_tudo(self) -> None:
        """Estado zerado. Existe para os testes, pelo mesmo motivo que o registro
        de analistas é recriado a cada um: isto é estado de processo, e um teste
        que herdasse as tentativas do anterior passaria ou falharia por causa
        dele."""
        with self._trava:
            self._instantes.clear()

    def _esquecer_expiradas(self, piso: float) -> None:
        """Descarta as chaves cuja tentativa mais recente já saiu da janela."""
        self._instantes = {
            chave: instantes
            for chave, instantes in self._instantes.items()
            if instantes and instantes[-1] > piso
        }


class TrabalhoSimultaneo:
    """Teto de quantas operações caras podem estar acontecendo ao mesmo tempo.

    Um semáforo escrito à mão em vez de `threading.Semaphore` porque o que se
    quer aqui é justamente o que um semáforo não oferece bem: **não esperar**.
    `Semaphore.acquire(blocking=False)` faria o serviço, mas o par
    `ocupar`/`liberar` com um inteiro visível diz em duas linhas o que está
    sendo contado, e `em_voo` é observável num teste sem tocar no interior do
    objeto.
    """

    def __init__(self) -> None:
        self._em_voo = 0
        self._trava = threading.Lock()

    @property
    def em_voo(self) -> int:
        return self._em_voo

    def ocupar(self) -> bool:
        """Toma uma vaga, ou devolve `False` de imediato se não houver."""
        with self._trava:
            if self._em_voo >= settings.autenticacoes_simultaneas:
                return False
            self._em_voo += 1
            return True

    def liberar(self) -> None:
        with self._trava:
            self._em_voo = max(0, self._em_voo - 1)

    def esquecer_tudo(self) -> None:
        with self._trava:
            self._em_voo = 0


#: Estado de processo, como o registro de analistas. Módulo-nível de propósito:
#: o limite precisa valer entre requisições, e uma instância por requisição não
#: limitaria nada.
tentativas = JanelaDeTentativas()
autenticacoes = TrabalhoSimultaneo()


@contextmanager
def vaga_de_autenticacao() -> Iterator[bool]:
    """Ocupa uma vaga pelo bloco, e devolve no fim — inclusive se houver erro.

    Rende `False` quando não havia vaga, em vez de levantar: quem chama é que
    sabe qual resposta HTTP isso vira, e este módulo não conhece HTTP. O
    `finally` é o que impede o vazamento que tornaria o mecanismo pior que a
    ausência dele — uma exceção no meio do registro sem devolver a vaga faria o
    teto encolher a cada falha até ninguém mais conseguir entrar.
    """
    concedida = autenticacoes.ocupar()
    try:
        yield concedida
    finally:
        if concedida:
            autenticacoes.liberar()


def esquecer_tudo() -> None:
    """Zera os dois contadores. Chamado entre testes."""
    tentativas.esquecer_tudo()
    autenticacoes.esquecer_tudo()
