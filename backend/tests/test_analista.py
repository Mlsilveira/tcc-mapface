"""Testes do `AnalistaEngajamento` — o seam principal do projeto (ticket 7).

Aqui mora a lógica de negócio do IEE, sem rede, banco nem UI, e é por isso que
estes são os testes mais valiosos da PoC. Todos batem só na interface pública
(`processar` e os dataclasses); nada aqui conhece método privado ou atributo
interno do módulo.

Os valores esperados foram calculados à mão a partir da fórmula acordada no
spec, não extraídos do código:

    IEE = P(t) × [0,6 × EAR_norm + 0,4 × HP_norm] × 100 − F

    EAR_norm = min(EAR / ear_neutro, 1)
    HP_norm  = 1 − min(√((yaw − yaw_neutro)² + (pitch − pitch_neutro)²) / 45, 1)
"""
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.analista import AnalistaEngajamento, Baseline, EstadoCalibracao

T0 = datetime(2026, 8, 17, 12, 0, 0, tzinfo=timezone.utc)

#: Aluno de padrão "típico": olho bem aberto, cabeça de frente para a tela.
BASELINE_TIPICA = Baseline(ear_neutro=0.30, yaw_neutro=0.0, pitch_neutro=0.0, amostras=60)

#: Aluno de óculos: a armação e o reflexo achatam o EAR medido, e o padrão
#: neutro dele é bem mais baixo que o do aluno "típico" — história 13 do spec.
BASELINE_OCULOS = Baseline(ear_neutro=0.18, yaw_neutro=0.0, pitch_neutro=0.0, amostras=60)


def test_sem_rosto_o_score_e_zero():
    # É o P(t) = 0 do spec: sem rosto não há comportamento observável, e
    # devolver um número degradado seria invenção.
    resultado = AnalistaEngajamento(baseline=BASELINE_TIPICA).processar(
        ear=0.30, yaw=0.0, pitch=0.0, rosto_detectado=False, agora=T0
    )

    assert resultado.score == 0.0


def test_aluno_no_proprio_neutro_pontua_o_maximo():
    # EAR_norm = 0,30/0,30 = 1; HP_norm = 1 − 0/45 = 1 → 100 × (0,6 + 0,4)
    resultado = AnalistaEngajamento(baseline=BASELINE_TIPICA).processar(
        ear=0.30, yaw=0.0, pitch=0.0, rosto_detectado=True, agora=T0
    )

    assert resultado.score == pytest.approx(100.0)
    assert resultado.calibrando is False


def test_aluno_de_oculos_no_proprio_neutro_pontua_como_o_aluno_tipico():
    # O teste mais importante do módulo (história 13): dois alunos com padrões
    # neutros bem diferentes, ambos parados no próprio neutro, recebem o mesmo
    # score. É isso que a calibração individual compra.
    tipico = AnalistaEngajamento(baseline=BASELINE_TIPICA).processar(
        ear=0.30, yaw=0.0, pitch=0.0, rosto_detectado=True, agora=T0
    )
    oculos = AnalistaEngajamento(baseline=BASELINE_OCULOS).processar(
        ear=0.18, yaw=0.0, pitch=0.0, rosto_detectado=True, agora=T0
    )

    assert oculos.score == pytest.approx(tipico.score)


def test_baseline_individual_evita_penalizar_o_padrao_atipico():
    # O mesmo EAR de 0,18 medido contra o neutro alheio (0,30) valeria
    # 0,18/0,30 = 0,6 → 100 × (0,6 × 0,6 + 0,4 × 1) = 76. Os 24 pontos de
    # diferença são exatamente o alerta injusto que a história 13 quer evitar.
    com_baseline_alheia = AnalistaEngajamento(baseline=BASELINE_TIPICA).processar(
        ear=0.18, yaw=0.0, pitch=0.0, rosto_detectado=True, agora=T0
    )
    com_baseline_propria = AnalistaEngajamento(baseline=BASELINE_OCULOS).processar(
        ear=0.18, yaw=0.0, pitch=0.0, rosto_detectado=True, agora=T0
    )

    assert com_baseline_alheia.score == pytest.approx(76.0)
    assert com_baseline_propria.score == pytest.approx(100.0)


