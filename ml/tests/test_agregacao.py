"""Testes da agregação frame → clipe.

Os DataFrames de frames são montados à mão, com números escolhidos para que a
conta esperada caiba de cabeça. O que está sendo testado aqui não é o pandas: é
a definição de cada feature — quem entra no denominador, o que acontece quando
não há rosto nenhum e o que sobra de um clipe com um único frame válido.
"""
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import pytest

import agregacao
from esquema import (
    COLUNA_CLIPE,
    COLUNA_SPLIT,
    COLUNA_USUARIO,
    COLUNAS_FRAMES,
    COLUNAS_METRICAS,
    COLUNAS_ROTULOS,
    EsquemaInvalido,
    LIMIAR_BOCA_ABERTA,
    LIMIAR_OLHOS_FECHADOS,
    colunas_clipes,
    colunas_features,
    valida_clipes,
)

NEUTRO: Dict[str, float] = {
    "ear_esq": 0.30,
    "ear_dir": 0.30,
    "ear": 0.30,
    "mar": 0.20,
    "yaw": 0.0,
    "pitch": 0.0,
    "roll": 0.0,
}


def com_rosto(**override: float) -> Optional[Dict[str, float]]:
    return dict(NEUTRO, **override)


SEM_ROSTO: Optional[Dict[str, float]] = None


def frames(*linhas: Optional[Dict[str, float]], clip_id: str = "c1") -> pd.DataFrame:
    registros: List[Dict[str, object]] = []
    for indice, metricas in enumerate(linhas):
        base: Dict[str, object] = {
            COLUNA_CLIPE: clip_id,
            "frame_idx": indice,
            "face_detectada": metricas is not None,
        }
        valores = metricas or {coluna: np.nan for coluna in COLUNAS_METRICAS}
        base.update(valores)
        registros.append(base)
    return pd.DataFrame(registros, columns=COLUNAS_FRAMES)


# --- agrega_clipe: contrato ------------------------------------------------


def test_agrega_clipe_devolve_clip_id_e_todas_as_features() -> None:
    linha = agregacao.agrega_clipe(frames(com_rosto(), com_rosto()))

    assert list(linha.keys()) == [COLUNA_CLIPE] + colunas_features()
    assert linha[COLUNA_CLIPE] == "c1"


def test_agrega_clipe_rejeita_mais_de_um_clipe() -> None:
    misturado = pd.concat([frames(com_rosto()), frames(com_rosto(), clip_id="c2")])

    with pytest.raises(ValueError):
        agregacao.agrega_clipe(misturado)


def test_agrega_clipe_rejeita_frames_vazios() -> None:
    with pytest.raises(ValueError):
        agregacao.agrega_clipe(frames())


# --- agrega_clipe: as cinco agregações -------------------------------------


def test_agregacoes_ignoram_frames_sem_rosto() -> None:
    linha = agregacao.agrega_clipe(
        frames(com_rosto(ear=0.10), SEM_ROSTO, com_rosto(ear=0.30))
    )

    assert linha["ear_media"] == pytest.approx(0.20)
    assert linha["ear_mediana"] == pytest.approx(0.20)
    assert linha["ear_min"] == pytest.approx(0.10)
    assert linha["ear_max"] == pytest.approx(0.30)
    # Literal, e não `np.std(..., ddof=1)`: recomputar com numpy o que o pandas
    # calculou só afirma que as duas bibliotecas concordam, e codifica o `ddof`
    # que é justamente a decisão sob teste. sqrt(((0.10-0.20)² + (0.30-0.20)²)/1).
    assert linha["ear_desvio"] == pytest.approx(0.1414213562)


def test_desvio_de_um_unico_frame_valido_fica_nan() -> None:
    """Decisão: NaN, não 0.0 — uma observação só não é "postura estável"."""
    linha = agregacao.agrega_clipe(frames(com_rosto(ear=0.25), SEM_ROSTO))

    assert np.isnan(linha["ear_desvio"])
    assert linha["ear_media"] == pytest.approx(0.25)


def test_clipe_sem_nenhum_rosto_agrega_para_nan() -> None:
    linha = agregacao.agrega_clipe(frames(SEM_ROSTO, SEM_ROSTO, SEM_ROSTO))

    for metrica in COLUNAS_METRICAS:
        assert np.isnan(linha[f"{metrica}_media"])
        assert np.isnan(linha[f"{metrica}_min"])
    assert linha["prop_frames_com_rosto"] == 0.0
    assert linha["n_frames"] == 3
    assert np.isnan(linha["prop_olhos_fechados"])
    assert np.isnan(linha["prop_boca_aberta"])


# --- Features derivadas ----------------------------------------------------


def test_prop_frames_com_rosto_e_sobre_o_total() -> None:
    linha = agregacao.agrega_clipe(frames(com_rosto(), SEM_ROSTO, com_rosto(), com_rosto()))

    assert linha["prop_frames_com_rosto"] == pytest.approx(0.75)


