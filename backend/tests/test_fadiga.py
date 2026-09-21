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

    PERCLOS = fechamento difuso / tempo observado, ambos **descontados dos
              episódios longos**, que já são cobrados pelo microssono
    penalidade_perclos = 25 × (PERCLOS − 0,15) / (0,40 − 0,15), limitada a [0, 25]
    penalidade de episódio = valor cheio × (1 − idade / 60 s)

Duas convenções explicam os números esperados. A primeira: o intervalo entre
duas amostras é atribuído ao estado da **primeira**, então um fechamento nas
amostras 10–12 vale até t=13. A segunda: episódios decaem pela idade, então o
mesmo evento vale menos conforme a sessão avança — foi a sessão real de webcam
de 28/08, com 88 de 92 leituras em penalidade cheia, que mostrou por que o
degrau anterior não servia.
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
#: Acima do `LIMIAR_MAR_BOCEJO` recalibrado (0,50). O bocejo real medido em
#: 28/08 chegou a 0,83; 0,70 é um ponto folgado dentro daquela curva.
MAR_BOCEJO = 0.70


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

    A proporção sozinha não distingue os dois casos. É por isso que a corrida
    máxima é um sinal separado — e por isso o episódio longo sai do PERCLOS,
    para que o mesmo fechamento não seja cobrado duas vezes.
    """
    estados = [EAR_FECHADO if i in (10, 11, 12) else EAR_ABERTO for i in range(61)]
    fadiga = roda(estados)

    assert fadiga.maior_fechamento_s == pytest.approx(3.0)

    # PERCLOS: antes era 3 s fechados / 60 s observados = 0,05. Agora o
    # episódio longo sai dos dois lados da razão: (3 − 3) / (60 − 3) = 0,0.
    assert fadiga.perclos == pytest.approx(0.0)
    assert "palpebras-pesadas" not in fadiga.motivos
    assert "olhos-fechados-prolongados" in fadiga.motivos

    # Fator: antes eram os 15 pontos cheios do microssono, sem decaimento. O
    # fechamento cobre as amostras 10-12, e o intervalo 12→13 ainda é atribuído
    # ao estado da amostra 12: o episódio vale até t=13. Avaliado em t=60, tem
    # 47 s de idade numa janela de 60 → peso 1 − 47/60 = 13/60.
    assert fadiga.fator == pytest.approx(PENALIDADE_MICROSSONO * 13 / 60)


def test_fechamento_recente_pesa_mais_que_o_antigo():
    """O decaimento é a diferença entre "está cochilando" e "cochilou".

    Sem ele a penalidade é um degrau: o mesmo valor no segundo seguinte ao
    episódio e 59 segundos depois, sumindo de uma vez. Na sessão real de 28/08,
    três episódios espaçados deixaram 88 de 92 leituras com penalidade cheia, e
    o fator parava de dizer se o aluno estava piorando ou se recuperando.
    """
    antigo = roda([EAR_FECHADO if i in (5, 6, 7) else EAR_ABERTO for i in range(61)])
    recente = roda([EAR_FECHADO if i in (56, 57, 58) else EAR_ABERTO for i in range(61)])

    assert recente.fator > antigo.fator

    # O episódio antigo vale até t=8 → peso 8/60; o recente até t=59 → 59/60.
    assert antigo.fator == pytest.approx(PENALIDADE_MICROSSONO * 8 / 60)
    assert recente.fator == pytest.approx(PENALIDADE_MICROSSONO * 59 / 60)


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
    assert "bocejos" in fadiga.motivos

    # Fator: antes eram os 8 pontos cheios. O bocejo cobre as amostras 20-22 e
    # vale até t=23; avaliado em t=60 tem 37 s de idade → peso 1 − 37/60 = 23/60.
    assert fadiga.fator == pytest.approx(PENALIDADE_POR_BOCEJO * 23 / 60)


def test_bocejo_em_curso_pesa_cheio():
    """Um bocejo é datado pelo fim, não por quando cruza os 2 s.

    Datá-lo na largada faria um bocejo ainda acontecendo perder peso enquanto
    acontece — o oposto do que deveria.
    """
    mars = [MAR_BOCEJO if i >= 57 else MAR_FECHADA for i in range(61)]
    fadiga = roda([EAR_ABERTO] * 61, mars=mars)

    assert fadiga.bocejos == 1
    # A boca abre em 57 e ainda está aberta na última amostra: o bocejo vale
    # até t=60, que é o próprio instante da avaliação → idade 0, peso 1.
    assert fadiga.fator == pytest.approx(PENALIDADE_POR_BOCEJO)


def test_olho_fechado_durante_bocejo_nao_vira_microssono():
    """Gente fecha os olhos ao bocejar — e isso não é cochilo.

    Sequência reproduzida de uma sessão real de webcam (28/08): o MAR subiu a
    0,83 enquanto o EAR caía a 0,095, e o mesmo evento cobrou duas vezes — 8
    pontos de bocejo mais 15 de microssono, 23 no total, que caem para 8,0 com a
    supressão. É o mesmo erro de categoria já corrigido entre PERCLOS e
    microssono.

    Nenhum teste sintético teria pego isso: ninguém planta de propósito uma
    sequência com a boca aberta e o olho fechado ao mesmo tempo.
    """
    bocejando = (12, 13, 14, 15)
    estados = [EAR_FECHADO if i in (14, 15) else EAR_ABERTO for i in range(61)]
    mars = [MAR_BOCEJO if i in bocejando else MAR_FECHADA for i in range(61)]

    fadiga = roda(estados, mars=mars)

    assert fadiga.bocejos == 1
    assert "bocejos" in fadiga.motivos
    assert "olhos-fechados-prolongados" not in fadiga.motivos
    assert fadiga.maior_fechamento_s == pytest.approx(0.0)

    # Só o bocejo é cobrado: ele cobre as amostras 12-15 e vale até t=16 →
    # peso 16/60. Sem a supressão seriam 8 × 16/60 mais os 15 do microssono.
    assert fadiga.fator == pytest.approx(PENALIDADE_POR_BOCEJO * 16 / 60)


def test_olho_fechado_fora_do_bocejo_continua_valendo():
    """A supressão é só durante o bocejo: cochilar depois de bocejar é cochilo."""
    estados = [EAR_FECHADO if i in (14, 15, 30, 31, 32) else EAR_ABERTO for i in range(61)]
    mars = [MAR_BOCEJO if i in (12, 13, 14, 15) else MAR_FECHADA for i in range(61)]

    fadiga = roda(estados, mars=mars)

    assert "bocejos" in fadiga.motivos
    assert "olhos-fechados-prolongados" in fadiga.motivos
    # Os fechamentos de 14 e 15 são engolidos pelo bocejo; o de 30-32 não, e é
    # ele que define a corrida máxima.
    assert fadiga.maior_fechamento_s == pytest.approx(3.0)


def test_boca_aberta_por_um_instante_nao_e_bocejo():
    """Falar, rir ou beber água abre a boca sem ser bocejo."""
    mars = [MAR_BOCEJO if i == 20 else MAR_FECHADA for i in range(61)]
    fadiga = roda([EAR_ABERTO] * 61, mars=mars)

    assert fadiga.bocejos == 0
    assert fadiga.fator == 0.0


def test_bocejos_somam_e_o_mais_recente_pesa_mais():
    mars = [MAR_BOCEJO if i in (10, 11, 12, 40, 41, 42) else MAR_FECHADA for i in range(61)]
    fadiga = roda([EAR_ABERTO] * 61, mars=mars)

    assert fadiga.bocejos == 2

    # Fator: antes era 2 × 8 = 16, o dobro cheio. Agora cada bocejo pesa pela
    # idade — eles valem até t=13 e t=43, logo pesos 13/60 e 43/60.
    assert fadiga.fator == pytest.approx(PENALIDADE_POR_BOCEJO * (13 / 60 + 43 / 60))


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


# --- Buracos na telemetria -------------------------------------------------


def test_buraco_na_telemetria_nao_estica_o_estado_da_amostra_anterior():
    """Uma piscada antes de um buraco de 4 s não é um cochilo de 4 s.

    Na sessão real de 28/08, 12% dos intervalos passaram de 1,5 s e chegaram a
    4 s no aquecimento do MediaPipe. Sem teto, a amostra anterior ao buraco tem
    o estado esticado por ele inteiro, e uma piscada sozinha dispara o
    microssono. Buraco é informação ausente, não estado que persistiu.
    """
    detector = DetectorDeFadiga()
    for i in range(20):
        detector.observar(agora=em(i), ear=EAR_ABERTO, baseline=BASELINE_PROVISORIA)
    detector.observar(agora=em(20), ear=EAR_FECHADO, baseline=BASELINE_PROVISORIA)

    # Quatro segundos sem payload, e o rosto volta com o olho aberto.
    fadiga = detector.observar(agora=em(24), ear=EAR_ABERTO, baseline=BASELINE_PROVISORIA)

    # Sem o teto: 4 s de olho fechado ≥ 2 s → microssono de 15 pontos cheios.
    # Com o teto: a piscada representa 1,5 s e não chega aos 2 s do microssono.
    assert fadiga.maior_fechamento_s == pytest.approx(1.5)
    assert "olhos-fechados-prolongados" not in fadiga.motivos
    assert fadiga.fator == 0.0

    # O excedente não entra em conta nenhuma — nem no numerador, nem no
    # denominador: 20 s abertos + 1,5 s fechados observados, e não 24 s.
    assert fadiga.perclos == pytest.approx(1.5 / 21.5)


def test_buraco_interrompe_a_corrida_de_fechamento():
    """Pelo mesmo motivo que a ausência de rosto interrompe.

    Um buraco não deixa afirmar continuidade: os fechamentos dos dois lados são
    duas corridas curtas, não uma longa que atravessa o que não foi observado.
    """
    detector = DetectorDeFadiga()
    for i in range(20):
        detector.observar(agora=em(i), ear=EAR_ABERTO, baseline=BASELINE_PROVISORIA)
    detector.observar(agora=em(20), ear=EAR_FECHADO, baseline=BASELINE_PROVISORIA)
    detector.observar(agora=em(24), ear=EAR_FECHADO, baseline=BASELINE_PROVISORIA)
    fadiga = detector.observar(agora=em(25), ear=EAR_ABERTO, baseline=BASELINE_PROVISORIA)

    # 1,5 s antes do buraco e 1,0 s depois. Emendadas dariam 2,5 s e virariam
    # microssono; separadas pelo buraco, nenhuma das duas chega aos 2 s.
    assert fadiga.maior_fechamento_s == pytest.approx(1.5)
    assert "olhos-fechados-prolongados" not in fadiga.motivos

    # PERCLOS = 2,5 s fechados / 22,5 s observados = 0,111, abaixo do limiar.
    assert fadiga.perclos == pytest.approx(2.5 / 22.5)
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
    assert baixa.maior_fechamento_s == pytest.approx(0.0)
    assert baixa.fator == 0.0

    # Para quem tem a baseline alta, o minuto inteiro é um só fechamento — e
    # por ser contínuo ele é microssono, não pálpebra difusa. O PERCLOS, que
    # antes marcava 1,0 (60 s fechados / 60 s observados), agora mede o que
    # sobra depois do episódio longo: (60 − 60) / (60 − 60) = 0,0 por definição.
    assert alta.maior_fechamento_s == pytest.approx(60.0)
    assert alta.perclos == pytest.approx(0.0)
    assert "olhos-fechados-prolongados" in alta.motivos


# --- Teto e janela ---------------------------------------------------------


def test_fator_nao_passa_do_teto():
    """Fadiga máxima não pode zerar o IEE sozinha.

    Se pudesse, a componente de atenção — EAR e head pose — viraria decoração,
    e o índice deixaria de informar o que se propõe a informar.
    """
    # Antes bastava boca aberta e olho fechado o minuto inteiro. Agora esse
    # cenário é *um* bocejo contínuo que suprime o microssono e vale 8,0 — o
    # que a correção da supressão faz de propósito. Para ainda estourar o teto,
    # a sequência abre e fecha a boca: são 20 bocejos de 2 s encadeados, e a
    # soma deles com o PERCLOS do fechamento difuso passa longe dos 40.
    mars = [MAR_BOCEJO if i % 3 else MAR_FECHADA for i in range(61)]
    fadiga = roda([EAR_FECHADO] * 61, mars=mars)

    assert fadiga.bocejos > 10
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
