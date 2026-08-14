"""Testes do cálculo de métricas e da renderização do relatório (ticket 2).

O helper de dataset sintético mora em `test_treino` — é o mesmo dataset, e
duplicá-lo aqui só criaria duas versões para manter em sincronia.
"""
import json

import numpy as np
import pytest

import relatorio
import treino
from tests.test_treino import dataset_sem_sinal, dataset_sintetico


@pytest.fixture(scope="module")
def resultado() -> "treino.ResultadoTreino":
    return treino.treina(dataset_sintetico())


@pytest.fixture(scope="module")
def resultado_ruim() -> "treino.ResultadoTreino":
    return treino.treina(dataset_sem_sinal())


# --- cálculo de métricas ---------------------------------------------------


def test_predicao_perfeita_zera_o_erro() -> None:
    y = [0, 1, 1, 0]

    m = relatorio.calcula_metricas(y, y, rotulos=[0, 1])

    assert m.acuracia == 1.0
    assert m.macro.precisao == 1.0
    assert m.macro.recall == 1.0
    assert m.macro.f1 == 1.0
    assert m.n_amostras == 4


def test_metricas_por_classe_trazem_suporte_e_nome() -> None:
    m = relatorio.calcula_metricas(
        [0, 1, 1, 1], [0, 1, 1, 0], rotulos=[0, 1], nomes={0: "nao_engajado", 1: "engajado"}
    )

    por_rotulo = {c.rotulo: c for c in m.por_classe}
    assert por_rotulo[1].nome == "engajado"
    assert por_rotulo[1].suporte == 3
    assert por_rotulo[1].recall == pytest.approx(2 / 3)
    assert por_rotulo[0].precisao == pytest.approx(0.5)


def test_classe_ausente_no_teste_nao_explode() -> None:
    """Níveis 0 e 1 do DAiSEE são raros: podem simplesmente não cair no split."""
    m = relatorio.calcula_metricas([2, 2, 3], [2, 3, 3], rotulos=[0, 1, 2, 3])

    por_rotulo = {c.rotulo: c for c in m.por_classe}
    assert por_rotulo[0].suporte == 0
    assert por_rotulo[0].precisao == 0.0
    assert por_rotulo[0].f1 == 0.0
    assert len(m.matriz_confusao) == 4


def test_rotulo_previsto_fora_dos_rotulos_declarados_e_erro() -> None:
    with pytest.raises(relatorio.RotulosInconsistentes):
        relatorio.calcula_metricas([0, 1], [0, 7], rotulos=[0, 1])


def test_acuracia_alta_esconde_classe_minoritaria() -> None:
    """O motivo de reportar por classe: 90% de acerto com recall 0 na minoria."""
    y_true = [1] * 9 + [0]
    y_pred = [1] * 10

    m = relatorio.calcula_metricas(y_true, y_pred, rotulos=[0, 1])

    assert m.acuracia == pytest.approx(0.9)
    assert m.ponderada.precisao > m.macro.precisao
    assert {c.rotulo: c.recall for c in m.por_classe}[0] == 0.0


def test_matriz_de_confusao_segue_a_ordem_dos_rotulos() -> None:
    m = relatorio.calcula_metricas([0, 0, 1], [0, 1, 1], rotulos=[0, 1])

    assert m.matriz_confusao == [[1, 1], [0, 1]]


def test_metricas_de_lista_vazia_falham_claramente() -> None:
    with pytest.raises(relatorio.MetricasInvalidas):
        relatorio.calcula_metricas([], [], rotulos=[0, 1])


def test_tamanhos_diferentes_falham_claramente() -> None:
    with pytest.raises(relatorio.MetricasInvalidas):
        relatorio.calcula_metricas([0, 1], [0], rotulos=[0, 1])


# --- meta de precisão ------------------------------------------------------


def test_meta_atingida_quando_a_precisao_macro_passa_de_80() -> None:
    avaliacao = relatorio.avalia_meta(relatorio.calcula_metricas([0, 1], [0, 1], rotulos=[0, 1]))

    assert avaliacao.atingida is True
    assert avaliacao.meta == relatorio.META_PRECISAO


