"""Curva de aprendizado do DAiSEE: o desempenho cresce com mais participantes no treino?

Reproduz, como script versionado, o experimento citado na seção 2.2 do TCC e no
relatório de 18/08 (seção 3.5), que tinha sido feito em rascunho fora do repositório.

Protocolo:
- os participantes do split `Train` são embaralhados uma vez por semente, e cada
  ponto da curva usa os N primeiros (subconjuntos aninhados: o ponto maior contém
  o menor, então a diferença entre pontos é só "mais gente");
- o modelo é sempre avaliado no mesmo split `Test`, disjunto por participante;
- a métrica é a acurácia balanceada, a mesma usada no restante do trabalho;
- com várias sementes, cada ponto traz média e desvio entre elas.

O modelo padrão é o Random Forest regularizado do relatório de 18/08
(max_depth=10, pesos de classe balanceados, 300 árvores), com imputação pela
mediana, como em `treino.monta_pipeline`.

Uso:
    python curva_aprendizado.py
    python curva_aprendizado.py --clipes dados/clipes.parquet --sementes 42 7 13 21 99
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import balanced_accuracy_score
from sklearn.pipeline import Pipeline

import treino as treino_mod
from esquema import COLUNA_SPLIT, COLUNA_USUARIO, colunas_features, valida_clipes

DIR_DADOS = Path(__file__).parent / "dados"
DIR_ARTEFATOS = Path(__file__).parent / "artefatos"
FRACOES_PADRAO = (0.1, 0.25, 0.4, 0.55, 0.7, 0.85, 1.0)
MAX_DEPTH_PADRAO = 10


@dataclass(frozen=True)
class PontoDaCurva:
    participantes: int
    clipes_media: float
    acuracia_balanceada_media: float
    acuracia_balanceada_desvio: float
    por_semente: List[float]


def _pipeline(semente: int, max_depth: Optional[int], n_estimators: int, n_jobs: Optional[int]) -> Pipeline:
    return Pipeline([
        ("imputacao", SimpleImputer(strategy="median", keep_empty_features=True)),
        ("floresta", RandomForestClassifier(
            n_estimators=n_estimators, max_depth=max_depth, class_weight="balanced",
            random_state=semente, n_jobs=n_jobs)),
    ])


def tamanhos(n_participantes: int, fracoes: Sequence[float]) -> List[int]:
    """Converte frações em número de participantes (pelo menos 2, sem repetir, terminando em todos)."""
    ns = sorted({max(2, min(n_participantes, int(round(f * n_participantes)))) for f in fracoes})
    if ns[-1] != n_participantes:
        ns.append(n_participantes)
    return ns


def curva(
    clipes: pd.DataFrame,
    alvo: str = "engagement",
    corte: int = treino_mod.CORTE_BINARIO_PADRAO,
    fracoes: Sequence[float] = FRACOES_PADRAO,
    sementes: Sequence[int] = (treino_mod.RANDOM_STATE_PADRAO,),
    max_depth: Optional[int] = MAX_DEPTH_PADRAO,
    n_estimators: int = treino_mod.N_ESTIMATORS_PADRAO,
    n_jobs: Optional[int] = None,
) -> List[PontoDaCurva]:
    valida_clipes(clipes)
    treino_mod.verifica_independencia_de_sujeito(clipes)
    features = colunas_features()
    y = treino_mod.binariza(clipes[alvo], corte)
    eh_treino = (clipes[COLUNA_SPLIT] == "Train").to_numpy()
    eh_teste = (clipes[COLUNA_SPLIT] == "Test").to_numpy()
    x_teste, y_teste = clipes.loc[eh_teste, features], y[eh_teste]
    participantes = np.array(sorted(clipes.loc[eh_treino, COLUNA_USUARIO].unique()))
    ns = tamanhos(len(participantes), fracoes)

    resultados = {n: ([], []) for n in ns}
    for semente in sementes:
        ordem = np.random.default_rng(semente).permutation(participantes)
        for n in ns:
            escolhidos = set(ordem[:n])
            mascara = eh_treino & clipes[COLUNA_USUARIO].isin(escolhidos).to_numpy()
            y_treino = y[mascara]
            if y_treino.nunique() < 2:   # subconjunto pequeno sem uma das classes: ponto não existe
                continue
            modelo = _pipeline(semente, max_depth, n_estimators, n_jobs)
            modelo.fit(clipes.loc[mascara, features], y_treino)
            ab = balanced_accuracy_score(y_teste, modelo.predict(x_teste))
            resultados[n][0].append(float(ab))
            resultados[n][1].append(int(mascara.sum()))

    return [
        PontoDaCurva(
            participantes=n,
            clipes_media=float(np.mean(qtd)),
            acuracia_balanceada_media=float(np.mean(abs_)),
            acuracia_balanceada_desvio=float(np.std(abs_)),
            por_semente=[round(v, 4) for v in abs_],
        )
        for n, (abs_, qtd) in resultados.items() if abs_
    ]


def relatorio_markdown(pontos: Sequence[PontoDaCurva], sementes: Sequence[int], max_depth: Optional[int]) -> str:
    linhas = [
        "# Curva de aprendizado no DAiSEE",
        "",
        f"Random Forest (max_depth={max_depth}, pesos balanceados), avaliado sempre no split Test. "
        f"Sementes: {', '.join(map(str, sementes))}.",
        "",
        "| Participantes no treino | Clipes (média) | Acurácia balanceada (média ± desvio) |",
        "| --- | --- | --- |",
    ]
    for p in pontos:
        linhas.append(f"| {p.participantes} | {p.clipes_media:.0f} | "
                      f"{p.acuracia_balanceada_media:.4f} ± {p.acuracia_balanceada_desvio:.4f} |")
    if len(pontos) >= 2:
        ganho = pontos[-1].acuracia_balanceada_media - pontos[0].acuracia_balanceada_media
        linhas += ["", f"Ganho do menor para o maior ponto: {ganho:+.4f} de acurácia balanceada."]
    return "\n".join(linhas) + "\n"


def _argumentos(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Curva de aprendizado por número de participantes (DAiSEE).")
    p.add_argument("--clipes", type=Path, default=DIR_DADOS / "clipes.parquet")
    p.add_argument("--saida", type=Path, default=DIR_ARTEFATOS)
    p.add_argument("--alvo", default="engagement")
    p.add_argument("--corte", type=int, default=treino_mod.CORTE_BINARIO_PADRAO)
    p.add_argument("--sementes", type=int, nargs="+", default=[42, 7, 13, 21, 99])
    p.add_argument("--max-depth", type=int, default=MAX_DEPTH_PADRAO)
    p.add_argument("--arvores", type=int, default=treino_mod.N_ESTIMATORS_PADRAO)
    p.add_argument("--jobs", type=int, default=-1)
    return p.parse_args(list(argv) if argv is not None else None)


def main(argv: Optional[Iterable[str]] = None) -> int:
    a = _argumentos(argv)
    if not a.clipes.is_file():
        print(f"{a.clipes} não existe; rode `python extrair_features.py --raiz <DAiSEE>` antes", file=sys.stderr)
        return 2
    clipes = pd.read_parquet(a.clipes)
    pontos = curva(clipes, a.alvo, a.corte, sementes=a.sementes, max_depth=a.max_depth,
                   n_estimators=a.arvores, n_jobs=a.jobs)
    a.saida.mkdir(parents=True, exist_ok=True)
    md = relatorio_markdown(pontos, a.sementes, a.max_depth)
    (a.saida / "curva_aprendizado.md").write_text(md, encoding="utf-8")
    (a.saida / "curva_aprendizado.json").write_text(
        json.dumps([asdict(p) for p in pontos], ensure_ascii=False, indent=2), encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
