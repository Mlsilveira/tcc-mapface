"""Resumo de uma sessão de estudo para o relatório de autopercepção (ticket 11).

Como `app/sessoes.py` e `app/analista.py`, este módulo não conhece HTTP, banco
nem UI: recebe a sessão e a série já lidas e devolve os indicadores. É o seam
que o relatório expõe ao aluno, e onde a regra é barata de testar.
"""
from collections import Counter
from dataclasses import dataclass
from datetime import timedelta
from statistics import mean
from typing import TYPE_CHECKING, Dict, List, Optional, Sequence, Tuple

from app import presenca, recomendacoes
from app.models import ENCERRAMENTO_POR_INATIVIDADE, LogEngajamento, SessaoEstudo

if TYPE_CHECKING:  # pragma: no cover - só para o verificador de tipos
    # Importado apenas para anotação, pelo mesmo motivo que `recomendacoes` faz
    # o inverso: em tempo de execução é `app.criterios` que depende daqui, para
    # reusar `resumir_serie` em cada bloco. Amarrar as duas direções faria um
    # ciclo de import, e o preço dele seria pago na primeira vez que alguém
    # importasse os módulos numa ordem diferente.
    from app.criterios import Avaliacao


@dataclass(frozen=True)
class ResumoDaSessao:
    """Os indicadores que o relatório apresenta sobre uma sessão.

    `media`, `pico` e `vale` são `None` quando não houve nenhuma medida — sessão
    que mal começou, ou sessão inteira em incerteza de captura. O `None` é o que
    permite ao relatório dizer "não deu para medir"; zero diria "o aluno estava
    aqui e desengajado", que é uma afirmação diferente e que estes dados não
    sustentam.

    Os dois agrupamentos de alerta são separados de propósito: fadiga é
    observação sobre o aluno, incerteza é diagnóstico do equipamento.

    As duas durações também são separadas de propósito, e a comparação entre
    elas é metade do valor do relatório: `duracao_total` é quanto tempo a sessão
    ficou aberta, `duracao_presente` é quanto tempo houve captura de fato. Quem
    abre o relatório e lê "2h de sessão, 40min medidos" aprende algo sobre a
    própria tarde que nenhum dos dois números diria sozinho.
    """

    media: Optional[float]
    pico: Optional[float]
    vale: Optional[float]
    pontos_medidos: int
    pontos_incertos: int
    pontos_zerados: int
    alertas_de_fadiga: Dict[str, int]
    motivos_de_incerteza: Dict[str, int]

    #: Média da probabilidade de sonolência lida pelo classificador treinado no
    #: UTA-RLDD, ou `None` quando não houve leitura — sem modelo carregado, ou
    #: sessão curta demais para fechar a primeira janela depois da calibração.
    #:
    #: **É uma segunda opinião, não o fator de fadiga.** `alertas_de_fadiga`
    #: continua vindo das regras, e é ele que explica o desconto no score. Este
    #: número existe para o aluno e a orientação verem os dois lado a lado — e
    #: para a decisão de promover um ao outro, se vier, ser tomada com dado na
    #: mão em vez de por analogia.
    sonolencia_media: Optional[float] = None
    duracao_total: timedelta = timedelta(0)
    duracao_presente: timedelta = timedelta(0)


