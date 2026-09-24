"""Leitura do UTA-RLDD em disco.

Único módulo que conhece o layout do dataset de sonolência, no mesmo papel que
`daisee` cumpre para o outro. Depois daqui tudo recebe DataFrame limpo.

O layout distribuído pelos autores é::

    <raiz>/Fold<N>_part<M>/<participante>/<estado>.<ext>

com `<estado>` em {0, 5, 10} e `<participante>` de "01" a "60". Três detalhes do
material real que o código precisa aguentar, e que não estão em nenhum README do
dataset:

**Alguns `part` vêm com a pasta repetida** — `Fold5_part2/Fold5_part2/55/0.mp4`.
É subproduto de descompactar o zip dentro de uma pasta de mesmo nome. Por isso a
varredura é por `rglob` e o participante é a pasta **imediatamente acima** do
arquivo, em vez de uma profundidade fixa.

**Os vídeos de sonolência de dois participantes vêm partidos** (`10_1` e `10_2`).
São a mesma gravação cortada, não duas sessões: o rótulo é o mesmo, e as duas
partes entram como gravações distintas para os índices de janela não colidirem.

**As extensões variam entre participantes** — `.mov`, `.MOV`, `.mp4`, `.m4v` —
porque cada um gravou com o próprio celular. Comparar em minúsculas é
obrigatório, e esquecer o `.m4v` faz um participante inteiro sumir sem erro.

**O fold vem da pasta, e é o dos autores.** Os 60 participantes já estão
distribuídos em cinco grupos disjuntos; sortear os nossos jogaria fora a
comparabilidade com a literatura e abriria a porta para um participante cair
nos dois lados de um split.
"""
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import pandas as pd

from esquema_rldd import (
    COLUNA_FOLD,
    COLUNA_INDICE_JANELA,
    COLUNA_JANELA,
    COLUNA_PARTE,
    COLUNA_PARTICIPANTE,
    COLUNA_SONOLENCIA,
    NIVEIS_SONOLENCIA,
)

#: Extensões aceitas, em minúsculas. Cada participante gravou com o próprio
#: aparelho, então a lista é mais larga que a de um dataset distribuído pronto.
EXTENSOES_VIDEO = (".mov", ".mp4", ".m4v", ".avi", ".mkv")

COLUNA_CAMINHO = "caminho"

#: `10_2` é a segunda parte da gravação `10`. O sufixo é opcional.
_PADRAO_ESTADO = re.compile(r"^(?P<estado>0|5|10)(?:_(?P<parte>\d+))?$")

#: `Fold3_part2` -> fold 3.
_PADRAO_FOLD = re.compile(r"^fold(?P<n>\d+)_part\d+$", re.IGNORECASE)

#: Participante é uma pasta de dois dígitos.
_PADRAO_PARTICIPANTE = re.compile(r"^\d{2}$")


class DatasetInvalido(Exception):
    """A raiz não parece um UTA-RLDD: sem pasta de fold ou sem vídeo dentro."""


@dataclass(frozen=True)
class Gravacao:
    """Um vídeo de ~10 minutos, com o estado declarado pelo participante."""

    participante: str
    fold: int
    sonolencia: int
    parte: int
    caminho: Path

    @property
    def prefixo(self) -> str:
        """Prefixo dos ids de janela desta gravação."""
        return f"rldd-{self.participante}-{self.sonolencia}-{self.parte}"


def id_da_janela(prefixo: str, indice: int) -> str:
    """Id canônico de uma janela: o prefixo da gravação mais o índice.

    O id carrega participante, estado, parte e posição — então o catálogo de
    rótulos é reconstruível a partir dos frames extraídos, sem um CSV paralelo
    que possa sair de sincronia com eles.
    """
    return f"{prefixo}-{indice:04d}"


def decompoe_id(clip_id: str) -> Dict[str, object]:
    """Inverso de `id_da_janela`. Levanta `ValueError` num id fora do formato."""
    partes = clip_id.split("-")
    if len(partes) != 5 or partes[0] != "rldd":
        raise ValueError(f"id de janela fora do formato: {clip_id!r}")

    _, participante, estado, parte, indice = partes
    if int(estado) not in NIVEIS_SONOLENCIA:
        raise ValueError(f"estado desconhecido em {clip_id!r}: {estado}")

    return {
        COLUNA_JANELA: clip_id,
        COLUNA_PARTICIPANTE: participante,
        COLUNA_SONOLENCIA: int(estado),
        COLUNA_PARTE: int(parte),
        COLUNA_INDICE_JANELA: int(indice),
    }


