"""Formatação do relatório do classificador de sonolência.

Separado do treino pela mesma razão que `relatorio.py` é separado de `treino.py`:
quem mede não formata, e quem formata não decide nada. Todas as funções aqui são
puras — recebem tabelas e devolvem texto.

**Por que acurácia balanceada e F1 macro, e não acurácia.** A lição do DAiSEE é
que a acurácia se deixa satisfazer pelo silêncio: com 95% dos clipes de uma
classe, responder sempre a majoritária dá 95%. Aqui as classes são equilibradas
por construção — cada participante gravou os três estados — então a acurácia
seria menos enganosa; mas manter a mesma métrica nos dois relatórios é o que
permite comparar os dois datasets sem nota de rodapé.
"""
from typing import Dict, List, Optional, Sequence

import pandas as pd

from relatorio import Metricas
from treino_fadiga import NORMALIZACOES_REPRODUZIVEIS, ResultadoDaValidacao

#: Piso de referência: uma classificação que ignora a entrada fica aqui.
CHAO = 0.50


def tabela(df: pd.DataFrame, casas: int = 4) -> str:
    """DataFrame como tabela Markdown, com os floats arredondados."""
    if df.empty:
        return "_(vazio)_"

    copia = df.copy()
    for coluna in copia.select_dtypes(include="number").columns:
        copia[coluna] = copia[coluna].round(casas)

    cabecalho = "| " + " | ".join(str(c) for c in copia.columns) + " |"
    separador = "| " + " | ".join("---" for _ in copia.columns) + " |"
    linhas = [
        "| " + " | ".join("" if pd.isna(v) else str(v) for v in linha) + " |"
        for linha in copia.itertuples(index=False)
    ]
    return "\n".join([cabecalho, separador] + linhas)


def grade_para_tabela(resultados: Sequence[ResultadoDaValidacao]) -> pd.DataFrame:
    """A grade de experimentos, ordenada do melhor para o pior.

    O desvio entre folds vai junto **na mesma linha**, e não numa seção de
    detalhes: uma média de 0,70 com desvio de 0,02 e outra de 0,72 com desvio de
    0,11 não são o mesmo resultado, e separar os dois números convidaria a
    comparar só o primeiro.
    """
    return (
        pd.DataFrame(
            [
                {
                    "modelo": r.modelo,
                    "normalizacao": r.normalizacao,
                    "reproduzivel": "sim"
                    if r.normalizacao in NORMALIZACOES_REPRODUZIVEIS
                    else "nao (teto)",
                    "alvo": r.alvo,
                    "acuracia_balanceada": r.acuracia_balanceada_media,
                    "desvio_entre_folds": r.acuracia_balanceada_desvio,
                    "f1_macro": r.f1_macro_medio,
                    "piores_folds": ", ".join(str(f) for f in r.piores_folds),
                    "folds_ignorados": ", ".join(str(f) for f in r.folds_ignorados) or "-",
                }
                for r in resultados
            ]
        )
        .sort_values("acuracia_balanceada", ascending=False)
        .reset_index(drop=True)
    )


def folds_para_tabela(resultado: ResultadoDaValidacao) -> pd.DataFrame:
    """Cada fold como uma linha — o intervalo de confiança honesto do número."""
    return pd.DataFrame(
        [
            {
                "fold": f.fold,
                "n_treino": f.n_treino,
                "n_teste": f.n_teste,
                "acuracia_balanceada": f.acuracia_balanceada,
                "f1_macro": f.f1_macro,
            }
            for f in resultado.folds
        ]
    )


def metricas_para_tabela(metricas: Metricas) -> pd.DataFrame:
    """Precisão, recall e F1 por classe, com o suporte que os contextualiza."""
    linhas = [
        {
            "classe": c.nome,
            "precisao": c.precisao,
            "recall": c.recall,
            "f1": c.f1,
            "suporte": c.suporte,
        }
        for c in metricas.por_classe
    ]
    linhas.append(
        {
            "classe": "**macro**",
            "precisao": metricas.macro.precisao,
            "recall": metricas.macro.recall,
            "f1": metricas.macro.f1,
            "suporte": metricas.n_amostras,
        }
    )
    return pd.DataFrame(linhas)


def confusao_para_tabela(metricas: Metricas, nomes: Dict[int, str]) -> pd.DataFrame:
    """Matriz de confusão com os nomes das classes nas duas direções."""
    rotulos = [nomes.get(r, str(r)) for r in metricas.rotulos]
    return pd.DataFrame(
        metricas.matriz_confusao,
        index=[f"**{nome}**" for nome in rotulos],
        columns=rotulos,
    ).reset_index(names="verdadeiro \\ previsto")


def importancias_para_tabela(ranking: Dict[str, float], quantas: int = 15) -> pd.DataFrame:
    return pd.DataFrame(
        [{"feature": nome, "importancia": valor} for nome, valor in list(ranking.items())[:quantas]]
    )


def veredito(resultado: ResultadoDaValidacao, chao: float = CHAO) -> str:
    """Uma frase dizendo se o modelo achou sinal, e com que margem."""
    media = resultado.acuracia_balanceada_media
    desvio = resultado.acuracia_balanceada_desvio
    margem = media - chao

    if media - desvio <= chao:
        return (
            f"**Resultado inconclusivo.** A média de {media:.4f} está a {margem:.4f} do chão "
            f"de {chao:.2f}, mas o desvio entre folds ({desvio:.4f}) cobre essa distância — "
            "há fold em que o modelo não supera um chute."
        )
    return (
        f"**O modelo encontra sinal.** Acurácia balanceada de {media:.4f} ± {desvio:.4f} "
        f"entre os cinco folds, contra {chao:.2f} de um classificador que ignora a entrada. "
        f"O pior fold fica acima do chão, então o resultado não depende de qual grupo "
        "de participantes caiu no teste."
    )
