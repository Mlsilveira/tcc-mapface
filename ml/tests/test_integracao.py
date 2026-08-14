"""Integração dos dois CLIs: DAiSEE em disco → features → modelo treinado.

Os testes dos módulos cobrem cada peça isoladamente com duplos. Estes cobrem a
costura — que `daisee`, `extracao`, `agregacao`, `treino` e `relatorio` de fato
encaixam quando ligados pelos CLIs, que os arquivos aparecem onde o README diz,
e que o artefato gravado volta do disco prevendo o mesmo.

O detector é falso na maior parte dos testes (rodar MediaPipe de verdade sobre um
retângulo colorido não acrescenta informação e custa segundos), mas um teste
exercita `main` inteiro com o detector real, porque é justamente a montagem do
MediaPipe que os duplos escondem.
"""
from pathlib import Path
from typing import Dict, List, Optional

import cv2
import numpy as np
import pandas as pd
import pytest

import esquema
import extracao
import extrair_features
import treinar
import treino as treino_mod
from tests.test_treino import dataset_sintetico

LARGURA, ALTURA = 64, 48


# --- Uma árvore DAiSEE de brinquedo ----------------------------------------


def _escreve_video(caminho: Path, n_frames: int = 6) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    escritor = cv2.VideoWriter(
        str(caminho), cv2.VideoWriter_fourcc(*"MJPG"), 10.0, (LARGURA, ALTURA)
    )
    assert escritor.isOpened(), "VideoWriter MJPG não abriu"
    try:
        for i in range(n_frames):
            escritor.write(np.full((ALTURA, LARGURA, 3), (i * 30) % 256, dtype=np.uint8))
    finally:
        escritor.release()


@pytest.fixture
def raiz_daisee(tmp_path: Path) -> Path:
    """Árvore mínima no formato do DAiSEE: 2 clipes por split, 1 por sujeito."""
    raiz = tmp_path / "DAiSEE"
    linhas: Dict[str, List[str]] = {}

    for split in esquema.SPLITS_VALIDOS:
        linhas[split] = ["ClipID,Boredom,Engagement,Confusion,Frustration"]
        for i in range(2):
            user_id = f"{split[:2].lower()}{i}"
            clip_id = f"{split[:2].lower()}{i}0001"
            _escreve_video(raiz / "DataSet" / split / user_id / clip_id / f"{clip_id}.avi")
            linhas[split].append(f"{clip_id}.avi,1,{i % 2 + 2},0,1")

    rotulos = raiz / "Labels"
    rotulos.mkdir(parents=True, exist_ok=True)
    for split, conteudo in linhas.items():
        (rotulos / f"{split}Labels.csv").write_text("\n".join(conteudo) + "\n", encoding="utf-8")

    return raiz


class DetectorFalso:
    """Landmarks constantes; devolve None nos frames listados em `sem_rosto_em`."""

    def __init__(self, sem_rosto_em: Optional[List[int]] = None) -> None:
        self.sem_rosto_em = set(sem_rosto_em or [])
        self.chamadas = 0

    def __call__(self, frame: np.ndarray) -> Optional[np.ndarray]:
        indice = self.chamadas
        self.chamadas += 1
        if indice in self.sem_rosto_em:
            return None
        # Landmarks de um rosto frontal plausível, com jitter determinístico,
        # para que as agregações não saiam todas com desvio zero.
        rng = np.random.default_rng(indice)
        return np.clip(rng.normal(0.5, 0.05, size=(478, 3)), 0.0, 1.0)


# --- Extração ---------------------------------------------------------------


def _extrai_tudo(raiz: Path, saida: Path, **kwargs) -> pd.DataFrame:
    import daisee

    catalogo = daisee.catalogo(raiz)
    extrair_features.extrai(catalogo, saida, detector=DetectorFalso(), **kwargs)
    extrair_features.consolida(saida, catalogo)
    return pd.read_parquet(saida / extrair_features.NOME_CLIPES)


def test_pipeline_produz_dataset_no_contrato(raiz_daisee: Path, tmp_path: Path) -> None:
    clipes = _extrai_tudo(raiz_daisee, tmp_path / "dados")

    esquema.valida_clipes(clipes)
    assert len(clipes) == 6
    assert set(clipes[esquema.COLUNA_SPLIT]) == set(esquema.SPLITS_VALIDOS)
    assert list(clipes.columns) == esquema.colunas_clipes()


