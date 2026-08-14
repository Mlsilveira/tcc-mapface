"""Testes do leitor do DAiSEE.

O dataset real tem ~2.7 GB e exige formulário de acesso, então todo teste monta
uma árvore sintética em `tmp_path` com a mesma estrutura de pastas e o mesmo
formato de CSV. Os vídeos são arquivos vazios: `daisee` só olha caminhos e
nomes, nunca abre um frame — decodificação é escopo do extrator.
"""
from pathlib import Path
from typing import Iterable, Optional

import pytest

import daisee
from esquema import COLUNA_CLIPE, COLUNA_SPLIT, COLUNA_USUARIO, COLUNAS_ROTULOS

CABECALHO = "ClipID,Boredom,Engagement,Confusion,Frustration"


def cria_video(raiz: Path, split: str, user_id: str, clip_id: str, ext: str = ".avi") -> Path:
    pasta = raiz / "DataSet" / split / user_id / clip_id
    pasta.mkdir(parents=True, exist_ok=True)
    caminho = pasta / f"{clip_id}{ext}"
    caminho.touch()
    return caminho


def escreve_rotulos(
    raiz: Path,
    split: str,
    linhas: Iterable[str],
    cabecalho: Optional[str] = None,
) -> Path:
    pasta = raiz / "Labels"
    pasta.mkdir(parents=True, exist_ok=True)
    caminho = pasta / f"{split}Labels.csv"
    caminho.write_text("\n".join([cabecalho or CABECALHO, *linhas]) + "\n")
    return caminho


@pytest.fixture
def raiz(tmp_path: Path) -> Path:
    """Árvore mínima e coerente: um clipe por split, todos rotulados."""
    cria_video(tmp_path, "Train", "500044", "5000441001")
    cria_video(tmp_path, "Validation", "500048", "5000481002")
    cria_video(tmp_path, "Test", "500052", "5000521003")

    escreve_rotulos(tmp_path, "Train", ["5000441001.avi,0,2,0,1"])
    escreve_rotulos(tmp_path, "Validation", ["5000481002.avi,1,3,0,0"])
    escreve_rotulos(tmp_path, "Test", ["5000521003.avi,2,1,1,0"])
    return tmp_path


# --- lista_clipes ----------------------------------------------------------


def test_lista_clipes_encontra_os_tres_splits(raiz: Path) -> None:
    clipes = daisee.lista_clipes(raiz)

    assert [c.clip_id for c in clipes] == ["5000441001", "5000481002", "5000521003"]
    assert [c.split for c in clipes] == ["Train", "Validation", "Test"]
    assert [c.user_id for c in clipes] == ["500044", "500048", "500052"]
    assert all(c.caminho.exists() for c in clipes)


def test_lista_clipes_filtra_por_split(raiz: Path) -> None:
    clipes = daisee.lista_clipes(raiz, split="Validation")

    assert [c.clip_id for c in clipes] == ["5000481002"]


def test_lista_clipes_aceita_mp4(tmp_path: Path) -> None:
    cria_video(tmp_path, "Train", "500044", "5000441001", ext=".mp4")
    escreve_rotulos(tmp_path, "Train", [])

    clipes = daisee.lista_clipes(tmp_path)

    assert [c.caminho.suffix for c in clipes] == [".mp4"]


def test_lista_clipes_ignora_arquivos_que_nao_sao_video(tmp_path: Path) -> None:
    cria_video(tmp_path, "Train", "500044", "5000441001")
    (tmp_path / "DataSet" / "Train" / "500044" / "5000441001" / ".DS_Store").touch()
    escreve_rotulos(tmp_path, "Train", [])

    clipes = daisee.lista_clipes(tmp_path)

    assert [c.clip_id for c in clipes] == ["5000441001"]


