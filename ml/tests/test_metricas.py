"""Testes de `metricas`, com landmarks sintéticos.

Nenhum teste aqui abre vídeo ou roda o MediaPipe: o módulo sob teste é
matemática pura, então os landmarks são construídos com geometria conhecida e o
resultado esperado sai da fórmula no papel, não de um valor observado que alguém
copiou de uma execução.

Os desenhadores de olho e boca são propositalmente simétricos, de modo que EAR e
MAR fiquem exatamente `altura_px / largura_px` — dá para escrever a expectativa
sem tolerância frouxa e o teste falha se a fórmula mudar de denominador.
"""
import math

import cv2
import numpy as np
import pytest

from esquema import COLUNAS_METRICAS, LIMIAR_BOCA_ABERTA, LIMIAR_OLHOS_FECHADOS
from metricas import ear_olhos, head_pose, mar, metricas_do_frame, sem_rosto

LARGURA = 640
ALTURA = 480

#: Mesmos índices do módulo, repetidos aqui de propósito: se alguém trocar um
#: índice em `metricas.py` sem querer, o teste tem que reclamar.
OLHO_ESQ = (362, 385, 387, 263, 373, 380)
OLHO_DIR = (33, 160, 158, 133, 153, 144)


def _base() -> np.ndarray:
    """468 landmarks empilhados no centro do frame, prontos para sobrescrita."""
    return np.full((468, 3), 0.5, dtype=float)


def _desenha_olho(
    landmarks: np.ndarray,
    indices: tuple[int, ...],
    centro: tuple[float, float],
    largura_px: float,
    altura_px: float,
) -> None:
    """Escreve um olho simétrico em `indices`, na ordem p1..p6 do EAR.

    Com p2/p3 e p6/p5 alinhados verticalmente, as duas distâncias verticais
    valem `altura_px` e a horizontal vale `largura_px` — logo o EAR esperado é
    exatamente `altura_px / largura_px`.
    """
    cx, cy = centro
    meia_l, terco, meia_a = largura_px / 2, largura_px / 6, altura_px / 2
    posicoes = [
        (cx - meia_l, cy),          # p1 — canto
        (cx - terco, cy - meia_a),  # p2 — pálpebra superior
        (cx + terco, cy - meia_a),  # p3 — pálpebra superior
        (cx + meia_l, cy),          # p4 — canto oposto
        (cx + terco, cy + meia_a),  # p5 — pálpebra inferior
        (cx - terco, cy + meia_a),  # p6 — pálpebra inferior
    ]
    for indice, (px, py) in zip(indices, posicoes):
        landmarks[indice] = (px / LARGURA, py / ALTURA, 0.0)


def _desenha_boca(
    landmarks: np.ndarray,
    centro: tuple[float, float],
    largura_px: float,
    altura_px: float,
) -> None:
    """Boca simétrica: as três verticais valem `altura_px`, a horizontal `largura_px`."""
    cx, cy = centro
    meia_l, meia_a = largura_px / 2, altura_px / 2
    landmarks[61] = ((cx - meia_l) / LARGURA, cy / ALTURA, 0.0)
    landmarks[291] = ((cx + meia_l) / LARGURA, cy / ALTURA, 0.0)
    verticais = {13: 0.0, 14: 0.0, 81: -largura_px / 4, 178: -largura_px / 4,
                 311: largura_px / 4, 402: largura_px / 4}
    superiores = (13, 81, 311)
    for indice, deslocamento in verticais.items():
        py = cy - meia_a if indice in superiores else cy + meia_a
        landmarks[indice] = ((cx + deslocamento) / LARGURA, py / ALTURA, 0.0)


