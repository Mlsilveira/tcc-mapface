"""Testes do fator de fadiga (ticket 8).

O `F` da fórmula do IEE vem de **regras diretas** sobre a série de EAR e MAR, e
não do Random Forest da ticket 2. A razão está medida em `resultado_18_08.md`: o
modelo treinado no DAiSEE empata com um classificador que responde sempre
"engajado", então o `F` derivado dele seria constante e a penalidade nunca
existiria na prática. Fadiga, diferente de engajamento, é estado físico
observável — e regra sobre estado observável é testável com sequência sintética,
que é exatamente o que este arquivo faz.

Todas as sequências abaixo são construídas à mão, a 1 Hz, com os valores
esperados calculados a partir das constantes acordadas:

    PERCLOS = tempo com pálpebra fechada / tempo com rosto visível
    penalidade_perclos = 25 × (PERCLOS − 0,15) / (0,40 − 0,15), limitada a [0, 25]
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.analista import (
    BASELINE_PROVISORIA,
    FADIGA_MAXIMA,
    PENALIDADE_MICROSSONO,
    PENALIDADE_PERCLOS_MAX,
    PENALIDADE_POR_BOCEJO,
    AnalistaEngajamento,
    Baseline,
    DetectorDeFadiga,
)

T0 = datetime(2026, 8, 18, 12, 0, 0, tzinfo=timezone.utc)

#: Com a baseline provisória (EAR neutro 0,30) o limiar de fechamento é 0,15.
EAR_ABERTO = 0.30
EAR_FECHADO = 0.05

MAR_FECHADA = 0.02
MAR_BOCEJO = 0.45


def em(segundos: float) -> datetime:
    return T0 + timedelta(seconds=segundos)


def roda(estados, mars=None, baseline=BASELINE_PROVISORIA, presencas=None):
    """Alimenta o detector a 1 Hz com uma sequência de EARs e devolve a fadiga."""
    detector = DetectorDeFadiga()
    fadiga = None
    for i, ear in enumerate(estados):
        fadiga = detector.observar(
            agora=em(i),
            ear=ear,
            baseline=baseline,
            mar=(mars[i] if mars else None),
            rosto_detectado=(presencas[i] if presencas else True),
        )
    return fadiga


# --- Ausência de fadiga ----------------------------------------------------


def test_olhos_abertos_o_tempo_todo_nao_geram_fadiga():
    fadiga = roda([EAR_ABERTO] * 61)

    assert fadiga.fator == 0.0
    assert fadiga.perclos == 0.0
    assert fadiga.motivos == ()


def test_uma_leitura_isolada_nao_gera_fadiga():
    # Sem dois pontos não há intervalo, e sem intervalo não há tempo medido.
    detector = DetectorDeFadiga()
    assert detector.observar(agora=T0, ear=EAR_FECHADO, baseline=BASELINE_PROVISORIA).fator == 0.0


def test_piscadas_normais_ficam_abaixo_do_limiar():
    """Piscar ocupa ~3–5% do tempo. Penalizar isso seria penalizar estar vivo."""
    # 1 segundo fechado a cada 20 → PERCLOS = 3/60 = 0,05
    estados = [EAR_FECHADO if i % 20 == 0 else EAR_ABERTO for i in range(61)]
    fadiga = roda(estados)

    assert fadiga.perclos == pytest.approx(0.05)
    assert fadiga.fator == 0.0


# --- PERCLOS ---------------------------------------------------------------


def test_perclos_acima_do_limiar_penaliza_proporcionalmente():
    # 1 fechado a cada 4 → 15 dos 60 intervalos → PERCLOS = 0,25
    # penalidade = 25 × (0,25 − 0,15)/0,25 = 25 × 0,4 = 10
    estados = [EAR_FECHADO if i % 4 == 0 else EAR_ABERTO for i in range(61)]
    fadiga = roda(estados)

    assert fadiga.perclos == pytest.approx(0.25)
    assert fadiga.fator == pytest.approx(10.0)
    assert "palpebras-pesadas" in fadiga.motivos


def test_perclos_saturado_da_a_penalidade_maxima():
    # Alternando → PERCLOS = 0,50, acima da saturação de 0,40.
    # Alternar mantém a maior corrida em 1 s, isolando o PERCLOS do microssono.
    estados = [EAR_FECHADO if i % 2 == 0 else EAR_ABERTO for i in range(61)]
    fadiga = roda(estados)

    assert fadiga.perclos == pytest.approx(0.50)
    assert fadiga.maior_fechamento_s == pytest.approx(1.0)
    assert fadiga.fator == pytest.approx(PENALIDADE_PERCLOS_MAX)


# --- Microssono ------------------------------------------------------------


def test_fechamento_prolongado_penaliza_mesmo_com_perclos_baixo():
    """Três segundos seguidos de olho fechado não são três piscadas.

    A proporção sozinha não distingue os dois casos — 3 s em 60 dá PERCLOS de
    0,05 de qualquer jeito. É por isso que a corrida máxima é um sinal separado.
    """
    estados = [EAR_FECHADO if i in (10, 11, 12) else EAR_ABERTO for i in range(61)]
    fadiga = roda(estados)

    assert fadiga.perclos == pytest.approx(0.05)   # abaixo do limiar
    assert fadiga.maior_fechamento_s == pytest.approx(3.0)
    assert fadiga.fator == pytest.approx(PENALIDADE_MICROSSONO)
    assert "olhos-fechados-prolongados" in fadiga.motivos


def test_fechamento_curto_nao_conta_como_microssono():
    # 1 s fechado: piscada longa, não cochilo.
    estados = [EAR_FECHADO if i == 10 else EAR_ABERTO for i in range(61)]
    fadiga = roda(estados)

    assert fadiga.maior_fechamento_s == pytest.approx(1.0)
    assert fadiga.fator == 0.0


# --- Bocejo ----------------------------------------------------------------


def test_bocejo_sustentado_e_contado():
    # Boca aberta em 20, 21, 22 → dois intervalos de 1 s → atinge os 2 s exigidos.
    mars = [MAR_BOCEJO if i in (20, 21, 22) else MAR_FECHADA for i in range(61)]
    fadiga = roda([EAR_ABERTO] * 61, mars=mars)

    assert fadiga.bocejos == 1
    assert fadiga.fator == pytest.approx(PENALIDADE_POR_BOCEJO)
    assert "bocejos" in fadiga.motivos


def test_boca_aberta_por_um_instante_nao_e_bocejo():
    """Falar, rir ou beber água abre a boca sem ser bocejo."""
    mars = [MAR_BOCEJO if i == 20 else MAR_FECHADA for i in range(61)]
    fadiga = roda([EAR_ABERTO] * 61, mars=mars)

    assert fadiga.bocejos == 0
    assert fadiga.fator == 0.0


def test_dois_bocejos_penalizam_o_dobro():
    mars = [MAR_BOCEJO if i in (10, 11, 12, 40, 41, 42) else MAR_FECHADA for i in range(61)]
    fadiga = roda([EAR_ABERTO] * 61, mars=mars)

    assert fadiga.bocejos == 2
    assert fadiga.fator == pytest.approx(2 * PENALIDADE_POR_BOCEJO)


def test_sem_mar_no_payload_nao_inventa_bocejo():
    # `mar=None` é falta de informação, não boca fechada — mas o único palpite
    # seguro é não penalizar.
    fadiga = roda([EAR_ABERTO] * 61, mars=None)
    assert fadiga.bocejos == 0


# --- Ausência de rosto -----------------------------------------------------


def test_ausencia_nao_conta_como_olho_fechado():
    """Sair da frente da webcam não é cochilar.

    Se a ausência entrasse como fechamento, um aluno que foi pegar água
    voltaria com penalidade máxima de fadiga.
    """
    presencas = [i >= 30 for i in range(61)]
    fadiga = roda([EAR_ABERTO] * 61, presencas=presencas)

    assert fadiga.fator == 0.0
    assert fadiga.perclos == 0.0


def test_ausencia_sai_do_denominador_do_perclos():
    # 30 s ausente, depois 30 s alternando aberto/fechado. O PERCLOS tem que
    # descrever os 30 s observados, não diluir no minuto inteiro.
    estados, presencas = [], []
    for i in range(61):
        presencas.append(i >= 30)
        estados.append(EAR_FECHADO if (i >= 30 and i % 2 == 0) else EAR_ABERTO)
    fadiga = roda(estados, presencas=presencas)

    assert fadiga.perclos == pytest.approx(0.50)


def test_ausencia_interrompe_a_corrida_de_fechamento():
    # Fechado, some, volta fechado: não dá para afirmar que ficou fechado no
    # meio, então são duas corridas de 1 s e não uma de 3 s.
    estados = [EAR_ABERTO] * 61
    presencas = [True] * 61
    for i in (20, 22):
        estados[i] = EAR_FECHADO
    presencas[21] = False

    fadiga = roda(estados, presencas=presencas)
    assert fadiga.maior_fechamento_s == pytest.approx(1.0)
    assert fadiga.fator == 0.0


# --- Limiar relativo à baseline (coerência com a ticket 7) -----------------


def test_limiar_de_fechamento_acompanha_a_baseline_do_aluno():
    """O caso dos óculos, de novo — agora na fadiga.

    Um aluno de EAR neutro 0,18 com os olhos plenamente abertos seria lido como
    "fechado" por um limiar absoluto de 0,20 da literatura, e passaria a sessão
    inteira com penalidade máxima de sonolência.
    """
    baseline = Baseline(ear_neutro=0.18, yaw_neutro=0.0)
    fadiga = roda([0.18] * 61, baseline=baseline)

    assert fadiga.fator == 0.0
    assert fadiga.perclos == 0.0


def test_o_mesmo_ear_e_fadiga_para_quem_tem_baseline_alta():
    # EAR 0,12: olho aberto para quem tem neutro 0,18 (limiar 0,09), olho
    # fechado para quem tem neutro 0,30 (limiar 0,15).
    baixa = roda([0.12] * 61, baseline=Baseline(ear_neutro=0.18, yaw_neutro=0.0))
    alta = roda([0.12] * 61, baseline=Baseline(ear_neutro=0.30, yaw_neutro=0.0))

    assert baixa.perclos == pytest.approx(0.0)
    assert alta.perclos == pytest.approx(1.0)


# --- Teto e janela ---------------------------------------------------------


def test_fator_nao_passa_do_teto():
    """Fadiga máxima não pode zerar o IEE sozinha.

    Se pudesse, a componente de atenção — EAR e head pose — viraria decoração,
    e o índice deixaria de informar o que se propõe a informar.
    """
    mars = [MAR_BOCEJO] * 61
    fadiga = roda([EAR_FECHADO] * 61, mars=mars)

    assert fadiga.fator == pytest.approx(FADIGA_MAXIMA)


def test_fadiga_antiga_sai_da_janela():
    """A janela é deslizante: cochilar às 14h não penaliza o resto da tarde."""
    detector = DetectorDeFadiga()
    for i in range(11):
        detector.observar(agora=em(i), ear=EAR_FECHADO, baseline=BASELINE_PROVISORIA)
    assert detector.observar(
        agora=em(11), ear=EAR_ABERTO, baseline=BASELINE_PROVISORIA
    ).fator > 0

    # Dois minutos depois, olhos abertos: o episódio saiu da janela de 60 s.
    for i in range(180, 241):
        fadiga = detector.observar(agora=em(i), ear=EAR_ABERTO, baseline=BASELINE_PROVISORIA)

    assert fadiga.fator == 0.0


# --- Integração com o IEE --------------------------------------------------


def test_fadiga_e_subtraida_do_score_do_iee():
    a = AnalistaEngajamento()
    # Um minuto de calibração de olhos abertos e cabeça de frente.
    for i in range(61):
        a.observar(ear=EAR_ABERTO, yaw=0.0, agora=em(i))
    assert a.calibrando is False
    assert a.validar_fadiga().fator == 0.0

    # Agora três segundos de olho fechado dentro da janela.
    for i in range(61, 64):
        resultado = a.observar(ear=EAR_FECHADO, yaw=0.0, agora=em(i))

    # O score do instante já reflete a penalidade acumulada.
    assert resultado.fadiga.fator > 0
    assert resultado.fadiga.motivos != ()
    assert resultado.score < 100.0


def test_validar_fadiga_expoe_a_ultima_avaliacao():
    a = AnalistaEngajamento()
    for i in range(61):
        a.observar(ear=EAR_ABERTO, yaw=0.0, agora=em(i))

    assert a.validar_fadiga() is not None
    assert a.validar_fadiga().fator == 0.0


def test_sem_rosto_o_score_zera_independente_da_fadiga():
    # `P(t) = 0` domina: sem rosto não há score a penalizar.
    a = AnalistaEngajamento()
    for i in range(61):
        a.observar(ear=EAR_FECHADO, yaw=0.0, agora=em(i))

    resultado = a.observar(ear=EAR_FECHADO, yaw=0.0, rosto_detectado=False, agora=em(61))
    assert resultado.score == 0.0
