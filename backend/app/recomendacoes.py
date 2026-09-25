"""Como o relatório fala com o aluno (ticket 11, AC-11-2 e AC-11-3).

Duas responsabilidades, e as duas são de vocabulário, não de cálculo: dar nome
aos rótulos que o resto do sistema grava em código (`palpebras-pesadas`,
`baixa-luz`) e transformar o resumo da sessão em recomendações de
autorregulação.

**A regra de tom, que vale para cada string deste arquivo.** O sistema mede
proxies comportamentais visuais — abertura ocular, orientação da cabeça,
abertura da boca. Ele não mede cansaço, atenção, interesse nem compreensão.
Então nada aqui afirma estado interno: o texto diz o que foi *observado* e o que
o aluno *pode fazer*, e deixa a interpretação com ele. "Você estava cansado" é
uma afirmação que estes dados não sustentam; "houve 8 minutos com a pálpebra
mais fechada que a sua média" é o que de fato aconteceu.

É a mesma régua da história 22 do spec — não afirmar estar medindo estado
emocional ou cognitivo real — aplicada ao único lugar do sistema onde o produto
literalmente escreve frases para uma pessoa ler sobre si mesma.

As recomendações também não são prescrição clínica. São as três ou quatro coisas
banais que a literatura de autorregulação sugere (pausar, fracionar, mudar de
estratégia, arrumar o ambiente), oferecidas na ordem em que os sinais aparecem.
"""
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

if TYPE_CHECKING:  # pragma: no cover - só para o verificador de tipos
    # Importado apenas para anotação. Em tempo de execução a dependência é ao
    # contrário: é `app.relatorio` que monta o relatório e chama daqui as
    # recomendações. Este módulo não precisa de nada de lá além do formato.
    from app.relatorio import ResumoDaSessao

#: Nome legível de cada rótulo gravado na coluna `alerta` de `log_engajamento`.
#:
#: A fonte dos três primeiros é `DetectorDeFadiga._avaliar`, e a dos quatro
#: últimos é `analista.MOTIVOS_DE_INCERTEZA` mais o `INCERTEZA_DESCONHECIDA`.
#: Traduzir aqui, e não no navegador, mantém uma única versão do vocabulário —
#: a tela do relatório recebe o nome pronto e não precisa saber que "oclusao"
#: existe.
NOMES_DE_ALERTA: Dict[str, str] = {
    "palpebras-pesadas": "Pálpebras pesadas",
    "olhos-fechados-prolongados": "Olhos fechados por tempo prolongado",
    "bocejos": "Bocejos",
    "baixa-luz": "Pouca luz no ambiente",
    "reflexo-ocular": "Reflexo nos óculos",
    "oclusao": "Rosto parcialmente encoberto",
    "desconhecida": "Captura não confiável",
}


def nome_do_alerta(codigo: str) -> str:
    """O nome legível do rótulo, ou o próprio código se ele for novo.

    Devolver o código cru é melhor que esconder o alerta: um rótulo que apareça
    no relatório sem tradução é um bug visível, e um alerta silenciosamente
    omitido é um bug invisível.
    """
    return NOMES_DE_ALERTA.get(codigo, codigo)


#: Tempo de captura contínua a partir do qual o relatório sugere fracionar a
#: sessão. Não é um limite fisiológico — é a ordem de grandeza das técnicas de
#: fracionamento mais difundidas (25–50 min por bloco). Provisório no mesmo
#: sentido que `LIMIAR_MAR_BOCEJO`: quer validação com dados de uso real.
DURACAO_SEM_FRACIONAR = timedelta(minutes=50)

#: Abaixo desta média o relatório sugere rever a estratégia de estudo. O IEE vai
#: de 0 a 100 e é medido contra a baseline do próprio aluno, então 50 é o meio
#: da escala dele, não de uma escala populacional. Continua sendo um corte
#: escolhido, e a recomendação é redigida como hipótese por causa disso.
MEDIA_BAIXA = 50.0

#: Fração da sessão em incerteza a partir da qual vale mexer no ambiente. Abaixo
#: disso é ruído normal de captura — alguém passa na frente, o aluno coça o
#: olho — e avisar a cada ocorrência treinaria o aluno a ignorar o aviso.
FRACAO_DE_INCERTEZA_RELEVANTE = 0.3


@dataclass(frozen=True)
class Recomendacao:
    """Uma sugestão de autorregulação, com o motivo que a disparou.

    `motivo` existe para a tela poder mostrar a evidência junto da sugestão. Uma
    recomendação sem o que a originou é um conselho genérico, e conselho
    genérico é o que faz o aluno parar de ler o relatório na terceira sessão.
    """

    codigo: str
    titulo: str
    texto: str
    motivo: str


