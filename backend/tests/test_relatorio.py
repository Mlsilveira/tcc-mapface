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
from app.relatorio import resumir_serie

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

        # Os dois pontos de `bocejos` são **contíguos**, logo um episódio só:
        # a janela de fadiga é de 60 s e mantém o rótulo aceso enquanto a
        # penalidade dura. Contar os dois separadamente é o que transformava um
        # bocejo em dezenas de "registros" na tela.
        assert resumo.alertas_de_fadiga == {"bocejos": 1, "palpebras-pesadas": 1}
        # `baixa-luz` também é contíguo: um episódio, não dois pontos.
        assert resumo.motivos_de_incerteza == {"baixa-luz": 1, "oclusao": 1}

    def test_ponto_sem_alerta_nao_entra_em_nenhum_agrupamento(self):
        serie = [ponto(80.0, 0), ponto(75.0, 1), ponto(None, 2)]

        resumo = relatorio.resumir(sessao(fim=2), serie)

        assert resumo.alertas_de_fadiga == {}
        assert resumo.motivos_de_incerteza == {}


# --- A leitura de sonolência no relatório ----------------------------------


def _ponto(segundo: int, score=70.0, sonolencia=None):
    return LogEngajamento(
        id_sessao=1,
        score=score,
        sonolencia=sonolencia,
        horario_registro=datetime(2026, 9, 24, 10, 0, segundo, tzinfo=timezone.utc),
    )


def test_a_sonolencia_media_sai_nos_indicadores():
    indicadores = resumir_serie(
        [_ponto(0, sonolencia=0.2), _ponto(1, sonolencia=0.8), _ponto(2, sonolencia=0.5)]
    )

    assert indicadores.sonolencia_media == pytest.approx(0.5)


def test_sem_leitura_de_sonolencia_o_indicador_fica_none():
    """Sessão sem modelo carregado, ou curta demais para fechar a primeira
    janela depois da calibração. `None` é "não houve leitura"; zero seria
    "o aluno estava perfeitamente desperto", que é afirmação diferente."""
    indicadores = resumir_serie([_ponto(0), _ponto(1)])

    assert indicadores.sonolencia_media is None


def test_a_sonolencia_de_um_ponto_incerto_continua_valendo():
    """Ela descreve uma janela de dez segundos, não aquele instante.

    Amarrá-la ao `score` faria um reflexo de óculos em um segundo descartar a
    leitura da janela inteira.
    """
    indicadores = resumir_serie(
        [_ponto(0, score=None, sonolencia=0.9), _ponto(1, score=None, sonolencia=0.7)]
    )

    assert indicadores.pontos_medidos == 0
    assert indicadores.sonolencia_media == pytest.approx(0.8)


def test_a_sonolencia_nao_entra_na_media_do_score():
    """A separação que a entrega inteira depende: são dois números diferentes."""
    indicadores = resumir_serie([_ponto(0, score=70.0, sonolencia=0.95)])

    assert indicadores.media == pytest.approx(70.0)
    assert indicadores.sonolencia_media == pytest.approx(0.95)


# --- Episódios, e não pontos -----------------------------------------------


def _com_alerta(segundo: int, alerta, score=70.0):
    return LogEngajamento(
        id_sessao=1,
        score=score,
        alerta=alerta,
        horario_registro=datetime(2026, 9, 24, 10, 0, segundo, tzinfo=timezone.utc),
    )


def test_um_sinal_continuo_conta_como_um_episodio():
    """O defeito que apareceu no primeiro teste com gente de verdade.

    A janela do `DetectorDeFadiga` é de 60 segundos, e o rótulo do ponto diz
    qual sinal domina a janela **naquele instante**. Um único bocejo mantinha o
    rótulo aceso em dezenas de pontos seguidos, e contar pontos virava "47
    bocejos" na tela de quem bocejou duas vezes. O número não errava por pouco:
    ele media outra coisa.
    """
    serie = [_com_alerta(s, "bocejos") for s in range(40)]

    assert resumir_serie(serie).alertas_de_fadiga == {"bocejos": 1}


def test_sinais_separados_por_silencio_sao_episodios_distintos():
    serie = (
        [_com_alerta(s, "bocejos") for s in range(5)]
        + [_com_alerta(s, None) for s in range(5, 20)]
        + [_com_alerta(s, "bocejos") for s in range(20, 25)]
    )

    assert resumir_serie(serie).alertas_de_fadiga == {"bocejos": 2}


def test_sinais_alternados_contam_cada_um_a_sua_corrida():
    serie = (
        [_com_alerta(s, "bocejos") for s in range(3)]
        + [_com_alerta(s, "palpebras-pesadas") for s in range(3, 6)]
        + [_com_alerta(s, "bocejos") for s in range(6, 9)]
    )

    assert resumir_serie(serie).alertas_de_fadiga == {
        "bocejos": 2,
        "palpebras-pesadas": 1,
    }


def test_a_incerteza_tambem_conta_por_episodio():
    """Mesma regra dos dois lados: sete segundos de reflexo são um episódio."""
    serie = [_com_alerta(s, "reflexo-ocular", score=None) for s in range(7)]

    indicadores = resumir_serie(serie)

    assert indicadores.motivos_de_incerteza == {"reflexo-ocular": 1}
    assert indicadores.alertas_de_fadiga == {}
    # A duração continua disponível, e por outro caminho: são sete pontos.
    assert indicadores.pontos_incertos == 7
