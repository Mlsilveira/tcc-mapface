"""Extração de features por frame a partir de um vídeo (ticket 1).

Este módulo é só o laço: abre o vídeo, percorre os frames, pergunta a alguém
onde estão os landmarks, pergunta a alguém quais são as métricas, e devolve uma
tabela conforme `esquema.COLUNAS_FRAMES`. Todo o resto entra injetado.

**Por que o detector é uma dependência, e não um `import mediapipe` no topo.**
O MediaPipe custa segundos para carregar, precisa de um rosto de verdade para
devolver qualquer coisa e mantém estado entre frames. Se ele estivesse costurado
aqui dentro, o único jeito de testar a leitura do vídeo, a amostragem e o
tratamento de frames sem rosto seria gravando pessoas de verdade — e o teste
levaria minutos. Com o detector injetado, um `lambda` determinístico cobre todos
esses caminhos, e o `DetectorMediaPipe` real vira uma peça pequena, testada uma
vez só. O mesmo vale para a calculadora de métricas: o extrator não sabe o que é
um EAR, ele só repassa landmarks e recebe um dicionário.

**Por que o frame sem rosto vira linha em vez de sumir.** A ausência de rosto é
um dado, não um buraco: `prop_frames_com_rosto` é uma das features do modelo, e
ela é indistinguível de 1.0 se os frames sem rosto forem descartados na leitura.
A linha existe, com `face_detectada=False` e as métricas em NaN — nunca 0, que
seria lido como olho fechado e cabeça de frente.

**Por que `frame_idx` é o índice no vídeo, e não o contador do laço.** Com
`amostragem > 1` os dois divergem, e é o índice real que carrega a escala
temporal (a 30 fps, `frame_idx` 90 são 3 segundos). A ticket 8 precisa disso
para medir pálpebra fechada prolongada; um contador de frames processados
mentiria por um fator igual à amostragem.
"""
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Protocol, Union

import cv2
import numpy as np
import pandas as pd

from esquema import COLUNA_CLIPE, COLUNAS_FRAMES


class VideoIlegivel(Exception):
    """O arquivo não existe, não abre ou não rendeu um único frame.

    Explícito de propósito: um clipe corrompido devolvido como DataFrame vazio
    viraria, lá na agregação, um clipe legítimo com zero frames — e sumiria no
    meio dos ~9k do DAiSEE sem ninguém notar.
    """


class DetectorDeLandmarks(Protocol):
    """Recebe um frame BGR e devolve os landmarks, ou `None` se não houver rosto.

    Os landmarks vêm como `np.ndarray` de shape `(N, 3)` em coordenadas
    normalizadas (0..1 em x/y), com N = 468 ou 478 conforme o `refine_landmarks`.
    """

    def __call__(self, frame: np.ndarray) -> Optional[np.ndarray]:
        ...


def reinicia_detector(detector: DetectorDeLandmarks) -> None:
    """Descarta o estado de rastreamento do detector, se ele tiver algum.

    Detectores sem estado (os duplos dos testes, um `lambda`) não precisam de
    nada e passam batido. Ver `DetectorMediaPipe.reinicia` para o porquê disso
    ser obrigatório entre clipes.
    """
    reinicia = getattr(detector, "reinicia", None)
    if callable(reinicia):
        reinicia()


class CalculadoraDeMetricas(Protocol):
    """As duas funções do módulo `metricas` que o extrator consome.

    O próprio módulo `metricas` satisfaz este protocolo — passá-lo como objeto é
    o uso normal. Nos testes entra um duplo com as mesmas duas funções.
    """

    def metricas_do_frame(
        self, landmarks: np.ndarray, largura: int, altura: int
    ) -> Dict[str, float]:
        ...

    def sem_rosto(self) -> Dict[str, float]:
        ...


class ClipeLocalizado(Protocol):
    """O mínimo que `frames_do_clipe` precisa — `daisee.Clipe` serve."""

    clip_id: str
    caminho: Path


def _calculadora_padrao() -> CalculadoraDeMetricas:
    """Importa `metricas` só na hora do uso.

    Tardio porque o import não é gratuito e porque nenhum teste deste módulo
    depende dele: quem não passar `calculadora` paga o import, quem passar não.
    """
    import metricas

    return metricas


@contextmanager
def _abre_video(caminho: Path) -> Iterator[cv2.VideoCapture]:
    """Abre o vídeo garantindo o `release()`, inclusive se o laço estourar.

    O `VideoCapture` segura um descritor de arquivo do FFmpeg; com ~9k clipes,
    esquecer o release esgota o limite do processo antes da metade do dataset.
    """
    if not caminho.is_file():
        raise VideoIlegivel(f"vídeo não encontrado: {caminho}")

    captura = cv2.VideoCapture(str(caminho))
    try:
        if not captura.isOpened():
            raise VideoIlegivel(f"vídeo não pôde ser aberto: {caminho}")
        yield captura
    finally:
        captura.release()