def test_n_frames_conta_tambem_os_frames_sem_rosto() -> None:
    linha = agregacao.agrega_clipe(frames(com_rosto(), SEM_ROSTO, SEM_ROSTO))

    assert linha["n_frames"] == 3


def test_prop_olhos_fechados_e_sobre_os_frames_com_rosto() -> None:
    """Metade dos frames com rosto, não um quarto do total."""
    linha = agregacao.agrega_clipe(
        frames(com_rosto(ear=0.10), com_rosto(ear=0.30), SEM_ROSTO, SEM_ROSTO)
    )

    assert linha["prop_olhos_fechados"] == pytest.approx(0.5)


def test_prop_boca_aberta_e_sobre_os_frames_com_rosto() -> None:
    linha = agregacao.agrega_clipe(
        frames(com_rosto(mar=0.90), com_rosto(mar=0.10), SEM_ROSTO)
    )

    assert linha["prop_boca_aberta"] == pytest.approx(0.5)


def test_limiares_sao_estritos() -> None:
    linha = agregacao.agrega_clipe(
        frames(com_rosto(ear=LIMIAR_OLHOS_FECHADOS, mar=LIMIAR_BOCA_ABERTA))
    )

    assert linha["prop_olhos_fechados"] == 0.0
    assert linha["prop_boca_aberta"] == 0.0


# --- agrega ----------------------------------------------------------------


def test_agrega_devolve_uma_linha_por_clipe() -> None:
    todos = pd.concat(
        [
            frames(com_rosto(ear=0.10), com_rosto(ear=0.30), clip_id="c1"),
            frames(com_rosto(ear=0.50), clip_id="c2"),
        ],
        ignore_index=True,
    )

    clipes = agregacao.agrega(todos)

    assert list(clipes[COLUNA_CLIPE]) == ["c1", "c2"]
    assert list(clipes.columns) == [COLUNA_CLIPE] + colunas_features()
    assert clipes.set_index(COLUNA_CLIPE).loc["c1", "ear_media"] == pytest.approx(0.20)
    assert clipes.set_index(COLUNA_CLIPE).loc["c2", "ear_media"] == pytest.approx(0.50)


def test_agrega_mantem_ordem_estavel_de_clipes() -> None:
    todos = pd.concat(
        [frames(com_rosto(), clip_id="c9"), frames(com_rosto(), clip_id="c2")],
        ignore_index=True,
    )

    assert list(agregacao.agrega(todos)[COLUNA_CLIPE]) == ["c2", "c9"]


def test_agrega_rejeita_frames_fora_do_contrato() -> None:
    with pytest.raises(EsquemaInvalido):
        agregacao.agrega(pd.DataFrame({"qualquer": [1]}))


def test_junta_rotulos_rejeita_rotulos_incompletos() -> None:
    clipes = agregacao.agrega(frames(com_rosto(), clip_id="c1"))
    sem_split = rotulos("c1").drop(columns=[COLUNA_SPLIT])

    with pytest.raises(EsquemaInvalido):
        agregacao.junta_rotulos(clipes, sem_split)


# --- junta_rotulos ---------------------------------------------------------


def rotulos(*clip_ids: str) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                COLUNA_CLIPE: clip_id,
                COLUNA_USUARIO: f"u{indice}",
                COLUNA_SPLIT: "Train",
                **{coluna: indice % 4 for coluna in COLUNAS_ROTULOS},
            }
            for indice, clip_id in enumerate(clip_ids)
        ]
    )


def test_junta_rotulos_monta_o_dataset_na_ordem_canonica() -> None:
    clipes = agregacao.agrega(
        pd.concat(
            [frames(com_rosto(), clip_id="c1"), frames(com_rosto(), clip_id="c2")],
            ignore_index=True,
        )
    )

    dataset = agregacao.junta_rotulos(clipes, rotulos("c1", "c2"))

    valida_clipes(dataset)
    assert list(dataset.columns) == colunas_clipes()
    assert list(dataset[COLUNA_CLIPE]) == ["c1", "c2"]
    assert list(dataset[COLUNA_USUARIO]) == ["u0", "u1"]


def test_junta_rotulos_descarta_clipe_sem_rotulo() -> None:
    clipes = agregacao.agrega(
        pd.concat(
            [frames(com_rosto(), clip_id="c1"), frames(com_rosto(), clip_id="c2")],
            ignore_index=True,
        )
    )

    dataset = agregacao.junta_rotulos(clipes, rotulos("c1"))

    assert list(dataset[COLUNA_CLIPE]) == ["c1"]


def test_junta_rotulos_descarta_rotulo_sem_clipe_extraido() -> None:
    clipes = agregacao.agrega(frames(com_rosto(), clip_id="c1"))

    dataset = agregacao.junta_rotulos(clipes, rotulos("c1", "c2"))

    assert list(dataset[COLUNA_CLIPE]) == ["c1"]
