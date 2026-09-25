"""Testes da montagem da janela de features que o modelo de sonolência recebe.

Dois grupos. O primeiro é aritmética: dadas leituras, saem 39 números certos.
O segundo é o ciclo — quando a janela fecha, o que vira baseline, e o que sai
depois dela.

Há ainda um terceiro, com um teste só, que não é sobre este módulo: ele compara
as constantes daqui com as de `ml/esquema.py`. A trilha de ML não é importável
do backend — ela vive noutro ambiente, com MediaPipe e OpenCV —, então os
limiares estão duplicados. Duplicação sem trava é dívida que vence sozinha: se
`LIMIAR_OLHOS_FECHADOS` mudar de um lado e não do outro, o modelo passa a
receber uma feature que significa outra coisa, e o resultado seria um número
plausível e errado.
"""
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app import janela as j

INICIO = datetime(2026, 9, 24, 10, 0, 0, tzinfo=timezone.utc)


def leitura(
    segundo: int,
    ear: float = 0.30,
    mar: float = 0.05,
    rosto: bool = True,
    **extras,
) -> j.Leitura:
    """Uma leitura completa, com as métricas derivadas do EAR quando não ditas."""
    padrao = {
        "ear_esq": ear,
        "ear_dir": ear,
        "yaw": 0.0,
        "pitch": 0.0,
        "roll": 0.0,
    }
    padrao.update(extras)
    return j.Leitura(
        horario=INICIO + timedelta(seconds=segundo),
        rosto_detectado=rosto,
        ear=ear if rosto else None,
        mar=mar if rosto else None,
        **({k: (v if rosto else None) for k, v in padrao.items()}),
    )


# --- O contrato das 39 features --------------------------------------------


def test_sao_exatamente_39_features_em_ordem_estavel() -> None:
    """O vetor de entrada do modelo é posicional: a ordem é o contrato."""
    nomes = j.nomes_das_features()

    assert len(nomes) == 39
    assert nomes[:2] == ["ear_esq_media", "ear_esq_desvio"]
    assert nomes[-4:] == [
        "prop_frames_com_rosto",
        "prop_olhos_fechados",
        "prop_boca_aberta",
        "n_frames",
    ]
    assert nomes == j.nomes_das_features(), "a ordem tem de ser determinística"


def test_a_janela_produz_todas_as_features() -> None:
    features = j.features_da_janela([leitura(s) for s in range(10)])

    assert set(features) == set(j.nomes_das_features())


# --- Aritmética ------------------------------------------------------------


def test_as_agregacoes_batem_com_a_conta_na_mao() -> None:
    leituras = [leitura(0, ear=0.20), leitura(1, ear=0.30), leitura(2, ear=0.40)]

    features = j.features_da_janela(leituras)

    assert features["ear_media"] == pytest.approx(0.30)
    assert features["ear_mediana"] == pytest.approx(0.30)
    assert features["ear_min"] == pytest.approx(0.20)
    assert features["ear_max"] == pytest.approx(0.40)
    assert features["ear_desvio"] == pytest.approx(0.1)
    assert features["n_frames"] == 3.0


def test_uma_leitura_so_nao_tem_desvio() -> None:
    """`nan`, e não 0,0 — zero afirmaria uma estabilidade que ninguém mediu.

    É o mesmo `ddof=1` do pandas na extração: com uma observação não existe
    dispersão.
    """
    features = j.features_da_janela([leitura(0)])

    assert math.isnan(features["ear_desvio"])
    assert features["ear_media"] == pytest.approx(0.30)


def test_leitura_sem_rosto_fica_fora_da_media_mas_conta_na_proporcao() -> None:
    """A ausência é um dado, não um buraco.

    Contá-la como zero puxaria o EAR para baixo e viraria "sonolência" — o aluno
    teria saído de quadro e o modelo diria que ele estava dormindo.
    """
    leituras = [leitura(0, ear=0.30), leitura(1, rosto=False), leitura(2, ear=0.30)]

    features = j.features_da_janela(leituras)

    assert features["ear_media"] == pytest.approx(0.30)
    assert features["n_frames"] == 3.0
    assert features["prop_frames_com_rosto"] == pytest.approx(2 / 3)