def test_olhos_a_meio_do_proprio_neutro_derrubam_a_parcela_ocular_igual():
    # Cada aluno cerrando os olhos até a metade do próprio neutro (0,15 para o
    # típico, 0,09 para o de óculos) perde o mesmo tanto:
    # 100 × (0,6 × 0,5 + 0,4 × 1) = 70.
    tipico = AnalistaEngajamento(baseline=BASELINE_TIPICA).processar(
        ear=0.15, yaw=0.0, pitch=0.0, rosto_detectado=True, agora=T0
    )
    oculos = AnalistaEngajamento(baseline=BASELINE_OCULOS).processar(
        ear=0.09, yaw=0.0, pitch=0.0, rosto_detectado=True, agora=T0
    )

    assert tipico.score == pytest.approx(70.0)
    assert oculos.score == pytest.approx(70.0)


def test_arregalar_os_olhos_nao_passa_do_teto_da_escala():
    # Abrir mais o olho que o próprio neutro não é "mais engajado" que o máximo.
    resultado = AnalistaEngajamento(baseline=BASELINE_TIPICA).processar(
        ear=0.60, yaw=0.0, pitch=0.0, rosto_detectado=True, agora=T0
    )

    assert resultado.score == pytest.approx(100.0)


def test_head_pose_soma_yaw_e_pitch_no_mesmo_desvio():
    # Head Pose é yaw E pitch: 27° na horizontal com 36° na vertical dão um
    # desvio de √(27² + 36²) = 45°, o limite. HP_norm = 0 → 100 × 0,6 = 60.
    resultado = AnalistaEngajamento(baseline=BASELINE_TIPICA).processar(
        ear=0.30, yaw=27.0, pitch=36.0, rosto_detectado=True, agora=T0
    )

    assert resultado.score == pytest.approx(60.0)


def test_pose_neutra_inclinada_e_o_zero_do_aluno():
    # Aluno com assimetria facial (ou monitor de lado) cujo neutro é yaw 15°:
    # parado no próprio neutro pontua 100, e é olhar de frente para a câmera
    # que passa a contar como desvio de 15° → 100 × (0,6 + 0,4 × 2/3) ≈ 86,67.
    baseline = Baseline(ear_neutro=0.30, yaw_neutro=15.0, pitch_neutro=0.0, amostras=60)
    analista = AnalistaEngajamento(baseline=baseline)

    no_neutro = analista.processar(
        ear=0.30, yaw=15.0, pitch=0.0, rosto_detectado=True, agora=T0
    )
    fora_do_neutro = analista.processar(
        ear=0.30, yaw=0.0, pitch=0.0, rosto_detectado=True, agora=T0
    )

    assert no_neutro.score == pytest.approx(100.0)
    assert fora_do_neutro.score == pytest.approx(86.6666, abs=1e-3)


def test_baseline_degenerada_nao_transforma_olho_quase_fechado_em_engajamento():
    # Webcam ruim ou aluno de olhos fechados durante a calibração produz um
    # ear_neutro perto de zero. Sem piso, dividir por ele faria quase qualquer
    # EAR normalizar em 1 — olho semicerrado viraria "plenamente engajado", o
    # inverso do que a métrica quer dizer. Com o piso de 0,10 no divisor:
    # 0,05/0,10 = 0,5 → 100 × (0,6 × 0,5 + 0,4 × 1) = 70.
    baseline = Baseline(ear_neutro=0.001, yaw_neutro=0.0, pitch_neutro=0.0, amostras=60)

    resultado = AnalistaEngajamento(baseline=baseline).processar(
        ear=0.05, yaw=0.0, pitch=0.0, rosto_detectado=True, agora=T0
    )

    assert resultado.score == pytest.approx(70.0)


def test_baseline_degenerada_nao_estoura_com_divisao_por_zero():
    # ear_neutro exatamente 0 (nenhuma abertura ocular medida na calibração)
    # não pode derrubar a sessão inteira com ZeroDivisionError.
    baseline = Baseline(ear_neutro=0.0, yaw_neutro=0.0, pitch_neutro=0.0, amostras=60)

    resultado = AnalistaEngajamento(baseline=baseline).processar(
        ear=0.0, yaw=0.0, pitch=0.0, rosto_detectado=True, agora=T0
    )

    # Só a parcela de cabeça sobra: 100 × 0,4 = 40.
    assert resultado.score == pytest.approx(40.0)


