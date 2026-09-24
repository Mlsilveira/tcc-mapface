"""Testes do leitor do UTA-RLDD.

Nenhum teste depende do dataset real: as árvores são montadas em `tmp_path` com
arquivos vazios, porque o que se afirma aqui é a **leitura do layout** — quem é
o participante, de qual fold, com qual rótulo — e não o conteúdo do vídeo.

Cada caso esquisito coberto aqui saiu do material distribuído, não de
imaginação: a pasta repetida, o vídeo de sonolência partido em dois e as
extensões que variam por participante estão todos nos 224 GB baixados.
"""
from pathlib import Path

import pytest

import rldd
from esquema_rldd import COLUNA_FOLD, COLUNA_PARTICIPANTE, COLUNA_SONOLENCIA


def monta(raiz: Path, arquivos) -> Path:
    for relativo in arquivos:
        caminho = raiz / relativo
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_bytes(b"")
    return raiz


@pytest.fixture
def dataset(tmp_path: Path) -> Path:
    return monta(
        tmp_path,
        [
            "Fold1_part1/01/0.mov",
            "Fold1_part1/01/5.MOV",
            "Fold1_part1/01/10.mp4",
            "Fold2_part1/13/0.m4v",
            "Fold2_part1/13/5.m4v",
            "Fold2_part1/13/10.m4v",
        ],
    )


# --- Leitura do layout -----------------------------------------------------


def test_le_participante_fold_e_rotulo(dataset: Path) -> None:
    gravacoes = rldd.lista_gravacoes(dataset)

    assert len(gravacoes) == 6
    primeira = gravacoes[0]
    assert primeira.participante == "01"
    assert primeira.fold == 1
    assert primeira.sonolencia == 0
    assert primeira.parte == 1


def test_a_ordem_e_estavel(dataset: Path) -> None:
    """A retomada da extração depende disto: mesma ordem, mesmos shards."""
    uma = [g.prefixo for g in rldd.lista_gravacoes(dataset)]
    outra = [g.prefixo for g in rldd.lista_gravacoes(dataset)]

    assert uma == outra
    assert uma == [
        "rldd-01-0-1",
        "rldd-01-5-1",
        "rldd-01-10-1",
        "rldd-13-0-1",
        "rldd-13-5-1",
        "rldd-13-10-1",
    ]


def test_aceita_a_pasta_repetida(tmp_path: Path) -> None:
    """`Fold5_part2/Fold5_part2/55/0.mp4` é como o zip descompacta na prática.

    Uma varredura de profundidade fixa perderia esses participantes em silêncio
    — e são 24 dos 60, quase metade do dataset.
    """
    dataset = monta(tmp_path, ["Fold5_part2/Fold5_part2/55/0.mp4"])

    gravacoes = rldd.lista_gravacoes(dataset)

    assert len(gravacoes) == 1
    assert gravacoes[0].participante == "55"
    assert gravacoes[0].fold == 5


def test_o_video_partido_vira_duas_gravacoes(tmp_path: Path) -> None:
    """`10_1` e `10_2` são a mesma gravação cortada: mesmo rótulo, partes distintas.

    Se as duas partilhassem o prefixo, os ids de janela colidiriam e a segunda
    sobrescreveria a primeira na agregação — sem erro nenhum, só com metade dos
    dados sumindo.
    """
    dataset = monta(tmp_path, ["Fold3_part2/32/10_1.mp4", "Fold3_part2/32/10_2.mp4"])

    gravacoes = rldd.lista_gravacoes(dataset)

    assert [g.parte for g in gravacoes] == [1, 2]
    assert {g.sonolencia for g in gravacoes} == {10}
    assert [g.prefixo for g in gravacoes] == ["rldd-32-10-1", "rldd-32-10-2"]


def test_extensao_maiuscula_e_m4v_entram(tmp_path: Path) -> None:
    """Cada participante gravou com o próprio celular; a extensão varia.

    Esquecer o `.m4v` faz o participante 46 sumir inteiro, sem erro.
    """
    dataset = monta(tmp_path, ["Fold4_part2/46/0.m4v", "Fold4_part2/46/10.MOV"])

    assert len(rldd.lista_gravacoes(dataset)) == 2


