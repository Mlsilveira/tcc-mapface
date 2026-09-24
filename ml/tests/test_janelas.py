"""Testes do corte de um vídeo longo em janelas de tamanho fixo.

Mesma disciplina do `test_extracao`: nenhum teste toca o MediaPipe nem um vídeo
de verdade. Os vídeos são gerados na hora e o detector entra injetado, então o
que se afirma aqui é o comportamento do **corte** — quantas janelas saem, quais
frames caem em qual, e o que acontece com o resto que não fecha uma janela.
"""
from pathlib import Path

import pytest

import extracao
from esquema import COLUNA_CLIPE
from tests.test_extracao import CalculadoraFalsa, DetectorFalso, escreve_video


def extrai(video: Path, frames_por_janela: int, **kwargs):
    kwargs.setdefault("detector", DetectorFalso())
    kwargs.setdefault("calculadora", CalculadoraFalsa())
    return extracao.extrai_frames_em_janelas(
        video, "rldd-01-10-1", frames_por_janela=frames_por_janela, **kwargs
    )


# --- O corte ---------------------------------------------------------------


def test_corta_em_janelas_do_tamanho_pedido(tmp_path: Path) -> None:
    video = escreve_video(tmp_path / "longo.avi", n_frames=12)

    frames = extrai(video, frames_por_janela=4)

    assert list(frames[COLUNA_CLIPE].unique()) == [
        "rldd-01-10-1-0000",
        "rldd-01-10-1-0001",
        "rldd-01-10-1-0002",
    ]
    assert frames.groupby(COLUNA_CLIPE).size().tolist() == [4, 4, 4]


def test_o_frame_idx_continua_sendo_o_do_video(tmp_path: Path) -> None:
    """A escala temporal é a do arquivo, não a posição dentro da janela.

    É o que permite medir duração de pálpebra fechada atravessando a fronteira
    de duas janelas — um contador reiniciado por janela mentiria justamente no
    evento mais longo, que é o mais relevante para sonolência.
    """
    video = escreve_video(tmp_path / "longo.avi", n_frames=8)

    frames = extrai(video, frames_por_janela=4)

    segunda = frames[frames[COLUNA_CLIPE] == "rldd-01-10-1-0001"]
    assert list(segunda["frame_idx"]) == [4, 5, 6, 7]


def test_descarta_a_ultima_janela_incompleta(tmp_path: Path) -> None:
    """`n_frames` é feature: uma janela de 2 frames não é comparável a uma de 4.

    O desvio-padrão de duas observações e o de sessenta descrevem coisas
    diferentes, e o modelo não tem como saber disso — ele veria só um número
    menor. Um resto de poucos segundos no fim de dez minutos não vale a
    heterogeneidade que introduziria em todas as linhas.
    """
    video = escreve_video(tmp_path / "longo.avi", n_frames=10)

    frames = extrai(video, frames_por_janela=4)

    assert list(frames[COLUNA_CLIPE].unique()) == [
        "rldd-01-10-1-0000",
        "rldd-01-10-1-0001",
    ]
    assert frames["frame_idx"].max() == 7


def test_video_curto_demais_para_uma_janela_e_ilegivel(tmp_path: Path) -> None:
    """Zero janela completa é falha de gravação, não dataset vazio.

    Sem isto a gravação viraria um shard sem linha nenhuma, e a consolidação a
    somaria em silêncio ao dataset — um vídeo faltando entre 182 não aparece.
    """
    video = escreve_video(tmp_path / "curto.avi", n_frames=3)

    with pytest.raises(extracao.VideoIlegivel):
        extrai(video, frames_por_janela=10)


# --- Amostragem ------------------------------------------------------------


def test_a_amostragem_nao_muda_o_tamanho_da_janela(tmp_path: Path) -> None:
    """A janela é contada em frames do vídeo, não em frames processados.

    É o que mantém os 10 segundos de relógio iguais num vídeo de 25 fps e num de
    30 — e a comparabilidade com os clipes de 10s do DAiSEE depende disso.
    """
    video = escreve_video(tmp_path / "longo.avi", n_frames=12)

    frames = extrai(video, frames_por_janela=4, amostragem=2)

    assert frames.groupby(COLUNA_CLIPE).size().tolist() == [2, 2, 2]
    assert list(frames["frame_idx"]) == [0, 2, 4, 6, 8, 10]


def test_amostragem_invalida(tmp_path: Path) -> None:
    video = escreve_video(tmp_path / "longo.avi", n_frames=4)

    with pytest.raises(ValueError):
        extrai(video, frames_por_janela=2, amostragem=0)


def test_janela_invalida(tmp_path: Path) -> None:
    video = escreve_video(tmp_path / "longo.avi", n_frames=4)

    with pytest.raises(ValueError):
        extrai(video, frames_por_janela=0)


# --- O rastreamento não é reiniciado entre janelas -------------------------


def test_nao_reinicia_o_detector_entre_janelas(tmp_path: Path) -> None:
    """Janelas contíguas são a mesma pessoa; reiniciar jogaria fora o rastreio.

    É o oposto do que vale entre clipes do DAiSEE, onde cada clipe é um corte
    duro para outro sujeito. Aqui o detector recebe os frames em sequência e
    nunca é tocado — quem reinicia é o CLI, uma vez por gravação.
    """

    class DetectorQueContaReinicios(DetectorFalso):
        def __init__(self) -> None:
            super().__init__()
            self.reinicios = 0

        def reinicia(self) -> None:
            self.reinicios += 1

    detector = DetectorQueContaReinicios()
    video = escreve_video(tmp_path / "longo.avi", n_frames=12)

    extrai(video, frames_por_janela=4, detector=detector)

    assert detector.reinicios == 0
    assert detector.chamadas == 12


# --- Redução de resolução --------------------------------------------------


def test_reduz_quadros_mais_largos_que_o_limite(tmp_path: Path) -> None:
    detector = DetectorFalso()
    video = escreve_video(tmp_path / "longo.avi", n_frames=4)

    extrai(video, frames_por_janela=2, detector=detector, largura_maxima=32)

    # `escreve_video` grava em 64x48; o limite de 32 corta pela metade.
    assert {formato[:2] for formato in detector.formatos} == {(24, 32)}


def test_nao_amplia_quadros_menores_que_o_limite(tmp_path: Path) -> None:
    """Interpolar para cima não cria detalhe — só custa tempo e inventa pixel."""
    detector = DetectorFalso()
    video = escreve_video(tmp_path / "longo.avi", n_frames=4)

    extrai(video, frames_por_janela=2, detector=detector, largura_maxima=4000)

    assert {formato[:2] for formato in detector.formatos} == {(48, 64)}


def test_sem_limite_o_quadro_passa_intacto(tmp_path: Path) -> None:
    detector = DetectorFalso()
    video = escreve_video(tmp_path / "longo.avi", n_frames=4)

    extrai(video, frames_por_janela=2, detector=detector, largura_maxima=None)

    assert {formato[:2] for formato in detector.formatos} == {(48, 64)}
