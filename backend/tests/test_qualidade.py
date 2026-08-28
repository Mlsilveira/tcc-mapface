"""Testes do alerta de Incerteza de Captura (ticket 10).

Os limiares foram calibrados contra sessões reais de webcam de 28/08/2026, e os
testes abaixo usam esses números como referência do que é captura boa:

    jitter mediano do EAR entre leituras vizinhas .... 0,034 (p90 0,095)
    sumiços breves do rosto ......................... 0

O risco desta ticket não é deixar de detectar captura ruim — é **alarmar em
captura boa**. Um alerta que aparece durante uma sessão normal treina o aluno a
ignorá-lo, e aí ele deixa de servir quando a captura estraga de verdade. Por
isso metade dos testes aqui afirma que o alerta *não* dispara.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.qualidade import (
    ALERTA_INCERTEZA,
    LIMIAR_JITTER_MEDIANO,
    MINIMO_SUMICOS_BREVES,
    MOTIVO_DETECCAO,
    MOTIVO_MEDIDA,
    DetectorDeIncerteza,
)

T0 = datetime(2026, 8, 28, 15, 0, 0, tzinfo=timezone.utc)

#: EAR típico de captura boa, alternando dentro do jitter observado (~0,03).
BOM = [0.25, 0.28, 0.26, 0.27, 0.25, 0.28, 0.26, 0.27, 0.25, 0.28, 0.26, 0.27]


def em(segundos: float) -> datetime:
    return T0 + timedelta(seconds=segundos)


def roda(ears, presencas=None):
    detector = DetectorDeIncerteza()
    resultado = None
    for i, ear in enumerate(ears):
        resultado = detector.observar(
            ear=ear,
            rosto_detectado=(presencas[i] if presencas else True),
            agora=em(i),
        )
    return resultado


# --- Captura boa não alarma ------------------------------------------------


def test_captura_estavel_e_confiavel():
    qualidade = roda(BOM * 2)

    assert qualidade.confiavel is True
    assert qualidade.motivo is None
    assert qualidade.alertas == ()


def test_o_jitter_de_uma_sessao_real_boa_fica_abaixo_do_limiar():
    """Referência empírica: a sessão de 28/08 deu 0,034 de jitter mediano."""
    qualidade = roda(BOM * 2)

    assert qualidade.jitter_mediano < LIMIAR_JITTER_MEDIANO
    assert qualidade.jitter_mediano == pytest.approx(0.02, abs=0.02)


def test_um_bocejo_isolado_nao_torna_a_captura_incerta():
    """O bocejo derruba o EAR de vez e o traz de volta — dois saltos grandes.

    É por isso que o sinal usa a **mediana** e não a média: para a mediana subir,
    a maioria dos pares precisa estar saltando, e não um evento isolado.
    """
    ears = list(BOM * 2)
    ears[10:13] = [0.09, 0.08, 0.09]  # olhos semicerrados durante o bocejo

    assert roda(ears).confiavel is True


def test_uma_ausencia_longa_nao_e_problema_de_captura():
    """O aluno se levantou. Isso é o `P(t) = 0` da ticket 7, não incerteza."""
    ears = BOM * 2
    presencas = [not (8 <= i <= 16) for i in range(len(ears))]

    qualidade = roda(ears, presencas)

    assert qualidade.confiavel is True
    assert qualidade.sumicos_breves == 0


def test_janela_curta_demais_nao_e_julgada():
    # Sem amostras suficientes, uma mediana não significa nada — e o começo de
    # toda sessão apareceria como incerto.
    assert roda([0.25, 0.05, 0.30]).confiavel is True


# --- Detecção instável -----------------------------------------------------


def test_sumicos_breves_e_repetidos_marcam_incerteza():
    """Landmarks que não se firmam produzem piscadas de detecção.

    Nas sessões reais medidas houve zero sumiços breves; três já é sintoma.
    """
    ears = BOM * 2
    # Some por 1 s, volta, três vezes.
    presencas = [i not in (4, 8, 12) for i in range(len(ears))]

    qualidade = roda(ears, presencas)

    assert qualidade.confiavel is False
    assert qualidade.motivo == MOTIVO_DETECCAO
    assert qualidade.sumicos_breves >= MINIMO_SUMICOS_BREVES
    assert qualidade.alertas == (ALERTA_INCERTEZA,)


def test_dois_sumicos_ainda_nao_bastam():
    # Folga deliberada: um tropeço isolado do detector não pode alarmar.
    ears = BOM * 2
    presencas = [i not in (4, 8) for i in range(len(ears))]

    assert roda(ears, presencas).confiavel is True


def test_ausencia_em_curso_no_fim_da_janela_nao_conta_como_sumico():
    """Enquanto a ausência não termina, não dá para saber se foi tropeço do
    detector ou o aluno tendo se levantado — e chutar o primeiro produziria
    alerta toda vez que alguém saísse da mesa."""
    ears = BOM * 2
    presencas = [i < len(ears) - 2 for i in range(len(ears))]

    assert roda(ears, presencas).sumicos_breves == 0


# --- Medida instável -------------------------------------------------------


def test_ear_saltando_entre_leituras_marca_incerteza():
    # Landmarks instáveis: o EAR pula de um extremo ao outro a cada leitura.
    ears = [0.05 if i % 2 else 0.35 for i in range(24)]

    qualidade = roda(ears)

    assert qualidade.confiavel is False
    assert qualidade.motivo == MOTIVO_MEDIDA
    assert qualidade.jitter_mediano > LIMIAR_JITTER_MEDIANO


def test_deteccao_instavel_manda_quando_os_dois_sinais_disparam():
    """Sem rosto firme, o EAR nem chega a ser medido de forma comparável: o
    jitter é consequência, e o motivo reportado tem que ser a causa."""
    ears = [0.05 if i % 2 else 0.35 for i in range(24)]
    presencas = [i not in (4, 8, 12) for i in range(len(ears))]

    assert roda(ears, presencas).motivo == MOTIVO_DETECCAO


def test_a_janela_desliza_e_a_captura_se_recupera():
    """Incerteza é estado, não sentença: a nuvem passa e o alerta some."""
    detector = DetectorDeIncerteza()
    for i in range(24):
        detector.observar(ear=(0.05 if i % 2 else 0.35), agora=em(i))
    assert detector.observar(ear=0.26, agora=em(24)).confiavel is False

    # Meio minuto de captura boa depois: a janela de 30 s já não tem o ruído.
    for i, ear in enumerate(BOM * 3):
        qualidade = detector.observar(ear=ear, agora=em(60 + i))

    assert qualidade.confiavel is True


# --- Integração com o analista ---------------------------------------------


def _analista_com_captura_ruim():
    """Alimenta um analista com landmarks instáveis e devolve o último resultado."""
    from app.analista import AnalistaEngajamento

    a = AnalistaEngajamento()
    resultado = None
    for i in range(24):
        resultado = a.observar(ear=(0.05 if i % 2 else 0.35), yaw=0.0, agora=em(i))
    return a, resultado


def test_o_resultado_do_iee_carrega_a_qualidade_da_captura():
    _, resultado = _analista_com_captura_ruim()

    assert resultado.qualidade.confiavel is False


def test_leitura_incerta_nao_alimenta_a_calibracao():
    """Calibrar contra landmarks instáveis fixaria uma baseline ruim para a
    sessão inteira — e a baseline é o que todo o resto é medido contra."""
    from app.analista import AnalistaEngajamento

    a = AnalistaEngajamento()
    # Um minuto inteiro de captura instável: sem a proteção, a calibração
    # fecharia com a mediana desse ruído.
    for i in range(61):
        a.observar(ear=(0.05 if i % 2 else 0.35), yaw=0.0, agora=em(i))

    assert a.calibrando is True, "a baseline não pode fechar sobre captura instável"


def test_leitura_incerta_nao_alimenta_a_fadiga():
    """Um EAR que salta produziria fechamentos e microssonos que nunca
    aconteceram."""
    _, resultado = _analista_com_captura_ruim()

    assert resultado.fadiga.fator == 0.0
    assert resultado.fadiga.motivos == ()


def test_captura_boa_volta_a_alimentar_a_calibracao():
    # A proteção não pode travar a calibração para sempre depois de um trecho
    # ruim: passada a instabilidade, o minuto volta a contar.
    from app.analista import AnalistaEngajamento

    a = AnalistaEngajamento()
    for i in range(24):
        a.observar(ear=(0.05 if i % 2 else 0.35), yaw=0.0, agora=em(i))
    for i in range(120):
        a.observar(ear=0.26, yaw=0.0, agora=em(60 + i))

    assert a.calibrando is False
    assert a.baseline.ear_neutro == pytest.approx(0.26)
