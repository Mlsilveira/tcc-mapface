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
import math
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app import analista
from app.analista import (
    BASELINE_PROVISORIA,
    AnalistaEngajamento,
    Baseline,
    RegistroDeAnalistas,
    calcular_iee,
)
from app.janela import nomes_das_features

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


# --- A leitura de sonolência (classificador do UTA-RLDD) -------------------


class ClassificadorFalso:
    """Responde uma probabilidade fixa e guarda as janelas que recebeu."""

    def __init__(self, probabilidade: float = 0.8) -> None:
        self.probabilidade = probabilidade
        self.janelas = []

    def avaliar(self, features):
        self.janelas.append(features)
        return SimpleNamespace(probabilidade=self.probabilidade, sonolento=True)


class ClassificadorQueExplode:
    def avaliar(self, features):
        raise RuntimeError("modelo pifou")


def _observar_segundos(analista, inicio, quantos, ear=0.30, **extras):
    """Alimenta o analista com uma leitura por segundo e devolve a última."""
    resultado = None
    for segundo in range(quantos):
        resultado = analista.observar(
            ear=ear,
            yaw=0.0,
            rosto_detectado=True,
            mar=0.05,
            agora=inicio + timedelta(seconds=segundo),
            ear_esq=ear,
            ear_dir=ear,
            pitch=0.0,
            roll=0.0,
            **extras,
        )
    return resultado


def test_sem_classificador_a_sonolencia_fica_none():
    """O caminho normal da suíte: o ciclo inteiro roda sem carregar modelo."""
    analista = AnalistaEngajamento()

    resultado = _observar_segundos(analista, T0, 90)

    assert resultado.sonolencia is None


def test_nao_ha_sonolencia_durante_a_calibracao_das_janelas():
    """Sem baseline, o número seria medido contra um rosto genérico.

    São as mesmas seis janelas de dez segundos que somam os 60 segundos de
    calibração do IEE — os dois relógios batem de propósito.
    """
    classificador = ClassificadorFalso()
    analista = AnalistaEngajamento(classificador=classificador)

    resultado = _observar_segundos(analista, T0, 55)

    assert resultado.sonolencia is None
    assert classificador.janelas == []


def test_depois_da_calibracao_a_sonolencia_aparece():
    classificador = ClassificadorFalso(probabilidade=0.82)
    analista = AnalistaEngajamento(classificador=classificador)

    resultado = _observar_segundos(analista, T0, 90)

    assert resultado.sonolencia == pytest.approx(0.82)
    assert len(classificador.janelas) >= 1
    assert set(classificador.janelas[0]) == set(nomes_das_features())


def test_a_sonolencia_vale_ate_a_proxima_janela_fechar():
    """Zerar entre janelas faria a série piscar sem nada ter mudado no aluno.

    É o mesmo regime de retenção do fator de fadiga.
    """
    classificador = ClassificadorFalso(probabilidade=0.6)
    analista = AnalistaEngajamento(classificador=classificador)

    _observar_segundos(analista, T0, 75)
    seguinte = analista.observar(
        ear=0.30, yaw=0.0, rosto_detectado=True, agora=T0 + timedelta(seconds=76)
    )

    assert seguinte.sonolencia == pytest.approx(0.6)


def test_falha_do_classificador_nao_derruba_a_leitura():
    """O score, o fator de fadiga e o relatório seguem sem a leitura secundária."""
    analista = AnalistaEngajamento(classificador=ClassificadorQueExplode())

    resultado = _observar_segundos(analista, T0, 90)

    assert resultado.sonolencia is None
    assert resultado.score is not None
    assert resultado.calibrando is False


def test_a_sonolencia_nao_mexe_no_score_nem_na_fadiga():
    """A separação inteira desta entrega, escrita como teste.

    O fator que desconta do IEE vem das regras do `DetectorDeFadiga`. Se um dia
    alguém quiser que o modelo decida, será uma mudança deliberada — e este
    teste é quem vai falhar para provocar a conversa.
    """
    com_modelo = AnalistaEngajamento(classificador=ClassificadorFalso(probabilidade=0.99))
    sem_modelo = AnalistaEngajamento()

    a = _observar_segundos(com_modelo, T0, 90)
    b = _observar_segundos(sem_modelo, T0, 90)

    assert a.score == pytest.approx(b.score)
    assert a.fadiga.fator == pytest.approx(b.fadiga.fator)
    assert a.sonolencia == pytest.approx(0.99)
    assert b.sonolencia is None


def test_cliente_antigo_sem_os_campos_novos_continua_sendo_aceito():
    """Exigir `ear_esq` encerraria a sessão de quem está com a aba aberta
    desde antes do deploy. As features ausentes saem `nan`, que é o que o
    imputador do pipeline sabe tratar."""
    classificador = ClassificadorFalso()
    analista = AnalistaEngajamento(classificador=classificador)

    resultado = None
    for segundo in range(90):
        resultado = analista.observar(
            ear=0.30, yaw=0.0, rosto_detectado=True, agora=T0 + timedelta(seconds=segundo)
        )

    assert resultado.sonolencia is not None
    assert math.isnan(classificador.janelas[0]["pitch_media"])
    assert not math.isnan(classificador.janelas[0]["ear_media"])
