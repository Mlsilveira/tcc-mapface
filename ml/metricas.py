"""Métricas faciais de um frame: EAR, MAR e head pose (ticket 1).

Este módulo é **matemática pura sobre landmarks**. Não abre vídeo, não toca em
arquivo e não instancia o MediaPipe: recebe um array de landmarks já detectados e
devolve números. Isso o torna testável com rostos sintéticos — sem dataset, sem
webcam — e permite que o extrator (`extracao.py`) fique responsável só por
decodificar frames e chamar o detector.

As mesmas fórmulas serão reimplementadas em TypeScript no navegador (ticket 5),
para que o score calculado ao vivo seja comparável ao dataset com que o Random
Forest foi treinado. Por isso os índices e as fórmulas estão escritos abaixo de
forma explícita: esta docstring é a especificação que a versão TS tem que copiar.

--- Entrada ----------------------------------------------------------------

`landmarks` é um `np.ndarray` de shape `(N, 3)`, com N ≥ 468 (478 quando o
MediaPipe roda com `refine_landmarks=True`), em coordenadas **normalizadas**: x e
y em [0, 1] relativos à largura e à altura do frame, z relativo. É exatamente o
que sai de `results.multi_face_landmarks[0].landmark` convertido para array.

--- Por que pixels, e não coordenadas normalizadas -------------------------

x e y são normalizados por eixos de tamanhos diferentes, então um frame 640x480
comprime o eixo y em 4/3 em relação ao x. Uma razão entre distância vertical e
horizontal calculada nas coordenadas cruas sai inflada por esse fator, e o limiar
clássico de 0.20 para olho fechado deixa de valer. Por isso todo cálculo aqui
multiplica x por `largura` e y por `altura` antes de medir distância. `ear_olhos`
e `mar` aceitam as dimensões como argumentos opcionais só para não quebrar
chamadas de uma linha; o padrão (1, 1) assume frame quadrado e **não** é o que o
extrator deve usar — ele sempre passa as dimensões reais via `metricas_do_frame`.

--- Por que NaN, e não 0 ---------------------------------------------------

Quando o MediaPipe não acha rosto, ou quando a geometria degenera (denominador
zero, `solvePnP` sem solução), o valor é `float('nan')`. Zero seria um número
plausível e errado: um EAR 0 significa "olho fechado", e a agregação por clipe
(`agregacao.py`) contaria frames sem rosto como frames de olho fechado. NaN se
propaga e é ignorado explicitamente pelas agregações — o esquema já reserva
`prop_frames_com_rosto` para contar o que foi perdido.

--- EAR (Soukupová & Čech, 2016) -------------------------------------------

    EAR = (|p2 - p6| + |p3 - p5|) / (2 * |p1 - p4|)

p1 e p4 são os cantos do olho (distância horizontal); (p2, p6) e (p3, p5) são
dois pares de pálpebra superior/inferior. Índices do Face Mesh, na ordem p1..p6:

    olho esquerdo (do sujeito): 362, 385, 387, 263, 373, 380
    olho direito  (do sujeito):  33, 160, 158, 133, 153, 144

Conferidos vértice a vértice contra o `canonical_face_model.obj` do MediaPipe:
385/380 e 387/373 são pares verticais do olho esquerdo (mesmo x, y acima/abaixo),
362/263 são os cantos; 160/144 e 158/153 são os pares do olho direito, 33/133 os
cantos. Nenhuma correção foi necessária. "Esquerdo" é o olho esquerdo do sujeito,
que aparece à **direita** na imagem quando ela não está espelhada.

--- MAR --------------------------------------------------------------------

Mesma ideia, com três verticais em vez de duas — a boca deforma de forma menos
uniforme que a pálpebra, e usar só o par central (13/14) torna a métrica sensível
demais a um lábio franzido:

    MAR = (|13 - 14| + |81 - 178| + |311 - 402|) / (3 * |61 - 291|)

61 e 291 são os cantos da boca; os três pares são pontos do contorno interno dos
lábios, alinhados verticalmente (confirmado no modelo canônico). Boca fechada dá
MAR ~0.02; um bocejo escancarado passa de 0.8, cruzando com folga o
`LIMIAR_BOCA_ABERTA` de 0.60.

--- Head pose --------------------------------------------------------------

`cv2.solvePnP` com seis pontos: nariz (1), queixo (199), cantos externos dos olhos
(263 esquerdo, 33 direito) e cantos da boca (291 esquerdo, 61 direito). O modelo
3D é o próprio `canonical_face_model.obj` do MediaPipe, com y e z invertidos para
cair no referencial da câmera do OpenCV (x para a direita da imagem, y para
baixo, z para dentro da cena) — assim um rosto frontal produz rotação identidade
e ângulos ~0, em vez de um offset arbitrário que teria de ser subtraído depois.

Câmera aproximada, sem calibração: focal = `largura` em ambos os eixos, centro
óptico no meio do frame, distorção zero. É grosseiro, mas o DAiSEE não traz
parâmetros de câmera e o erro entra como um viés quase constante por vídeo — o
que a normalização por baseline da ticket 7 absorve.

A matriz de rotação vira ângulos de Euler na ordem R = Rz(roll) · Ry(yaw) ·
Rx(pitch), em **graus**. Convenção de sinal, sempre do ponto de vista do sujeito:

    yaw   > 0  →  cabeça virada para a direita do sujeito
    pitch > 0  →  cabeça abaixada (queixo em direção ao peito)
    roll  > 0  →  cabeça pendendo para o ombro esquerdo do sujeito

Se o frontend espelhar o vídeo (o que é comum, para o usuário se ver como num
espelho), yaw e roll trocam de sinal — o espelhamento tem que ser desfeito antes
de chamar estas fórmulas, não depois.
"""
import math
from typing import Dict, Sequence, Tuple

