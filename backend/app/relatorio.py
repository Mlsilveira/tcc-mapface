"""Resumo de uma sessão de estudo para o relatório de autopercepção (ticket 11).

Como `app/sessoes.py` e `app/analista.py`, este módulo não conhece HTTP, banco
nem UI: recebe a sessão e a série já lidas e devolve os indicadores. É o seam
que o relatório expõe ao aluno, e onde a regra é barata de testar.
"""
from dataclasses import dataclass
from statistics import mean
from typing import List, Optional, Sequence

from app.models import LogEngajamento, SessaoEstudo


@dataclass(frozen=True)
class ResumoDaSessao:
    """Os indicadores que o relatório apresenta sobre uma sessão.

    `media`, `pico` e `vale` são `None` quando não houve nenhuma medida — sessão
    que mal começou, ou sessão inteira em incerteza de captura. O `None` é o que
    permite ao relatório dizer "não deu para medir"; zero diria "o aluno estava
    aqui e desengajado", que é uma afirmação diferente e que estes dados não
    sustentam.
    """

    media: Optional[float]
    pico: Optional[float]
    vale: Optional[float]
    pontos_medidos: int
    pontos_incertos: int
    pontos_zerados: int


def resumir(sessao: SessaoEstudo, serie: Sequence[LogEngajamento]) -> ResumoDaSessao:
    """Indicadores da sessão a partir da série gravada.

    Pontos com `score` nulo são a incerteza da ticket 10 e não entram nas
    estatísticas: não dá para afirmar nada sobre aquele segundo, e tratá-los
    como zero diria que o aluno não estava lá.
    """
    medidos: List[float] = [p.score for p in serie if p.score is not None]
    houve_medida = bool(medidos)

    # Score zero é medição verdadeira — diferente da incerteza, que é a recusa
    # de medir —, então continua dentro de `pontos_medidos` e da média.
    #
    # O que ele **não** diz é a causa. `calcular_iee` devolve 0.0 tanto no
    # `P(t) = 0` (rosto ausente) quanto no `max(0.0, bruto - fadiga)` de um
    # aluno presente que a fadiga zerou. Separar os dois exigiria um
    # `rosto_detectado` em `log_engajamento`, que não existe; por isso o
    # indicador se chama "zerados" e não "ausentes". Ver risk-spots.md.
    zerados = [s for s in medidos if s == 0.0]

    return ResumoDaSessao(
        media=mean(medidos) if houve_medida else None,
        pico=max(medidos) if houve_medida else None,
        vale=min(medidos) if houve_medida else None,
        pontos_medidos=len(medidos),
        pontos_incertos=len(serie) - len(medidos),
        pontos_zerados=len(zerados),
    )
