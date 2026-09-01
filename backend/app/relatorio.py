"""Relatório de autopercepção da sessão de estudo (ticket 11).

Como `sessoes.py` e `analista.py`, este módulo não conhece HTTP nem WebSocket:
recebe a série de logs e devolve indicadores. É onde os testes batem.

**O relatório é calculado sob demanda, não guardado.** Guardá-lo criaria uma
segunda fonte de verdade que envelhece — e a ticket 13, que vai sumarizar os
logs granulares depois da sessão, teria de manter as duas em dia. Calcular na
hora custa uma varredura sobre alguns milhares de linhas de uma sessão, o que é
barato, e garante que o relatório sempre descreve o que está no banco.

**Sessão aberta também tem relatório.** É o critério de relatório parcial da
ticket 11: se o navegador caiu ou a conexão morreu antes do encerramento formal,
o aluno não pode perder o que já foi medido. Não há caminho especial para isso —
o relatório simplesmente não exige `fim`, e se marca como `parcial`.

O tom das recomendações é decisão de produto, não de implementação: o sistema
**não diagnostica, não avalia e não julga**. As frases abaixo sugerem, não
prescrevem, e nenhuma delas afirma algo sobre o estado mental do aluno — só
relatam o que foi observado e oferecem uma ação possível.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Sequence

from app.models import LogEngajamento, SessaoEstudo
from app.telemetria import AgregadoDaSessao
from app.tempo import como_utc

#: Abaixo disto, a sessão teve engajamento médio baixo o bastante para valer uma
#: sugestão de pausa. Não é diagnóstico: é o ponto em que a média deixa de ser
#: explicável por variação normal de atenção ao longo de uma sessão.
SCORE_BAIXO = 55.0

#: Queda, em pontos, entre o primeiro e o último terço da sessão que caracteriza
#: uma tendência — e não a oscilação normal de quem estuda.
QUEDA_RELEVANTE = 15.0

#: Fração da sessão com alerta de fadiga a partir da qual a fadiga deixa de ser
#: episódica.
FRACAO_FADIGA_ALTA = 0.30

#: Abaixo desta fração de leituras com rosto, a medição cobriu pouco da sessão e
#: os indicadores merecem ressalva explícita — em vez de serem apresentados como
#: se descrevessem a sessão inteira.
PRESENCA_BAIXA = 0.70

#: Fração da sessão com captura incerta a partir da qual vale avisar o aluno.
#: Abaixo disso é oscilação normal — uma nuvem passando, um movimento brusco —
#: e transformar isso em recomendação seria ruído.
CAPTURA_INCERTA_ALTA = 0.20


@dataclass(frozen=True)
class Indicadores:
    """Os números que resumem uma sessão."""

    n_leituras: int
    duracao_s: float
    score_medio: float
    score_minimo: float
    score_maximo: float
    #: Média do primeiro e do último terço, para enxergar tendência.
    score_inicio: float
    score_fim: float
    prop_com_rosto: float
    prop_com_fadiga: float
    fadiga_maxima: float
    desvio_olhar_medio: float
    #: Fração da sessão em que a captura não foi confiável (ticket 10).
    prop_captura_incerta: float


@dataclass(frozen=True)
class PontoDaSerie:
    """Um instante do gráfico do IEE."""

    horario: datetime
    score: float
    fadiga: float
    alerta: Optional[str]


@dataclass(frozen=True)
class Relatorio:
    id_sessao: int
    inicio: datetime
    fim: Optional[datetime]
    #: `True` quando a sessão não foi encerrada formalmente.
    parcial: bool
    indicadores: Indicadores
    serie: List[PontoDaSerie]
    #: Quantas leituras registraram cada tipo de alerta.
    alertas: Dict[str, int]
    recomendacoes: List[str]


def _media(valores: Sequence[float]) -> float:
    return sum(valores) / len(valores) if valores else 0.0


def _terco(valores: Sequence[float], final: bool) -> float:
    """Média do primeiro ou do último terço da série.

    Terços, e não primeiro-versus-último ponto: um único ponto é ruído, e a
    pergunta que interessa — "o engajamento caiu ao longo da sessão?" — é sobre
    tendência.
    """
    if not valores:
        return 0.0
    tamanho = max(1, len(valores) // 3)
    return _media(valores[-tamanho:] if final else valores[:tamanho])


def _proporcao(logs: Sequence[LogEngajamento], criterio) -> float:
    """Fração das leituras que satisfazem o critério, **ponderada**.

    Depois da sumarização da ticket 13, uma linha pode representar um minuto
    inteiro. Contar linhas trataria esse minuto como uma leitura só, e a
    proporção passaria a depender de a sessão já ter sido resumida ou não —
    o mesmo relatório mudaria de número sem nenhum dado ter mudado.
    """
    total = sum(log.n_leituras for log in logs)
    if total == 0:
        return 0.0
    return sum(log.n_leituras for log in logs if criterio(log)) / total


def _indicadores(logs: Sequence[LogEngajamento]) -> Indicadores:
    # **Os indicadores de score descrevem só o que foi bem medido.** Uma câmera
    # instável produz scores baixos que não são sobre o aluno, e incluí-los faria
    # o relatório dizer "você esteve disperso" quando o certo é "a captura
    # falhou". A proporção de captura incerta vai separada, como indicador
    # próprio, para o aluno saber o quanto da sessão está fora da conta.
    confiaveis = [log for log in logs if log.captura_confiavel]
    scores = [log.score for log in confiaveis]
    com_rosto = [log for log in confiaveis if log.direcao_olhar is not None]
    total_leituras = sum(log.n_leituras for log in logs)

    if logs:
        duracao = (como_utc(logs[-1].horario_registro) - como_utc(logs[0].horario_registro))
        duracao_s = duracao.total_seconds()
    else:
        duracao_s = 0.0

    def media_ponderada(selecionados: Sequence[LogEngajamento], valor) -> float:
        peso = sum(log.n_leituras for log in selecionados)
        if peso == 0:
            return 0.0
        return sum(valor(log) * log.n_leituras for log in selecionados) / peso

    return Indicadores(
        n_leituras=total_leituras,
        duracao_s=duracao_s,
        score_medio=media_ponderada(confiaveis, lambda log: log.score),
        score_minimo=min(scores) if scores else 0.0,
        score_maximo=max(scores) if scores else 0.0,
        score_inicio=_terco(scores, final=False),
        score_fim=_terco(scores, final=True),
        prop_com_rosto=_proporcao(logs, lambda log: log.direcao_olhar is not None),
        prop_com_fadiga=_proporcao(logs, lambda log: log.flag_fadiga),
        prop_captura_incerta=_proporcao(logs, lambda log: not log.captura_confiavel),
        fadiga_maxima=max((log.fator_fadiga for log in confiaveis), default=0.0),
        # Só faz sentido sobre as leituras em que havia rosto: incluir as outras
        # como zero puxaria a média para "olhando de frente" justamente nos
        # instantes em que não havia para onde olhar.
        desvio_olhar_medio=media_ponderada(com_rosto, lambda log: abs(log.direcao_olhar)),
    )


def _contar_alertas(logs: Sequence[LogEngajamento]) -> Dict[str, int]:
    """Quantas leituras registraram cada tipo de alerta.

    Conta **leituras**, não episódios. Um cochilo de quatro segundos aparece em
    várias leituras seguidas, e a janela de fadiga o mantém vivo por um minuto —
    então este número mede *por quanto tempo o alerta esteve de pé*, que é o que
    o gráfico mostra. Contar episódios distintos exigiria reprocessar a série
    inteira pelo detector, e é trabalho da ticket 13, ao sumarizar.

    E conta **ponderado por `n_leituras`**, pela mesma razão que `_proporcao`:
    depois da sumarização da ticket 13 uma linha vale um minuto inteiro. Somar
    linhas faria o mesmo episódio valer 12 antes de a retenção rodar e 1 depois,
    sem nenhum dado ter mudado — e a tela mostra esse número com unidade de
    leitura.
    """
    contagem: Dict[str, int] = {}
    for log in logs:
        if not log.alerta_gerado:
            continue
        for alerta in log.alerta_gerado.split(","):
            contagem[alerta] = contagem.get(alerta, 0) + log.n_leituras
    return contagem


def _recomendacoes(ind: Indicadores, alertas: Dict[str, int]) -> List[str]:
    """Sugestões de autorregulação a partir do que foi observado.

    Cada frase relata o observado antes de sugerir, de propósito: uma sugestão
    sem o dado que a motivou é um palpite, e o aluno não tem como avaliar se faz
    sentido para ele. Nenhuma afirma nada sobre estado mental — o sistema mede
    proxies comportamentais visuais, e o texto não pode prometer mais que isso.
    """
    frases: List[str] = []

    if ind.n_leituras == 0:
        return ["Não houve medição nesta sessão — a webcam pode não ter sido autorizada."]

    # Vem primeiro de propósito: se a captura falhou em boa parte da sessão, é a
    # primeira coisa que o aluno precisa saber antes de ler qualquer indicador —
    # e a ação que ela sugere (arrumar a luz, tirar o obstáculo) é a única que
    # melhora as próximas sessões.
    if ind.prop_captura_incerta > CAPTURA_INCERTA_ALTA:
        frases.append(
            f"Em {ind.prop_captura_incerta:.0%} da sessão a captura ficou instável, e "
            "esses trechos ficaram de fora dos indicadores. Luz de frente e sem "
            "contraluz costuma resolver; óculos com reflexo e algo cobrindo parte do "
            "rosto também atrapalham."
        )

    if ind.prop_com_rosto < PRESENCA_BAIXA:
        frases.append(
            f"Seu rosto foi detectado em {ind.prop_com_rosto:.0%} do tempo, então os "
            "indicadores abaixo descrevem só essa parte da sessão."
        )

    if alertas.get("olhos-fechados-prolongados"):
        frases.append(
            "Houve momentos de olhos fechados por vários segundos seguidos. "
            "Se você se sentir cansado, uma pausa curta costuma render mais que insistir."
        )
    elif ind.prop_com_fadiga > FRACAO_FADIGA_ALTA:
        frases.append(
            f"Sinais de cansaço apareceram em {ind.prop_com_fadiga:.0%} da sessão. "
            "Considere uma pausa antes do próximo bloco de estudo."
        )

    if alertas.get("bocejos"):
        frases.append("Bocejos foram registrados — vale observar se o horário de estudo está favorecendo você.")

    queda = ind.score_inicio - ind.score_fim
    if queda >= QUEDA_RELEVANTE:
        frases.append(
            f"Seu índice caiu cerca de {queda:.0f} pontos entre o começo e o fim da sessão. "
            "Trocar de assunto ou de formato de estudo pode ajudar a retomar."
        )

    if ind.desvio_olhar_medio > 20:
        frases.append(
            "Sua cabeça esteve bastante virada em relação à sua posição neutra. "
            "Se houver algo disputando sua atenção por perto, afastá-lo pode ajudar."
        )

    if not frases and ind.score_medio >= SCORE_BAIXO:
        frases.append("Sessão estável, sem sinais relevantes de dispersão ou cansaço.")
    elif not frases:
        frases.append(
            "O índice ficou baixo sem um motivo isolado que se destaque. "
            "Vale observar se o ambiente ou o horário estão ajudando."
        )

    return frases


@dataclass(frozen=True)
class ItemDoHistorico:
    """Uma linha da lista de sessões passadas (ticket 12).

    Traz o suficiente para o aluno **escolher** qual relatório abrir. Uma lista
    só com datas o obrigaria a abrir sessão por sessão para lembrar como cada
    uma foi, que é o oposto de um histórico.
    """

    id_sessao: int
    inicio: datetime
    fim: Optional[datetime]
    parcial: bool
    duracao_s: float
    n_leituras: int
    score_medio: float
    teve_fadiga: bool


def historico(
    sessoes: Sequence[SessaoEstudo], agregados: Dict[int, AgregadoDaSessao]
) -> List[ItemDoHistorico]:
    """Combina sessões e seus agregados numa lista para a tela de histórico.

    Função pura: recebe o que já foi lido do banco. Quem consulta é o router,
    e é por isso que este módulo continua testável sem subir banco nenhum.

    A duração vem de `inicio`/`fim` da sessão, e não do intervalo entre a
    primeira e a última leitura: uma sessão em que a webcam foi negada tem
    duração real e nenhuma leitura, e mostrar zero ali seria mentir sobre o
    tempo que o aluno passou na tela.
    """
    itens: List[ItemDoHistorico] = []
    for sessao in sessoes:
        inicio = como_utc(sessao.inicio)
        fim = como_utc(sessao.fim) if sessao.fim else None
        agregado = agregados.get(sessao.id)

        itens.append(
            ItemDoHistorico(
                id_sessao=sessao.id,
                inicio=inicio,
                fim=fim,
                parcial=sessao.fim is None,
                duracao_s=(fim - inicio).total_seconds() if fim else 0.0,
                n_leituras=agregado.n_leituras if agregado else 0,
                score_medio=agregado.score_medio if agregado else 0.0,
                teve_fadiga=agregado.teve_fadiga if agregado else False,
            )
        )
    return itens


def montar(sessao: SessaoEstudo, logs: Sequence[LogEngajamento]) -> Relatorio:
    """Monta o relatório de uma sessão a partir da série gravada.

    Função pura sobre os dados: não consulta o banco, não sabe de HTTP, e por
    isso os testes conseguem montar sessões improváveis — vazia, interrompida,
    toda sem rosto — sem subir aplicação nenhuma.
    """
    ordenados = sorted(logs, key=lambda log: como_utc(log.horario_registro))
    indicadores = _indicadores(ordenados)
    alertas = _contar_alertas(ordenados)

    return Relatorio(
        id_sessao=sessao.id,
        inicio=como_utc(sessao.inicio),
        fim=como_utc(sessao.fim) if sessao.fim else None,
        parcial=sessao.fim is None,
        indicadores=indicadores,
        serie=[
            PontoDaSerie(
                horario=como_utc(log.horario_registro),
                score=log.score,
                fadiga=log.fator_fadiga,
                alerta=log.alerta_gerado,
            )
            for log in ordenados
        ],
        alertas=alertas,
        recomendacoes=_recomendacoes(indicadores, alertas),
    )