def test_lista_clipes_e_deterministica(tmp_path: Path) -> None:
    for user_id, clip_id in [("500052", "5000521003"), ("500044", "5000441002"), ("500044", "5000441001")]:
        cria_video(tmp_path, "Train", user_id, clip_id)
    escreve_rotulos(tmp_path, "Train", [])

    ordem = [c.clip_id for c in daisee.lista_clipes(tmp_path)]

    assert ordem == sorted(ordem)
    assert ordem == [c.clip_id for c in daisee.lista_clipes(tmp_path)]


def test_lista_clipes_com_split_ausente_em_disco(raiz: Path) -> None:
    """Download parcial é comum: a ausência da pasta não é erro, só ausência de dados."""
    import shutil

    shutil.rmtree(raiz / "DataSet" / "Test")

    assert daisee.lista_clipes(raiz, split="Test") == []
    assert [c.split for c in daisee.lista_clipes(raiz)] == ["Train", "Validation"]


def test_lista_clipes_rejeita_split_desconhecido(raiz: Path) -> None:
    with pytest.raises(daisee.DatasetInvalido):
        daisee.lista_clipes(raiz, split="treino")


def test_lista_clipes_rejeita_raiz_inexistente(tmp_path: Path) -> None:
    with pytest.raises(daisee.DatasetInvalido):
        daisee.lista_clipes(tmp_path / "nao-existe")


def test_lista_clipes_aceita_extensao_maiuscula(tmp_path: Path) -> None:
    cria_video(tmp_path, "Train", "500044", "5000441001", ext=".AVI")
    escreve_rotulos(tmp_path, "Train", [])

    assert [c.clip_id for c in daisee.lista_clipes(tmp_path)] == ["5000441001"]


def test_lista_clipes_rejeita_video_fora_da_pasta_do_usuario(tmp_path: Path) -> None:
    """Sem a pasta de usuário não há como saber o sujeito — e o split é subject-independent."""
    pasta = tmp_path / "DataSet" / "Train"
    pasta.mkdir(parents=True)
    (pasta / "5000441001.avi").touch()
    escreve_rotulos(tmp_path, "Train", [])

    with pytest.raises(daisee.DatasetInvalido):
        daisee.lista_clipes(tmp_path)


def test_lista_clipes_rejeita_raiz_sem_dataset(tmp_path: Path) -> None:
    escreve_rotulos(tmp_path, "Train", [])

    with pytest.raises(daisee.DatasetInvalido):
        daisee.lista_clipes(tmp_path)


# --- carrega_rotulos -------------------------------------------------------


def test_carrega_rotulos_normaliza_colunas_e_ordem(raiz: Path) -> None:
    rotulos = daisee.carrega_rotulos(raiz, split="Train")

    assert list(rotulos.columns) == [COLUNA_CLIPE, COLUNA_SPLIT] + COLUNAS_ROTULOS
    linha = rotulos.iloc[0]
    assert linha[COLUNA_CLIPE] == "5000441001"
    assert linha[COLUNA_SPLIT] == "Train"
    assert linha["boredom"] == 0
    assert linha["engagement"] == 2
    assert linha["confusion"] == 0
    assert linha["frustration"] == 1


def test_carrega_rotulos_clip_id_e_string_sem_extensao(tmp_path: Path) -> None:
    cria_video(tmp_path, "Train", "500044", "5000441001")
    escreve_rotulos(tmp_path, "Train", ["5000441001.avi,0,2,0,1", "5000441002,1,1,0,0"])

    rotulos = daisee.carrega_rotulos(tmp_path, split="Train")

    assert list(rotulos[COLUNA_CLIPE]) == ["5000441001", "5000441002"]
    assert rotulos[COLUNA_CLIPE].map(type).eq(str).all()


def test_carrega_rotulos_preserva_zeros_a_esquerda(tmp_path: Path) -> None:
    """`ClipID` é identificador, não número: lido como int viraria 11002001."""
    cria_video(tmp_path, "Train", "500044", "0011002001")
    escreve_rotulos(tmp_path, "Train", ["0011002001.avi,0,2,0,1"])

    assert list(daisee.carrega_rotulos(tmp_path)[COLUNA_CLIPE]) == ["0011002001"]
    assert list(daisee.catalogo(tmp_path)[COLUNA_CLIPE]) == ["0011002001"]