def test_fadiga_desconta_pontos_do_score():
    # A fadiga real chega na ticket 8; aqui prova-se que o encaixe do "− F" da
    # fórmula existe e desconta na escala de 0 a 100.
    resultado = AnalistaEngajamento(baseline=BASELINE_TIPICA).processar(
        ear=0.30, yaw=0.0, pitch=0.0, rosto_detectado=True, agora=T0, fadiga=25.0
    )

    assert resultado.score == pytest.approx(75.0)


def test_fadiga_maior_que_o_score_nao_produz_score_negativo():
    # O clamp em 0 é o que impede a subtração da ticket 8 de furar a escala.
    resultado = AnalistaEngajamento(baseline=BASELINE_TIPICA).processar(
        ear=0.30, yaw=0.0, pitch=0.0, rosto_detectado=True, agora=T0, fadiga=140.0
    )

    assert resultado.score == 0.0


def _sessao(payloads):
    """Roda uma sequência de payloads como o router roda: um analista novo a
    cada segundo, reconstruído a partir do estado/baseline que vieram do banco.

    `payloads` é uma lista de (segundo, ear, yaw, pitch, rosto_detectado).
    """
    estado = None
    baseline = None
    resultado = None

    for segundo, ear, yaw, pitch, rosto in payloads:
        resultado = AnalistaEngajamento(baseline=baseline, estado=estado).processar(
            ear=ear,
            yaw=yaw,
            pitch=pitch,
            rosto_detectado=rosto,
            agora=T0 + timedelta(seconds=segundo),
        )
        estado, baseline = resultado.estado, resultado.baseline

    return resultado


def _calibracao(ear, yaw=0.0, pitch=0.0, ate_o_segundo=60):
    """Um payload por segundo, o aluno parado no próprio padrão neutro."""
    return _sessao(
        [(s, ear, yaw, pitch, True) for s in range(ate_o_segundo + 1)]
    )


def test_o_primeiro_payload_da_sessao_abre_a_calibracao():
    resultado = AnalistaEngajamento().processar(
        ear=0.15, yaw=0.0, pitch=0.0, rosto_detectado=True, agora=T0
    )

    assert resultado.calibrando is True
    assert resultado.baseline is None
    assert resultado.estado == EstadoCalibracao(
        inicio=T0, soma_ear=0.15, soma_yaw=0.0, soma_pitch=0.0, amostras=1
    )


def test_durante_a_calibracao_o_score_sai_pelas_referencias_padrao():
    # A calibração é silenciosa, não cega: o dashboard da ticket 9 não pode
    # ficar em branco por um minuto. EAR 0,15 contra a referência padrão de
    # 0,30 → 100 × (0,6 × 0,5 + 0,4 × 1) = 70.
    resultado = AnalistaEngajamento().processar(
        ear=0.15, yaw=0.0, pitch=0.0, rosto_detectado=True, agora=T0
    )

    assert resultado.score == pytest.approx(70.0)


def test_a_calibracao_acumula_os_payloads_seguintes():
    analista = AnalistaEngajamento(
        estado=EstadoCalibracao(
            inicio=T0, soma_ear=0.60, soma_yaw=9.0, soma_pitch=3.0, amostras=3
        )
    )

    resultado = analista.processar(
        ear=0.20,
        yaw=3.0,
        pitch=1.0,
        rosto_detectado=True,
        agora=T0 + timedelta(seconds=3),
    )

    assert resultado.calibrando is True
    assert resultado.estado.inicio == T0
    assert resultado.estado.amostras == 4
    assert resultado.estado.soma_ear == pytest.approx(0.80)
    assert resultado.estado.soma_yaw == pytest.approx(12.0)
    assert resultado.estado.soma_pitch == pytest.approx(4.0)


def test_um_segundo_antes_do_fim_da_janela_ainda_esta_calibrando():
    resultado = _calibracao(ear=0.18, ate_o_segundo=59)

    assert resultado.calibrando is True
    assert resultado.baseline is None


def test_ao_fechar_a_janela_a_baseline_e_a_media_do_que_foi_medido():
    resultado = _calibracao(ear=0.18, yaw=5.0, pitch=-2.0, ate_o_segundo=60)

    assert resultado.calibrando is False
    assert resultado.estado is None
    assert resultado.baseline.ear_neutro == pytest.approx(0.18)
    assert resultado.baseline.yaw_neutro == pytest.approx(5.0)
    assert resultado.baseline.pitch_neutro == pytest.approx(-2.0)
    assert resultado.baseline.amostras == 61


