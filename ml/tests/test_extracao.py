"""Testes do extrator de features por frame.

Nenhum teste depende do DAiSEE nem do MediaPipe: os vídeos são gerados na hora
com `cv2.VideoWriter` (poucos frames, resolução ridícula) e tanto o detector de
landmarks quanto a calculadora de métricas entram injetados. É justamente para
isso que `extrai_frames` recebe as duas dependências — sem elas, testar o laço
de leitura exigiria um rosto de verdade em vídeo, e o módulo `metricas` de outro
agente teria que estar pronto.

O único teste que toca o MediaPipe de verdade está no fim, e não asserta valor
de landmark nenhum: um retângulo colorido não tem rosto. Ele existe só para
provar que a integração roda e devolve "sem rosto" em vez de explodir.
"""
from pathlib import Path
from typing import Dict, List, Optional

import cv2
import numpy as np
import pandas as pd
import pytest

import extracao
from esquema import COLUNA_CLIPE, COLUNAS_FRAMES, COLUNAS_METRICAS, valida_frames

LARGURA, ALTURA = 64, 48


# --- Duplos e fixtures -----------------------------------------------------


def escreve_video(caminho: Path, n_frames: int) -> Path:
    """Grava um .avi MJPG com `n_frames` retângulos de cor variável."""
    escritor = cv2.VideoWriter(
        str(caminho), cv2.VideoWriter_fourcc(*"MJPG"), 10.0, (LARGURA, ALTURA)
    )
    assert escritor.isOpened(), "não foi possível abrir o VideoWriter (codec MJPG)"
    try:
        for i in range(n_frames):
            frame = np.full((ALTURA, LARGURA, 3), (i * 10) % 256, dtype=np.uint8)
            escritor.write(frame)
    finally:
        escritor.release()
    return caminho


@pytest.fixture
def video(tmp_path: Path) -> Path:
    return escreve_video(tmp_path / "clipe.avi", n_frames=6)


class DetectorFalso:
    """Devolve landmarks constantes, exceto nos `sem_rosto_em` (devolve None)."""

    def __init__(self, sem_rosto_em: Optional[List[int]] = None) -> None:
        self.sem_rosto_em = set(sem_rosto_em or [])
        self.chamadas = 0
        self.formatos: List[tuple] = []

    def __call__(self, frame: np.ndarray) -> Optional[np.ndarray]:
        indice = self.chamadas
        self.chamadas += 1
        self.formatos.append(frame.shape)
        if indice in self.sem_rosto_em:
            return None
        return np.full((478, 3), 0.5, dtype=float)


class CalculadoraFalsa:
    """Satisfaz o mesmo protocolo que o módulo `metricas` de verdade."""

    def __init__(self) -> None:
        self.dimensoes: List[tuple] = []

    def metricas_do_frame(
        self, landmarks: np.ndarray, largura: int, altura: int
    ) -> Dict[str, float]:
        self.dimensoes.append((largura, altura))
        return {coluna: float(landmarks[0, 0]) for coluna in COLUNAS_METRICAS}

    def sem_rosto(self) -> Dict[str, float]:
        return {coluna: float("nan") for coluna in COLUNAS_METRICAS}


def extrai(video: Path, **kwargs) -> pd.DataFrame:
    kwargs.setdefault("detector", DetectorFalso())
    kwargs.setdefault("calculadora", CalculadoraFalsa())
    return extracao.extrai_frames(video, "5000441001", **kwargs)


# --- Contrato de saída -----------------------------------------------------


def test_extrai_uma_linha_por_frame(video: Path) -> None:
    frames = extrai(video)

    assert len(frames) == 6
    assert list(frames["frame_idx"]) == [0, 1, 2, 3, 4, 5]
    assert set(frames[COLUNA_CLIPE]) == {"5000441001"}
    assert frames["face_detectada"].all()


def test_saida_segue_o_contrato_do_esquema(video: Path) -> None:
    frames = extrai(video)

    valida_frames(frames)
    assert list(frames.columns) == COLUNAS_FRAMES