def test_carrega_rotulos_tolera_espacos_no_cabecalho(tmp_path: Path) -> None:
    cria_video(tmp_path, "Train", "500044", "5000441001")
    escreve_rotulos(
        tmp_path,
        "Train",
        ["5000441001.avi,0,2,0,1"],
        cabecalho="ClipID, Boredom , Engagement ,Confusion,Frustration ",
    )

    rotulos = daisee.carrega_rotulos(tmp_path, split="Train")

    assert list(rotulos.columns) == [COLUNA_CLIPE, COLUNA_SPLIT] + COLUNAS_ROTULOS


def test_carrega_rotulos_junta_os_tres_splits(raiz: Path) -> None:
    rotulos = daisee.carrega_rotulos(raiz)

    assert list(rotulos[COLUNA_SPLIT]) == ["Train", "Validation", "Test"]
    assert len(rotulos) == 3


def test_carrega_rotulos_com_csv_de_split_ausente(raiz: Path) -> None:
    (raiz / "Labels" / "TestLabels.csv").unlink()

    assert daisee.carrega_rotulos(raiz, split="Test").empty
    assert list(daisee.carrega_rotulos(raiz)[COLUNA_SPLIT]) == ["Train", "Validation"]


def test_carrega_rotulos_ignora_all_labels(raiz: Path) -> None:
    escreve_rotulos(raiz, "All", ["9999999999.avi,0,0,0,0"])

    rotulos = daisee.carrega_rotulos(raiz)

    assert "9999999999" not in set(rotulos[COLUNA_CLIPE])


def test_carrega_rotulos_descarta_duplicata_do_mesmo_clipe(tmp_path: Path) -> None:
    cria_video(tmp_path, "Train", "500044", "5000441001")
    escreve_rotulos(
        tmp_path, "Train", ["5000441001.avi,0,2,0,1", "5000441001,3,3,3,3"]
    )

    rotulos = daisee.carrega_rotulos(tmp_path, split="Train")

    assert len(rotulos) == 1
    assert rotulos.iloc[0]["engagement"] == 2  # a primeira ocorrência vence


def test_carrega_rotulos_rejeita_nivel_fora_de_0_a_3(tmp_path: Path) -> None:
    cria_video(tmp_path, "Train", "500044", "5000441001")
    escreve_rotulos(tmp_path, "Train", ["5000441001.avi,0,7,0,1"])

    with pytest.raises(daisee.DatasetInvalido):
        daisee.carrega_rotulos(tmp_path, split="Train")


def test_carrega_rotulos_rejeita_coluna_faltando(tmp_path: Path) -> None:
    cria_video(tmp_path, "Train", "500044", "5000441001")
    escreve_rotulos(
        tmp_path, "Train", ["5000441001.avi,0,2,0"], cabecalho="ClipID,Boredom,Engagement,Confusion"
    )

    with pytest.raises(daisee.DatasetInvalido):
        daisee.carrega_rotulos(tmp_path, split="Train")


def test_carrega_rotulos_rejeita_raiz_sem_labels(tmp_path: Path) -> None:
    cria_video(tmp_path, "Train", "500044", "5000441001")

    with pytest.raises(daisee.DatasetInvalido):
        daisee.carrega_rotulos(tmp_path)


# --- catalogo --------------------------------------------------------------


def test_catalogo_tem_identidade_caminho_e_rotulos(raiz: Path) -> None:
    catalogo = daisee.catalogo(raiz, split="Train")

    assert list(catalogo.columns) == [
        COLUNA_CLIPE,
        COLUNA_USUARIO,
        COLUNA_SPLIT,
        daisee.COLUNA_CAMINHO,
    ] + COLUNAS_ROTULOS

    linha = catalogo.iloc[0]
    assert linha[COLUNA_CLIPE] == "5000441001"
    assert linha[COLUNA_USUARIO] == "500044"
    assert linha[daisee.COLUNA_CAMINHO].is_file()
    assert linha["engagement"] == 2