@dataclass(frozen=True)
class IndicadoresDaSerie:
    """O que se pode dizer de um **trecho** de série, sem saber de que sessão é.

    Extraído de `resumir` quando os blocos entraram (ticket 17): a mesma conta
    passou a valer para a sessão inteira e para cada bloco de foco dentro dela, e
    duas cópias dela divergiriam no dia em que alguém corrigisse uma só. A
    diferença entre este tipo e `ResumoDaSessao` é exatamente o que **não** cabe
    num trecho: as duas durações, que dependem de `inicio` e `fim` da sessão.
    """

    media: Optional[float]
    pico: Optional[float]
    vale: Optional[float]
    pontos_medidos: int
    pontos_incertos: int
    pontos_zerados: int
    alertas_de_fadiga: Dict[str, int]
    motivos_de_incerteza: Dict[str, int]

    #: Média da probabilidade de sonolência lida pelo classificador treinado no
    #: UTA-RLDD, ou `None` quando não houve leitura — sem modelo carregado, ou
    #: sessão curta demais para fechar a primeira janela depois da calibração.
    #:
    #: **É uma segunda opinião, não o fator de fadiga.** `alertas_de_fadiga`
    #: continua vindo das regras, e é ele que explica o desconto no score. Este
    #: número existe para o aluno e a orientação verem os dois lado a lado — e
    #: para a decisão de promover um ao outro, se vier, ser tomada com dado na
    #: mão em vez de por analogia.
    sonolencia_media: Optional[float] = None


def resumir_serie(serie: Sequence[LogEngajamento]) -> IndicadoresDaSerie:
    """Os indicadores de um trecho de série, do tamanho que ele for.

    Pontos com `score` nulo são a incerteza da ticket 10 e não entram nas
    estatísticas: não dá para afirmar nada sobre aquele segundo, e tratá-los
    como zero diria que o aluno não estava lá.
    """
    medidos: List[float] = [p.score for p in serie if p.score is not None]
    houve_medida = bool(medidos)

    # Independente de `score`: a sonolência descreve uma janela de dez segundos,
    # não aquele instante. Amarrá-la ao score descartaria janelas inteiras por
    # causa de um reflexo de óculos em um segundo.
    sonolencias = [p.sonolencia for p in serie if p.sonolencia is not None]

    # Score zero é medição verdadeira — diferente da incerteza, que é a recusa
    # de medir —, então continua dentro de `pontos_medidos` e da média.
    #
    # O que ele **não** diz é a causa. `calcular_iee` devolve 0.0 tanto no
    # `P(t) = 0` (rosto ausente) quanto no `max(0.0, bruto - fadiga)` de um
    # aluno presente que a fadiga zerou. Separar os dois exigiria um
    # `rosto_detectado` em `log_engajamento`, que não existe; por isso o
    # indicador se chama "zerados" e não "ausentes". Ver risk-spots.md.
    zerados = [s for s in medidos if s == 0.0]

    # O agrupamento é por `score is None`, não pelo texto do rótulo: é o `score`
    # que decide qual vocabulário a coluna `alerta` está usando naquele ponto
    # (ver `_alerta_do`, em routers/telemetria.py). Classificar pelo rótulo
    # deixaria um motivo novo cair silenciosamente no balde errado.
    fadiga = Counter(p.alerta for p in serie if p.score is not None and p.alerta)
    incerteza = Counter(p.alerta for p in serie if p.score is None and p.alerta)

    return IndicadoresDaSerie(
        media=mean(medidos) if houve_medida else None,
        pico=max(medidos) if houve_medida else None,
        vale=min(medidos) if houve_medida else None,
        pontos_medidos=len(medidos),
        pontos_incertos=len(serie) - len(medidos),
        pontos_zerados=len(zerados),
        alertas_de_fadiga=dict(fadiga),
        motivos_de_incerteza=dict(incerteza),
        sonolencia_media=mean(sonolencias) if sonolencias else None,
    )


