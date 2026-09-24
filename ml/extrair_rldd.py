"""CLI: UTA-RLDD em disco -> dataset tabular de janelas de 10 segundos.

Irmão de `extrair_features.py`, que faz o mesmo para o DAiSEE. Os dois produzem
as **mesmas 39 features** (`esquema.colunas_features()`), calculadas pelo mesmo
extrator e pela mesma agregação — é isso que permite treinar, comparar e, se
fizer sentido, juntar os dois datasets.

O que muda é a unidade de entrada. O DAiSEE já vem cortado em clipes de 10s, com
um rótulo por clipe; o UTA-RLDD vem em 182 gravações de ~10 minutos, com um
rótulo por gravação. Aqui cada gravação é fatiada em janelas de 10 segundos
durante a leitura, e cada janela herda o rótulo da gravação.

**Um shard por gravação, e não a cada N janelas.** São 182 gravações de dez
minutos: se a execução morrer no meio da 97ª, retomar do início da 97ª custa
dez minutos de vídeo, não dez horas. O nome do shard é o prefixo da gravação,
então a retomada é uma checagem de existência de arquivo — sem precisar abrir
nada para descobrir o que já foi feito.

**`--folds` existe para paralelizar.** O MediaPipe é de um núcleo só na prática;
com 12 disponíveis, rodar cinco processos, um por fold, divide o relógio por
cinco. Os folds são disjuntos por participante, então dois processos nunca
escrevem o mesmo shard.

Uso típico:

    python extrair_rldd.py --raiz "D:/tcc/database/Nova pasta" --limite 2
    python extrair_rldd.py --raiz "D:/tcc/database/Nova pasta" --folds 1
    python extrair_rldd.py --raiz "D:/tcc/database/Nova pasta" --so-consolidar
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional

import cv2
import pandas as pd

import agregacao
import esquema
import esquema_rldd
import extracao
import rldd

#: Duração de cada janela, em segundos. Dez para casar com o clipe do DAiSEE:
#: as features agregadas só são comparáveis entre os dois datasets se a unidade
#: de tempo for a mesma.
SEGUNDOS_POR_JANELA = 10

#: Processa 1 frame a cada N. O mesmo padrão do DAiSEE, pela mesma razão: uma
#: piscada dura ~100 ms e ainda aparece a ~6 fps.
AMOSTRAGEM_PADRAO = 5

#: Largura máxima antes da detecção. Ver `extracao.reduz_para`.
LARGURA_MAXIMA_PADRAO = 640

#: Usado quando o contêiner não declara fps — acontece em arquivo remuxado.
FPS_PADRAO = 30.0

NOME_FRAMES = "frames.parquet"
NOME_JANELAS = "janelas.parquet"
NOME_GRAVACOES = "gravacoes.parquet"
DIR_SHARDS = "shards"


@dataclass
class Progresso:
    """Contagem de uma execução, para o relatório final e para os testes."""

    total: int = 0
    extraidas: int = 0
    puladas: int = 0
    falhas: List[str] = field(default_factory=list)


def fps_do_video(caminho: Path) -> float:
    """Frames por segundo declarados pelo arquivo, com queda para o padrão.

    Vem do contêiner, não de contar frames: contar exigiria decodificar o vídeo
    inteiro só para descobrir o tamanho da janela. Um valor absurdo (0, negativo
    ou acima de 240) é sinal de metadado corrompido e cai no padrão — melhor uma
    janela de 10s aproximada que uma de 0 frames.
    """
    captura = cv2.VideoCapture(str(caminho))
    try:
        fps = captura.get(cv2.CAP_PROP_FPS)
    finally:
        captura.release()

    if not fps or fps <= 0 or fps > 240:
        return FPS_PADRAO
    return float(fps)


def caminho_do_shard(saida: Path, prefixo: str) -> Path:
    return saida / DIR_SHARDS / f"{prefixo}.parquet"


def shards_existentes(saida: Path) -> List[Path]:
    diretorio = saida / DIR_SHARDS
    if not diretorio.is_dir():
        return []
    return sorted(diretorio.glob("rldd-*.parquet"))


def extrai(
    gravacoes: List[rldd.Gravacao],
    saida: Path,
    detector: extracao.DetectorDeLandmarks,
    segundos_por_janela: int = SEGUNDOS_POR_JANELA,
    amostragem: int = AMOSTRAGEM_PADRAO,
    largura_maxima: Optional[int] = LARGURA_MAXIMA_PADRAO,
    retomar: bool = True,
    registra=lambda _: None,
) -> Progresso:
    """Extrai as janelas de cada gravação, gravando um shard por gravação.

    Uma gravação que falha é anotada e a execução continua: parar 182 vídeos por
    causa de um arquivo ruim trocaria um dado faltante por horas perdidas.
    """
    progresso = Progresso(total=len(gravacoes))
    (saida / DIR_SHARDS).mkdir(parents=True, exist_ok=True)

    for gravacao in gravacoes:
        destino = caminho_do_shard(saida, gravacao.prefixo)
        if retomar and destino.is_file():
            progresso.puladas += 1
            continue

        # Gravação nova: o rastreamento do frame anterior é de outra pessoa.
        extracao.reinicia_detector(detector)
        fps = fps_do_video(gravacao.caminho)
        frames_por_janela = max(1, round(fps * segundos_por_janela))

        try:
            frames = extracao.extrai_frames_em_janelas(
                caminho_video=gravacao.caminho,
                prefixo=gravacao.prefixo,
                detector=detector,
                frames_por_janela=frames_por_janela,
                amostragem=amostragem,
                largura_maxima=largura_maxima,
                id_da_janela=rldd.id_da_janela,
            )
        except extracao.VideoIlegivel as erro:
            progresso.falhas.append(f"{gravacao.prefixo}: {erro}")
            registra(f"falhou {gravacao.prefixo}: {erro}")
            continue

        # Arquivo temporário e rename: um shard cortado no meio por Ctrl-C teria
        # o nome certo e conteúdo pela metade, e a retomada o aceitaria.
        parcial = destino.with_suffix(".parcial")
        frames.to_parquet(parcial, index=False)
        parcial.replace(destino)

        progresso.extraidas += 1
        n_janelas = frames[esquema.COLUNA_CLIPE].nunique()
        registra(
            f"{gravacao.prefixo}: {n_janelas} janelas, {len(frames)} frames "
            f"({fps:.0f} fps) [{progresso.extraidas}/{progresso.total}]"
        )

    return progresso


def consolida(saida: Path, folds: dict) -> tuple[Path, Path]:
    """Junta os shards nos dois artefatos finais: `frames` e `janelas`.

    Separado da extração de propósito: é barato, idempotente, e roda sobre uma
    extração parcial para inspecionar o que já saiu sem esperar o resto.
    """
    shards = shards_existentes(saida)
    if not shards:
        raise FileNotFoundError(f"nenhum shard em {saida / DIR_SHARDS}; rode a extração antes")

    frames = pd.concat((pd.read_parquet(s) for s in shards), ignore_index=True)
    esquema.valida_frames(frames)

    features = agregacao.agrega(frames)
    identidade = rldd.catalogo_de_janelas(features[esquema.COLUNA_CLIPE], folds)

    janelas = features.merge(identidade, on=esquema.COLUNA_CLIPE, how="inner")
    janelas = janelas[esquema_rldd.colunas_janelas()].reset_index(drop=True)
    esquema_rldd.valida_janelas(janelas)

    caminho_frames = saida / NOME_FRAMES
    caminho_janelas = saida / NOME_JANELAS
    frames.to_parquet(caminho_frames, index=False)
    janelas.to_parquet(caminho_janelas, index=False)
    return caminho_frames, caminho_janelas


def _argumentos(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extrai features de EAR/Head Pose/MAR das gravações do UTA-RLDD.",
    )
    parser.add_argument("--raiz", type=Path, required=True, help="raiz do UTA-RLDD (contém Fold<N>_part<M>/)")
    parser.add_argument("--saida", type=Path, default=Path(__file__).parent / "dados_rldd")
    parser.add_argument("--folds", type=str, default=None, help="restringe aos folds, ex. 1 ou 1,2")
    parser.add_argument(
        "--fatia",
        type=str,
        default=None,
        help=(
            "divide o trabalho entre processos, no formato i/n — `--fatia 0/4` pega "
            "a 1a, 5a, 9a... gravação. Intercalar em vez de cortar em blocos é o que "
            "mantém os processos com carga parecida: as gravações não têm todas o "
            "mesmo tamanho, e um bloco pode cair inteiro nos arquivos de 1 GB."
        ),
    )
    parser.add_argument("--segundos-por-janela", type=int, default=SEGUNDOS_POR_JANELA)
    parser.add_argument("--amostragem", type=int, default=AMOSTRAGEM_PADRAO, help="processa 1 frame a cada N")
    parser.add_argument("--largura-maxima", type=int, default=LARGURA_MAXIMA_PADRAO, help="0 desliga a redução")
    parser.add_argument("--limite", type=int, default=None, help="processa só as N primeiras gravações")
    parser.add_argument("--confianca", type=float, default=0.5, help="min_detection_confidence do Face Mesh")
    parser.add_argument("--recomecar", action="store_true", help="ignora shards existentes em vez de retomar")
    parser.add_argument("--so-consolidar", action="store_true", help="não extrai; só junta os shards já gravados")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = _argumentos(argv)
    fala = lambda msg: print(msg, file=sys.stderr, flush=True)

    try:
        catalogo = rldd.catalogo_de_gravacoes(args.raiz)
        folds = rldd.folds_por_participante(catalogo)
    except rldd.DatasetInvalido as erro:
        fala(f"dataset inválido: {erro}")
        return 2

    gravacoes = rldd.lista_gravacoes(args.raiz)
    if args.folds:
        pedidos = {int(n) for n in args.folds.split(",")}
        gravacoes = [g for g in gravacoes if g.fold in pedidos]
    if args.fatia:
        indice, total = (int(n) for n in args.fatia.split("/"))
        if not 0 <= indice < total:
            fala(f"fatia inválida: {args.fatia}")
            return 2
        gravacoes = gravacoes[indice::total]
    if args.limite is not None:
        gravacoes = gravacoes[: args.limite]

    fala(
        f"catálogo: {len(catalogo)} gravações de {catalogo['participante'].nunique()} "
        f"participantes em {catalogo['fold'].nunique()} folds; "
        f"esta execução cobre {len(gravacoes)}"
    )

    args.saida.mkdir(parents=True, exist_ok=True)

    if not args.so_consolidar:
        with extracao.DetectorMediaPipe(min_detection_confidence=args.confianca) as detector:
            progresso = extrai(
                gravacoes=gravacoes,
                saida=args.saida,
                detector=detector,
                segundos_por_janela=args.segundos_por_janela,
                amostragem=args.amostragem,
                largura_maxima=args.largura_maxima or None,
                retomar=not args.recomecar,
                registra=fala,
            )
        fala(
            f"extração: {progresso.extraidas} novas, {progresso.puladas} já feitas, "
            f"{len(progresso.falhas)} falharam"
        )
        for falha in progresso.falhas[:20]:
            fala(f"  {falha}")

    caminho_frames, caminho_janelas = consolida(args.saida, folds)
    janelas = pd.read_parquet(caminho_janelas)
    fala(f"{caminho_frames}")
    fala(
        f"{caminho_janelas}: {len(janelas)} janelas x "
        f"{len(esquema.colunas_features())} features"
    )
    fala(str(janelas[esquema_rldd.COLUNA_SONOLENCIA].value_counts().sort_index().to_dict()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
