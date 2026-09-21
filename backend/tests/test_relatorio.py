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


class TestSeriesDegeneradas:
    """Sessões sem nada para medir.

    As duas caem no mesmo caminho — nenhum ponto medido —, mas dizem coisas
    diferentes ao aluno: uma sessão sem série é uma sessão que mal começou; uma
    sessão inteiramente incerta é uma sessão em que a câmera não deu conta. Em
    nenhuma das duas o indicador pode ser zero: zero é "o aluno estava aqui e
    desengajado", que é uma afirmação que estes dados não sustentam.
    """

    def test_serie_vazia_nao_e_erro(self):
        resumo = relatorio.resumir(sessao(fim=0), [])

        assert resumo.media is None
        assert resumo.pico is None
        assert resumo.vale is None
        assert resumo.pontos_medidos == 0
        assert resumo.pontos_incertos == 0

    def test_serie_inteiramente_incerta_nao_vira_zero(self):
        serie = [
            ponto(None, 0, alerta="baixa-luz"),
            ponto(None, 1, alerta="baixa-luz"),
            ponto(None, 2, alerta="reflexo-ocular"),
        ]

        resumo = relatorio.resumir(sessao(fim=2), serie)

        assert resumo.media is None
        assert resumo.pico is None
        assert resumo.vale is None
        assert resumo.pontos_medidos == 0
        assert resumo.pontos_incertos == 3


class TestZeradoNaoEIncerto:
    """Medir zero não é deixar de medir, e o relatório não pode confundir os dois.

    `score = 0.0` é uma medição verdadeira. `score = None` é incerteza de
    captura: havia rosto, mas as condições não sustentam número nenhum. Somar os
    dois apagaria a distinção que a ticket 10 comprou.

    O que o zero **não** diz é a causa. `calcular_iee` devolve 0.0 no `P(t) = 0`
    (rosto ausente) e também no `max(0.0, bruto - fadiga)` de um aluno presente
    que a fadiga zerou. `log_engajamento` não guarda `rosto_detectado`, então
    nenhum indicador separa os dois com os dados de hoje — daí o nome
    `pontos_zerados`, e não `pontos_ausentes`.
    """

    def test_incerteza_no_meio_nao_puxa_a_media(self):
        # média de 80 e 40 = 60. Os nulos no meio não entram como zero.
        serie = [
            ponto(80.0, 0),
            ponto(None, 1, alerta="baixa-luz"),
            ponto(None, 2, alerta="baixa-luz"),
            ponto(40.0, 3),
        ]

        resumo = relatorio.resumir(sessao(fim=3), serie)

        assert resumo.media == pytest.approx(60.0)
        assert resumo.pontos_medidos == 2
        assert resumo.pontos_incertos == 2

    def test_score_zerado_conta_separado_da_incerteza(self):
        serie = [
            ponto(80.0, 0),
            ponto(0.0, 1),  # medição verdadeira que deu zero
            ponto(None, 2, alerta="oclusao"),  # incerteza: recusa de medir
        ]

        resumo = relatorio.resumir(sessao(fim=2), serie)

        assert resumo.pontos_zerados == 1
        assert resumo.pontos_incertos == 1
        # zero é medição, então continua dentro de `pontos_medidos` e da média
        assert resumo.pontos_medidos == 2
        assert resumo.media == pytest.approx(40.0)


class TestAlertas:
    """O que o relatório conta ao aluno sobre o que saiu do normal na sessão.

    A coluna `alerta` guarda **um rótulo só**, e qual deles depende do `score`:
    sob incerteza é o motivo dela (`baixa-luz`, `reflexo-ocular`, `oclusao`,
    `desconhecida`); havendo score, é o motivo dominante da fadiga
    (`palpebras-pesadas`, `olhos-fechados-prolongados`, `bocejos`). Quem decide é
    `_alerta_do`, em `routers/telemetria.py`.

    Por isso o agrupamento é por `score is None`, não por rótulo. Misturar os
    dois vocabulários numa lista só diria ao aluno que "a sala estava escura" e
    "você bocejou" são a mesma espécie de acontecimento — uma é diagnóstico do
    equipamento, a outra é observação sobre ele.
    """

    def test_separa_alertas_de_fadiga_dos_motivos_de_incerteza(self):
        serie = [
            ponto(70.0, 0, fadiga=10.0, alerta="bocejos"),
            ponto(65.0, 1, fadiga=12.0, alerta="bocejos"),
            ponto(60.0, 2, fadiga=20.0, alerta="palpebras-pesadas"),
            ponto(None, 3, alerta="baixa-luz"),
            ponto(None, 4, alerta="baixa-luz"),
            ponto(None, 5, alerta="oclusao"),
        ]

        resumo = relatorio.resumir(sessao(fim=5), serie)

        assert resumo.alertas_de_fadiga == {"bocejos": 2, "palpebras-pesadas": 1}
        assert resumo.motivos_de_incerteza == {"baixa-luz": 2, "oclusao": 1}

    def test_ponto_sem_alerta_nao_entra_em_nenhum_agrupamento(self):
        serie = [ponto(80.0, 0), ponto(75.0, 1), ponto(None, 2)]

        resumo = relatorio.resumir(sessao(fim=2), serie)

        assert resumo.alertas_de_fadiga == {}
        assert resumo.motivos_de_incerteza == {}