import cv2
import numpy as np

from esquema import COLUNAS_METRICAS

# --- Índices do MediaPipe Face Mesh ----------------------------------------

#: Número mínimo de landmarks de um Face Mesh. Com `refine_landmarks=True` vêm
#: 478 (os 10 extras são íris), e aceitamos os dois casos.
N_LANDMARKS_MINIMO = 468

#: Olho esquerdo do sujeito, na ordem p1..p6 da fórmula do EAR.
IDX_OLHO_ESQUERDO: Tuple[int, ...] = (362, 385, 387, 263, 373, 380)

#: Olho direito do sujeito, na ordem p1..p6.
IDX_OLHO_DIREITO: Tuple[int, ...] = (33, 160, 158, 133, 153, 144)

#: Cantos da boca (direito do sujeito, esquerdo do sujeito) — a distância
#: horizontal que normaliza o MAR.
IDX_BOCA_CANTOS: Tuple[int, int] = (61, 291)

#: Pares (lábio superior interno, lábio inferior interno) alinhados
#: verticalmente: centro, lado direito e lado esquerdo do sujeito.
IDX_BOCA_VERTICAIS: Tuple[Tuple[int, int], ...] = ((13, 14), (81, 178), (311, 402))

#: Pontos usados no solvePnP, na mesma ordem de `MODELO_3D_POSE`.
IDX_POSE: Tuple[int, ...] = (1, 199, 263, 33, 291, 61)

#: Modelo 3D dos seis pontos de pose, em unidades arbitrárias (~cm), no
#: referencial da câmera do OpenCV. Valores tirados do `canonical_face_model.obj`
#: do MediaPipe com y e z negados. Só a forma importa: a escala afeta a
#: translação estimada, não a rotação.
MODELO_3D_POSE = np.array(
    [
        (0.000, 1.127, -7.476),    # 1   — ponta do nariz
        (0.000, 7.942, -5.181),    # 199 — queixo
        (4.446, -2.664, -3.173),   # 263 — canto externo do olho esquerdo
        (-4.446, -2.664, -3.173),  # 33  — canto externo do olho direito
        (2.456, 4.343, -4.284),    # 291 — canto esquerdo da boca
        (-2.456, 4.343, -4.284),   # 61  — canto direito da boca
    ],
    dtype=np.float64,
)