def test_catalogo_e_a_intersecao_entre_disco_e_rotulos(tmp_path: Path) -> None:
    cria_video(tmp_path, "Train", "500044", "5000441001")
    cria_video(tmp_path, "Train", "500044", "5000441002")  # sem rótulo
    escreve_rotulos(
        tmp_path,
        "Train",
        ["5000441001.avi,0,2,0,1", "5000449999.avi,0,0,0,0"],  # rótulo sem vídeo
    )

    catalogo = daisee.catalogo(tmp_path)

    assert list(catalogo[COLUNA_CLIPE]) == ["5000441001"]


def test_catalogo_usa_o_split_da_pasta_e_nao_o_do_csv(tmp_path: Path) -> None:
    cria_video(tmp_path, "Validation", "500044", "5000441001")
    escreve_rotulos(tmp_path, "Train", ["5000441001.avi,0,2,0,1"])
    escreve_rotulos(tmp_path, "Validation", [])

    catalogo = daisee.catalogo(tmp_path)

    assert list(catalogo[COLUNA_SPLIT]) == ["Validation"]


def test_catalogo_filtra_por_split(raiz: Path) -> None:
    assert list(daisee.catalogo(raiz, split="Test")[COLUNA_CLIPE]) == ["5000521003"]


def test_catalogo_preserva_a_ordem_de_lista_clipes(raiz: Path) -> None:
    catalogo = daisee.catalogo(raiz)

    assert list(catalogo[COLUNA_CLIPE]) == [c.clip_id for c in daisee.lista_clipes(raiz)]


def test_catalogo_sem_pares_devolve_vazio_com_as_colunas(tmp_path: Path) -> None:
    cria_video(tmp_path, "Train", "500044", "5000441001")
    escreve_rotulos(tmp_path, "Train", [])

    catalogo = daisee.catalogo(tmp_path)

    assert catalogo.empty
    assert COLUNA_CLIPE in catalogo.columns
    assert list(catalogo.columns)[-len(COLUNAS_ROTULOS) :] == COLUNAS_ROTULOS


# --- descasamento ----------------------------------------------------------


def test_descasamento_relata_os_dois_lados(tmp_path: Path) -> None:
    cria_video(tmp_path, "Train", "500044", "5000441001")
    cria_video(tmp_path, "Train", "500044", "5000441002")
    escreve_rotulos(
        tmp_path, "Train", ["5000441001.avi,0,2,0,1", "5000449999.avi,0,0,0,0"]
    )

    relatorio = daisee.descasamento(tmp_path)

    assert relatorio.clipes_sem_rotulo == ["5000441002"]
    assert relatorio.rotulos_sem_video == ["5000449999"]
    assert relatorio.n_clipes == 2
    assert relatorio.n_rotulos == 2
    assert relatorio.n_pareados == 1


def test_descasamento_sem_problemas(raiz: Path) -> None:
    relatorio = daisee.descasamento(raiz)

    assert relatorio.clipes_sem_rotulo == []
    assert relatorio.rotulos_sem_video == []
    assert relatorio.n_pareados == 3


def test_descasamento_lista_rotulos_duplicados(tmp_path: Path) -> None:
    cria_video(tmp_path, "Train", "500044", "5000441001")
    escreve_rotulos(
        tmp_path, "Train", ["5000441001.avi,0,2,0,1", "5000441001,3,3,3,3"]
    )

    relatorio = daisee.descasamento(tmp_path)

    assert relatorio.rotulos_duplicados == ["5000441001"]
    assert relatorio.n_pareados == 1


def test_descasamento_filtra_por_split(raiz: Path) -> None:
    cria_video(raiz, "Train", "500044", "5000441002")

    assert daisee.descasamento(raiz, split="Train").clipes_sem_rotulo == ["5000441002"]
    assert daisee.descasamento(raiz, split="Test").clipes_sem_rotulo == []
