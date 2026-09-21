"""Os métodos de estudo e os parâmetros que cada um impõe à sessão.

Como `app/presenca.py` e `app/analista.py`, este módulo não conhece HTTP nem
banco: recebe códigos e devolve parâmetros.

**Por que só estes cinco.** Um método só entra aqui se tiver assinatura
*temporal* — se a diferença entre segui-lo e não segui-lo aparecer no relógio.
Feynman, active recall e SQ3R ficam de fora de propósito: eles diferem por
atividade cognitiva, e EAR, MAR e head pose não distinguem "explicar em voz
alta" de "reler". Incluí-los faria o sistema afirmar que mede o que não mede,
que é exatamente o que a ticket 10 comprou o direito de não fazer.

**Por que catálogo em código, e não tabela.** Uma tabela precisaria de *seed* no
boot, e `database._acrescentar_colunas_faltantes` recusa explicitamente
preencher valor — ensiná-la a inserir linha é justamente a capacidade que ela
declara não ter. Além disso, vocabulário fechado neste projeto mora em Python:
`recomendacoes.NOMES_DE_ALERTA` e `qualidade.MOTIVOS_DE_INCERTEZA` são os
precedentes. Tabela só passa a valer o peso se um dia existir método
customizado pelo aluno — e aí ela conviverá com o snapshot gravado na sessão,
sem substituí-lo.

**O catálogo não é a sessão.** O que vale para uma sessão é o `pausa_maxima_s`
gravado nela no instante em que foi aberta, não o que este dicionário diz hoje.
Se o Pomodoro for reparametrizado em março, o relatório de janeiro não pode
mudar junto — mesmo princípio que fez a ticket 13 congelar os indicadores em
`resumo_sessao`.
"""
from dataclasses import dataclass
from datetime import timedelta
from typing import Dict, Optional

#: Quanto o aluno pode atrasar o retorno sem perder a sessão.
#:
#: O relógio do aluno não é o do sistema: ele volta do café três minutos depois
#: do que o método previa. Encerrar a sessão por isso ensina o aluno a **não
#: declarar a pausa** — e sem pausa declarada o recurso inteiro deixa de ter
#: sentido. Três minutos, e não cinco, porque com cinco tanto o Pomodoro (15+5)
#: quanto o 52/17 (17+5) bateriam no teto abaixo e a tolerância viraria
#: decoração.
TOLERANCIA_DE_RETORNO = timedelta(minutes=3)

#: Teto absoluto de ausência: nenhum método mantém uma sessão viva além disto.
#:
#: Duas razões, e a segunda é de segurança. (a) Um método mal parametrizado não
#: pode fazer cadeira vazia virar sessão eterna. (b) `pausa_maxima_s` é
#: resolvido **pelo servidor**, a partir deste catálogo, e nunca aceito do
#: cliente; o teto é a segunda linha de defesa caso um dia alguém aceite. Sem
#: ele, "sessão imortal" seria um campo de request.
TETO_DE_AUSENCIA = timedelta(minutes=20)


@dataclass(frozen=True)
class MetodoDeEstudo:
    """Os parâmetros de um método, como o sistema os enxerga.

    `foco_s` é `None` quando o método não prescreve duração de bloco — Flow não
    tem uma, e o Timeboxing tem a que o aluno declarar. Deixar `None` em vez de
    zero evita que o relatório compare a execução com um alvo que não existe.

    `ciclos_ate_pausa_longa` e `pausa_longa_s` não configuram o encerramento:
    eles descrevem o ciclo para que o cliente saiba **conduzi-lo**. A decisão de
    produto é que uma sessão aqui é *um ciclo* — a pausa longa encerra a sessão,
    e o relatório é do ciclo. Isso mantém o teto de ausência intacto e, de
    quebra, deixa todos os blocos do ciclo dentro da mesma calibração de
    baseline, que é a única condição em que compará-los é honesto.
    """

    codigo: str
    nome: str
    foco_s: Optional[int]
    pausa_s: int
    ciclos_ate_pausa_longa: Optional[int] = None
    pausa_longa_s: Optional[int] = None