#: Abaixo disto, uma distância em pixels é ruído de arredondamento e a razão que
#: ela normalizaria não significa nada.
_EPSILON_PIXEL = 1e-9

_NAN = float("nan")


# --- Infraestrutura interna ------------------------------------------------


def _em_pixels(landmarks: np.ndarray, largura: int, altura: int) -> np.ndarray:
    """Valida o array e devolve as coordenadas (x, y) em pixels.

    Levanta `ValueError` se o shape não for `(N, 3)` com N ≥ 468: um array
    truncado ou sem a coluna z quase sempre é sinal de que alguém converteu o
    resultado do MediaPipe errado, e falhar aqui é mais barato que devolver um
    EAR silenciosamente calculado sobre os landmarks errados.
    """
    array = np.asarray(landmarks, dtype=np.float64)
    if array.ndim != 2 or array.shape[1] != 3:
        raise ValueError(
            f"landmarks deve ter shape (N, 3) com coordenadas normalizadas; "
            f"recebido {array.shape}"
        )
    if array.shape[0] < N_LANDMARKS_MINIMO:
        raise ValueError(
            f"landmarks deve trazer ao menos {N_LANDMARKS_MINIMO} pontos do Face "
            f"Mesh; recebido {array.shape[0]}"
        )
    return array[:, :2] * np.array([largura, altura], dtype=np.float64)


def _distancia(pixels: np.ndarray, origem: int, destino: int) -> float:
    return float(np.linalg.norm(pixels[origem] - pixels[destino]))


def _razao(verticais: Sequence[float], horizontal: float) -> float:
    """Média das verticais dividida pela horizontal, ou NaN se a horizontal sumiu."""
    if not math.isfinite(horizontal) or horizontal <= _EPSILON_PIXEL:
        return _NAN
    return float(np.mean(verticais)) / horizontal


def _ear(pixels: np.ndarray, indices: Tuple[int, ...]) -> float:
    p1, p2, p3, p4, p5, p6 = indices
    verticais = (_distancia(pixels, p2, p6), _distancia(pixels, p3, p5))
    return _razao(verticais, _distancia(pixels, p1, p4))


def _angulos_de_euler(rotacao: np.ndarray) -> Tuple[float, float, float]:
    """Decompõe R = Rz(roll) · Ry(yaw) · Rx(pitch) em graus.

    No gimbal lock (rosto de perfil quase perfeito, yaw ~±90°) roll e yaw deixam
    de ser separáveis; fixamos roll em 0 e jogamos a rotação restante no pitch,
    que é a escolha convencional e mantém os três valores finitos.
    """
    seno_yaw = math.hypot(rotacao[0, 0], rotacao[1, 0])
    if seno_yaw < 1e-6:
        pitch = math.atan2(-rotacao[1, 2], rotacao[1, 1])
        roll = 0.0
    else:
        pitch = math.atan2(rotacao[2, 1], rotacao[2, 2])
        roll = math.atan2(rotacao[1, 0], rotacao[0, 0])
    yaw = math.atan2(-rotacao[2, 0], seno_yaw)
    return math.degrees(yaw), math.degrees(pitch), math.degrees(roll)


# --- Interface pública -----------------------------------------------------