def _fold_do_caminho(caminho: Path, raiz: Path) -> Optional[int]:
    """O número do fold, lido da primeira pasta `Fold<N>_part<M>` do caminho."""
    for parte in caminho.relative_to(raiz).parts:
        achado = _PADRAO_FOLD.match(parte)
        if achado:
            return int(achado.group("n"))
    return None


def lista_gravacoes(raiz: Path) -> List[Gravacao]:
    """Varre a raiz e devolve as gravações encontradas, em ordem estável.

    A ordem é determinística (participante, estado, parte) para que a extração
    possa ser retomada de onde parou e para que duas execuções produzam o mesmo
    arquivo.
    """
    if not raiz.is_dir():
        raise DatasetInvalido(f"raiz do dataset não encontrada: {raiz}")

    gravacoes: List[Gravacao] = []
    for caminho in raiz.rglob("*"):
        if not caminho.is_file() or caminho.suffix.lower() not in EXTENSOES_VIDEO:
            continue

        estado = _PADRAO_ESTADO.match(caminho.stem)
        participante = caminho.parent.name
        if not estado or not _PADRAO_PARTICIPANTE.match(participante):
            continue

        fold = _fold_do_caminho(caminho, raiz)
        if fold is None:
            continue

        gravacoes.append(
            Gravacao(
                participante=participante,
                fold=fold,
                sonolencia=int(estado.group("estado")),
                parte=int(estado.group("parte") or 1),
                caminho=caminho,
            )
        )

    if not gravacoes:
        raise DatasetInvalido(
            f"{raiz} nao contem video no formato Fold<N>_part<M>/<participante>/<estado>"
        )

    return sorted(gravacoes, key=lambda g: (g.participante, g.sonolencia, g.parte))


def catalogo_de_gravacoes(raiz: Path) -> pd.DataFrame:
    """As gravações como tabela — o que a extração percorre."""
    gravacoes = lista_gravacoes(raiz)
    return pd.DataFrame(
        [
            {
                COLUNA_PARTICIPANTE: g.participante,
                COLUNA_FOLD: g.fold,
                COLUNA_SONOLENCIA: g.sonolencia,
                COLUNA_PARTE: g.parte,
                COLUNA_CAMINHO: str(g.caminho),
            }
            for g in gravacoes
        ]
    )


def folds_por_participante(catalogo: pd.DataFrame) -> Dict[str, int]:
    """Mapa participante -> fold, conferindo que cada um está num fold só."""
    por_participante = catalogo.groupby(COLUNA_PARTICIPANTE)[COLUNA_FOLD].unique()

    ambiguos = {p: list(f) for p, f in por_participante.items() if len(f) > 1}
    if ambiguos:
        raise DatasetInvalido(
            f"participantes em mais de um fold, o que quebraria a independencia: {ambiguos}"
        )

    return {str(p): int(f[0]) for p, f in por_participante.items()}


def catalogo_de_janelas(
    clip_ids: Iterable[str], folds: Dict[str, int]
) -> pd.DataFrame:
    """Reconstrói identidade e rótulo das janelas a partir dos ids extraídos.

    `folds` vem de `folds_por_participante`: o fold não cabe no id porque é
    propriedade do participante, não da janela, e repeti-lo em cada id seria
    guardar a mesma informação em dois lugares que podem divergir.
    """
    tabela = pd.DataFrame([decompoe_id(str(clip_id)) for clip_id in clip_ids])

    desconhecidos = sorted(set(tabela[COLUNA_PARTICIPANTE]) - set(folds))
    if desconhecidos:
        raise DatasetInvalido(
            f"janelas de participantes fora do catalogo: {desconhecidos[:5]}"
        )

    tabela[COLUNA_FOLD] = tabela[COLUNA_PARTICIPANTE].map(folds)
    return tabela.sort_values(COLUNA_JANELA).reset_index(drop=True)
