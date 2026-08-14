"""Agregação frame → clipe: a tabela que o Random Forest treina (ticket 1).

O DAiSEE rotula clipes de 10s, não frames. Entre a saída do extrator (~300
linhas por clipe) e o treino (uma linha por clipe) existe uma decisão de
modelagem, e ela mora aqui: como espremer uma série temporal em um vetor de
tamanho fixo sem jogar fora o que distingue um aluno atento de um sonolento.

Três decisões que valem estar escritas, porque nenhuma é a única possível:

**Frames sem rosto não entram nas agregações.** Eles chegam com métricas em NaN
e o pandas os ignora com `skipna`, mas a exclusão é explícita: um clipe em que o
aluno saiu de quadro na metade tem média de EAR calculada sobre a metade em que
ele estava lá, não diluída por zeros. A informação "ele sumiu" não se perde —
vira `prop_frames_com_rosto`, uma feature por si só.

**Um clipe sem nenhum rosto agrega para NaN, não para 0.0.** Zero significaria
"olhos completamente fechados, cabeça de frente", que é uma leitura, não uma
ausência de leitura. O treino da ticket 2 decide o que fazer com o NaN
(descartar o clipe ou imputar); a extração não tem autoridade para inventar
número. Pela mesma razão, `desvio` de um único frame válido fica NaN (ddof=1 do
pandas): com uma observação só não existe dispersão, e 0.0 afirmaria uma
estabilidade que ninguém mediu.

**`prop_olhos_fechados` e `prop_boca_aberta` são frações sobre os frames com
rosto**, não sobre o total. Se fossem sobre o total, um clipe com 90% de frames
sem rosto teria proporções artificialmente baixas — não por estar de olhos
abertos, mas por não ter sido observado — e a feature passaria a medir a
qualidade da detecção em vez do comportamento do aluno. Esse aspecto já é
medido, separadamente, por `prop_frames_com_rosto`. `n_frames`, ao contrário,
conta tudo o que foi lido: é a base sobre a qual as outras proporções são lidas.
"""
from typing import Dict, List

import pandas as pd

from esquema import (
    AGREGACOES,
    COLUNA_CLIPE,
    COLUNAS_IDENTIDADE,
    COLUNAS_METRICAS,
    COLUNAS_ROTULOS,
    EsquemaInvalido,
    LIMIAR_BOCA_ABERTA,
    LIMIAR_OLHOS_FECHADOS,
    colunas_agregadas,
    colunas_clipes,
    colunas_features,
    valida_clipes,
    valida_frames,
)

#: Tradução dos nomes do esquema para os métodos do pandas. Todos ignoram NaN
#: por padrão, que é exatamente o tratamento que os frames sem rosto pedem.
METODOS = {
    "media": "mean",
    "desvio": "std",
    "mediana": "median",
    "min": "min",
    "max": "max",
}


def agrega_clipe(frames: pd.DataFrame) -> Dict[str, object]:
    """Reduz os frames de um clipe a uma única linha de features.

    Espera frames de um clipe só — misturar clipes aqui seria um erro de quem
    chamou, e a média resultante não significaria nada. Use `agrega` para um
    DataFrame com vários.
    """
    valida_frames(frames)

    if frames.empty:
        raise ValueError("frames vazio: um clipe sem frames não é agregável")

    clipes = frames[COLUNA_CLIPE].unique()
    if len(clipes) != 1:
        raise ValueError(f"esperado um único clip_id, recebidos {list(clipes)}")

    com_rosto = frames[frames["face_detectada"].fillna(False).astype(bool)]

    linha: Dict[str, object] = {COLUNA_CLIPE: clipes[0]}
    linha.update(_agregacoes(com_rosto))
    linha.update(_derivadas(frames, com_rosto))
    return linha


def _agregacoes(com_rosto: pd.DataFrame) -> Dict[str, float]:
    """As cinco agregações de cada métrica, na ordem de `colunas_agregadas()`."""
    if com_rosto.empty:
        # Curto-circuito, e não só uma economia: agregar coluna vazia faz o numpy
        # emitir `RuntimeWarning: Mean of empty slice` uma vez por métrica. Num
        # dataset com milhares de clipes sem rosto detectado, isso inunda o mesmo
        # stderr em que o CLI escreve progresso e erros de vídeo ilegível. O
        # resultado é o mesmo NaN, sem o ruído.
        return {nome: float("nan") for nome in colunas_agregadas()}

    # A ordem do laço espelha a de `colunas_agregadas()` (métrica por fora,
    # agregação por dentro); os nomes vêm de lá, nunca montados aqui.
    valores = [
        getattr(com_rosto[metrica], METODOS[agregacao])()
        for metrica in COLUNAS_METRICAS
        for agregacao in AGREGACOES
    ]
    return {
        nome: float(valor) for nome, valor in zip(colunas_agregadas(), valores)
    }


def _derivadas(frames: pd.DataFrame, com_rosto: pd.DataFrame) -> Dict[str, object]:
    n_frames = len(frames)
    n_com_rosto = len(com_rosto)

    return {
        "prop_frames_com_rosto": n_com_rosto / n_frames,
        "prop_olhos_fechados": _fracao(com_rosto["ear"] < LIMIAR_OLHOS_FECHADOS, n_com_rosto),
        "prop_boca_aberta": _fracao(com_rosto["mar"] > LIMIAR_BOCA_ABERTA, n_com_rosto),
        "n_frames": n_frames,
    }


def _fracao(condicao: pd.Series, n_com_rosto: int) -> float:
    """Fração dos frames com rosto que satisfazem a condição.

    Sem nenhum frame com rosto o denominador é zero, e o resultado é NaN — não
    0.0: ninguém observou olho aberto, apenas não se observou nada.
    """
    if n_com_rosto == 0:
        return float("nan")
    return float(condicao.sum()) / n_com_rosto


def agrega(frames: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por clipe, em ordem estável de `clip_id`.

    A ordem é determinística para que reexecutar a extração produza o mesmo
    arquivo — o dataset é versionado e um diff só deve aparecer quando os
    números mudam de verdade.
    """
    valida_frames(frames)

    linhas: List[Dict[str, object]] = [
        agrega_clipe(grupo) for _, grupo in frames.groupby(COLUNA_CLIPE, sort=True)
    ]
    return pd.DataFrame(linhas, columns=[COLUNA_CLIPE] + colunas_features())


def junta_rotulos(clipes: pd.DataFrame, rotulos: pd.DataFrame) -> pd.DataFrame:
    """Casa as features com os rótulos do DAiSEE e monta o dataset final.

    O join é interno nos dois sentidos, de propósito: clipe sem rótulo não tem
    como ser treinado, e rótulo sem clipe extraído (vídeo faltando ou ilegível)
    não tem features. Qualquer um dos dois sobrando é assunto de auditoria, não
    de linha com NaN no meio do treino.
    """
    _confere(clipes, [COLUNA_CLIPE] + colunas_features(), "clipes")
    _confere(rotulos, COLUNAS_IDENTIDADE + COLUNAS_ROTULOS, "rótulos")

    dataset = clipes.merge(
        rotulos[COLUNAS_IDENTIDADE + COLUNAS_ROTULOS], on=COLUNA_CLIPE, how="inner"
    )
    dataset = dataset[colunas_clipes()].reset_index(drop=True)

    valida_clipes(dataset)
    return dataset


def _confere(df: pd.DataFrame, esperadas: List[str], nome: str) -> None:
    faltando = [coluna for coluna in esperadas if coluna not in df.columns]
    if faltando:
        raise EsquemaInvalido(f"{nome}: colunas faltando: {faltando}")