def test_sem_rosto_durante_a_calibracao_zera_o_score_e_descarta_o_acumulado():
    # Meio minuto de calibração e o aluno sai de quadro: o acumulado vai fora.
    resultado = _sessao(
        [(s, 0.30, 0.0, 0.0, True) for s in range(30)] + [(30, 0.0, 0.0, 0.0, False)]
    )

    assert resultado.score == 0.0
    assert resultado.calibrando is True
    assert resultado.estado is None


def test_depois_da_ausencia_a_janela_de_60s_recomeça_do_zero():
    # 30s medindo EAR 0,30, uma ausência, e o aluno volta com EAR 0,18. A
    # baseline final tem de ser 0,18 — se o acumulado antigo sobrevivesse, a
    # média sairia misturada (~0,22) e não representaria nem um aluno nem outro.
    # A janela nova começa no retorno (s=31) e só fecha em s=91.
    payloads = (
        [(s, 0.30, 0.0, 0.0, True) for s in range(30)]
        + [(30, 0.0, 0.0, 0.0, False)]
        + [(s, 0.18, 0.0, 0.0, True) for s in range(31, 92)]
    )

    ainda_calibrando = _sessao(payloads[:-1])
    resultado = _sessao(payloads)

    assert ainda_calibrando.calibrando is True
    assert resultado.calibrando is False
    assert resultado.baseline.ear_neutro == pytest.approx(0.18)
    assert resultado.baseline.amostras == 61


def test_a_baseline_calibrada_do_aluno_de_oculos_o_pontua_no_maximo():
    # A história 13 ponta a ponta: o aluno de óculos passa pela calibração real
    # e, parado no padrão que ele mesmo mostrou, tira 100 — sem nunca ter sido
    # comparado ao olho de outra pessoa.
    calibrado = _calibracao(ear=0.18)

    depois = AnalistaEngajamento(baseline=calibrado.baseline).processar(
        ear=0.18, yaw=0.0, pitch=0.0, rosto_detectado=True, agora=T0 + timedelta(seconds=61)
    )

    assert depois.score == pytest.approx(100.0)
    assert depois.calibrando is False


def test_a_baseline_volta_para_o_chamador_persistir_a_cada_payload():
    # O analista é reconstruído a cada payload a partir do banco, então o
    # Resultado precisa carregar de volta o que deve ser gravado.
    resultado = AnalistaEngajamento(baseline=BASELINE_OCULOS).processar(
        ear=0.18, yaw=0.0, pitch=0.0, rosto_detectado=True, agora=T0
    )

    assert resultado.baseline == BASELINE_OCULOS
    assert resultado.estado is None


def test_processar_nao_guarda_estado_no_proprio_analista():
    # Duas chamadas no mesmo objeto não podem acumular entre si: quem acumula é
    # o chamador, repassando o estado devolvido. Sem isso, uma reconexão de
    # WebSocket mudaria silenciosamente o resultado da calibração.
    analista = AnalistaEngajamento()

    primeira = analista.processar(
        ear=0.20, yaw=0.0, pitch=0.0, rosto_detectado=True, agora=T0
    )
    segunda = analista.processar(
        ear=0.20, yaw=0.0, pitch=0.0, rosto_detectado=True, agora=T0 + timedelta(seconds=1)
    )

    assert primeira.estado.amostras == 1
    assert segunda.estado.amostras == 1
    assert segunda.estado.inicio == T0 + timedelta(seconds=1)


def test_o_seam_nao_arrasta_banco_nem_framework_web():
    # O valor deste módulo é poder rodar sem subir nada. Importá-lo não pode
    # puxar sqlmodel nem fastapi junto — o dia em que puxar, os testes acima
    # deixam de ser unitários e a ticket 8 herda o problema.
    codigo = (
        "import sys; import app.analista; "
        "print(sorted(m for m in ('sqlmodel', 'fastapi', 'sqlalchemy') "
        "if m in sys.modules))"
    )
    saida = subprocess.run(
        [sys.executable, "-c", codigo],
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=True,
        text=True,
        check=True,
    )

    assert saida.stdout.strip() == "[]"