def ear_olhos(landmarks: np.ndarray, largura: int = 1, altura: int = 1) -> Tuple[float, float]:
    """Eye aspect ratio de cada olho, na ordem (esquerdo, direito) do sujeito.

    Passe `largura` e `altura` do frame: sem elas o cálculo assume frame quadrado
    e o aspect ratio distorce a razão (ver docstring do módulo).
    """
    pixels = _em_pixels(landmarks, largura, altura)
    return _ear(pixels, IDX_OLHO_ESQUERDO), _ear(pixels, IDX_OLHO_DIREITO)


def mar(landmarks: np.ndarray, largura: int = 1, altura: int = 1) -> float:
    """Mouth aspect ratio — proxy de bocejo. Ver a fórmula na docstring do módulo."""
    pixels = _em_pixels(landmarks, largura, altura)
    verticais = [_distancia(pixels, cima, baixo) for cima, baixo in IDX_BOCA_VERTICAIS]
    return _razao(verticais, _distancia(pixels, *IDX_BOCA_CANTOS))


def head_pose(landmarks: np.ndarray, largura: int, altura: int) -> Tuple[float, float, float]:
    """Orientação da cabeça em graus, na ordem (yaw, pitch, roll).

    Devolve `(nan, nan, nan)` quando o `solvePnP` não converge — geometria
    degenerada, pontos colineares ou landmarks não finitos. Nunca levanta: um
    frame ruim no meio de um clipe de 300 não pode derrubar a extração inteira.
    """
    pixels = _em_pixels(landmarks, largura, altura)
    pontos2d = np.ascontiguousarray(pixels[list(IDX_POSE)], dtype=np.float64)
    if not np.isfinite(pontos2d).all():
        return _NAN, _NAN, _NAN

    matriz_camera = np.array(
        [[largura, 0.0, largura / 2.0], [0.0, largura, altura / 2.0], [0.0, 0.0, 1.0]],
        dtype=np.float64,
    )
    try:
        sucesso, rvec, _ = cv2.solvePnP(
            MODELO_3D_POSE,
            pontos2d,
            matriz_camera,
            np.zeros((4, 1), dtype=np.float64),
            flags=cv2.SOLVEPNP_ITERATIVE,
        )
    except cv2.error:
        return _NAN, _NAN, _NAN
    if not sucesso or not np.isfinite(rvec).all():
        return _NAN, _NAN, _NAN

    rotacao, _ = cv2.Rodrigues(rvec)
    angulos = _angulos_de_euler(rotacao)
    if not all(math.isfinite(angulo) for angulo in angulos):
        return _NAN, _NAN, _NAN
    return angulos


def metricas_do_frame(landmarks: np.ndarray, largura: int, altura: int) -> Dict[str, float]:
    """Todas as métricas de um frame com rosto detectado.

    As chaves são exatamente `COLUNAS_METRICAS`, na mesma ordem — é o dicionário
    que o extrator vira linha do DataFrame de frames.
    """
    pixels = _em_pixels(landmarks, largura, altura)
    ear_esq = _ear(pixels, IDX_OLHO_ESQUERDO)
    ear_dir = _ear(pixels, IDX_OLHO_DIREITO)
    verticais = [_distancia(pixels, cima, baixo) for cima, baixo in IDX_BOCA_VERTICAIS]
    yaw, pitch, roll = head_pose(landmarks, largura, altura)
    return {
        "ear_esq": ear_esq,
        "ear_dir": ear_dir,
        "ear": (ear_esq + ear_dir) / 2.0,
        "mar": _razao(verticais, _distancia(pixels, *IDX_BOCA_CANTOS)),
        "yaw": yaw,
        "pitch": pitch,
        "roll": roll,
    }


def sem_rosto() -> Dict[str, float]:
    """Métricas de um frame em que o MediaPipe não detectou rosto: tudo NaN.

    NaN e nunca 0 — ver a docstring do módulo. O extrator marca `face_detectada`
    como False na mesma linha, e a agregação usa esse par para separar "não sei"
    de "sei que estava fechado".
    """
    return {coluna: _NAN for coluna in COLUNAS_METRICAS}
