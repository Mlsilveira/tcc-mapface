"""O plano executado de uma sessão de estudo, bloco a bloco.

Como `app/presenca.py`, `app/metodos.py` e `app/analista.py`, este módulo não
conhece HTTP nem banco: recebe estruturas e devolve estruturas. É por isso que
a regra de transição pode ser testada sem subir FastAPI nem abrir `Session`, e
é onde ela deve ser lida por quem for revisar o recurso.

**O que um bloco afirma.** Um bloco é o *plano executado*: o que o método
mandou fazer e o aluno aceitou, declarado na transição e fechado na transição
seguinte. Nada mais.

**O que ele não afirma, e a armadilha de fazê-lo afirmar demais.** Um bloco
**não** é afirmação de presença. Fazer "bloco de foco" significar "o aluno
estava ali, focado" obrigaria a reconciliar cada bloco com a série do IEE toda
vez que alguém o lesse — e erraria, porque a série mede captura e o bloco mede
intenção declarada. Os dois ficam lado a lado, que é o idioma da casa:

    "Bloco 3 (foco): 25 min planejados · 11 min com captura · IEE médio 54"

A discrepância entre as duas primeiras durações é **informação para o aluno**,
não inconsistência a esconder. É a mesma retórica de `presenca.duracao_total`
ao lado de `presenca.duracao_presente`: sozinha, cada duração engana; juntas,
elas informam.

**Por que as bordas são declaradas e não inferidas.** O aplicativo conduz o
método — cronômetro na tela, aviso da hora da pausa —, então o instante da
transição é um fato que o cliente *sabe*, e não um que o servidor precise
adivinhar. Inferir as bordas da série custaria ±60 s de erro (a janela do
`DetectorDeFadiga` carrega resíduo por até um minuto depois da saída, e
`score == 0` é ambíguo entre "cadeira vazia" e "fadiga saturada") e, pior,
tornaria uma queda de Wi-Fi indistinguível de uma pausa real: rede instável
passaria a **fabricar** blocos Pomodoro no relatório de quem não fez nenhum.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Iterable, List, Optional, Sequence, TypeVar

try:  # pragma: no cover - `Protocol` é do typing desde o 3.8
    from typing import Protocol
except ImportError:  # pragma: no cover
    from typing_extensions import Protocol  # type: ignore

from app.tempo import como_utc

#: O aluno declarou que está trabalhando no material.
TIPO_FOCO = "foco"

#: O aluno declarou que parou — a pausa que o método prescreve, ou a que ele
#: decidiu tirar. Note que "pausa declarada" e "ausência observada" são coisas
#: diferentes e podem não coincidir: quem declara a pausa e fica na frente da
#: webcam continua produzindo presença, e quem sai sem declarar nada não vira
#: bloco de pausa nenhum. O relatório mostra as duas leituras.
TIPO_PAUSA = "pausa"

#: Vocabulário fechado, no molde de `recomendacoes.NOMES_DE_ALERTA` e
#: `qualidade.MOTIVOS_DE_INCERTEZA`. Tipo fora daqui é entrada inválida, e não
#: um tipo novo: gravar um terceiro valor faria o relatório calar sobre aquele
#: trecho da sessão sem que ninguém percebesse.
TIPOS = frozenset({TIPO_FOCO, TIPO_PAUSA})

#: A transição aconteceu na hora que o método previa — o cronômetro chegou ao
#: fim e o aluno seguiu o plano.
ORIGEM_METODO = "metodo"

#: O aluno antecipou ou adiou a transição por conta própria.
#:
#: A distinção existe porque ela é a única coisa que separa "o método foi
#: seguido" de "o método foi reescrito no meio", e essa é uma pergunta que o
#: relatório vai querer responder **sem** transformá-la em nota. Ela é
#: declarada pelo cliente, que é quem sabe se o cronômetro tinha ou não zerado
#: quando o botão foi apertado; o servidor não tem como derivá-la, porque não
#: guarda o cronômetro.
ORIGEM_ALUNO = "aluno"

ORIGENS = frozenset({ORIGEM_METODO, ORIGEM_ALUNO})

SEM_DURACAO = timedelta(0)


class TipoDeBlocoDesconhecido(Exception):
    """Declararam um tipo de bloco que não está no vocabulário."""


class OrigemDeBlocoDesconhecida(Exception):
    """Declararam uma origem de transição que não está no vocabulário."""


class BlocoLido(Protocol):
    """O mínimo que este módulo precisa saber sobre um bloco.

    Um `Protocol`, e não `app.models.BlocoEstudo`, de propósito: se este módulo
    importasse o modelo de tabela, ele deixaria de ser testável sem banco e o
    seam desapareceria. Do lado de cá interessa `indice`, `tipo`, `inicio` e
    `fim` — e tanto a linha do SQLModel quanto o `Bloco` abaixo os oferecem.
    """

    indice: int
    tipo: str
    inicio: datetime
    fim: Optional[datetime]


@dataclass(frozen=True)
class Bloco:
    """Um bloco fora do banco — o que os testes e os cálculos manipulam.

    Congelado pelo mesmo motivo que `metodos.MetodoDeEstudo`: um bloco já
    declarado é fato passado, e código que precise de outro bloco cria outro
    bloco em vez de reescrever a história deste.
    """

    indice: int
    tipo: str
    inicio: datetime
    fim: Optional[datetime] = None
    origem: str = ORIGEM_METODO


def validar_declaracao(tipo: str, origem: str) -> None:
    """Recusa tipo ou origem fora do vocabulário, antes de qualquer escrita.

    Entrada do aluno se valida contra o vocabulário; não se aceita e se conserta
    depois. Um `tipo` inventado gravado na tabela não estoura em lugar nenhum:
    ele simplesmente some do relatório, porque todo critério pergunta por
    `TIPO_FOCO` ou `TIPO_PAUSA`. Falha silenciosa num relatório é o defeito que
    este projeto mais persegue.
    """
    if tipo not in TIPOS:
        raise TipoDeBlocoDesconhecido(tipo)
    if origem not in ORIGENS:
        raise OrigemDeBlocoDesconhecida(origem)


def e_redundante(tipo: str, tipo_aberto: Optional[str]) -> bool:
    """Se declarar `tipo` agora não muda nada, porque já é o que está aberto.

    Acontece por dois caminhos honestos, e os dois precisam terminar bem:

    1. **Retentativa de rede.** O cliente manda "entrei em pausa", a resposta se
       perde, ele repete. Abrir um segundo bloco de pausa transformaria uma
       pausa em duas, e a primeira teria duração zero — um artefato do
       transporte virando fato no relatório do aluno.
    2. **Duas abas abertas na mesma sessão.** Enquanto o defeito das abas
       duplicadas não for fechado, as duas declaram transições; quando declaram
       a *mesma*, absorver é claramente melhor que serrar o bloco ao meio.

    A escolha deliberada é preservar o **instante da primeira** declaração. Ela
    é a que o aluno de fato fez; a segunda é eco.
    """
    return tipo_aberto is not None and tipo == tipo_aberto


def proximo_indice(indices: Iterable[int]) -> int:
    """O número do próximo bloco, contando a partir de 1.

    Deriva do maior índice já usado, e não da contagem de blocos, para que uma
    linha apagada à mão no banco não faça dois blocos nascerem com o mesmo
    número — o índice é o que o aluno lê ("bloco 3"), e dois "bloco 3" na mesma
    sessão é pior que um buraco na sequência.

    Começa em 1 porque é numeração para pessoa, não deslocamento em vetor.
    """
    usados = list(indices)
    return max(usados) + 1 if usados else 1


def duracao(bloco: BlocoLido, ate: Optional[datetime] = None) -> timedelta:
    """Quanto durou o bloco — do início ao fim, ou até `ate` se ainda aberto.

    `ate` existe porque o bloco em andamento tem duração e o relatório de uma
    sessão viva não é o único leitor possível; sem ele, o chamador acabaria
    fabricando um `fim` que ninguém declarou.

    Nunca devolve negativo. Não é paranoia de assinatura: uma sessão encerrada
    pela varredura recebe `fim = ultima_presenca`, que é um instante do passado,
    e um bloco declarado **depois** daquela última presença — o aluno que apertou
    "pausa" e não voltou mais — teria fim anterior ao início. Zero é a leitura
    certa desse caso: o bloco foi declarado e não foi executado.
    """
    borda = bloco.fim if bloco.fim is not None else ate
    if borda is None:
        return SEM_DURACAO
    return max(SEM_DURACAO, como_utc(borda) - como_utc(bloco.inicio))


T = TypeVar("T")


def recortar(
    bloco: BlocoLido, serie: Sequence[T], instante_de: Callable[[T], datetime]
) -> List[T]:
    """Os pontos da série que caem dentro do bloco.

    `instante_de` é explícito, e não um atributo assumido, porque é justamente
    ele que mantém este módulo sem conhecer `LogEngajamento`. Quem tem a série
    sabe de onde sai o carimbo de tempo dela.

    **O intervalo é semiaberto, `[inicio, fim)`.** Dois blocos consecutivos
    compartilham um instante — o da transição —, e num sistema que grava um
    ponto por segundo esse ponto existe. Fechar os dois lados o contaria duas
    vezes: uma sessão de quatro blocos reportaria três pontos a mais do que
    gravou, e o erro cresceria com o número de blocos, que é exatamente o
    parâmetro que este recurso existe para aumentar. O ponto da borda pertence
    ao bloco que **começa**, pela mesma razão que o instante do encerramento
    pertence ao que acabou de terminar: uma transição declarada às 10h05 diz
    "daqui em diante", não "até aqui".
    """
    inicio = como_utc(bloco.inicio)
    fim = como_utc(bloco.fim) if bloco.fim is not None else None

    dentro = []
    for item in serie:
        instante = como_utc(instante_de(item))
        if instante < inicio:
            continue
        if fim is not None and instante >= fim:
            continue
        dentro.append(item)

    return dentro
