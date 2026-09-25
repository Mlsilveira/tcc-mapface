"""CLI da ticket 1: DAiSEE em disco → dataset tabular de features.

Amarra os quatro módulos da trilha de extração — `daisee` acha os clipes e seus
rótulos, `extracao` roda o MediaPipe frame a frame, `metricas` faz a matemática
dos landmarks, `agregacao` resume cada clipe numa linha — e é o único lugar que
escreve arquivo.

O critério da ticket pede um pipeline *reproduzível via script*, e a escala é o
que dita o desenho: o DAiSEE tem ~9 mil clipes de 10 segundos, o que dá horas de
processamento. Uma execução que perde tudo ao ser interrompida não é reproduzível
na prática — é uma aposta. Por isso a extração grava em **shards** a cada N
clipes e sabe retomar de onde parou: rodar o comando de novo pula o que já foi
extraído em vez de recomeçar. A consolidação dos shards nos dois parquets finais
é um passo separado e barato, que pode ser repetido à vontade.

Uso típico:

    python extrair_features.py --raiz ~/datasets/DAiSEE
    python extrair_features.py --raiz ~/datasets/DAiSEE --split Train --amostragem 5
    python extrair_features.py --raiz ~/datasets/DAiSEE --limite 20   # amostra p/ conferir
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Set

import pandas as pd

import agregacao
import agregacao_producao
import daisee
import esquema
import extracao

#: Quantos clipes acumular em memória antes de despejar um shard em disco.
#: Baixo demais gera milhares de arquivinhos; alto demais perde muito trabalho
#: quando a execução é interrompida.
CLIPES_POR_SHARD = 50

#: Um clipe do DAiSEE tem ~10s a 30fps. Processar todo frame é caro e redundante
#: — piscadas duram ~100ms, então 6fps (amostragem 5) ainda as enxerga. É um
#: default, não uma imposição: `--amostragem 1` processa tudo.
AMOSTRAGEM_PADRAO = 5

NOME_FRAMES = "frames.parquet"
NOME_CLIPES = "clipes.parquet"
DIR_SHARDS = "shards"


@dataclass
class Progresso:
    """Contagem de uma execução, para o relatório final e para os testes."""

    total: int = 0
    extraidos: int = 0
    pulados: int = 0
    falhos: int = 0
    falhas: Optional[List[str]] = None

    def __post_init__(self) -> None:
        if self.falhas is None:
            self.falhas = []


def caminhos_de_shard(saida: Path) -> List[Path]:
    """Shards já gravados, em ordem estável."""
    diretorio = saida / DIR_SHARDS
    if not diretorio.is_dir():
        return []
    return sorted(diretorio.glob("parte-*.parquet"))


def clipes_ja_extraidos(saida: Path) -> Set[str]:
    """Ids que já aparecem em algum shard — o conjunto que a retomada pula.

    Lê só a coluna de id: um shard de 50 clipes tem ~15 mil linhas de frame, e
    carregar tudo só para conferir o que já foi feito custaria caro na retomada.
    """
    vistos: Set[str] = set()
    for shard in caminhos_de_shard(saida):
        coluna = pd.read_parquet(shard, columns=[esquema.COLUNA_CLIPE])
        vistos.update(coluna[esquema.COLUNA_CLIPE].astype(str).unique())
    return vistos


def _grava_shard(saida: Path, indice: int, frames: List[pd.DataFrame]) -> Path:
    diretorio = saida / DIR_SHARDS
    diretorio.mkdir(parents=True, exist_ok=True)
    caminho = diretorio / f"parte-{indice:05d}.parquet"
    pd.concat(frames, ignore_index=True).to_parquet(caminho, index=False)
    return caminho


def _limpa_shards(saida: Path) -> None:
    for shard in caminhos_de_shard(saida):
        shard.unlink()


def _proximo_indice_de_shard(saida: Path) -> int:
    existentes = caminhos_de_shard(saida)
    if not existentes:
        return 0
    return int(existentes[-1].stem.split("-")[-1]) + 1


def extrai(
    catalogo: pd.DataFrame,
    saida: Path,
    detector: extracao.DetectorDeLandmarks,
    amostragem: int = AMOSTRAGEM_PADRAO,
    clipes_por_shard: int = CLIPES_POR_SHARD,
    retomar: bool = True,
    registra=lambda _: None,
) -> Progresso:
    """Extrai os frames de cada clipe do catálogo, gravando em shards.

    Um clipe que falha (vídeo corrompido, codec que o OpenCV não abre) é anotado
    e a execução continua: interromper 9 mil clipes por causa de um arquivo ruim
    seria trocar um dado faltante por horas perdidas. As falhas voltam em
    `Progresso.falhas` para irem ao relatório.
    """
    progresso = Progresso(total=len(catalogo))
    if not retomar:
        # Apagar é obrigatório, não higiene: reiniciar o índice em 0 sobrescreve
        # os primeiros shards, mas os do fim da execução anterior sobrevivem, e a
        # consolidação os junta aos novos. O resultado seria um dataset que
        # mistura clipes de duas execuções — possivelmente com amostragens
        # diferentes — sem nada no arquivo denunciando isso.
        _limpa_shards(saida)
    vistos = clipes_ja_extraidos(saida) if retomar else set()
    indice = _proximo_indice_de_shard(saida) if retomar else 0
    acumulado: List[pd.DataFrame] = []

    for _, linha in catalogo.iterrows():
        clip_id = str(linha[esquema.COLUNA_CLIPE])
        if clip_id in vistos:
            progresso.pulados += 1
            continue
        # O detector de vídeo rastreia entre frames; sem zerar aqui, o primeiro
        # frame deste clipe seria procurado onde estava o rosto do clipe anterior.
        extracao.reinicia_detector(detector)
        try:
            frames = extracao.extrai_frames(
                caminho_video=Path(linha[daisee.COLUNA_CAMINHO]),
                clip_id=clip_id,
                detector=detector,
                amostragem=amostragem,
            )
        except extracao.VideoIlegivel as erro:
            progresso.falhos += 1
            progresso.falhas.append(f"{clip_id}: {erro}")
            registra(f"falhou {clip_id}: {erro}")
            continue

        acumulado.append(frames)
        progresso.extraidos += 1
        if len(acumulado) >= clipes_por_shard:
            caminho = _grava_shard(saida, indice, acumulado)
            registra(f"shard {caminho.name} ({progresso.extraidos}/{progresso.total})")
            acumulado = []
            indice += 1

    if acumulado:
        caminho = _grava_shard(saida, indice, acumulado)
        registra(f"shard {caminho.name} ({progresso.extraidos}/{progresso.total})")

    return progresso


def consolida(saida: Path, catalogo: pd.DataFrame) -> tuple[Path, Path]:
    """Junta os shards nos dois artefatos finais: `frames` e `clipes`.

    É um passo separado da extração de propósito — é barato, idempotente, e pode
    ser rodado sobre uma extração parcial para inspecionar o que já saiu sem
    esperar as horas restantes.
    """
    shards = caminhos_de_shard(saida)
    if not shards:
        raise FileNotFoundError(f"nenhum shard em {saida / DIR_SHARDS}; rode a extração antes")

    frames = pd.concat((pd.read_parquet(s) for s in shards), ignore_index=True)
    esquema.valida_frames(frames)

    # Os shards podem conter mais clipes que o catálogo pedido — é o que acontece
    # ao consolidar com `--split` ou `--limite` depois de uma extração completa.
    # Os dois artefatos precisam descrever o mesmo conjunto: a ticket 8 lê
    # `frames` para as sequências temporais dos clipes com que o modelo treinou, e
    # encontrar ali clipes que não estão em `clipes` é uma armadilha silenciosa.
    do_catalogo = set(catalogo[esquema.COLUNA_CLIPE].astype(str))
    frames = frames[frames[esquema.COLUNA_CLIPE].astype(str).isin(do_catalogo)]
    if frames.empty:
        raise FileNotFoundError(
            f"nenhum shard em {saida / DIR_SHARDS} corresponde aos {len(do_catalogo)} "
            "clipes do catálogo; rode a extração para este split antes"
        )

    clipes = agregacao.junta_rotulos(agregacao.agrega(frames), catalogo)

    caminho_frames = saida / NOME_FRAMES
    caminho_clipes = saida / NOME_CLIPES
    frames.to_parquet(caminho_frames, index=False)
    clipes.to_parquet(caminho_clipes, index=False)
    return caminho_frames, caminho_clipes


#: Frames por segundo dos clipes do DAiSEE. Constante porque o dataset é
#: homogêneo: todos os clipes têm 10s e ~300 frames, gravados pela mesma
#: captura de webcam. O UTA-RLDD, gravado por 60 celulares diferentes, precisa
#: medir o fps arquivo por arquivo; aqui isso seria 8570 aberturas de vídeo para
#: confirmar um número que o dataset garante.
FPS_DO_DAISEE = 30.0

NOME_CLIPES_PRODUTO = "clipes_produto.parquet"


def consolida_produto(saida: Path, catalogo: pd.DataFrame) -> Path:
    """Monta `clipes_produto.parquet`: as features como o backend as veria.

    Existe pela mesma razão que o arquivo irmão do UTA-RLDD: o backend recebe a
    telemetria a 1 Hz, já resumida no navegador, e não os ~60 frames a 6 fps que
    saem do vídeo. Comparar os dois datasets — ou transferir um modelo de um para
    o outro — exige que os dois estejam na mesma granularidade, senão a diferença
    medida é de amostragem, não de comportamento.

    **O sintoma disso apareceu de verdade.** Na primeira comparação de domínios,
    `n_frames` tinha um `d` de Cohen de 112: 60 no DAiSEE contra 10,7 no RLDD.
    Uma feature que separa os datasets perfeitamente é uma bandeira de origem
    disfarçada — no treino conjunto, o modelo podia ler "n_frames = 60, logo
    DAiSEE, logo engajado" sem olhar para o rosto.
    """
    shards = caminhos_de_shard(saida)
    if not shards:
        raise FileNotFoundError(f"nenhum shard em {saida / DIR_SHARDS}; rode a extração antes")

    frames = pd.concat((pd.read_parquet(s) for s in shards), ignore_index=True)
    esquema.valida_frames(frames)

    do_catalogo = set(catalogo[esquema.COLUNA_CLIPE].astype(str))
    frames = frames[frames[esquema.COLUNA_CLIPE].astype(str).isin(do_catalogo)]

    fps = {str(clipe): FPS_DO_DAISEE for clipe in frames[esquema.COLUNA_CLIPE].unique()}
    features = agregacao_producao.agrega_como_o_produto(frames, fps)
    clipes = agregacao.junta_rotulos(features, catalogo)

    caminho = saida / NOME_CLIPES_PRODUTO
    clipes.to_parquet(caminho, index=False)
    return caminho


def _argumentos(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extrai features de EAR/Head Pose/MAR dos vídeos do DAiSEE (ticket 1).",
    )
    parser.add_argument("--raiz", type=Path, required=True, help="raiz do DAiSEE (contém DataSet/ e Labels/)")
    parser.add_argument("--saida", type=Path, default=Path(__file__).parent / "dados")
    parser.add_argument("--split", choices=esquema.SPLITS_VALIDOS, default=None, help="restringe a um split")
    parser.add_argument("--amostragem", type=int, default=AMOSTRAGEM_PADRAO, help="processa 1 frame a cada N")
    parser.add_argument("--limite", type=int, default=None, help="processa só os N primeiros clipes")
    parser.add_argument("--confianca", type=float, default=0.5, help="min_detection_confidence do Face Mesh")
    parser.add_argument("--clipes-por-shard", type=int, default=CLIPES_POR_SHARD)
    parser.add_argument("--recomecar", action="store_true", help="ignora shards existentes em vez de retomar")
    parser.add_argument("--so-consolidar", action="store_true", help="não extrai; só junta os shards já gravados")
    parser.add_argument(
        "--como-o-produto",
        action="store_true",
        help="gera também clipes_produto.parquet, com as features por médias de segundo",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = _argumentos(argv)
    fala = lambda msg: print(msg, file=sys.stderr, flush=True)

    try:
        catalogo = daisee.catalogo(args.raiz, split=args.split)
    except daisee.DatasetInvalido as erro:
        fala(f"dataset inválido: {erro}")
        return 2

    if catalogo.empty:
        fala(f"nenhum clipe com rótulo encontrado em {args.raiz}")
        return 2

    descasamento = daisee.descasamento(args.raiz, split=args.split)
    fala(
        f"catálogo: {descasamento.n_pareados} clipes pareados "
        f"({len(descasamento.clipes_sem_rotulo)} sem rótulo, "
        f"{len(descasamento.rotulos_sem_video)} rótulos sem vídeo)"
    )

    if args.limite is not None:
        catalogo = catalogo.head(args.limite)

    args.saida.mkdir(parents=True, exist_ok=True)

    if not args.so_consolidar:
        with extracao.DetectorMediaPipe(min_detection_confidence=args.confianca) as detector:
            progresso = extrai(
                catalogo=catalogo,
                saida=args.saida,
                detector=detector,
                amostragem=args.amostragem,
                clipes_por_shard=args.clipes_por_shard,
                retomar=not args.recomecar,
                registra=fala,
            )
        fala(
            f"extração: {progresso.extraidos} novos, {progresso.pulados} já feitos, "
            f"{progresso.falhos} falharam"
        )
        for falha in progresso.falhas[:20]:
            fala(f"  {falha}")

    caminho_frames, caminho_clipes = consolida(args.saida, catalogo)
    if args.como_o_produto:
        caminho_produto = consolida_produto(args.saida, catalogo)
        fala(f"{caminho_produto}: features como o backend as vê (médias por segundo)")
    frames = pd.read_parquet(caminho_frames, columns=[esquema.COLUNA_CLIPE])
    clipes = pd.read_parquet(caminho_clipes)
    fala(f"{caminho_frames}: {len(frames)} frames")
    fala(f"{caminho_clipes}: {len(clipes)} clipes x {len(esquema.colunas_features())} features")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
