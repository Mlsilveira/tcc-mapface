"""Curva de aprendizado: protocolo, não números.

O que se protege: os subconjuntos são aninhados e só usam participantes do Train;
o teste é sempre o mesmo split Test; vazamento de participante falha alto; o
resultado é reprodutível pela semente; e, com sinal plantado, mais participantes
não pioram a curva de forma grosseira.
"""
import json

import pytest

import curva_aprendizado as ca
from esquema import COLUNA_SPLIT, COLUNA_USUARIO
from tests.test_treino import dataset_sintetico
import treino


@pytest.fixture(scope="module")
def clipes():
    return dataset_sintetico()


def test_tamanhos_terminam_em_todos_e_nao_repetem():
    assert ca.tamanhos(69, ca.FRACOES_PADRAO) == [7, 17, 28, 38, 48, 59, 69]
    assert ca.tamanhos(3, (0.1, 0.2, 1.0)) == [2, 3]


def test_curva_tem_um_ponto_por_tamanho_e_o_ultimo_usa_todos(clipes):
    pontos = ca.curva(clipes, n_estimators=30, sementes=(1,))
    n_treino = clipes.loc[clipes[COLUNA_SPLIT] == "Train", COLUNA_USUARIO].nunique()

    assert pontos[-1].participantes == n_treino
    assert pontos[-1].clipes_media == (clipes[COLUNA_SPLIT] == "Train").sum()
    assert [p.participantes for p in pontos] == sorted(p.participantes for p in pontos)


def test_clipes_crescem_com_os_participantes(clipes):
    pontos = ca.curva(clipes, n_estimators=30, sementes=(1,))

    assert all(a.clipes_media <= b.clipes_media for a, b in zip(pontos, pontos[1:]))


def test_curva_e_reprodutivel_pela_semente(clipes):
    a = ca.curva(clipes, n_estimators=30, sementes=(5,))
    b = ca.curva(clipes, n_estimators=30, sementes=(5,))

    assert a == b


def test_varias_sementes_geram_desvio(clipes):
    pontos = ca.curva(clipes, n_estimators=30, sementes=(1, 2, 3))

    assert all(len(p.por_semente) == 3 for p in pontos)
    assert pontos[-1].acuracia_balanceada_desvio >= 0


def test_com_sinal_plantado_o_maior_ponto_aprende(clipes):
    pontos = ca.curva(clipes, n_estimators=50, sementes=(1,))

    assert pontos[-1].acuracia_balanceada_media > 0.6


def test_vazamento_de_participante_falha_alto(clipes):
    vazado = clipes.copy()
    de_treino = vazado.loc[vazado[COLUNA_SPLIT] == "Train", COLUNA_USUARIO].iloc[0]
    vazado.loc[vazado.index[vazado[COLUNA_SPLIT] == "Test"][0], COLUNA_USUARIO] = de_treino

    with pytest.raises(treino.VazamentoDeSujeito):
        ca.curva(vazado, n_estimators=10)


def test_cli_grava_md_e_json(clipes, tmp_path):
    caminho = tmp_path / "clipes.parquet"
    clipes.to_parquet(caminho)

    codigo = ca.main(["--clipes", str(caminho), "--saida", str(tmp_path), "--sementes", "1", "--arvores", "20"])

    assert codigo == 0
    assert "Participantes no treino" in (tmp_path / "curva_aprendizado.md").read_text(encoding="utf-8")
    assert json.loads((tmp_path / "curva_aprendizado.json").read_text(encoding="utf-8"))


def test_cli_sem_dataset_sai_com_2(tmp_path):
    assert ca.main(["--clipes", str(tmp_path / "nao_existe.parquet")]) == 2