def test_metricas_vem_da_calculadora(video: Path) -> None:
    calculadora = CalculadoraFalsa()

    frames = extrai(video, calculadora=calculadora)

    assert (frames["ear"] == 0.5).all()
    assert calculadora.dimensoes == [(LARGURA, ALTURA)] * 6


# --- Frames sem rosto ------------------------------------------------------


def test_frame_sem_rosto_vira_linha_com_nan(video: Path) -> None:
    """A linha existe: pular o frame falsearia `prop_frames_com_rosto`."""
    frames = extrai(video, detector=DetectorFalso(sem_rosto_em=[1, 3]))

    assert len(frames) == 6
    assert list(frames["frame_idx"]) == [0, 1, 2, 3, 4, 5]
    assert list(frames["face_detectada"]) == [True, False, True, False, True, True]

    sem_rosto = frames[~frames["face_detectada"]]
    assert sem_rosto[COLUNAS_METRICAS].isna().all().all()
    com_rosto = frames[frames["face_detectada"]]
    assert com_rosto[COLUNAS_METRICAS].notna().all().all()


def test_video_inteiro_sem_rosto_nao_explode(video: Path) -> None:
    frames = extrai(video, detector=DetectorFalso(sem_rosto_em=list(range(6))))

    assert len(frames) == 6
    assert not frames["face_detectada"].any()


# --- Amostragem ------------------------------------------------------------


def test_amostragem_preserva_o_frame_idx_real(tmp_path: Path) -> None:
    """A ticket 8 precisa da escala temporal: o índice é o do vídeo, não o do laço."""
    video = escreve_video(tmp_path / "longo.avi", n_frames=7)

    frames = extrai(video, amostragem=3)

    assert list(frames["frame_idx"]) == [0, 3, 6]


def test_amostragem_nao_manda_frame_pulado_para_o_detector(tmp_path: Path) -> None:
    video = escreve_video(tmp_path / "longo.avi", n_frames=7)
    detector = DetectorFalso()

    extrai(video, detector=detector, amostragem=3)

    assert detector.chamadas == 3


def test_amostragem_invalida_e_erro(video: Path) -> None:
    with pytest.raises(ValueError):
        extrai(video, amostragem=0)


# --- Vídeo ilegível --------------------------------------------------------


def test_video_inexistente_levanta_video_ilegivel(tmp_path: Path) -> None:
    with pytest.raises(extracao.VideoIlegivel):
        extrai(tmp_path / "nao-existe.avi")


def test_video_corrompido_levanta_video_ilegivel(tmp_path: Path) -> None:
    corrompido = tmp_path / "lixo.avi"
    corrompido.write_bytes(b"isto nao e um video" * 32)

    with pytest.raises(extracao.VideoIlegivel):
        extrai(corrompido)


# --- frames_do_clipe -------------------------------------------------------


class ClipeFalso:
    """Mesmos atributos que `daisee.Clipe` — o extrator só precisa destes dois."""

    def __init__(self, clip_id: str, caminho: Path) -> None:
        self.clip_id = clip_id
        self.caminho = caminho


def test_frames_do_clipe_usa_clip_id_e_caminho_do_clipe(video: Path) -> None:
    clipe = ClipeFalso("5000481002", video)

    frames = extracao.frames_do_clipe(
        clipe, detector=DetectorFalso(), calculadora=CalculadoraFalsa()
    )

    valida_frames(frames)
    assert set(frames[COLUNA_CLIPE]) == {"5000481002"}
    assert len(frames) == 6


# --- Integração real com o MediaPipe ---------------------------------------


def test_detector_mediapipe_roda_no_video_sintetico(video: Path) -> None:
    """Único teste que carrega o MediaPipe de verdade (pulado se ele faltar).

    Não asserta landmark nenhum: um retângulo liso não tem rosto. Prova só que
    o `FaceMesh` abre, processa o frame BGR e devolve `None` sem estourar.
    """
    pytest.importorskip("mediapipe")

    with extracao.DetectorMediaPipe() as detector:
        frames = extracao.extrai_frames(
            video, "5000441001", detector=detector, calculadora=CalculadoraFalsa()
        )

    valida_frames(frames)
    assert len(frames) == 6
    assert not frames["face_detectada"].any()
