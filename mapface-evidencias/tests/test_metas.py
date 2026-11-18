"""Critérios de aceitação das metas e a reprodução da Tabela 10 a partir das evidências.

O que se protege: a meta é julgada na cauda (p95 para tempo, p5 para quadros),
a mediana não decide, o limite exato conta como atendido, e os números da
Tabela 10 saem dos arquivos de evidência, e não de anotação à mão.
"""
import json
import sys
from pathlib import Path

import pytest

PASTA = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PASTA))

import metas  # noqa: E402


class TestPercentil:
    def test_posto_mais_proximo_sem_interpolar(self):
        assert metas.percentil(range(1, 101), 95) == 95
        assert metas.percentil([10, 20, 30, 40], 50) == 20

    def test_lista_vazia_nao_tem_percentil(self):
        assert metas.percentil([], 95) is None


class TestCriterio:
    def test_mediana_boa_nao_salva_cauda_ruim(self):
        valores = [50] * 90 + [300] * 10  # mediana 50 ms, p95 300 ms
        r = metas.METAS["websocket"].julgar(valores)
        assert r["mediana"] == 50
        assert r["atendida"] is False

    def test_limite_exato_conta_como_atendido(self):
        assert metas.METAS["backend"].julgar([100] * 20)["atendida"] is True

    def test_fps_e_julgado_pelo_percentil_5(self):
        segundos = [30] * 96 + [10] * 4  # 4% dos segundos abaixo de 15
        assert metas.METAS["fps"].julgar(segundos)["atendida"] is True
        segundos = [30] * 90 + [10] * 10  # 10% abaixo de 15
        assert metas.METAS["fps"].julgar(segundos)["atendida"] is False

    def test_proporcao_dentro_do_limite(self):
        r = metas.METAS["websocket"].julgar([100, 150, 250, 400])
        assert r["proporcao_dentro"] == 0.5

    def test_sem_dados_nao_e_julgado(self):
        assert metas.METAS["backend"].julgar([])["atendida"] is None

    def test_criterio_tem_data_fixada(self):
        assert metas.CRITERIOS_FIXADOS_EM == "2026-11-17"


class TestTabela10:
    """Os valores e as situações da Tabela 10 para a sessão 10, recalculados."""

    @pytest.fixture(scope="class")
    def sessao10(self):
        caminho = PASTA / "evidencias" / "sessao-real-1.json"
        return metas.avaliar(json.loads(caminho.read_text(encoding="utf-8")))

    def test_websocket(self, sessao10):
        r = sessao10["websocket"]
        assert (round(r["mediana"]), round(r["valor"]), round(100 * r["proporcao_dentro"])) == (161, 310, 86)
        assert r["atendida"] is False

    def test_backend(self, sessao10):
        r = sessao10["backend"]
        assert (round(r["mediana"], 1), round(r["valor"]), round(100 * r["proporcao_dentro"])) == (10.6, 140, 92)
        assert r["atendida"] is False

    def test_fps(self, sessao10):
        r = sessao10["fps"]
        assert (r["mediana"], r["valor"]) == (32, 28)
        assert r["atendida"] is True

    def test_ciclo_no_trecho_medido(self, sessao10):
        r = sessao10["ciclo"]
        assert round(r["valor"]) == 310
        assert r["atendida"] is True

    def test_sintetica(self):
        dados = json.loads((PASTA / "latencia-1cliente.json").read_text(encoding="utf-8"))["resumo"]
        assert (round(dados["rtt_ms"]["p50"]), round(dados["rtt_ms"]["p95"])) == (125, 257)
        assert (round(dados["processamento_ms"]["p50"], 1), round(dados["processamento_ms"]["p95"])) == (10.6, 142)