def test_ignora_arquivo_que_nao_e_estado_conhecido(tmp_path: Path) -> None:
    """Miniatura, `.DS_Store` renomeado, sobra de edição — nada disso é gravação."""
    dataset = monta(
        tmp_path, ["Fold1_part1/01/0.mov", "Fold1_part1/01/teste.mov", "Fold1_part1/01/7.mov"]
    )

    assert [g.sonolencia for g in rldd.lista_gravacoes(dataset)] == [0]


def test_raiz_sem_video_e_dataset_invalido(tmp_path: Path) -> None:
    with pytest.raises(rldd.DatasetInvalido):
        rldd.lista_gravacoes(tmp_path)


def test_raiz_inexistente(tmp_path: Path) -> None:
    with pytest.raises(rldd.DatasetInvalido):
        rldd.lista_gravacoes(tmp_path / "nao-existe")


# --- Identidade da janela --------------------------------------------------


def test_id_da_janela_e_reversivel(dataset: Path) -> None:
    """O id carrega a identidade inteira — é o que dispensa um CSV paralelo."""
    gravacao = rldd.lista_gravacoes(dataset)[2]
    clip_id = rldd.id_da_janela(gravacao.prefixo, 7)

    assert clip_id == "rldd-01-10-1-0007"
    assert rldd.decompoe_id(clip_id) == {
        "clip_id": clip_id,
        COLUNA_PARTICIPANTE: "01",
        COLUNA_SONOLENCIA: 10,
        "parte": 1,
        "indice_janela": 7,
    }


def test_id_fora_do_formato(dataset: Path) -> None:
    with pytest.raises(ValueError):
        rldd.decompoe_id("5000441001")


def test_id_com_estado_desconhecido(dataset: Path) -> None:
    with pytest.raises(ValueError):
        rldd.decompoe_id("rldd-01-7-1-0000")


# --- Catálogos -------------------------------------------------------------


def test_catalogo_de_gravacoes(dataset: Path) -> None:
    catalogo = rldd.catalogo_de_gravacoes(dataset)

    assert len(catalogo) == 6
    assert set(catalogo[COLUNA_PARTICIPANTE]) == {"01", "13"}
    assert dict(catalogo.groupby(COLUNA_PARTICIPANTE)[COLUNA_FOLD].first()) == {
        "01": 1,
        "13": 2,
    }


def test_catalogo_de_janelas_reconstroi_o_rotulo(dataset: Path) -> None:
    folds = rldd.folds_por_participante(rldd.catalogo_de_gravacoes(dataset))

    janelas = rldd.catalogo_de_janelas(
        ["rldd-01-10-1-0000", "rldd-13-0-1-0005"], folds
    )

    assert list(janelas[COLUNA_SONOLENCIA]) == [10, 0]
    assert list(janelas[COLUNA_FOLD]) == [1, 2]


def test_janela_de_participante_fora_do_catalogo(dataset: Path) -> None:
    """Shard órfão de uma extração antiga não entra calado no dataset."""
    folds = rldd.folds_por_participante(rldd.catalogo_de_gravacoes(dataset))

    with pytest.raises(rldd.DatasetInvalido):
        rldd.catalogo_de_janelas(["rldd-99-0-1-0000"], folds)


def test_participante_em_dois_folds_e_recusado(tmp_path: Path) -> None:
    """É a única garantia de independência que o dataset oferece.

    Um participante nos dois lados do split faz a acurácia subir porque o modelo
    passa a reconhecer o rosto — e o número sobe sem o modelo ter melhorado, que
    é o pior tipo de erro possível aqui.
    """
    dataset = monta(tmp_path, ["Fold1_part1/01/0.mov", "Fold2_part1/01/5.mov"])
    catalogo = rldd.catalogo_de_gravacoes(dataset)

    with pytest.raises(rldd.DatasetInvalido):
        rldd.folds_por_participante(catalogo)