def test_janela_inteira_sem_rosto_agrega_para_nan() -> None:
    """Zero seria "olhos fechados, cabeça de frente" — uma leitura, não a falta dela."""
    features = j.features_da_janela([leitura(s, rosto=False) for s in range(5)])

    assert math.isnan(features["ear_media"])
    assert math.isnan(features["prop_olhos_fechados"])
    assert features["prop_frames_com_rosto"] == 0.0
    assert features["n_frames"] == 5.0


def test_proporcao_de_olhos_fechados_usa_so_as_leituras_com_rosto() -> None:
    """Se usasse o total, a feature mediria a qualidade da detecção, não o aluno."""
    leituras = [
        leitura(0, ear=0.10),  # fechado
        leitura(1, ear=0.30),
        leitura(2, rosto=False),
    ]

    features = j.features_da_janela(leituras)

    assert features["prop_olhos_fechados"] == pytest.approx(0.5)


def test_proporcao_de_boca_aberta() -> None:
    leituras = [leitura(0, mar=0.70), leitura(1, mar=0.05), leitura(2, mar=0.05)]

    features = j.features_da_janela(leituras)

    assert features["prop_boca_aberta"] == pytest.approx(1 / 3)


def test_janela_vazia_e_erro_de_quem_chamou() -> None:
    with pytest.raises(ValueError):
        j.features_da_janela([])


# --- O ciclo da janela -----------------------------------------------------


def acumulador(**kwargs) -> j.AcumuladorDeJanelas:
    return j.AcumuladorDeJanelas(**kwargs)


def test_a_janela_fecha_por_relogio_e_nao_por_contagem() -> None:
    """Dez leituras não são dez segundos quando a aba foi para segundo plano."""
    acc = acumulador()

    for segundo in range(9):
        assert acc.observar(leitura(segundo)) is None

    # A décima leitura completa os 10 segundos e fecha a janela — que vai para a
    # baseline, então ainda não há saída.
    assert acc.observar(leitura(10)) is None
    assert acc.janelas_de_baseline == 1


def test_as_seis_primeiras_janelas_viram_baseline_e_nao_saem() -> None:
    """Enquanto não há baseline, um número seria medido contra um rosto genérico."""
    acc = acumulador()
    saidas = [acc.observar(leitura(s)) for s in range(0, 61)]

    assert all(saida is None for saida in saidas)
    assert acc.janelas_de_baseline == j.JANELAS_DE_CALIBRACAO
    assert acc.calibrando is False


def test_depois_da_calibracao_as_features_saem_centradas() -> None:
    """A sétima janela em diante sai com a mediana da baseline subtraída."""
    acc = acumulador()
    for segundo in range(0, 61):
        acc.observar(leitura(segundo, ear=0.30))

    saida = None
    for segundo in range(61, 72):
        resultado = acc.observar(leitura(segundo, ear=0.30))
        saida = resultado or saida

    assert saida is not None
    assert set(saida) == set(j.nomes_das_features())
    # Mesmo EAR da calibração: centrado, dá zero.
    assert saida["ear_media"] == pytest.approx(0.0, abs=1e-9)


