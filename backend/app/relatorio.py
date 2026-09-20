"""Resumo de uma sessão de estudo para o relatório de autopercepção (ticket 11).

Como `app/sessoes.py` e `app/analista.py`, este módulo não conhece HTTP, banco
nem UI: recebe a sessão e a série já lidas e devolve os indicadores. É o seam
que o relatório expõe ao aluno, e onde a regra é barata de testar.
"""
from dataclasses import dataclass
from statistics import mean
from typing import List, Sequence

from app.models import LogEngajamento, SessaoEstudo


@dataclass(frozen=True)
class ResumoDaSessao:
    """Os indicadores que o relatório apresenta sobre uma sessão."""

    media: float
    pico: float
    vale: float
    pontos_medidos: int
    pontos_incertos: int


def resumir(sessao: SessaoEstudo, serie: Sequence[LogEngajamento]) -> ResumoDaSessao:
    """Indicadores da sessão a partir da série gravada.

    Pontos com `score` nulo são a incerteza da ticket 10 e não entram nas
    estatísticas: não dá para afirmar nada sobre aquele segundo, e tratá-los
    como zero diria que o aluno não estava lá.
    """
    medidos: List[float] = [p.score for p in serie if p.score is not None]

    return ResumoDaSessao(
        media=mean(medidos),
        pico=max(medidos),
        vale=min(medidos),
        pontos_medidos=len(medidos),
        pontos_incertos=len(serie) - len(medidos),
    )