def test_meta_nao_atingida_com_modelo_sem_sinal(resultado_ruim: "treino.ResultadoTreino") -> None:
    avaliacao = relatorio.avalia_meta(resultado_ruim.metricas["Test"])

    assert avaliacao.atingida is False
    assert avaliacao.precisao_macro < relatorio.META_PRECISAO


# --- markdown --------------------------------------------------------------


def test_markdown_tem_todas_as_secoes_exigidas(resultado: "treino.ResultadoTreino") -> None:
    texto = relatorio.relatorio_markdown(resultado)

    for secao in (
        "## Parâmetros",
        "## Split",
        "## Distribuição de classes",
        "## Métricas por split",
        "## Matriz de confusão",
        "## Importância das features",
        "## Meta de precisão",
    ):
        assert secao in texto


def test_markdown_registra_reprodutibilidade(resultado: "treino.ResultadoTreino") -> None:
    texto = relatorio.relatorio_markdown(resultado)

    assert "`random_state`" in texto
    assert str(resultado.parametros.random_state) in texto
    assert "subject-independent" in texto
    assert "balanced" in texto


def test_markdown_diz_que_a_meta_foi_atingida(resultado: "treino.ResultadoTreino") -> None:
    texto = relatorio.relatorio_markdown(resultado)
    atingida = relatorio.avalia_meta(resultado.metricas["Test"]).atingida

    assert ("**Meta atingida:** sim" in texto) is atingida
    assert ("**Meta atingida:** não" in texto) is not atingida


def test_markdown_diz_que_a_meta_nao_foi_atingida(
    resultado_ruim: "treino.ResultadoTreino",
) -> None:
    texto = relatorio.relatorio_markdown(resultado_ruim)

    assert "**Meta atingida:** não" in texto
    assert "80" in texto


def test_markdown_lista_as_features_mais_importantes(
    resultado: "treino.ResultadoTreino",
) -> None:
    texto = relatorio.relatorio_markdown(resultado, top_features=5)

    for feature in list(resultado.importancias)[:5]:
        assert feature in texto


def test_markdown_cobre_os_tres_splits(resultado: "treino.ResultadoTreino") -> None:
    texto = relatorio.relatorio_markdown(resultado)

    for split in ("Train", "Validation", "Test"):
        assert split in texto


def test_markdown_e_estavel(resultado: "treino.ResultadoTreino") -> None:
    assert relatorio.relatorio_markdown(resultado) == relatorio.relatorio_markdown(resultado)


# --- json ------------------------------------------------------------------


def test_json_e_carregavel_e_traz_as_metricas(resultado: "treino.ResultadoTreino") -> None:
    dados = json.loads(relatorio.relatorio_json(resultado))

    assert dados["parametros"]["modo"] == treino.MODO_BINARIO
    assert dados["parametros"]["random_state"] == resultado.parametros.random_state
    assert set(dados["metricas"]) == {"Train", "Validation", "Test"}
    assert dados["metricas"]["Test"]["acuracia"] == pytest.approx(
        resultado.metricas["Test"].acuracia, abs=1e-6
    )
    assert dados["meta"]["atingida"] in (True, False)
    assert set(dados["importancias"]) == set(resultado.importancias)


def test_json_e_diffavel(resultado: "treino.ResultadoTreino") -> None:
    """Duas execuções idênticas têm de gerar bytes idênticos, ou o diff é ruído."""
    assert relatorio.relatorio_json(resultado) == relatorio.relatorio_json(resultado)


def test_json_nao_contem_tipos_do_numpy(resultado: "treino.ResultadoTreino") -> None:
    dados = json.loads(relatorio.relatorio_json(resultado))

    contagens = dados["distribuicao"]["Train"]
    assert all(isinstance(v, int) and not isinstance(v, np.integer) for v in contagens.values())
    assert all(isinstance(v, float) for v in dados["importancias"].values())