def test_a_queda_de_ear_aparece_como_desvio_negativo() -> None:
    """É o que o modelo lê: quanto o aluno se afastou da própria baseline."""
    acc = acumulador()
    for segundo in range(0, 61):
        acc.observar(leitura(segundo, ear=0.30))

    saida = None
    for segundo in range(61, 72):
        resultado = acc.observar(leitura(segundo, ear=0.22))
        saida = resultado or saida

    assert saida is not None
    # Nem exatamente -0,08: a leitura que fechou a janela anterior abre esta,
    # e ela ainda traz o EAR antigo. A média da janela é (0,30 + 10x0,22)/11,
    # e o que sai é isso menos a baseline de 0,30.
    esperado = (0.30 + 10 * 0.22) / 11 - 0.30
    assert saida["ear_media"] == pytest.approx(esperado, abs=1e-6)
    assert saida["ear_media"] < 0


def test_janela_com_poucas_leituras_e_descartada() -> None:
    """Ela descreveria a queda de conexão, não o aluno.

    Mesma razão pela qual a extração descarta a última janela incompleta:
    `n_frames` é feature, e o desvio de uma janela pela metade não é comparável
    ao de uma inteira.
    """
    acc = acumulador()

    # Duas leituras separadas por dez segundos fecham a janela com n=2.
    assert acc.observar(leitura(0)) is None
    assert acc.observar(leitura(10)) is None
    assert acc.janelas_de_baseline == 0


def test_relogio_para_tras_recomeca_a_janela() -> None:
    """Aba suspensa e retomada, ou relógio do cliente ajustado.

    Produzir uma janela de duração negativa seria pior que perder a atual.
    """
    acc = acumulador()
    acc.observar(leitura(5))

    assert acc.observar(leitura(0)) is None
    assert acc.observar(leitura(1)) is None


def test_a_leitura_que_fecha_a_janela_abre_a_seguinte() -> None:
    """Descartá-la abriria um vão de um segundo entre janelas consecutivas."""
    acc = acumulador(janelas_de_calibracao=1, leituras_minimas=2)

    for segundo in range(0, 11):
        acc.observar(leitura(segundo))

    # A janela seguinte já começa contando do segundo 10; com mais 10 segundos
    # ela fecha, e agora há baseline, então sai resultado.
    saida = None
    for segundo in range(11, 21):
        saida = acc.observar(leitura(segundo)) or saida

    assert saida is not None


# --- A trava contra a divergência com a trilha de ML -----------------------


def test_os_limiares_batem_com_os_do_treino() -> None:
    """A duplicação de `ml/esquema.py` tem de continuar sendo uma cópia fiel.

    Se um limiar mudar de um lado só, o modelo passa a receber uma feature que
    significa outra coisa — e não erra alto: devolve um número plausível e
    errado, que é o pior modo de falhar.
    """
    esquema = Path(__file__).resolve().parents[2] / "ml" / "esquema.py"
    if not esquema.is_file():
        pytest.skip("a trilha de ML não está neste checkout")

    fonte = esquema.read_text(encoding="utf-8")
    achados = dict(re.findall(r"^(LIMIAR_\w+|AGREGACOES) = (.+)$", fonte, re.M))

    assert float(achados["LIMIAR_OLHOS_FECHADOS"]) == j.LIMIAR_OLHOS_FECHADOS
    assert float(achados["LIMIAR_BOCA_ABERTA"]) == j.LIMIAR_BOCA_ABERTA
    assert eval(achados["AGREGACOES"]) == j.AGREGACOES


def test_os_nomes_das_features_batem_com_os_do_treino() -> None:
    """A ordem é posicional no vetor de entrada: uma permutação prevê errado calada."""
    esquema = Path(__file__).resolve().parents[2] / "ml" / "esquema.py"
    if not esquema.is_file():
        pytest.skip("a trilha de ML não está neste checkout")

    fonte = esquema.read_text(encoding="utf-8")
    bloco = re.search(r"COLUNAS_METRICAS: List\[str\] = \[(.*?)\]", fonte, re.S).group(1)
    # Os nomes vêm de dentro das aspas: o bloco tem um comentário por linha, e
    # um `eval` no texto cru engasgaria neles.
    metricas = tuple(re.findall(r'"([^"]+)"', bloco))

    assert metricas == j.METRICAS