def extrai_frames(
    caminho_video: Union[str, Path],
    clip_id: str,
    detector: DetectorDeLandmarks,
    amostragem: int = 1,
    calculadora: Optional[CalculadoraDeMetricas] = None,
) -> pd.DataFrame:
    """Roda o detector sobre o vídeo e devolve uma linha por frame amostrado.

    `amostragem` é o passo entre frames processados (1 = todos, 3 = um a cada
    três). Um clipe do DAiSEE tem ~300 frames e o dataset tem ~9k clipes, então
    processar tudo custa horas de MediaPipe; pular frames é a única alavanca
    barata. Os frames pulados são descartados na decodificação (`grab()` sem
    `retrieve()`), que é justamente a parte cara.

    Levanta `VideoIlegivel` se o arquivo não abrir ou não render nenhum frame.
    """
    if amostragem < 1:
        raise ValueError(f"amostragem deve ser >= 1, recebido {amostragem}")

    calculadora = calculadora or _calculadora_padrao()
    caminho = Path(caminho_video)
    linhas: List[Dict[str, object]] = []

    with _abre_video(caminho) as captura:
        frame_idx = 0
        while captura.grab():
            if frame_idx % amostragem == 0:
                lido, frame = captura.retrieve()
                if not lido or frame is None:
                    # Frame truncado no fim do arquivo: o que veio antes vale.
                    break
                linhas.append(_linha(frame, clip_id, frame_idx, detector, calculadora))
            frame_idx += 1

    if not linhas:
        raise VideoIlegivel(f"vídeo sem frames legíveis: {caminho}")

    frames = pd.DataFrame(linhas, columns=COLUNAS_FRAMES)
    return frames.astype({"frame_idx": "int64", "face_detectada": "bool"})


def _linha(
    frame: np.ndarray,
    clip_id: str,
    frame_idx: int,
    detector: DetectorDeLandmarks,
    calculadora: CalculadoraDeMetricas,
) -> Dict[str, object]:
    altura, largura = frame.shape[:2]
    landmarks = detector(frame)

    if landmarks is None:
        metricas = calculadora.sem_rosto()
    else:
        metricas = calculadora.metricas_do_frame(landmarks, largura, altura)

    return {
        COLUNA_CLIPE: clip_id,
        "frame_idx": frame_idx,
        "face_detectada": landmarks is not None,
        **metricas,
    }


def frames_do_clipe(
    clipe: ClipeLocalizado,
    detector: DetectorDeLandmarks,
    amostragem: int = 1,
    calculadora: Optional[CalculadoraDeMetricas] = None,
) -> pd.DataFrame:
    """`extrai_frames` para um clipe já localizado por `daisee.lista_clipes`."""
    return extrai_frames(
        clipe.caminho,
        clipe.clip_id,
        detector=detector,
        amostragem=amostragem,
        calculadora=calculadora,
    )


class DetectorMediaPipe:
    """Face Mesh do MediaPipe embrulhado no protocolo `DetectorDeLandmarks`.

    É um context manager porque o `FaceMesh` precisa ser fechado — ele segura o
    grafo do TensorFlow Lite, e um por clipe sem fechar vaza memória ao longo do
    dataset. O modo é o de vídeo (`static_image_mode=False`): o MediaPipe passa
    a rastrear o rosto entre frames em vez de redetectar do zero, o que é mais
    rápido e bem mais estável em pose. `refine_landmarks=True` acrescenta os
    pontos finos de íris e lábios, que é de onde saem EAR e MAR decentes.

    **O modo de vídeo cobra um preço na fronteira entre clipes.** Rastreando, o
    Face Mesh só volta a rodar a detecção quando perde o rosto; nos demais frames
    ele reaproveita a região do frame anterior. Isso é o que se quer *dentro* de
    um clipe e é errado *entre* clipes: o clipe seguinte é um corte duro para
    outro sujeito, em outra posição, e o rastreador continuaria sobre a região do
    rosto antigo — os primeiros frames de cada clipe sairiam com landmarks
    ajustados ao lugar errado. Por isso `reinicia` existe, e por isso quem varre
    um dataset inteiro precisa chamá-la a cada clipe.
    """

    def __init__(
        self,
        min_detection_confidence: float = 0.5,
        min_tracking_confidence: float = 0.5,
    ) -> None:
        # Import tardio: quem só usa um detector falso não paga os segundos de
        # carga do MediaPipe nem precisa tê-lo instalado.
        import mediapipe as mp

        self._face_mesh = mp.solutions.face_mesh.FaceMesh
        self._parametros = dict(
            static_image_mode=False,
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=min_detection_confidence,
            min_tracking_confidence=min_tracking_confidence,
        )
        self._malha = self._face_mesh(**self._parametros)

    def reinicia(self) -> None:
        """Zera o rastreamento, para o próximo clipe começar por uma detecção.

        A API do Face Mesh não expõe um reset, então o jeito é fechar e abrir de
        novo. Custa dezenas de milissegundos por clipe — irrelevante perto dos
        ~300 frames que vêm a seguir, e o preço de não contaminar a fronteira.
        """
        self._malha.close()
        self._malha = self._face_mesh(**self._parametros)

    def __call__(self, frame: np.ndarray) -> Optional[np.ndarray]:
        # O OpenCV entrega BGR; o MediaPipe espera RGB.
        resultado = self._malha.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        if not resultado.multi_face_landmarks:
            return None

        rosto = resultado.multi_face_landmarks[0]
        return np.array(
            [[ponto.x, ponto.y, ponto.z] for ponto in rosto.landmark], dtype=float
        )

    def fecha(self) -> None:
        self._malha.close()

    def __enter__(self) -> "DetectorMediaPipe":
        return self

    def __exit__(self, *_) -> None:
        self.fecha()
