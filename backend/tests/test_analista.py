"""Testes do núcleo de inferência do IEE (ticket 7, seam principal do spec).

Este é o módulo que o spec elege como o mais valioso de testar isoladamente: é
onde mora a regra de negócio do projeto, sem rede, banco nem UI por perto.

Os valores esperados foram calculados à mão a partir da fórmula acordada, não
extraídos do código::

    IEE = 100 × (0,6 × min(EAR/EAR_neutro, 1) + 0,4 × max(0, 1 − |yaw − yaw_neutro|/45))

Os testes de fórmula que usam `BASELINE_PROVISORIA` são os mesmos números da
ticket 6, de propósito: a estrutura de pesos não mudou na ticket 7, só a origem
das referências. Se eles se moverem, alguma coisa quebrou no caminho.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app import analista
from app.analista import (
    BASELINE_PROVISORIA,
    AnalistaEngajamento,
    Baseline,
    RegistroDeAnalistas,
    calcular_iee,
)

T0 = datetime(2026, 8, 18, 12, 0, 0, tzinfo=timezone.utc)


def em(segundos: float) -> datetime:
    return T0 + timedelta(seconds=segundos)


def calibrar(
    analista_: AnalistaEngajamento,
    ear: float = 0.30,
    yaw: float = 0.0,
    inicio: float = 0.0,
    duracao: int = 60,
):
    """Alimenta o analista a 1 Hz por `duracao` segundos, como o cliente faz.

    Devolve o resultado da última leitura — a que fecha a baseline.
    """
    resultado = None
    for segundo in range(duracao + 1):
        resultado = analista_.observar(ear=ear, yaw=yaw, agora=em(inicio + segundo))
    return resultado


# --- A fórmula, isolada da calibração --------------------------------------


def test_score_maximo_com_olhos_abertos_e_cabeca_de_frente():
    # 100 × (0,6 × 1 + 0,4 × 1) = 100
    assert calcular_iee(ear=0.30, yaw=0.0, baseline=BASELINE_PROVISORIA) == pytest.approx(100.0)


def test_olhos_semicerrados_derrubam_a_parcela_ocular():
    # EAR 0,15 → 0,15/0,3 = 0,5 → 100 × (0,6 × 0,5 + 0,4 × 1) = 70
    assert calcular_iee(ear=0.15, yaw=0.0, baseline=BASELINE_PROVISORIA) == pytest.approx(70.0)


def test_cabeca_totalmente_virada_zera_a_parcela_de_orientacao():
    # yaw 45° → 1 − 45/45 = 0 → 100 × (0,6 × 1 + 0,4 × 0) = 60
    assert calcular_iee(ear=0.30, yaw=45.0, baseline=BASELINE_PROVISORIA) == pytest.approx(60.0)


def test_score_nao_passa_de_100_com_olhos_muito_abertos():
    # Arregalar os olhos não é "mais engajado" que o teto: sem o limite, um EAR
    # atípico geraria score acima de 100 e quebraria a escala de 0 a 100.
    assert calcular_iee(ear=0.90, yaw=0.0, baseline=BASELINE_PROVISORIA) == pytest.approx(100.0)


def test_score_nao_fica_negativo_com_cabeca_alem_do_limite():
    # yaw 90° passaria de 1 na normalização; sem o piso, a parcela viraria
    # negativa e roubaria pontos da parcela ocular.
    assert calcular_iee(ear=0.30, yaw=90.0, baseline=BASELINE_PROVISORIA) == pytest.approx(60.0)


def test_desvio_de_yaw_e_simetrico_entre_esquerda_e_direita():
    esquerda = calcular_iee(ear=0.30, yaw=-30.0, baseline=BASELINE_PROVISORIA)
    direita = calcular_iee(ear=0.30, yaw=30.0, baseline=BASELINE_PROVISORIA)
    assert esquerda == pytest.approx(direita)


def test_sem_rosto_o_score_e_zero():
    """O `P(t) = 0` do spec — critério 4 da ticket 7."""
    resultado = calcular_iee(
        ear=0.30, yaw=0.0, baseline=BASELINE_PROVISORIA, rosto_detectado=False
    )
    assert resultado == 0.0


def test_sem_rosto_zera_mesmo_com_baseline_calibrada():
    # A ausência não é atenuada por ter uma boa referência: não há o que medir.
    baseline = Baseline(ear_neutro=0.18, yaw_neutro=-10.0)
    assert calcular_iee(ear=0.18, yaw=-10.0, baseline=baseline, rosto_detectado=False) == 0.0


def test_fadiga_e_subtraida_em_pontos_da_escala():
    # O `− F` da fórmula. Na ticket 7 o F é sempre 0; o parâmetro existe para a
    # ticket 8 plugar o Random Forest sem reabrir a fórmula.
    assert calcular_iee(
        ear=0.30, yaw=0.0, baseline=BASELINE_PROVISORIA, fadiga=25.0
    ) == pytest.approx(75.0)


def test_fadiga_nao_empurra_o_score_abaixo_de_zero():
    assert calcular_iee(ear=0.15, yaw=45.0, baseline=BASELINE_PROVISORIA, fadiga=90.0) == 0.0


# --- Calibração da baseline (critérios 1 e 2) ------------------------------


def test_baseline_nao_fecha_antes_dos_60_segundos():
    a = AnalistaEngajamento()
    calibrar(a, duracao=59)

    assert a.calibrando is True
    assert a.baseline is None


def test_baseline_fecha_ao_completar_os_60_segundos():
    a = AnalistaEngajamento()
    resultado = calibrar(a, ear=0.24, yaw=-8.0)

    assert a.calibrando is False
    assert a.baseline == Baseline(ear_neutro=0.24, yaw_neutro=-8.0)
    assert resultado.calibrando is False


def test_durante_a_calibracao_o_score_usa_a_referencia_provisoria():
    """A calibração é silenciosa: o canal não fica um minuto mudo.

    É o comportamento da ticket 6 preservado no primeiro minuto — e é por isso
    que os testes de WebSocket daquela ticket continuam valendo.
    """
    a = AnalistaEngajamento()
    resultado = a.observar(ear=0.15, yaw=0.0, agora=T0)

    assert resultado.calibrando is True
    assert resultado.baseline == BASELINE_PROVISORIA
    assert resultado.score == pytest.approx(70.0)


def test_baseline_usa_mediana_e_ignora_as_piscadas():
    """Piscar durante a calibração não pode rebaixar o neutro do aluno.

    A média de 61 amostras com 6 piscadas de EAR 0,05 daria ~0,275 em vez de
    0,30, e a sessão inteira seria medida contra um olho mais fechado que o
    real — inflando o score de quem estivesse de olhos semicerrados.
    """
    a = AnalistaEngajamento()
    for segundo in range(61):
        ear = 0.05 if segundo % 10 == 0 else 0.30
        a.observar(ear=ear, yaw=0.0, agora=em(segundo))

    assert a.baseline.ear_neutro == pytest.approx(0.30)


def test_poucas_amostras_nao_fecham_baseline_mesmo_depois_de_60s():
    # Cliente em rede ruim: 4 payloads espalhados por 90 s. Uma mediana de 4
    # pontos é ruído com cara de referência.
    a = AnalistaEngajamento(tolerancia_ausencia=timedelta(seconds=120))
    for segundo in (0, 30, 60, 90):
        a.observar(ear=0.30, yaw=0.0, agora=em(segundo))

    assert a.calibrando is True


def test_ausencia_prolongada_durante_a_calibracao_recomeca_do_zero():
    """Critério 2: recalibração automática se o aluno se ausentar.

    Fechar a baseline com os 30 s em que ele estava presente descreveria aqueles
    30 s, não o padrão neutro dele.
    """
    a = AnalistaEngajamento()

    for segundo in range(30):
        a.observar(ear=0.30, yaw=0.0, agora=em(segundo))
    for segundo in range(30, 40):
        a.observar(ear=0.0, yaw=0.0, rosto_detectado=False, agora=em(segundo))

    # Voltou: o relógio da calibração recomeça agora, não continua de 30 s.
    for segundo in range(40, 71):
        a.observar(ear=0.20, yaw=0.0, agora=em(segundo))
    assert a.calibrando is True

    for segundo in range(71, 102):
        a.observar(ear=0.20, yaw=0.0, agora=em(segundo))
    assert a.calibrando is False
    # Só as amostras de depois da volta entraram: 0,20, não algo entre 0,20 e 0,30.
    assert a.baseline.ear_neutro == pytest.approx(0.20)


def test_ausencia_curta_nao_descarta_a_calibracao():
    # Uma piscada longa ou um frame perdido não podem custar o minuto inteiro.
    a = AnalistaEngajamento()

    for segundo in range(30):
        a.observar(ear=0.30, yaw=0.0, agora=em(segundo))
    a.observar(ear=0.0, yaw=0.0, rosto_detectado=False, agora=em(30))
    for segundo in range(31, 61):
        a.observar(ear=0.30, yaw=0.0, agora=em(segundo))

    assert a.calibrando is False
    assert a.baseline.ear_neutro == pytest.approx(0.30)


def test_silencio_do_cliente_durante_a_calibracao_tambem_recomeca():
    # Queda de WebSocket não manda `rosto_detectado: false` — simplesmente para
    # de mandar payload. A recalibração precisa enxergar o buraco no relógio.
    a = AnalistaEngajamento()

    for segundo in range(30):
        a.observar(ear=0.30, yaw=0.0, agora=em(segundo))
    for segundo in range(600, 661):
        a.observar(ear=0.22, yaw=0.0, agora=em(segundo))

    assert a.calibrando is False
    assert a.baseline.ear_neutro == pytest.approx(0.22)


def test_baseline_nao_se_move_depois_de_fechada():
    # Fechada a calibração, o aluno cansar não pode redefinir o que é "neutro"
    # para ele — senão o IEE nunca cairia.
    a = AnalistaEngajamento()
    calibrar(a, ear=0.30)

    for segundo in range(61, 200):
        a.observar(ear=0.10, yaw=0.0, agora=em(segundo))

    assert a.baseline.ear_neutro == pytest.approx(0.30)


# --- Baseline normal x atípica (critério 5) --------------------------------


def test_aluno_com_ear_naturalmente_baixo_nao_e_penalizado():
    """O caso dos óculos, que é a razão de existir da ticket 7.

    Com a referência fixa de 0,30 da ticket 6, um aluno de EAR neutro 0,18
    atento e de frente marcaria 100 × (0,6 × 0,6 + 0,4) = 76 — perderia 24
    pontos por ter o rosto que tem. Contra a própria baseline, marca 100.
    """
    a = AnalistaEngajamento()
    calibrar(a, ear=0.18)

    resultado = a.observar(ear=0.18, yaw=0.0, agora=em(61))
    assert resultado.score == pytest.approx(100.0)
    assert calcular_iee(ear=0.18, yaw=0.0, baseline=BASELINE_PROVISORIA) == pytest.approx(76.0)


def test_aluno_com_pose_neutra_de_lado_nao_e_penalizado():
    # Quem estuda com o monitor levemente à esquerda tem yaw neutro ≠ 0 e não
    # está desatento por isso.
    a = AnalistaEngajamento()
    calibrar(a, yaw=-12.0)

    assert a.observar(ear=0.30, yaw=-12.0, agora=em(61)).score == pytest.approx(100.0)


def test_desvio_e_medido_a_partir_da_pose_neutra_do_aluno():
    # Neutro em −12°, agora em +3°: desvio de 15°, não de 3°.
    a = AnalistaEngajamento()
    calibrar(a, yaw=-12.0)

    # 100 × (0,6 + 0,4 × (1 − 15/45)) = 60 + 40 × 2/3 = 86,67
    assert a.observar(ear=0.30, yaw=3.0, agora=em(61)).score == pytest.approx(86.666667)


def test_baseline_degenerada_cai_para_a_referencia_provisoria():
    """Calibrar de olhos fechados não pode virar uma baseline válida.

    Uma mediana de 0,02 faria qualquer leitura posterior saturar em EAR_norm = 1
    e o aluno apareceria perfeitamente atento pelo resto da sessão — o pior tipo
    de falha, a que produz um número bonito.
    """
    a = AnalistaEngajamento()
    calibrar(a, ear=0.02)

    assert a.baseline.ear_neutro == pytest.approx(BASELINE_PROVISORIA.ear_neutro)


def test_ear_neutro_de_quem_usa_oculos_continua_valendo_como_baseline():
    # O piso protege contra calibração degenerada sem anular o caso que a
    # calibração existe para atender: 0,15 é baixo, mas é um olho aberto.
    a = AnalistaEngajamento()
    calibrar(a, ear=0.15)

    assert a.baseline.ear_neutro == pytest.approx(0.15)


# --- Registro de analistas por sessão --------------------------------------


def test_a_mesma_sessao_reencontra_o_analista_e_a_baseline():
    """É o que faz a reconexão da ticket 6 não jogar a calibração fora."""
    registro = RegistroDeAnalistas()
    calibrar(registro.obter(1, agora=T0), ear=0.22)

    assert registro.obter(1, agora=em(61)).calibrando is False


def test_sessoes_diferentes_nao_compartilham_baseline():
    registro = RegistroDeAnalistas()
    calibrar(registro.obter(1, agora=T0), ear=0.22)

    assert registro.obter(2, agora=em(61)).calibrando is True


def test_analista_de_sessao_parada_ha_muito_tempo_e_descartado():
    # Sem isso o processo acumularia uma baseline por sessão já encerrada até
    # ficar sem memória.
    registro = RegistroDeAnalistas(validade=timedelta(minutes=30))
    calibrar(registro.obter(1, agora=T0), ear=0.22)

    assert registro.obter(1, agora=em(3600)).calibrando is True


def test_descartar_esquece_a_sessao():
    registro = RegistroDeAnalistas()
    calibrar(registro.obter(1, agora=T0), ear=0.22)

    registro.descartar(1)
    assert registro.obter(1, agora=em(61)).calibrando is True
