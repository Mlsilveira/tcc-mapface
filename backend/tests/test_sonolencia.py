"""Testes do adaptador do classificador de sonolência.

Nenhum teste carrega o modelo de verdade: o estimador entra como duplo, porque o
que está sob teste é o **contrato** — ordem das colunas, recusa de artefato
incompatível, degradação quando o arquivo não existe. O modelo real é medido em
validação cruzada na trilha de ML, e um teste unitário não tem como afirmar
nada sobre acurácia.

Os dois testes de recusa são os que mais importam. Um modelo que recebe features
na ordem errada, ou features que não são as que ele treinou, **não erra alto**:
devolve um número plausível e errado. É o modo de falha mais caro que existe
aqui, e o único jeito de pegá-lo é recusar na entrada.
"""
import logging
from pathlib import Path

import pytest

from app import sonolencia
from app.janela import nomes_das_features


#: As colunas que o estimador recebeu, em ordem. Módulo, e não atributo de
#: instância: o `joblib.dump` seguido de `load` devolve uma **cópia** do duplo,
#: e o que o teste guardaria na instância original nunca seria escrito.
RECEBIDOS = []


class EstimadorFalso:
    """Registra as colunas recebidas e responde sonolência alta."""

    def predict_proba(self, X):
        RECEBIDOS.append(list(X.columns))
        return [[0.25, 0.75]]


class EstimadorCalmo:
    """Responde abaixo do limiar."""

    def predict_proba(self, X):
        return [[0.7, 0.3]]


class EstimadorComRotulosInvertidos:
    """As colunas saem na ordem de `rotulos`, que aqui é [1, 0]."""

    def predict_proba(self, X):
        return [[0.9, 0.1]]


@pytest.fixture(autouse=True)
def sem_cache():
    sonolencia.esquecer_cache()
    RECEBIDOS.clear()
    yield
    sonolencia.esquecer_cache()
    RECEBIDOS.clear()


def grava_artefato(caminho: Path, **ajustes) -> Path:
    import joblib

    artefato = {
        "estimador": EstimadorFalso(),
        "colunas": nomes_das_features(),
        "rotulos": [0, 1],
        "nomes_rotulos": {0: "alerta", 1: "sonolento"},
        "parametros": {"modelo": "falso"},
        "versao_sklearn": "1.5.2",
    }
    artefato.update(ajustes)
    joblib.dump(artefato, caminho)
    return caminho


def features(valor: float = 0.0) -> dict:
    return {nome: valor for nome in nomes_das_features()}


# --- Carregamento ----------------------------------------------------------


def test_artefato_ausente_devolve_none(tmp_path: Path) -> None:
    """Derrubar o backend por causa de uma leitura secundária seria trocar uma
    degradação graciosa por uma indisponibilidade."""
    assert sonolencia.carregar(tmp_path / "nao-existe.joblib") is None


def test_artefato_valido_carrega(tmp_path: Path) -> None:
    caminho = grava_artefato(tmp_path / "modelo.joblib")

    assert sonolencia.carregar(caminho) is not None


def test_artefato_com_features_diferentes_e_recusado(tmp_path: Path, caplog) -> None:
    """Preencher o que falta com zero produziria previsão bem-comportada sobre
    uma entrada que ninguém mediu."""
    caminho = grava_artefato(tmp_path / "modelo.joblib", colunas=["ear_media", "inventada"])

    with caplog.at_level(logging.ERROR):
        assert sonolencia.carregar(caminho) is None

    assert "features diferentes" in caplog.text


def test_artefato_sem_classe_positiva_e_recusado(tmp_path: Path) -> None:
    caminho = grava_artefato(tmp_path / "modelo.joblib", rotulos=[0, 2])

    assert sonolencia.carregar(caminho) is None


def test_artefato_corrompido_nao_derruba(tmp_path: Path, caplog) -> None:
    caminho = tmp_path / "modelo.joblib"
    caminho.write_bytes(b"isto nao e um joblib")

    with caplog.at_level(logging.ERROR):
        assert sonolencia.carregar(caminho) is None


def test_o_artefato_e_lido_uma_vez_so(tmp_path: Path) -> None:
    """São ~4,5 MB de árvores; reler por sessão custaria sem mudar resposta."""
    caminho = grava_artefato(tmp_path / "modelo.joblib")

    primeiro = sonolencia.carregar(caminho)
    segundo = sonolencia.carregar(caminho)

    assert primeiro is segundo


# --- Classificação ---------------------------------------------------------


def test_devolve_a_probabilidade_da_classe_positiva(tmp_path: Path) -> None:
    classificador = sonolencia.carregar(grava_artefato(tmp_path / "modelo.joblib"))

    leitura = classificador.avaliar(features())

    assert leitura.probabilidade == pytest.approx(0.75)
    assert leitura.sonolento is True


def test_abaixo_do_limiar_nao_e_sonolento(tmp_path: Path) -> None:
    classificador = sonolencia.carregar(
        grava_artefato(tmp_path / "modelo.joblib", estimador=EstimadorCalmo())
    )

    leitura = classificador.avaliar(features())

    assert leitura.probabilidade == pytest.approx(0.3)
    assert leitura.sonolento is False


def test_as_colunas_vao_na_ordem_do_treino(tmp_path: Path) -> None:
    """O estimador recebe posições, não nomes: outra ordem prevê errado calada."""
    classificador = sonolencia.carregar(grava_artefato(tmp_path / "modelo.joblib"))

    # O dicionário chega embaralhado; o adaptador reordena.
    embaralhado = dict(reversed(list(features().items())))
    classificador.avaliar(embaralhado)

    assert RECEBIDOS[0] == nomes_das_features()


def test_feature_faltando_e_recusada(tmp_path: Path) -> None:
    classificador = sonolencia.carregar(grava_artefato(tmp_path / "modelo.joblib"))

    incompleto = features()
    del incompleto["ear_media"]

    with pytest.raises(ValueError, match="ear_media"):
        classificador.avaliar(incompleto)


def test_a_classe_positiva_e_achada_pelo_rotulo_e_nao_pela_posicao(tmp_path: Path) -> None:
    """Um artefato com os rótulos em ordem inversa não pode trocar as classes."""

    classificador = sonolencia.carregar(
        grava_artefato(
            tmp_path / "modelo.joblib",
            estimador=EstimadorComRotulosInvertidos(),
            rotulos=[1, 0],
        )
    )

    assert classificador.avaliar(features()).probabilidade == pytest.approx(0.9)