def test_rotulos_do_daisee_sobrevivem_ate_o_dataset_final(
    raiz_daisee: Path, tmp_path: Path
) -> None:
    clipes = _extrai_tudo(raiz_daisee, tmp_path / "dados")

    for rotulo in esquema.COLUNAS_ROTULOS:
        assert clipes[rotulo].notna().all()
    # O CSV alterna engagement entre 2 e 3 dentro de cada split.
    assert set(clipes["engagement"]) == {2, 3}
    assert set(clipes["boredom"]) == {1}


def test_frames_ficam_disponiveis_alem_do_agregado(raiz_daisee: Path, tmp_path: Path) -> None:
    """A ticket 8 precisa da sequência temporal, que a média por clipe apaga."""
    saida = tmp_path / "dados"
    _extrai_tudo(raiz_daisee, saida, amostragem=1)

    frames = pd.read_parquet(saida / extrair_features.NOME_FRAMES)
    esquema.valida_frames(frames)
    assert len(frames) == 6 * 6  # 6 clipes x 6 frames
    assert frames.groupby(esquema.COLUNA_CLIPE)["frame_idx"].max().eq(5).all()


def test_amostragem_reduz_os_frames_lidos(raiz_daisee: Path, tmp_path: Path) -> None:
    saida = tmp_path / "dados"
    _extrai_tudo(raiz_daisee, saida, amostragem=3)

    frames = pd.read_parquet(saida / extrair_features.NOME_FRAMES)
    assert len(frames) == 6 * 2
    assert sorted(frames["frame_idx"].unique()) == [0, 3]


# --- Retomada ---------------------------------------------------------------


def test_segunda_execucao_pula_o_que_ja_foi_extraido(
    raiz_daisee: Path, tmp_path: Path
) -> None:
    """Uma execução de horas interrompida não pode recomeçar do zero."""
    import daisee

    saida = tmp_path / "dados"
    catalogo = daisee.catalogo(raiz_daisee)

    primeira = extrair_features.extrai(catalogo, saida, detector=DetectorFalso())
    assert primeira.extraidos == 6 and primeira.pulados == 0

    segunda = extrair_features.extrai(catalogo, saida, detector=DetectorFalso())
    assert segunda.extraidos == 0 and segunda.pulados == 6


def test_retomada_completa_uma_extracao_parcial(raiz_daisee: Path, tmp_path: Path) -> None:
    import daisee

    saida = tmp_path / "dados"
    catalogo = daisee.catalogo(raiz_daisee)

    extrair_features.extrai(catalogo.head(2), saida, detector=DetectorFalso())
    assert len(extrair_features.clipes_ja_extraidos(saida)) == 2

    progresso = extrair_features.extrai(catalogo, saida, detector=DetectorFalso())
    assert (progresso.extraidos, progresso.pulados) == (4, 2)

    extrair_features.consolida(saida, catalogo)
    clipes = pd.read_parquet(saida / extrair_features.NOME_CLIPES)
    assert len(clipes) == 6


def test_recomecar_ignora_os_shards_anteriores(raiz_daisee: Path, tmp_path: Path) -> None:
    import daisee

    saida = tmp_path / "dados"
    catalogo = daisee.catalogo(raiz_daisee)

    extrair_features.extrai(catalogo, saida, detector=DetectorFalso())
    progresso = extrair_features.extrai(
        catalogo, saida, detector=DetectorFalso(), retomar=False
    )
    assert progresso.extraidos == 6 and progresso.pulados == 0


def test_recomecar_apaga_os_shards_da_execucao_anterior(
    raiz_daisee: Path, tmp_path: Path
) -> None:
    """Sobrescrever os primeiros shards deixaria os do fim sobrando no dataset."""
    import daisee

    saida = tmp_path / "dados"
    catalogo = daisee.catalogo(raiz_daisee)

    extrair_features.extrai(catalogo, saida, detector=DetectorFalso(), clipes_por_shard=1)
    assert len(extrair_features.caminhos_de_shard(saida)) == 6

    extrair_features.extrai(
        catalogo.head(2), saida, detector=DetectorFalso(), clipes_por_shard=1, retomar=False
    )

    assert extrair_features.clipes_ja_extraidos(saida) == set(
        catalogo.head(2)[esquema.COLUNA_CLIPE]
    )
    extrair_features.consolida(saida, catalogo.head(2))
    assert len(pd.read_parquet(saida / extrair_features.NOME_CLIPES)) == 2


