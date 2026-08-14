"""CLI da ticket 2: dataset tabular → Random Forest treinado, avaliado e serializado.

Lê o `clipes.parquet` produzido pela ticket 1, treina o modelo com `treino`,
escreve o artefato `.joblib` que o backend vai carregar na ticket 8, e emite o
relatório de métricas em Markdown (para versionar junto do TCC) e em JSON (para
comparar execuções sem ler texto).

O código de saída carrega informação: **1 quando a meta de precisão não é
atingida**, 0 quando é. Assim `--exigir-meta` pode entrar num CI sem ninguém ter
que fazer parsing do relatório — e o default é *não* exigir, porque uma execução
que falha por métrica baixa ainda precisa gravar o relatório que explica o
porquê.

Uso típico:

    python treinar.py
    python treinar.py --modo multiclasse --alvo boredom
    python treinar.py --corte 3 --exigir-meta
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd

import esquema
import relatorio as relatorio_mod
import treino as treino_mod

DIR_DADOS = Path(__file__).parent / "dados"
DIR_ARTEFATOS = Path(__file__).parent / "artefatos"

NOME_MODELO = "random_forest.joblib"
NOME_RELATORIO_MD = "relatorio.md"
NOME_RELATORIO_JSON = "relatorio.json"


def carrega_clipes(caminho: Path) -> pd.DataFrame:
    """Lê o dataset da ticket 1 e confere o contrato antes de treinar.

    Falhar aqui, com o nome da coluna que falta, é muito mais barato que falhar
    lá dentro do sklearn com um `KeyError` sem contexto.
    """
    if not caminho.is_file():
        raise FileNotFoundError(
            f"{caminho} não existe — rode `python extrair_features.py --raiz <DAiSEE>` antes"
        )
    clipes = pd.read_parquet(caminho)
    esquema.valida_clipes(clipes)
    return clipes


def _argumentos(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Treina e valida o Random Forest baseline sobre as features do DAiSEE (ticket 2).",
    )
    parser.add_argument("--clipes", type=Path, default=DIR_DADOS / "clipes.parquet")
    parser.add_argument("--artefatos", type=Path, default=DIR_ARTEFATOS)
    parser.add_argument("--alvo", default="engagement", choices=esquema.COLUNAS_ROTULOS)
    parser.add_argument(
        "--modo",
        default=treino_mod.MODO_BINARIO,
        choices=[treino_mod.MODO_BINARIO, treino_mod.MODO_MULTICLASSE],
    )
    parser.add_argument(
        "--corte",
        type=int,
        default=treino_mod.CORTE_BINARIO_PADRAO,
        help="no modo binário, nível a partir do qual o clipe conta como engajado",
    )
    parser.add_argument("--arvores", type=int, default=treino_mod.N_ESTIMATORS_PADRAO)
    parser.add_argument("--random-state", type=int, default=treino_mod.RANDOM_STATE_PADRAO)
    parser.add_argument("--jobs", type=int, default=-1, help="núcleos usados pelo Random Forest")
    parser.add_argument(
        "--exigir-meta",
        action="store_true",
        help=f"sai com código 1 se a precisão macro no {relatorio_mod.SPLIT_META} não atingir a meta",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = _argumentos(argv)
    fala = lambda msg: print(msg, file=sys.stderr, flush=True)

    try:
        clipes = carrega_clipes(args.clipes)
    except (FileNotFoundError, esquema.EsquemaInvalido) as erro:
        fala(str(erro))
        return 2

    fala(f"{args.clipes}: {len(clipes)} clipes")

    try:
        resultado = treino_mod.treina(
            clipes,
            alvo=args.alvo,
            modo=args.modo,
            corte=args.corte,
            random_state=args.random_state,
            n_estimators=args.arvores,
            n_jobs=args.jobs,
        )
    except treino_mod.TreinoInvalido as erro:
        fala(f"treino inválido: {erro}")
        return 2

    args.artefatos.mkdir(parents=True, exist_ok=True)
    caminho_modelo = treino_mod.salva_modelo(resultado, args.artefatos / NOME_MODELO)
    caminho_md = args.artefatos / NOME_RELATORIO_MD
    caminho_json = args.artefatos / NOME_RELATORIO_JSON
    caminho_md.write_text(relatorio_mod.relatorio_markdown(resultado), encoding="utf-8")
    caminho_json.write_text(relatorio_mod.relatorio_json(resultado), encoding="utf-8")

    fala(f"modelo:    {caminho_modelo}")
    fala(f"relatório: {caminho_md}")
    fala(f"métricas:  {caminho_json}")

    avaliacao = relatorio_mod.avalia_meta(resultado.metricas[relatorio_mod.SPLIT_META])
    veredito = "atingida" if avaliacao.atingida else "NÃO atingida"
    fala(
        f"meta de precisão {avaliacao.meta:.0%} ({relatorio_mod.SPLIT_META}, macro): "
        f"{avaliacao.precisao_macro:.4f} — {veredito}"
    )

    if args.exigir_meta and not avaliacao.atingida:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
