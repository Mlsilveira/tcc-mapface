"""Leitura do dataset DAiSEE em disco (ticket 1).

Este é o único módulo do pipeline que conhece o layout do DAiSEE. Tudo depois
daqui recebe um DataFrame já limpo, então trocar de dataset — ou reorganizar as
pastas — não obriga a mexer no extrator, na agregação nem no treino.

O layout distribuído pelos autores é::

    <raiz>/DataSet/<Split>/<user_id>/<clip_id>/<clip_id>.avi
    <raiz>/Labels/<Split>Labels.csv

**O split vem da pasta, não do CSV.** Os arquivos de rótulo não trazem coluna de
split, e o `AllLabels.csv` mistura os três; a hierarquia de diretórios é a única
fonte que o dataset oferece. Isso também preserva a propriedade que mais importa
para o treino: o DAiSEE é *subject-independent*, e é a pasta que garante que um
mesmo `user_id` não apareça em dois splits.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import pandas as pd

from esquema import (
    COLUNA_CLIPE,
    COLUNA_SPLIT,
    COLUNA_USUARIO,
    COLUNAS_ROTULOS,
    NIVEIS_ROTULO,
    SPLITS_VALIDOS,
)

#: Extensões de vídeo aceitas. O DAiSEE distribui `.avi`, mas cópias
#: reencodadas para economizar espaço costumam virar `.mp4`.
EXTENSOES_VIDEO = (".avi", ".mp4")

PASTA_DATASET = "DataSet"
PASTA_ROTULOS = "Labels"


class DatasetInvalido(Exception):
    """A raiz não parece um DAiSEE: falta `DataSet/`, `Labels/` ou o split pedido."""


@dataclass(frozen=True)
class Clipe:
    """Um clipe de 10s do DAiSEE localizado em disco."""

    clip_id: str
    user_id: str
    split: str
    caminho: Path


def _splits_pedidos(split: Optional[str]) -> List[str]:
    if split is None:
        return list(SPLITS_VALIDOS)
    if split not in SPLITS_VALIDOS:
        raise DatasetInvalido(
            f"split desconhecido: {split!r} (esperado um de {list(SPLITS_VALIDOS)})"
        )
    return [split]


def _pasta(raiz: Path, nome: str) -> Path:
    if not raiz.is_dir():
        raise DatasetInvalido(f"raiz do dataset não encontrada: {raiz}")

    caminho = raiz / nome
    if not caminho.is_dir():
        raise DatasetInvalido(f"{raiz} não contém a pasta {nome}/")
    return caminho


def lista_clipes(raiz: Path, split: Optional[str] = None) -> List[Clipe]:
    """Varre `DataSet/` e devolve os clipes que existem em disco.

    A ausência da pasta de um split não é erro: o DAiSEE é grande e baixá-lo
    por partes é comum. Já a ausência de `DataSet/` é — significa que a raiz
    apontada não é o dataset.

    A ordem é estável (split na ordem canônica, depois usuário e clipe) para que
    a extração possa ser retomada de onde parou.
    """
    dataset = _pasta(raiz, PASTA_DATASET)
    clipes: List[Clipe] = []

    for split_atual in _splits_pedidos(split):
        pasta_split = dataset / split_atual
        if not pasta_split.is_dir():
            continue

        videos = [
            caminho
            for caminho in pasta_split.rglob("*")
            if caminho.is_file() and caminho.suffix.lower() in EXTENSOES_VIDEO
        ]
        for caminho in sorted(videos):
            # O usuário é sempre o primeiro nível abaixo do split; o clip_id vem
            # do nome do arquivo, e não da pasta, porque é ele que o CSV de
            # rótulos referencia.
            relativo = caminho.relative_to(pasta_split)
            if len(relativo.parts) < 2:
                raise DatasetInvalido(
                    f"{caminho}: vídeo fora de uma pasta de usuário — "
                    f"esperado {PASTA_DATASET}/{split_atual}/<user_id>/<clip_id>/<clip_id>.avi"
                )
            clipes.append(
                Clipe(
                    clip_id=caminho.stem,
                    user_id=relativo.parts[0],
                    split=split_atual,
                    caminho=caminho,
                )
            )

    return clipes


# --- Rótulos ---------------------------------------------------------------

COLUNAS_ROTULOS_SAIDA: List[str] = [COLUNA_CLIPE, COLUNA_SPLIT] + COLUNAS_ROTULOS

#: Nomes de coluna do CSV que não são o `ClipID` já batem com `COLUNAS_ROTULOS`
#: depois de minúsculos; só o identificador precisa de tradução explícita.
_ALIAS_COLUNAS = {"clipid": COLUNA_CLIPE, "clip_id": COLUNA_CLIPE}


def _normaliza_nome(coluna: str) -> str:
    limpo = coluna.strip().lower()
    return _ALIAS_COLUNAS.get(limpo, limpo)


def _sem_extensao(clip_id: str) -> str:
    """Remove a extensão do `ClipID` — o mesmo CSV traz as duas formas."""
    nome = clip_id.strip()
    if Path(nome).suffix.lower() in EXTENSOES_VIDEO:
        return Path(nome).stem
    return nome


def _rotulos_vazios() -> pd.DataFrame:
    return pd.DataFrame({coluna: pd.Series(dtype="object") for coluna in COLUNAS_ROTULOS_SAIDA})


def _le_csv_rotulos(caminho: Path, split: str) -> pd.DataFrame:
    # Tudo entra como texto: `ClipID` é identificador, não número (tem zeros à
    # esquerda), e ler os níveis como texto deixa a validação abaixo enxergar
    # células malformadas em vez de recebê-las já convertidas em NaN silencioso.
    bruto = pd.read_csv(caminho, dtype=str, skipinitialspace=True)
    df = bruto.rename(columns={coluna: _normaliza_nome(coluna) for coluna in bruto.columns})

    faltando = [c for c in [COLUNA_CLIPE] + COLUNAS_ROTULOS if c not in df.columns]
    if faltando:
        raise DatasetInvalido(f"{caminho}: colunas faltando: {faltando}")

    df[COLUNA_CLIPE] = df[COLUNA_CLIPE].astype(str).map(_sem_extensao)

    for coluna in COLUNAS_ROTULOS:
        valores = pd.to_numeric(df[coluna], errors="coerce")
        invalidos = df.loc[~valores.isin(NIVEIS_ROTULO), COLUNA_CLIPE].tolist()
        if invalidos:
            raise DatasetInvalido(
                f"{caminho}: coluna {coluna} fora de {list(NIVEIS_ROTULO)} "
                f"nos clipes {invalidos[:5]}"
            )
        df[coluna] = valores.astype(int)

    df[COLUNA_SPLIT] = split
    return df.reset_index(drop=True)[COLUNAS_ROTULOS_SAIDA]


def _rotulos_brutos(raiz: Path, split: Optional[str]) -> pd.DataFrame:
    """Rótulos normalizados, ainda com eventuais duplicatas — ver `descasamento`."""
    pasta = _pasta(raiz, PASTA_ROTULOS)

    partes = [
        _le_csv_rotulos(pasta / f"{split_atual}Labels.csv", split_atual)
        for split_atual in _splits_pedidos(split)
        if (pasta / f"{split_atual}Labels.csv").is_file()
    ]
    partes = [parte for parte in partes if not parte.empty]
    if not partes:
        return _rotulos_vazios()

    return pd.concat(partes, ignore_index=True)


def carrega_rotulos(raiz: Path, split: Optional[str] = None) -> pd.DataFrame:
    """Lê `Labels/<Split>Labels.csv` e devolve os rótulos normalizados.

    O `AllLabels.csv` é ignorado de propósito: ele repete as mesmas linhas dos
    três arquivos por split e não diz de qual split cada clipe veio, então usá-lo
    só criaria duplicatas sem informação nova.

    Um CSV de split ausente devolve zero linhas, pela mesma razão que uma pasta
    de split ausente devolve zero clipes; faltar `Labels/` inteiro, não.

    **Duplicata do mesmo `clip_id` fica na primeira ocorrência.** Manter as duas
    contaria o mesmo clipe duas vezes no treino, e escolher a última faria o
    dataset depender da ordem em que o CSV foi editado. Nada é perdido em
    silêncio: `descasamento` lista os clip_ids duplicados.
    """
    return (
        _rotulos_brutos(raiz, split)
        .drop_duplicates(subset=COLUNA_CLIPE, keep="first")
        .reset_index(drop=True)
    )


# --- Catálogo --------------------------------------------------------------

#: Caminho do vídeo em disco. Não vive em `esquema` porque não é feature nem
#: rótulo: some do dataset assim que a extração termina.
COLUNA_CAMINHO = "caminho"

COLUNAS_CATALOGO: List[str] = [
    COLUNA_CLIPE,
    COLUNA_USUARIO,
    COLUNA_SPLIT,
    COLUNA_CAMINHO,
] + COLUNAS_ROTULOS


def _tabela_clipes(clipes: List[Clipe]) -> pd.DataFrame:
    colunas = [COLUNA_CLIPE, COLUNA_USUARIO, COLUNA_SPLIT, COLUNA_CAMINHO]
    linhas = [(c.clip_id, c.user_id, c.split, c.caminho) for c in clipes]
    return pd.DataFrame(linhas, columns=colunas)


def catalogo(raiz: Path, split: Optional[str] = None) -> pd.DataFrame:
    """Uma linha por clipe que existe em disco **e** tem rótulo.

    É o ponto de entrada da extração: quem consome já recebe caminho de vídeo e
    rótulo juntos, sem precisar saber que são duas fontes diferentes.

    O join é uma interseção de propósito. Vídeo sem rótulo não serve para treino
    supervisionado, e rótulo sem vídeo não tem features para extrair — processar
    qualquer um dos dois só produziria linha incompleta. O que sobrou de fora é
    contado por `descasamento`.

    A junção é por `clip_id` e o `split` que fica é o da pasta: o CSV não é fonte
    de split (ver docstring do módulo).
    """
    clipes = _tabela_clipes(lista_clipes(raiz, split))
    rotulos = carrega_rotulos(raiz, split).drop(columns=[COLUNA_SPLIT])

    juntos = clipes.merge(rotulos, on=COLUNA_CLIPE, how="inner")
    return juntos[COLUNAS_CATALOGO].reset_index(drop=True)


@dataclass(frozen=True)
class Descasamento:
    """O que não pareou entre o disco e os arquivos de rótulo."""

    n_clipes: int
    n_rotulos: int
    n_pareados: int
    clipes_sem_rotulo: List[str]
    rotulos_sem_video: List[str]
    rotulos_duplicados: List[str]


def descasamento(raiz: Path, split: Optional[str] = None) -> Descasamento:
    """Conta e nomeia o que `catalogo` descartou.

    O DAiSEE real vem com clipes faltando e com linhas de rótulo órfãs. O
    pipeline precisa disso explícito — um dataset que encolheu 15% sem ninguém
    perceber vira uma acurácia que ninguém sabe explicar.

    `n_rotulos` conta clip_ids distintos, não linhas de CSV; as linhas repetidas
    aparecem em `rotulos_duplicados`.
    """
    clipes = lista_clipes(raiz, split)
    brutos = _rotulos_brutos(raiz, split)

    ids_clipes = {clipe.clip_id for clipe in clipes}
    ids_rotulos = set(brutos[COLUNA_CLIPE])
    duplicados = brutos[COLUNA_CLIPE][brutos[COLUNA_CLIPE].duplicated()]

    return Descasamento(
        n_clipes=len(ids_clipes),
        n_rotulos=len(ids_rotulos),
        n_pareados=len(ids_clipes & ids_rotulos),
        clipes_sem_rotulo=sorted(ids_clipes - ids_rotulos),
        rotulos_sem_video=sorted(ids_rotulos - ids_clipes),
        rotulos_duplicados=sorted(set(duplicados)),
    )