def test_clipe_ilegivel_nao_derruba_a_execucao(raiz_daisee: Path, tmp_path: Path) -> None:
    """Um vídeo ruim entre 9 mil não pode custar as horas dos outros 8999."""
    import daisee

    catalogo = daisee.catalogo(raiz_daisee)
    quebrado = Path(catalogo.iloc[0][daisee.COLUNA_CAMINHO])
    quebrado.write_bytes(b"isto nao e um video")

    progresso = extrair_features.extrai(catalogo, tmp_path / "dados", detector=DetectorFalso())

    assert progresso.falhos == 1
    assert progresso.extraidos == 5
    assert catalogo.iloc[0][esquema.COLUNA_CLIPE] in progresso.falhas[0]


def test_consolidar_sem_shard_e_erro_explicito(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="rode a extração"):
        extrair_features.consolida(tmp_path, pd.DataFrame())


def test_os_dois_artefatos_descrevem_o_mesmo_conjunto(
    raiz_daisee: Path, tmp_path: Path
) -> None:
    """Consolidar um subconjunto não pode deixar `frames` mais largo que `clipes`."""
    import daisee

    saida = tmp_path / "dados"
    catalogo = daisee.catalogo(raiz_daisee)
    extrair_features.extrai(catalogo, saida, detector=DetectorFalso())

    so_treino = daisee.catalogo(raiz_daisee, split="Train")
    extrair_features.consolida(saida, so_treino)

    frames = pd.read_parquet(saida / extrair_features.NOME_FRAMES)
    clipes = pd.read_parquet(saida / extrair_features.NOME_CLIPES)
    assert set(frames[esquema.COLUNA_CLIPE]) == set(clipes[esquema.COLUNA_CLIPE])
    assert len(clipes) == 2


def test_consolidar_split_sem_extracao_e_erro_explicito(
    raiz_daisee: Path, tmp_path: Path
) -> None:
    import daisee

    saida = tmp_path / "dados"
    extrair_features.extrai(
        daisee.catalogo(raiz_daisee, split="Train"), saida, detector=DetectorFalso()
    )

    with pytest.raises(FileNotFoundError, match="corresponde"):
        extrair_features.consolida(saida, daisee.catalogo(raiz_daisee, split="Test"))


# --- Estado do detector entre clipes ----------------------------------------


class DetectorComEstado:
    """Registra em que ponto do laço foi reiniciado."""

    def __init__(self) -> None:
        self.frames_desde_o_reinicio = 0
        self.historico: List[int] = []

    def __call__(self, frame: np.ndarray) -> Optional[np.ndarray]:
        self.frames_desde_o_reinicio += 1
        return np.full((478, 3), 0.5, dtype=float)

    def reinicia(self) -> None:
        self.historico.append(self.frames_desde_o_reinicio)
        self.frames_desde_o_reinicio = 0


def test_detector_e_reiniciado_a_cada_clipe(raiz_daisee: Path, tmp_path: Path) -> None:
    """O clipe seguinte é outro sujeito: rastrear por cima do anterior mente."""
    import daisee

    detector = DetectorComEstado()
    catalogo = daisee.catalogo(raiz_daisee)

    extrair_features.extrai(catalogo, tmp_path / "dados", detector=detector, amostragem=1)

    # Um reinício por clipe, e nenhum clipe herdou frames do anterior.
    assert len(detector.historico) == 6
    assert detector.historico[1:] == [6, 6, 6, 6, 6]
    assert detector.frames_desde_o_reinicio == 6


def test_reinicia_detector_ignora_detector_sem_estado() -> None:
    extracao.reinicia_detector(lambda frame: None)  # não deve levantar


# --- CLI de extração, com o MediaPipe de verdade ----------------------------


def test_main_da_extracao_roda_ponta_a_ponta(raiz_daisee: Path, tmp_path: Path) -> None:
    saida = tmp_path / "dados"

    codigo = extrair_features.main(
        ["--raiz", str(raiz_daisee), "--saida", str(saida), "--amostragem", "3"]
    )

    assert codigo == 0
    clipes = pd.read_parquet(saida / extrair_features.NOME_CLIPES)
    esquema.valida_clipes(clipes)
    assert len(clipes) == 6
    # Retângulos coloridos não têm rosto: o pipeline atravessa inteiro sem
    # detecção nenhuma, em vez de explodir.
    assert (clipes["prop_frames_com_rosto"] == 0.0).all()