def recomendar(resumo: "ResumoDaSessao") -> Tuple[Recomendacao, ...]:
    """As recomendações que o resumo da sessão justifica, em ordem de urgência.

    A ordem não é cosmética: microssono vem antes de pálpebra pesada, que vem
    antes de fracionar a sessão, porque é essa a ordem em que os sinais pedem
    ação. E a lista é curta de propósito — um relatório com oito recomendações
    não tem nenhuma.

    Sessão sem nada a sinalizar recebe uma recomendação mesmo assim. O relatório
    que volta vazio ensina o aluno que só vale a pena abri-lo quando algo deu
    errado, e o objetivo declarado é autopercepção, não alarme.
    """
    fadiga = resumo.alertas_de_fadiga
    sugestoes: List[Recomendacao] = []

    if not resumo.pontos_medidos and not resumo.pontos_incertos:
        # Sessão sem nenhum ponto: encerrada antes do primeiro segundo, ou com a
        # captura que nunca subiu. Não há o que recomendar sobre o estudo, e
        # fingir que há seria inventar leitura sobre dado que não existe.
        return (
            Recomendacao(
                codigo="sem-dados",
                titulo="Esta sessão não gerou medições",
                texto=(
                    "Nenhuma leitura chegou ao servidor. Verifique se a webcam ficou "
                    "liberada durante a sessão e comece uma nova quando puder."
                ),
                motivo="Nenhum ponto registrado.",
            ),
        )

    if "olhos-fechados-prolongados" in fadiga:
        sugestoes.append(
            Recomendacao(
                codigo="descanso",
                titulo="Vale interromper e descansar",
                texto=(
                    "Foram registrados fechamentos de pálpebra de dois segundos ou mais. "
                    "Continuar estudando logo depois disso costuma render pouco — dormir "
                    "ou descansar de verdade tende a valer mais que a próxima meia hora."
                ),
                motivo=_ocorrencias("olhos-fechados-prolongados", fadiga),
            )
        )
    elif "palpebras-pesadas" in fadiga or "bocejos" in fadiga:
        dominante = "palpebras-pesadas" if "palpebras-pesadas" in fadiga else "bocejos"
        sugestoes.append(
            Recomendacao(
                codigo="pausa",
                titulo="Faça uma pausa curta",
                texto=(
                    "O sistema registrou sinais físicos associados a cansaço. Cinco a dez "
                    "minutos longe da tela, de preferência em pé, costumam ser suficientes "
                    "para retomar em outra condição."
                ),
                motivo=_ocorrencias(dominante, fadiga),
            )
        )

    if resumo.duracao_presente >= DURACAO_SEM_FRACIONAR:
        sugestoes.append(
            Recomendacao(
                codigo="fracionar",
                titulo="Divida a próxima sessão em blocos",
                texto=(
                    "Esta sessão teve captura contínua por um período longo. Blocos de 25 a "
                    "50 minutos com pausa entre eles são mais fáceis de sustentar do que um "
                    "bloco único, e deixam o relatório mais fácil de comparar."
                ),
                motivo=f"{_minutos(resumo.duracao_presente)} de captura.",
            )
        )

    if resumo.media is not None and resumo.media < MEDIA_BAIXA and not fadiga:
        sugestoes.append(
            Recomendacao(
                codigo="estrategia",
                titulo="Experimente mudar a estratégia de estudo",
                texto=(
                    "O índice ficou abaixo do meio da sua escala sem que aparecessem sinais "
                    "de cansaço. Pode ser o formato do material: trocar leitura passiva por "
                    "exercícios, resumo ou explicação em voz alta costuma mudar esse quadro."
                ),
                motivo=f"Média de {resumo.media:.0f} no índice.",
            )
        )

    motivo_de_incerteza = _incerteza_relevante(resumo)
    if motivo_de_incerteza is not None:
        sugestoes.append(
            Recomendacao(
                codigo="ambiente",
                titulo="Ajuste o ambiente de captura",
                texto=(
                    "Parte da sessão não pôde ser medida com confiança, então o índice "
                    "acima descreve menos tempo do que você estudou. Corrigir isso na "
                    "próxima sessão vale mais que interpretar esta."
                ),
                motivo=f"{nome_do_alerta(motivo_de_incerteza)} em parte da sessão.",
            )
        )

    if not sugestoes:
        sugestoes.append(
            Recomendacao(
                codigo="manter",
                titulo="Nada a sinalizar nesta sessão",
                texto=(
                    "Não apareceram sinais de fadiga nem problemas de captura. Se a sessão "
                    "rendeu, vale anotar o que estava diferente — horário, ambiente, tipo "
                    "de material — para repetir."
                ),
                motivo="Nenhum alerta registrado.",
            )
        )

    return tuple(sugestoes)


def _incerteza_relevante(resumo: "ResumoDaSessao") -> Optional[str]:
    """O motivo dominante de incerteza, se ela tomou parte relevante da sessão.

    Dominante é o mais frequente; empate resolve pela ordem alfabética do
    rótulo, para que o mesmo relatório gere sempre o mesmo texto.
    """
    total = resumo.pontos_medidos + resumo.pontos_incertos
    if not total or resumo.pontos_incertos / total < FRACAO_DE_INCERTEZA_RELEVANTE:
        return None
    if not resumo.motivos_de_incerteza:
        return "desconhecida"

    return max(sorted(resumo.motivos_de_incerteza), key=resumo.motivos_de_incerteza.get)


def _ocorrencias(codigo: str, alertas: Dict[str, int]) -> str:
    quantidade = alertas.get(codigo, 0)
    plural = "s" if quantidade != 1 else ""
    return f"{nome_do_alerta(codigo)}: {quantidade} episódio{plural}."


def _minutos(duracao: timedelta) -> str:
    return f"{int(duracao.total_seconds() // 60)} min"
