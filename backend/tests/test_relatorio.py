"""Testes do resumo da sessão para o relatório de autopercepção (ticket 11, E01-S01).

Seam do mesmo tipo que `app/analista.py`: função pura de série + sessão para
indicadores, sem banco, HTTP nem UI por perto. É onde a regra do relatório mora
e onde ela é barata de testar.

Como em `test_analista.py`, os valores esperados são calculados à mão a partir da
definição do indicador, nunca extraídos da implementação. Um teste que copia o
resultado do código não pega regressão — só congela o que houver lá.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app import relatorio
from app.models import LogEngajamento, SessaoEstudo

T0 = datetime(2026, 9, 19, 12, 0, 0, tzinfo=timezone.utc)


def em(segundos: float) -> datetime:
    return T0 + timedelta(seconds=segundos)


def ponto(score, segundo: int, fadiga: float = 0.0, alerta=None) -> LogEngajamento:
    """Um ponto da série, como `telemetria.registrar_log` o grava."""
    return LogEngajamento(
        id_sessao=1,
        score=score,
        fadiga=fadiga,
        alerta=alerta,
        horario_registro=em(segundo),
    )


def sessao(inicio: float = 0.0, fim=0.0) -> SessaoEstudo:
    return SessaoEstudo(
        id=1,
        id_aluno=1,
        inicio=em(inicio),
        fim=em(fim) if fim is not None else None,
        ultima_atividade=em(fim if fim is not None else inicio),
    )


class TestIndicadores:
    def test_resume_a_serie_em_media_pico_e_vale(self):
        # média de 80, 60 e 40 = 60; pico 80; vale 40. Calculado à mão.
        serie = [ponto(80.0, 0), ponto(60.0, 1), ponto(40.0, 2)]

        resumo = relatorio.resumir(sessao(fim=2), serie)

        assert resumo.media == pytest.approx(60.0)
        assert resumo.pico == pytest.approx(80.0)
        assert resumo.vale == pytest.approx(40.0)
        assert resumo.pontos_medidos == 3
        assert resumo.pontos_incertos == 0