#: O aluno que escolhe não usar método nenhum. Note que isto **não** é o mesmo
#: que `metodo IS NULL`: nulo significa "esta sessão é anterior ao recurso".
#: Colapsar os dois faria a migração inventar uma escolha que ninguém fez.
METODO_LIVRE = "livre"

METODOS: Dict[str, MetodoDeEstudo] = {
    "pomodoro": MetodoDeEstudo(
        codigo="pomodoro",
        nome="Pomodoro",
        foco_s=25 * 60,
        pausa_s=5 * 60,
        ciclos_ate_pausa_longa=4,
        pausa_longa_s=15 * 60,
    ),
    "52-17": MetodoDeEstudo(
        codigo="52-17",
        nome="52/17",
        foco_s=52 * 60,
        pausa_s=17 * 60,
    ),
    "flow": MetodoDeEstudo(
        codigo="flow",
        nome="Flow / Deep Work",
        foco_s=None,
        # Cinco minutos, e não zero, apesar de o método não prescrever pausa.
        # Com zero, ir ao banheiro custaria a sessão — e a regra viraria "fique
        # imóvel na frente da webcam", que não é o que o método pede nem o que o
        # sistema quer incentivar.
        pausa_s=5 * 60,
    ),
    "timeboxing": MetodoDeEstudo(
        codigo="timeboxing",
        nome="Timeboxing",
        foco_s=None,
        pausa_s=5 * 60,
    ),
    METODO_LIVRE: MetodoDeEstudo(
        codigo=METODO_LIVRE,
        nome="Sem método",
        foco_s=None,
        pausa_s=5 * 60,
    ),
}


class MetodoDesconhecido(Exception):
    """Pediram um código que não está no catálogo."""


def buscar(codigo: Optional[str]) -> Optional[MetodoDeEstudo]:
    """O método de um código, ou `None` se o código for nulo ou desconhecido.

    Devolver `None` para código desconhecido, em vez de estourar, é o que
    permite ao relatório abrir uma sessão gravada por uma versão futura sem
    quebrar. Quem precisa recusar entrada do aluno usa `resolver_pausa_maxima`.
    """
    if codigo is None:
        return None
    return METODOS.get(codigo)


def resolver_pausa_maxima(codigo: Optional[str]) -> Optional[int]:
    """A pausa máxima de um método, em segundos — resolvida no servidor.

    Este é o ponto em que o parâmetro deixa de ser opinião do cliente e passa a
    ser fato do servidor. O cliente manda o **código** do método; o número sai
    daqui. Aceitar o número do cliente abriria "sessão que nunca encerra" como
    um campo de request.

    Código nulo devolve `None` — a sessão fica sem método e cai no limite
    legado, que é a regra que valia quando ela foi aberta.
    """
    if codigo is None:
        return None

    metodo = METODOS.get(codigo)
    if metodo is None:
        raise MetodoDesconhecido(codigo)

    return metodo.pausa_s


def limite_de_ausencia(pausa_maxima_s: Optional[int], legado: timedelta) -> timedelta:
    """Quanto tempo sem rosto na câmera antes de a sessão ser encerrada.

    Repare que esta pergunta **não** é a mesma que `presenca.limite_de_ausencia`
    responde, apesar do nome parecido. Aqui se pergunta "a sessão acabou?", e a
    evidência é `sessao_estudo.ultima_presenca`. Lá se pergunta "este vão entre
    dois pontos da série foi pausa de captura ou fim de sessão?", e a evidência
    é a série. Elas compartilhavam uma constante enquanto a série era a única
    evidência de presença que o sistema tinha; desde que existe `ultima_presenca`
    isso deixou de ser verdade, e cada uma tem razão própria.

    `legado` é o que vale para sessão sem método — inclusive para a que estava
    aberta no instante do deploy. Não é invenção: é a regra anterior aplicada a
    dado anterior. Ele também passa pelo teto, para que um `.env` torto não
    consiga produzir sessão imortal por outra porta.
    """
    if pausa_maxima_s is None:
        return min(legado, TETO_DE_AUSENCIA)

    return min(timedelta(seconds=pausa_maxima_s) + TOLERANCIA_DE_RETORNO, TETO_DE_AUSENCIA)
