"""Agregação que reproduz **o que o backend consegue ver em produção**.

`agregacao.py` resume uma janela a partir dos frames como eles saem do vídeo:
~60 linhas para 10 segundos, a 6 fps. O backend nunca terá isso. O que chega
nele é a telemetria da ticket 6: **uma linha por segundo**, já com as métricas
do segundo resumidas no navegador.

Treinar num nível de granularidade e servir noutro é a armadilha clássica de
train/serve skew, e ela é silenciosa: o desvio-padrão de 60 medições a 6 fps é
sistematicamente maior que o de 10 médias por segundo, porque a média já comeu a
variação de dentro do segundo. O modelo aprenderia uma escala de `ear_desvio`
que em produção nunca aparece, e passaria a responder como se todo mundo
estivesse anormalmente parado — sem erro nenhum no log, só com o número errado.

Este módulo existe para eliminar essa diferença: ele **primeiro** resume os
frames em segundos, exatamente como o navegador faz, e **só então** aplica as
mesmas agregações de `agregacao.py` sobre a série de segundos. As 39 colunas
resultantes têm os mesmos nomes e a mesma ordem; o que muda é que agora elas
descrevem a mesma coisa nos dois lados.

**Por que a média é a redução certa dentro do segundo.** É o que
`frontend/src/app/core/telemetria/agregacao.ts` já faz — e ele já faz o que
importa: frames sem rosto ficam fora da média em vez de entrar como zero, e uma
janela sem nenhum rosto vira ausência em vez de leitura. Aqui a regra é
reproduzida em vez de reinventada.
"""
from typing import Dict, List, Optional

import pandas as pd

from agregacao import agrega
from esquema import COLUNA_CLIPE, COLUNAS_FRAMES, COLUNAS_METRICAS, valida_frames

#: Nome da coluna temporária que marca a qual segundo o frame pertence.
COLUNA_SEGUNDO = "segundo"


class FpsDesconhecido(Exception):
    """Falta o fps de um clipe — sem ele não há como saber onde um segundo acaba."""


def _fps_do_clipe(clip_id: str, fps: Dict[str, float]) -> float:
    """O fps da gravação a que este clipe pertence.

    A chave pode ser o id da janela inteiro ou o prefixo da gravação
    (`rldd-01-10-1`), porque o fps é propriedade do arquivo de vídeo e todas as
    janelas dele compartilham o mesmo.
    """
    if clip_id in fps:
        return float(fps[clip_id])

    prefixo = clip_id.rsplit("-", 1)[0]
    if prefixo in fps:
        return float(fps[prefixo])

    raise FpsDesconhecido(f"sem fps para {clip_id!r} nem para o prefixo {prefixo!r}")


def resume_em_segundos(frames: pd.DataFrame, fps: Dict[str, float]) -> pd.DataFrame:
    """Uma linha por segundo de vídeo, como a telemetria entrega ao backend.

    Devolve um DataFrame no mesmo contrato de `COLUNAS_FRAMES`, com `frame_idx`
    passando a ser o índice do **segundo**. Isso é de propósito: o resto do
    pipeline continua funcionando sem saber que a granularidade mudou, e o
    `agrega` de sempre pode ser aplicado por cima.

    Frames sem rosto não entram na média das métricas — a mesma regra do
    `agregacao.py` e do agregador do navegador. Um segundo inteiro sem rosto sai
    com `face_detectada=False` e métricas em NaN, que é a ausência de leitura, e
    não uma leitura de zero.
    """
    valida_frames(frames)
    if frames.empty:
        raise ValueError("frames vazio: não há o que resumir")

    trabalho = frames.copy()
    trabalho[COLUNA_SEGUNDO] = [
        int(idx // _fps_do_clipe(str(clip), fps))
        for clip, idx in zip(trabalho[COLUNA_CLIPE], trabalho["frame_idx"])
    ]

    com_rosto = trabalho[trabalho["face_detectada"].fillna(False).astype(bool)]
    chaves = [COLUNA_CLIPE, COLUNA_SEGUNDO]

    medias = com_rosto.groupby(chaves)[list(COLUNAS_METRICAS)].mean()
    # `any` e não `all`: um segundo em que o rosto apareceu em ao menos um frame
    # produz leitura, e é assim que o navegador se comporta — ele agrega os
    # quadros com rosto da janela e descarta os demais.
    houve_rosto = trabalho.groupby(chaves)["face_detectada"].any()

    segundos = (
        houve_rosto.to_frame("face_detectada")
        .join(medias, how="left")
        .reset_index()
        .rename(columns={COLUNA_SEGUNDO: "frame_idx"})
    )
    return segundos[COLUNAS_FRAMES].sort_values([COLUNA_CLIPE, "frame_idx"]).reset_index(drop=True)


def agrega_como_o_produto(frames: pd.DataFrame, fps: Dict[str, float]) -> pd.DataFrame:
    """As 39 features, calculadas sobre a série de segundos.

    Mesmos nomes, mesma ordem e mesmo significado das colunas de `agregacao.agrega`
    — a diferença está na granularidade da entrada, que aqui é a que existe em
    produção. `n_frames` passa a contar **segundos**, e é a única coluna cujo
    valor muda de escala; ela continua sendo a base sobre a qual as proporções
    são lidas.
    """
    return agrega(resume_em_segundos(frames, fps))


def fps_das_gravacoes(catalogo: pd.DataFrame, medidor) -> Dict[str, float]:
    """Mapa prefixo da gravação -> fps, medido uma vez por arquivo.

    `medidor` recebe o caminho e devolve o fps — injetado para o teste não
    precisar de vídeo, e para o CLI poder reusar `extrair_rldd.fps_do_video`.
    """
    from rldd import COLUNA_CAMINHO
    from esquema_rldd import COLUNA_PARTE, COLUNA_PARTICIPANTE, COLUNA_SONOLENCIA

    return {
        f"rldd-{linha[COLUNA_PARTICIPANTE]}-{linha[COLUNA_SONOLENCIA]}-{linha[COLUNA_PARTE]}":
            float(medidor(linha[COLUNA_CAMINHO]))
        for _, linha in catalogo.iterrows()
    }
