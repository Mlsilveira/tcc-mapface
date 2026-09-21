"""Quanto tempo o estudante de fato esteve na sessão (AC-11-5, ticket 11).

Como `app/sessoes.py` e `app/analista.py`, este módulo não conhece HTTP nem
banco: recebe instantes e devolve duração.

**O problema que ele existe para resolver.** Até aqui a única duração disponível
era `fim - inicio`, e `fim` é escrito ou pelo clique em "Encerrar" ou pela
varredura de inatividade. Só que a varredura observa `ultima_atividade`, que o
navegador atualiza a cada 60 s **enquanto a aba estiver aberta** — inclusive com
o aluno na cozinha. Aba aberta virava tempo de estudo, e o relatório abriria
dizendo "você estudou 3 horas" para quem estudou quarenta minutos.

A correção é trocar a fonte da evidência. Quem prova presença não é o heartbeat,
que bate sozinho: é a **série do IEE**. Cada ponto de `log_engajamento` só existe
porque a captura estava rodando e mandou uma leitura — é o sinal mais próximo de
"o aluno estava aí" que o sistema tem sem guardar nada de imagem.

**O que a duração presente afirma, e o que ela não afirma.** Ela afirma que
houve captura naquele intervalo. Não afirma que o aluno estava olhando para o
material: isso é o que o score do IEE mede, e o relatório mostra os dois lado a
lado justamente porque são perguntas diferentes. O que ela recusa a contar é
tempo sem evidência nenhuma — aba em segundo plano, máquina suspensa, captura
parada.

**O limite responde a uma pergunta sobre a série, não sobre o aluno.** Um vão
entre dois pontos só deixa de contar quando passa de
`vao_maximo_da_serie_minutos` — o maior silêncio ainda atribuível a **perda de
captura** (reconexão do WebSocket, aba em segundo plano, máquina suspensa) e não
a fim de sessão.

Até os métodos de estudo entrarem, esta constante era a mesma que decidia o
encerramento automático, e havia aqui um parágrafo dizendo que uma constante
própria faria o sistema ter duas opiniões sobre o que significa silêncio. Esse
argumento pressupunha que **a série é a evidência de presença** — e era
verdadeiro enquanto era a única que existia. Desde que `sessao_estudo` guarda
`ultima_presenca`, não é mais: "a sessão acabou?" se responde com a coluna e com
o limite do método (`app.metodos.limite_de_ausencia`), e "este vão foi perda de
captura?" se responde aqui. Perguntas diferentes, evidências diferentes,
constantes diferentes — cada uma com razão própria.

**Cuidado que a leitura desatenta deste módulo produz.** Durante uma pausa
declarada a aba fica aberta e a webcam ligada; o navegador continua mandando um
payload por segundo, com `rosto_detectado: false`, e o backend continua gravando
um ponto por segundo (com score zero). A série **não tem buraco** numa pausa, e
portanto `duracao_presente` a soma inteira. Isso é coerente com o que a função
afirma — houve captura —, mas não é "tempo estudando". Quem quer o tempo de
pausa lê os blocos da sessão, não esta função.
"""
from datetime import datetime, timedelta
from typing import Iterable, Optional

from app.config import settings
from app.tempo import como_utc

SEM_DURACAO = timedelta(0)


def limite_de_ausencia() -> timedelta:
    """Maior vão entre dois pontos ainda atribuível a perda de captura.

    Não confundir com `app.metodos.limite_de_ausencia`, que decide o
    encerramento da sessão. O nome é parecido e a pergunta é outra — ver o
    docstring do módulo.
    """
    return timedelta(minutes=settings.vao_maximo_da_serie_minutos)


def duracao_total(inicio: datetime, fim: Optional[datetime]) -> timedelta:
    """Da abertura ao encerramento — o tempo de aba aberta, sem julgamento.

    Continua sendo exibido no relatório, ao lado da duração presente. Sozinho
    ele engana; ao lado dela, é justamente a comparação que informa o aluno.
    """
    if fim is None:
        return SEM_DURACAO
    return max(SEM_DURACAO, como_utc(fim) - como_utc(inicio))


def duracao_presente(
    inicio: datetime, fim: Optional[datetime], instantes: Iterable[datetime]
) -> timedelta:
    """Soma dos intervalos em que houve evidência de captura.

    O algoritmo é uma costura de marcos: `inicio`, cada instante da série e
    `fim`, em ordem. Cada vão entre dois marcos consecutivos conta se for menor
    que o limite de ausência, e é descartado inteiro se for maior — não pela
    metade, porque não há nada no meio de um silêncio de vinte minutos que
    permita dizer onde o aluno voltou.

    Série vazia devolve zero, e zero aqui é uma afirmação honesta: sem nenhum
    ponto gravado, nada prova que alguém esteve na frente da webcam. É o mesmo
    princípio que faz `media` ser `None` em vez de 0 no resumo — a diferença é
    que ausência de tempo é de fato zero tempo, enquanto ausência de medida não
    é um score de zero.
    """
    marcos = sorted(como_utc(instante) for instante in instantes)
    if not marcos:
        return SEM_DURACAO

    limite = limite_de_ausencia()
    bordas = [como_utc(inicio), *marcos]
    if fim is not None:
        bordas.append(como_utc(fim))

    total = SEM_DURACAO
    for anterior, seguinte in zip(bordas, bordas[1:]):
        vao = seguinte - anterior
        if SEM_DURACAO < vao <= limite:
            total += vao

    return total