#: Os seis pontos de pose no referencial da câmera do OpenCV (x para a direita
#: da imagem, y para baixo, z para dentro da cena), lidos do
#: `canonical_face_model.obj` do MediaPipe com y e z invertidos. Escritos aqui de
#: forma independente do módulo para que o teste valide a convenção de sinal, e
#: não apenas o ida-e-volta de uma constante compartilhada.
MODELO_TESTE = np.array(
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
INDICES_POSE = (1, 199, 263, 33, 291, 61)


def _rosto_rotacionado(rvec: tuple[float, float, float], distancia: float = 60.0) -> np.ndarray:
    """Projeta o rosto canônico girado por `rvec` (Rodrigues, radianos).

    Usa a mesma câmera aproximada que o módulo assume (focal = largura, centro no
    meio do frame), então recuperar `rvec` de volta é um round-trip honesto.
    """
    matriz = np.array(
        [[LARGURA, 0.0, LARGURA / 2], [0.0, LARGURA, ALTURA / 2], [0.0, 0.0, 1.0]],
        dtype=np.float64,
    )
    pontos2d, _ = cv2.projectPoints(
        MODELO_TESTE,
        np.array(rvec, dtype=np.float64).reshape(3, 1),
        np.array([[0.0], [0.0], [distancia]], dtype=np.float64),
        matriz,
        np.zeros((4, 1), dtype=np.float64),
    )
    landmarks = _base()
    for indice, (px, py) in zip(INDICES_POSE, pontos2d.reshape(-1, 2)):
        landmarks[indice] = (px / LARGURA, py / ALTURA, 0.0)
    return landmarks


# --- EAR -------------------------------------------------------------------


def test_olho_fechado_fica_abaixo_do_limiar():
    landmarks = _base()
    _desenha_olho(landmarks, OLHO_ESQ, (400.0, 200.0), largura_px=30.0, altura_px=0.0)
    _desenha_olho(landmarks, OLHO_DIR, (240.0, 200.0), largura_px=30.0, altura_px=0.0)

    esquerdo, direito = ear_olhos(landmarks, LARGURA, ALTURA)

    assert esquerdo == pytest.approx(0.0)
    assert direito == pytest.approx(0.0)
    assert esquerdo < LIMIAR_OLHOS_FECHADOS


def test_olho_aberto_realista_cai_na_faixa_esperada():
    landmarks = _base()
    _desenha_olho(landmarks, OLHO_ESQ, (400.0, 200.0), largura_px=30.0, altura_px=10.0)
    _desenha_olho(landmarks, OLHO_DIR, (240.0, 200.0), largura_px=30.0, altura_px=10.0)

    esquerdo, direito = ear_olhos(landmarks, LARGURA, ALTURA)

    assert esquerdo == pytest.approx(1 / 3)
    assert direito == pytest.approx(1 / 3)
    assert 0.25 <= esquerdo <= 0.40
    assert esquerdo > LIMIAR_OLHOS_FECHADOS


def test_ear_e_calculado_em_pixels_e_nao_em_coordenadas_normalizadas():
    """Num frame 4:3, ignorar o aspect ratio inflaria o EAR em 640/480."""
    landmarks = _base()
    _desenha_olho(landmarks, OLHO_ESQ, (400.0, 200.0), largura_px=30.0, altura_px=10.0)

    esquerdo, _ = ear_olhos(landmarks, LARGURA, ALTURA)

    assert esquerdo == pytest.approx(1 / 3)
    assert esquerdo != pytest.approx((1 / 3) * (LARGURA / ALTURA))


def test_os_dois_olhos_sao_medidos_de_forma_independente():
    landmarks = _base()
    _desenha_olho(landmarks, OLHO_ESQ, (400.0, 200.0), largura_px=30.0, altura_px=1.5)
    _desenha_olho(landmarks, OLHO_DIR, (240.0, 200.0), largura_px=30.0, altura_px=9.0)

    esquerdo, direito = ear_olhos(landmarks, LARGURA, ALTURA)

    assert esquerdo == pytest.approx(0.05)
    assert direito == pytest.approx(0.30)


def test_olho_degenerado_sem_largura_devolve_nan():
    landmarks = _base()
    _desenha_olho(landmarks, OLHO_ESQ, (400.0, 200.0), largura_px=0.0, altura_px=0.0)
    _desenha_olho(landmarks, OLHO_DIR, (240.0, 200.0), largura_px=30.0, altura_px=10.0)

    esquerdo, direito = ear_olhos(landmarks, LARGURA, ALTURA)

    assert math.isnan(esquerdo)
    assert not math.isnan(direito)


# --- MAR -------------------------------------------------------------------


def test_boca_fechada_fica_abaixo_do_limiar():
    landmarks = _base()
    _desenha_boca(landmarks, (320.0, 300.0), largura_px=50.0, altura_px=1.0)

    assert mar(landmarks, LARGURA, ALTURA) == pytest.approx(0.02)
    assert mar(landmarks, LARGURA, ALTURA) < LIMIAR_BOCA_ABERTA


def test_boca_escancarada_cruza_o_limiar():
    landmarks = _base()
    _desenha_boca(landmarks, (320.0, 300.0), largura_px=50.0, altura_px=45.0)

    assert mar(landmarks, LARGURA, ALTURA) == pytest.approx(0.9)
    assert mar(landmarks, LARGURA, ALTURA) > LIMIAR_BOCA_ABERTA


def test_boca_sem_largura_devolve_nan():
    landmarks = _base()
    _desenha_boca(landmarks, (320.0, 300.0), largura_px=0.0, altura_px=10.0)

    assert math.isnan(mar(landmarks, LARGURA, ALTURA))


# --- Head pose -------------------------------------------------------------


def test_rosto_frontal_tem_angulos_proximos_de_zero():
    landmarks = _rosto_rotacionado((0.0, 0.0, 0.0))

    yaw, pitch, roll = head_pose(landmarks, LARGURA, ALTURA)

    assert yaw == pytest.approx(0.0, abs=2.0)
    assert pitch == pytest.approx(0.0, abs=2.0)
    assert roll == pytest.approx(0.0, abs=2.0)


def test_yaw_positivo_quando_a_cabeca_vira_para_a_direita_do_sujeito():
    graus = 20.0
    landmarks = _rosto_rotacionado((0.0, math.radians(graus), 0.0))

    yaw, pitch, roll = head_pose(landmarks, LARGURA, ALTURA)

    assert yaw > 0
    assert yaw == pytest.approx(graus, abs=3.0)
    assert pitch == pytest.approx(0.0, abs=3.0)
    assert roll == pytest.approx(0.0, abs=3.0)


def test_yaw_negativo_quando_a_cabeca_vira_para_a_esquerda_do_sujeito():
    landmarks = _rosto_rotacionado((0.0, math.radians(-20.0), 0.0))

    yaw, _, _ = head_pose(landmarks, LARGURA, ALTURA)

    assert yaw < 0
    assert yaw == pytest.approx(-20.0, abs=3.0)


def test_pitch_positivo_quando_a_cabeca_abaixa():
    graus = 15.0
    landmarks = _rosto_rotacionado((math.radians(graus), 0.0, 0.0))

    yaw, pitch, roll = head_pose(landmarks, LARGURA, ALTURA)

    assert pitch > 0
    assert pitch == pytest.approx(graus, abs=3.0)
    assert yaw == pytest.approx(0.0, abs=3.0)
    assert roll == pytest.approx(0.0, abs=3.0)


def test_roll_positivo_quando_a_cabeca_pende_para_o_ombro_esquerdo():
    graus = 25.0
    landmarks = _rosto_rotacionado((0.0, 0.0, math.radians(graus)))

    yaw, pitch, roll = head_pose(landmarks, LARGURA, ALTURA)

    assert roll > 0
    assert roll == pytest.approx(graus, abs=3.0)
    assert yaw == pytest.approx(0.0, abs=3.0)
    assert pitch == pytest.approx(0.0, abs=3.0)


def test_pose_degenerada_devolve_nan_sem_explodir():
    """Todos os pontos de pose no mesmo pixel: solvePnP não tem solução."""
    landmarks = _base()

    yaw, pitch, roll = head_pose(landmarks, LARGURA, ALTURA)

    assert math.isnan(yaw)
    assert math.isnan(pitch)
    assert math.isnan(roll)


# --- Agregação por frame ---------------------------------------------------


def test_metricas_do_frame_devolve_exatamente_as_chaves_do_esquema():
    landmarks = _rosto_rotacionado((0.0, 0.0, 0.0))

    metricas = metricas_do_frame(landmarks, LARGURA, ALTURA)

    assert list(metricas) == list(COLUNAS_METRICAS)
    assert all(isinstance(valor, float) for valor in metricas.values())


def test_ear_do_frame_e_a_media_dos_dois_olhos():
    landmarks = _base()
    _desenha_olho(landmarks, OLHO_ESQ, (400.0, 200.0), largura_px=30.0, altura_px=3.0)
    _desenha_olho(landmarks, OLHO_DIR, (240.0, 200.0), largura_px=30.0, altura_px=9.0)
    _desenha_boca(landmarks, (320.0, 300.0), largura_px=50.0, altura_px=5.0)

    metricas = metricas_do_frame(landmarks, LARGURA, ALTURA)

    assert metricas["ear_esq"] == pytest.approx(0.10)
    assert metricas["ear_dir"] == pytest.approx(0.30)
    assert metricas["ear"] == pytest.approx(0.20)
    assert metricas["mar"] == pytest.approx(0.10)


def test_metricas_do_frame_nao_explode_com_rosto_degenerado():
    metricas = metricas_do_frame(_base(), LARGURA, ALTURA)

    assert list(metricas) == list(COLUNAS_METRICAS)


def test_sem_rosto_devolve_as_mesmas_chaves_todas_nan():
    metricas = sem_rosto()

    assert list(metricas) == list(COLUNAS_METRICAS)
    assert all(math.isnan(valor) for valor in metricas.values())


def test_sem_rosto_nunca_usa_zero():
    """Zero seria indistinguível de um olho de fato fechado."""
    assert not any(valor == 0.0 for valor in sem_rosto().values())


# --- Validação de entrada --------------------------------------------------


@pytest.mark.parametrize(
    "shape",
    [(468, 2), (300, 3), (468,), (468, 3, 1), (0, 3)],
    ids=["sem_z", "poucos_landmarks", "unidimensional", "tridimensional", "vazio"],
)
def test_shape_invalido_levanta_erro_claro(shape):
    landmarks = np.zeros(shape, dtype=float)

    for funcao in (
        lambda lm: ear_olhos(lm, LARGURA, ALTURA),
        lambda lm: mar(lm, LARGURA, ALTURA),
        lambda lm: head_pose(lm, LARGURA, ALTURA),
        lambda lm: metricas_do_frame(lm, LARGURA, ALTURA),
    ):
        with pytest.raises(ValueError, match="landmarks"):
            funcao(landmarks)


def test_aceita_os_478_landmarks_do_refine_landmarks():
    landmarks = np.full((478, 3), 0.5, dtype=float)
    _desenha_olho(landmarks, OLHO_ESQ, (400.0, 200.0), largura_px=30.0, altura_px=10.0)
    _desenha_olho(landmarks, OLHO_DIR, (240.0, 200.0), largura_px=30.0, altura_px=10.0)

    esquerdo, direito = ear_olhos(landmarks, LARGURA, ALTURA)

    assert esquerdo == pytest.approx(1 / 3)
    assert direito == pytest.approx(1 / 3)