def test_main_da_extracao_respeita_o_limite(raiz_daisee: Path, tmp_path: Path) -> None:
    saida = tmp_path / "dados"

    codigo = extrair_features.main(
        ["--raiz", str(raiz_daisee), "--saida", str(saida), "--limite", "2"]
    )

    assert codigo == 0
    assert len(pd.read_parquet(saida / extrair_features.NOME_CLIPES)) == 2


def test_main_da_extracao_recusa_raiz_invalida(tmp_path: Path) -> None:
    assert extrair_features.main(["--raiz", str(tmp_path / "nada"), "--saida", str(tmp_path)]) == 2


# --- CLI de treino ----------------------------------------------------------


@pytest.fixture
def clipes_parquet(tmp_path: Path) -> Path:
    caminho = tmp_path / "clipes.parquet"
    dataset_sintetico().to_parquet(caminho, index=False)
    return caminho


def test_main_do_treino_grava_modelo_e_relatorios(
    clipes_parquet: Path, tmp_path: Path
) -> None:
    artefatos = tmp_path / "artefatos"

    codigo = treinar.main(
        ["--clipes", str(clipes_parquet), "--artefatos", str(artefatos), "--arvores", "40"]
    )

    assert codigo == 0
    assert (artefatos / treinar.NOME_MODELO).is_file()
    assert (artefatos / treinar.NOME_RELATORIO_MD).is_file()
    assert (artefatos / treinar.NOME_RELATORIO_JSON).is_file()


def test_modelo_gravado_pelo_cli_volta_prevendo_o_mesmo(
    clipes_parquet: Path, tmp_path: Path
) -> None:
    """O artefato existe para a ticket 8 — se não sobrevive ao disco, não serve."""
    artefatos = tmp_path / "artefatos"
    treinar.main(
        ["--clipes", str(clipes_parquet), "--artefatos", str(artefatos), "--arvores", "40"]
    )

    modelo = treino_mod.carrega_modelo(artefatos / treinar.NOME_MODELO)
    clipes = pd.read_parquet(clipes_parquet)
    previsoes = modelo.preve(clipes)

    assert len(previsoes) == len(clipes)
    assert set(previsoes).issubset(set(modelo.rotulos))


def test_relatorio_registra_o_veredito_da_meta(clipes_parquet: Path, tmp_path: Path) -> None:
    artefatos = tmp_path / "artefatos"
    treinar.main(
        ["--clipes", str(clipes_parquet), "--artefatos", str(artefatos), "--arvores", "40"]
    )

    markdown = (artefatos / treinar.NOME_RELATORIO_MD).read_text(encoding="utf-8")
    assert "80" in markdown
    assert "precis" in markdown.lower()


def test_exigir_meta_falha_quando_nao_ha_sinal(tmp_path: Path) -> None:
    """Sem `--exigir-meta` o relatório ainda é gravado — é ele que explica a falha."""
    from tests.test_treino import dataset_sem_sinal

    caminho = tmp_path / "ruido.parquet"
    dataset_sem_sinal().to_parquet(caminho, index=False)
    artefatos = tmp_path / "artefatos"

    codigo = treinar.main(
        [
            "--clipes", str(caminho),
            "--artefatos", str(artefatos),
            "--arvores", "40",
            "--exigir-meta",
        ]
    )

    assert codigo == 1
    assert (artefatos / treinar.NOME_RELATORIO_MD).is_file()


def test_main_do_treino_recusa_dataset_ausente(tmp_path: Path) -> None:
    assert treinar.main(["--clipes", str(tmp_path / "nada.parquet")]) == 2


def test_main_do_treino_recusa_dataset_fora_do_contrato(tmp_path: Path) -> None:
    caminho = tmp_path / "torto.parquet"
    dataset_sintetico().drop(columns=["ear_media"]).to_parquet(caminho, index=False)

    assert treinar.main(["--clipes", str(caminho)]) == 2


def test_main_do_treino_detecta_vazamento_de_sujeito(tmp_path: Path) -> None:
    """O sintoma do vazamento é uma métrica boa — e métrica boa ninguém investiga."""
    clipes = dataset_sintetico()
    clipes.loc[clipes[esquema.COLUNA_SPLIT] == "Test", esquema.COLUNA_USUARIO] = "train_u0"
    caminho = tmp_path / "vazado.parquet"
    clipes.to_parquet(caminho, index=False)

    assert treinar.main(["--clipes", str(caminho), "--artefatos", str(tmp_path / "a")]) == 2