def resumir(sessao: SessaoEstudo, serie: Sequence[LogEngajamento]) -> ResumoDaSessao:
    """Indicadores da sessão a partir da série gravada.

    Assinatura e comportamento **intocados** pela ticket 17: o que mudou é que a
    aritmética mora em `resumir_serie` e esta função acrescenta a ela o que só a
    sessão sabe, que são as duas durações. Decomposição, não redesenho —
    `test_relatorio.py` continua valendo sem uma linha de edição, e
    `test_criterios.py` tem um teste afirmando que as duas concordam.
    """
    indicadores = resumir_serie(serie)

    return ResumoDaSessao(
        media=indicadores.media,
        pico=indicadores.pico,
        vale=indicadores.vale,
        pontos_medidos=indicadores.pontos_medidos,
        pontos_incertos=indicadores.pontos_incertos,
        pontos_zerados=indicadores.pontos_zerados,
        alertas_de_fadiga=indicadores.alertas_de_fadiga,
        motivos_de_incerteza=indicadores.motivos_de_incerteza,
        sonolencia_media=indicadores.sonolencia_media,
        duracao_total=presenca.duracao_total(sessao.inicio, sessao.fim),
        # Os pontos incertos entram como evidência de presença junto com os
        # medidos: incerteza é a recusa de afirmar um *score*, não a afirmação
        # de que não havia ninguém ali. Uma sala escura não esvazia a cadeira.
        duracao_presente=presenca.duracao_presente(
            sessao.inicio, sessao.fim, (p.horario_registro for p in serie)
        ),
    )


@dataclass(frozen=True)
class RelatorioDaSessao:
    """O relatório inteiro: o que foi medido, a curva e o que fazer a respeito.

    `parcial` é a AC-11-4. Uma sessão que o aluno encerrou tem `fim` no instante
    do clique; uma que caiu — queda de conexão, navegador fechado, máquina
    suspensa — é fechada pela varredura de inatividade, e o `fim` dela é o
    último sinal recebido. O relatório sai nos dois casos, mas só no segundo ele
    precisa avisar que o fim da sessão foi inferido, e não observado.

    Sessão anterior à ticket 11 não tem `encerramento` gravado, e é tratada como
    não-parcial: sem a marca não dá para afirmar que foi interrompida, e marcar
    todas as antigas como parciais seria inventar uma informação que o banco não
    tem.
    """

    sessao: SessaoEstudo
    resumo: ResumoDaSessao
    serie: Sequence[LogEngajamento]
    recomendacoes: Tuple[recomendacoes.Recomendacao, ...]
    parcial: bool

    #: A leitura da sessão pelo método declarado, ou `None` quando não houve
    #: método (AC-17-11). O `None` atravessa até a tela de propósito: sessão com
    #: `metodo IS NULL` é anterior ao recurso, e uma seção de método vazia diria
    #: ao aluno que ele escolheu estudar sem método — que é `"livre"`, uma
    #: escolha, e não a ausência de uma.
    avaliacao: Optional["Avaliacao"] = None


def montar(
    sessao: SessaoEstudo,
    serie: Sequence[LogEngajamento],
    resumo: Optional[ResumoDaSessao] = None,
    avaliacao: Optional["Avaliacao"] = None,
) -> RelatorioDaSessao:
    """Junta indicadores, curva, critérios do método e recomendações numa peça só.

    `resumo` é opcional porque ele pode vir congelado de `resumo_sessao`
    (ticket 13) em vez de ser recalculado: depois que a série é colapsada em
    médias por minuto, recalcular daria números diferentes dos que o aluno viu
    no dia seguinte à sessão.

    `avaliacao` chega pronta, de `criterios.avaliar`, em vez de ser construída
    aqui. Não é preferência de estilo: `app.criterios` precisa de
    `resumir_serie` para cada bloco, e chamá-lo daqui fecharia um ciclo de
    import entre os dois módulos. O composto continua sendo um só — quem monta
    o relatório junta as quatro peças —, e nenhuma decisão sobre método vazou
    para a borda HTTP: `avaliar` devolve `None` sozinho quando não houve método.
    """
    resumo = resumo if resumo is not None else resumir(sessao, serie)

    return RelatorioDaSessao(
        sessao=sessao,
        resumo=resumo,
        serie=serie,
        recomendacoes=recomendacoes.recomendar(resumo),
        parcial=sessao.encerramento == ENCERRAMENTO_POR_INATIVIDADE,
        avaliacao=avaliacao,
    )
