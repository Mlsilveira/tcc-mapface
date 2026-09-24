"""Testes da agregação que reproduz o que o backend vê.

O que se afirma aqui é a **equivalência com a produção**: a janela que o modelo
treina tem de ser montada do mesmo jeito que a janela que ele vai receber. Um
teste de desvio-padrão parece detalhe e não é — é exatamente a coluna que o
train/serve skew estraga em silêncio.
"""
import numpy as np
import pandas as pd
import pytest

import agregacao_producao as ap
from esquema import COLUNA_CLIPE, COLUNAS_FRAMES, COLUNAS_METRICAS, colunas_features

FPS = {"rldd-01-10-1": 4.0}


def monta_frames(clip_id: str = "rldd-01-10-1-0000", n: int = 40, semente: int = 1) -> pd.DataFrame:
    """Frames a 4 fps: dez segundos de quatro amostras cada."""
    rng = np.random.default_rng(semente)
    linhas = []
    for i in range(n):
        metricas = {nome: float(rng.normal(0.3, 0.05)) for nome in COLUNAS_METRICAS}
        linhas.append(
            {COLUNA_CLIPE: clip_id, "frame_idx": i, "face_detectada": True, **metricas}
        )
    return pd.DataFrame(linhas, columns=COLUNAS_FRAMES).astype(
        {"frame_idx": "int64", "face_detectada": "bool"}
    )


# --- Resumo em segundos ----------------------------------------------------


def test_uma_linha_por_segundo() -> None:
    resumo = ap.resume_em_segundos(monta_frames(n=40), FPS)

    assert len(resumo) == 10
    assert list(resumo["frame_idx"]) == list(range(10))
    assert list(resumo.columns) == COLUNAS_FRAMES


def test_a_metrica_do_segundo_e_a_media_dos_frames_dele() -> None:
    frames = monta_frames(n=40)

    resumo = ap.resume_em_segundos(frames, FPS)

    primeiro = frames[frames["frame_idx"] < 4]["ear"].mean()
    assert resumo.iloc[0]["ear"] == pytest.approx(primeiro)


def test_frames_sem_rosto_ficam_fora_da_media() -> None:
    """Contá-los como zero puxaria o EAR para baixo e viraria "sonolência".

    Mesma regra do agregador do navegador, reproduzida em vez de reinventada.
    """
    frames = monta_frames(n=8)
    frames.loc[frames["frame_idx"] == 1, "face_detectada"] = False
    frames.loc[frames["frame_idx"] == 1, list(COLUNAS_METRICAS)] = np.nan

    resumo = ap.resume_em_segundos(frames, FPS)

    validos = frames[(frames["frame_idx"] < 4) & frames["face_detectada"]]["ear"].mean()
    assert resumo.iloc[0]["ear"] == pytest.approx(validos)
    assert bool(resumo.iloc[0]["face_detectada"]) is True


def test_segundo_inteiro_sem_rosto_vira_ausencia_e_nao_zero() -> None:
    frames = monta_frames(n=8)
    sem_rosto = frames["frame_idx"] < 4
    frames.loc[sem_rosto, "face_detectada"] = False
    frames.loc[sem_rosto, list(COLUNAS_METRICAS)] = np.nan

    resumo = ap.resume_em_segundos(frames, FPS)

    assert bool(resumo.iloc[0]["face_detectada"]) is False
    assert pd.isna(resumo.iloc[0]["ear"])


def test_fps_pode_vir_pelo_prefixo_da_gravacao() -> None:
    """O fps é do arquivo de vídeo; todas as janelas dele compartilham o mesmo."""
    resumo = ap.resume_em_segundos(monta_frames(n=8), {"rldd-01-10-1": 4.0})

    assert len(resumo) == 2


def test_fps_ausente_falha_alto() -> None:
    with pytest.raises(ap.FpsDesconhecido):
        ap.resume_em_segundos(monta_frames(n=8), {})


def test_frames_vazio() -> None:
    with pytest.raises(ValueError):
        ap.resume_em_segundos(monta_frames(n=0), FPS)


# --- Equivalência com a produção -------------------------------------------


def test_as_colunas_sao_exatamente_as_mesmas_da_agregacao_normal() -> None:
    """Mesmos nomes e mesma ordem: o modelo não sabe por qual caminho veio."""
    import agregacao

    frames = monta_frames(n=40)

    produto = ap.agrega_como_o_produto(frames, FPS)
    normal = agregacao.agrega(frames)

    assert list(produto.columns) == list(normal.columns)
    assert list(produto.columns) == [COLUNA_CLIPE] + colunas_features()


def test_a_media_por_segundo_achata_o_desvio() -> None:
    """A coluna que o descasamento entre treino e produção estraga em silêncio.

    O desvio de 40 medições é sistematicamente maior que o de 10 médias, porque
    a média já comeu a variação de dentro do segundo. Um modelo treinado no
    primeiro e servido com o segundo passaria a ver todo mundo anormalmente
    parado — sem erro no log, só com o número errado.
    """
    import agregacao

    frames = monta_frames(n=40)

    produto = ap.agrega_como_o_produto(frames, FPS)
    normal = agregacao.agrega(frames)

    assert produto.iloc[0]["ear_desvio"] < normal.iloc[0]["ear_desvio"]


def test_n_frames_passa_a_contar_segundos() -> None:
    produto = ap.agrega_como_o_produto(monta_frames(n=40), FPS)

    assert produto.iloc[0]["n_frames"] == 10


def test_varias_janelas_de_uma_vez() -> None:
    uma = monta_frames("rldd-01-10-1-0000", n=40, semente=1)
    outra = monta_frames("rldd-01-10-1-0001", n=40, semente=2)

    produto = ap.agrega_como_o_produto(pd.concat([uma, outra], ignore_index=True), FPS)

    assert len(produto) == 2
    assert list(produto[COLUNA_CLIPE]) == ["rldd-01-10-1-0000", "rldd-01-10-1-0001"]


# --- Catálogo de fps -------------------------------------------------------


def test_fps_das_gravacoes_usa_o_prefixo_como_chave() -> None:
    catalogo = pd.DataFrame(
        [
            {"participante": "01", "fold": 1, "sonolencia": 10, "parte": 1, "caminho": "a.mov"},
            {"participante": "02", "fold": 1, "sonolencia": 0, "parte": 2, "caminho": "b.mp4"},
        ]
    )

    mapa = ap.fps_das_gravacoes(catalogo, medidor=lambda caminho: 30 if caminho == "a.mov" else 25)

    assert mapa == {"rldd-01-10-1": 30.0, "rldd-02-0-2": 25.0}
