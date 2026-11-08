"""Sensibilidade do IEE aos pesos e ao limiar de olho fechado (parecer TC2, F05).

Os pesos 0,6/0,4 são escolha de projeto, e o parecer pede para mostrar o quanto
o resultado depende dela. A pergunta aqui é proporcional ao que uma PoC sustenta:
**a ordem dos blocos de foco, do melhor para o pior, muda se a escolha mudar?**

Uso:
    python sensibilidade_iee.py --sessao sessao-real-1.json \\
        --blocos blocos-sessao-1.json --rotulo "Sessão real 1"

`--sessao` é o JSON baixado pelo `mapface-evidencias/gravador_mapface.js`;
`--blocos` é o baixado pelo `mapface-evidencias/baixar_blocos.js`.

**A sessão é reproduzida no analista de produção, e não numa cópia da fórmula.**
Calibração, abstenção por incerteza, ausência e fadiga vêm junto. Uma segunda
implementação concordaria com a primeira até o dia em que uma delas mudasse.

**Por que precisa da gravação, e não do banco.** O banco guarda o `score` já
calculado. Não dá para separar dele a parte dos olhos e a da cabeça, e o EAR que
decide o olho fechado não é persistido. Só o JSON do gravador tem as entradas.

**O script se recusa a responder se não reproduzir a produção.** O cenário
0,6/0,4/50% precisa devolver os `score` que o servidor enviou na própria sessão.
Sem isso, os outros oito cenários não teriam referência nenhuma.

**O que este resultado afirma.** Estabilidade da ordem em uma sessão de uma
pessoa. Não valida o índice como medida de engajamento.
"""
import argparse
import contextlib
import csv
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Dict, Iterator, List, Optional, Sequence, Tuple

# `append`, e não `insert`: `ml/` e `backend/` têm cada um a sua pasta `tests`.
sys.path.append(str(Path(__file__).resolve().parent.parent / "backend"))

from app import analista, blocos as modulo_blocos  # noqa: E402
from app.tempo import como_utc  # noqa: E402

PESOS: Tuple[Tuple[float, float], ...] = ((0.5, 0.5), (0.6, 0.4), (0.7, 0.3))
LIMIARES: Tuple[float, ...] = (0.4, 0.5, 0.6)
CENARIO_PADRAO: Tuple[float, float, float] = (0.6, 0.4, 0.5)

#: Quanto o replay pode diferir do `score` gravado. Não é zero porque o servidor
#: mede as durações pelo próprio relógio e o gravador pelo do navegador.
TOLERANCIA_PONTOS = 0.5
FRACAO_MINIMA_DENTRO = 0.99

#: Acima disto a média do relatório é apontada como divergente. É só um aviso:
#: depois de 24 h o relatório é calculado sobre médias por minuto.
TOLERANCIA_RELATORIO = 1.0

#: Espelha `criterios.MEDIDA_MINIMA_S`, que não dá para importar aqui porque
#: `criterios` carrega os modelos de banco. Bloco com menos medida não tem média.
MEDIDA_MINIMA_S = 60

#: Série categórica validada; marcador e traço mantêm a leitura em P&B.
CORES = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100")
MARCADORES = ("o", "s", "^", "D")
TRACOS = ("-", "--", "-.", ":")


class ErroDeEntrada(Exception):
    """Arquivo que não permite responder à pergunta. A mensagem diz o que fazer."""


@dataclass(frozen=True)
class Leitura:
    indice_envio: int
    instante: datetime
    ear: float
    yaw: float
    rosto_detectado: bool
    mar: Optional[float]
    incerteza: Optional[str]


@dataclass(frozen=True)
class Ponto:
    indice_envio: int
    instante: datetime
    score: Optional[float]


@dataclass(frozen=True)
class Bloco:
    indice: int
    tipo: str
    inicio: datetime
    fim: Optional[datetime]
    media_relatorio: Optional[float] = None


@dataclass(frozen=True)
class Cenario:
    peso_ocular: float
    peso_orientacao: float
    limiar: float
    medias: Dict[int, Optional[float]]
    ordem: Tuple[int, ...]

    @property
    def chave(self) -> Tuple[float, float, float]:
        return (self.peso_ocular, self.peso_orientacao, self.limiar)


@dataclass(frozen=True)
class Validacao:
    pares: int
    dentro: int
    maior_diferenca: float

    @property
    def aprovada(self) -> bool:
        return self.pares > 0 and self.dentro / self.pares >= FRACAO_MINIMA_DENTRO


def _numero(valor) -> Optional[float]:
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        return None
    return float(valor)


def _ler_json(caminho: Path):
    try:
        return json.loads(Path(caminho).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ErroDeEntrada(f"arquivo não encontrado: {caminho}")
    except json.JSONDecodeError as erro:
        raise ErroDeEntrada(f"{caminho} não é um JSON válido: {erro}")


def _instante_ms(t_ms: float) -> datetime:
    return datetime.fromtimestamp(t_ms / 1000, tz=timezone.utc)


def ler_leituras(dados: dict) -> List[Leitura]:
    """Os payloads na ordem de envio, com o mesmo filtro de `_ler_metricas`.

    `indice_envio` é a posição em `enviados`, que é o que o `i_envio` de
    `recebidos` referencia. Payload que o servidor recusaria não é reproduzido.
    """
    if not isinstance(dados, dict) or not isinstance(dados.get("enviados"), list):
        raise ErroDeEntrada("o arquivo da sessão não tem a lista `enviados` do gravador")

    leituras = []
    for indice, item in enumerate(dados["enviados"]):
        ear, yaw, t = _numero(item.get("ear")), _numero(item.get("yaw")), _numero(item.get("t"))
        rosto = item.get("rosto_detectado", True)
        if ear is None or yaw is None or t is None or not isinstance(rosto, bool):
            continue
        incerteza = item.get("incerteza")
        leituras.append(
            Leitura(
                indice_envio=indice,
                instante=_instante_ms(t),
                ear=ear,
                yaw=yaw,
                rosto_detectado=rosto,
                mar=_numero(item.get("mar")),
                incerteza=incerteza if isinstance(incerteza, str) else None,
            )
        )

    if not leituras:
        raise ErroDeEntrada("a gravação não tem nenhum payload de telemetria")
    return sorted(leituras, key=lambda leitura: leitura.instante)


def ler_blocos(dados) -> List[Bloco]:
    """Aceita o arquivo do `baixar_blocos.js` ou a lista crua de `/blocos`."""
    lista = dados.get("blocos") if isinstance(dados, dict) else dados
    if not isinstance(lista, list) or not lista:
        raise ErroDeEntrada("o arquivo de blocos não tem nenhum bloco")

    blocos = []
    for item in lista:
        try:
            blocos.append(
                Bloco(
                    indice=int(item["indice"]),
                    tipo=str(item["tipo"]),
                    inicio=como_utc(datetime.fromisoformat(item["inicio"])),
                    fim=como_utc(datetime.fromisoformat(item["fim"])) if item.get("fim") else None,
                    media_relatorio=_numero(item.get("media")),
                )
            )
        except (KeyError, TypeError, ValueError) as erro:
            raise ErroDeEntrada(f"bloco malformado no arquivo de blocos: {erro!r}")
    return sorted(blocos, key=lambda bloco: bloco.indice)


def blocos_de_foco(blocos: Sequence[Bloco]) -> List[Bloco]:
    focos = [bloco for bloco in blocos if bloco.tipo == modulo_blocos.TIPO_FOCO]
    if not focos:
        raise ErroDeEntrada("a sessão não tem nenhum bloco de foco para comparar")
    return focos


@contextlib.contextmanager
def _constantes(peso_ocular: float, peso_orientacao: float, limiar: float) -> Iterator[None]:
    """Troca os parâmetros do analista só durante o replay."""
    originais = (analista.PESO_OCULAR, analista.PESO_ORIENTACAO, analista.FRACAO_OLHO_FECHADO)
    analista.PESO_OCULAR = peso_ocular
    analista.PESO_ORIENTACAO = peso_orientacao
    analista.FRACAO_OLHO_FECHADO = limiar
    try:
        yield
    finally:
        analista.PESO_OCULAR, analista.PESO_ORIENTACAO, analista.FRACAO_OLHO_FECHADO = originais


def reproduzir(
    leituras: Sequence[Leitura], peso_ocular: float, peso_orientacao: float, limiar: float
) -> List[Ponto]:
    """A sessão inteira, num analista novo, com os parâmetros pedidos."""
    pontos = []
    with _constantes(peso_ocular, peso_orientacao, limiar):
        engajamento = analista.AnalistaEngajamento()
        for leitura in leituras:
            resultado = engajamento.observar(
                ear=leitura.ear,
                yaw=leitura.yaw,
                rosto_detectado=leitura.rosto_detectado,
                agora=leitura.instante,
                mar=leitura.mar,
                incerteza=leitura.incerteza,
            )
            pontos.append(Ponto(leitura.indice_envio, leitura.instante, resultado.score))
    return pontos


def validar(pontos: Sequence[Ponto], dados: dict) -> Validacao:
    """Compara o cenário padrão com o que o servidor respondeu na sessão."""
    gravados = {
        item["i_envio"]: item.get("score")
        for item in dados.get("recebidos", [])
        if item.get("tipo") == "score" and item.get("i_envio") is not None
    }

    pares = dentro = 0
    maior = 0.0
    for ponto in pontos:
        if ponto.indice_envio not in gravados:
            continue
        pares += 1
        gravado = gravados[ponto.indice_envio]
        if gravado is None or ponto.score is None:
            if gravado is None and ponto.score is None:
                dentro += 1
            else:
                maior = float("inf")
            continue
        diferenca = abs(gravado - ponto.score)
        maior = max(maior, diferenca)
        if diferenca <= TOLERANCIA_PONTOS:
            dentro += 1

    return Validacao(pares=pares, dentro=dentro, maior_diferenca=maior)


def media_do_bloco(bloco: Bloco, pontos: Sequence[Ponto]) -> Optional[float]:
    """Média como a do relatório: incerteza fora, zero dentro, bordas semiabertas."""
    dentro = modulo_blocos.recortar(bloco, pontos, lambda ponto: ponto.instante)
    medidos = [ponto.score for ponto in dentro if ponto.score is not None]
    if len(medidos) < MEDIDA_MINIMA_S:
        return None
    return mean(medidos)


def ordem_dos_blocos(medias: Dict[int, Optional[float]]) -> Tuple[int, ...]:
    """Índices do melhor para o pior. Bloco sem média não entra na comparação."""
    medidos = [(indice, media) for indice, media in medias.items() if media is not None]
    return tuple(indice for indice, _ in sorted(medidos, key=lambda par: (-par[1], par[0])))


def calcular_cenarios(leituras: Sequence[Leitura], focos: Sequence[Bloco]) -> List[Cenario]:
    cenarios = []
    for peso_ocular, peso_orientacao in PESOS:
        for limiar in LIMIARES:
            pontos = reproduzir(leituras, peso_ocular, peso_orientacao, limiar)
            medias = {bloco.indice: media_do_bloco(bloco, pontos) for bloco in focos}
            cenarios.append(
                Cenario(peso_ocular, peso_orientacao, limiar, medias, ordem_dos_blocos(medias))
            )
    return cenarios


def cenario_padrao(cenarios: Sequence[Cenario]) -> Cenario:
    return next(cenario for cenario in cenarios if cenario.chave == CENARIO_PADRAO)


def cenarios_com_ordem_diferente(cenarios: Sequence[Cenario]) -> List[Cenario]:
    padrao = cenario_padrao(cenarios)
    return [cenario for cenario in cenarios if cenario.ordem != padrao.ordem]


def divergencias_do_relatorio(focos: Sequence[Bloco], padrao: Cenario) -> List[str]:
    avisos = []
    for bloco in focos:
        media = padrao.medias[bloco.indice]
        if bloco.media_relatorio is None or media is None:
            continue
        if abs(bloco.media_relatorio - media) > TOLERANCIA_RELATORIO:
            avisos.append(
                f"bloco {bloco.indice}: relatório {_br(bloco.media_relatorio)}, "
                f"replay {_br(media)}"
            )
    return avisos


def _br(valor: Optional[float], casas: int = 2) -> str:
    return "—" if valor is None else f"{valor:.{casas}f}".replace(".", ",")


def _nome_do_cenario(cenario: Cenario) -> str:
    return (
        f"{_br(cenario.peso_ocular, 1)}/{_br(cenario.peso_orientacao, 1)}, "
        f"limiar {cenario.limiar:.0%}"
    )


def _nomes_de_foco(focos: Sequence[Bloco]) -> Dict[int, str]:
    return {bloco.indice: f"Foco {posicao}" for posicao, bloco in enumerate(focos, start=1)}


def _ordem_em_texto(ordem: Sequence[int], nomes: Dict[int, str]) -> str:
    return " > ".join(nomes[indice] for indice in ordem) or "—"


def conclusao(cenarios: Sequence[Cenario], focos: Sequence[Bloco]) -> str:
    comparaveis = len(cenario_padrao(cenarios).ordem)
    if comparaveis < 2:
        return (
            "A sessão tem menos de dois blocos de foco com média, então não há ordem a comparar."
        )
    diferentes = cenarios_com_ordem_diferente(cenarios)
    if not diferentes:
        return f"A ordem dos blocos de foco foi a mesma nos {len(cenarios)} cenários."
    return (
        f"A ordem dos blocos de foco mudou em {len(diferentes)} dos {len(cenarios)} cenários: "
        + "; ".join(_nome_do_cenario(cenario) for cenario in diferentes)
        + "."
    )


def escrever_csv(cenarios: Sequence[Cenario], focos: Sequence[Bloco], caminho: Path) -> None:
    nomes = _nomes_de_foco(focos)
    padrao = cenario_padrao(cenarios)
    with open(caminho, "w", newline="", encoding="utf-8") as saida:
        escritor = csv.writer(saida)
        escritor.writerow(
            ["peso_ocular", "peso_orientacao", "limiar_olho_fechado", "bloco", "indice_bloco",
             "iee_medio", "posicao", "ordem_igual_ao_padrao"]
        )
        for cenario in cenarios:
            for bloco in focos:
                media = cenario.medias[bloco.indice]
                posicao = (
                    cenario.ordem.index(bloco.indice) + 1 if bloco.indice in cenario.ordem else ""
                )
                escritor.writerow(
                    [cenario.peso_ocular, cenario.peso_orientacao, cenario.limiar,
                     nomes[bloco.indice], bloco.indice,
                     "" if media is None else f"{media:.4f}", posicao,
                     cenario.ordem == padrao.ordem]
                )


def escrever_relatorio(
    cenarios: Sequence[Cenario],
    focos: Sequence[Bloco],
    validacao: Validacao,
    avisos: Sequence[str],
    rotulo: str,
    caminho: Path,
) -> None:
    nomes = _nomes_de_foco(focos)
    colunas = [nomes[bloco.indice] for bloco in focos]
    linhas = [
        f"# Sensibilidade do IEE: {rotulo}",
        "",
        f"**{conclusao(cenarios, focos)}**",
        "",
        f"- Validação contra a sessão: {validacao.dentro} de {validacao.pares} pontos a até "
        f"{_br(TOLERANCIA_PONTOS, 1)} ponto do `score` gravado.",
        f"- Blocos de foco comparados: {len(focos)}.",
    ]
    if avisos:
        linhas.append(
            "- Médias do relatório divergentes (esperado se baixadas depois de 24 h): "
            + "; ".join(avisos)
            + "."
        )
    linhas += [
        "",
        "| Pesos (olhos/cabeça) | Limiar | " + " | ".join(colunas) + " | Ordem |",
        "| --- | --- | " + " | ".join("---" for _ in colunas) + " | --- |",
    ]
    for cenario in cenarios:
        medias = " | ".join(_br(cenario.medias[bloco.indice]) for bloco in focos)
        linhas.append(
            f"| {_br(cenario.peso_ocular, 1)}/{_br(cenario.peso_orientacao, 1)} "
            f"| {cenario.limiar:.0%} | {medias} | {_ordem_em_texto(cenario.ordem, nomes)} |"
        )
    linhas += [
        "",
        "Limite: resultado de uma sessão de uma pessoa. Mostra a estabilidade da ordem dos "
        "blocos diante dos parâmetros, e não valida o índice como medida de engajamento.",
        "",
    ]
    Path(caminho).write_text("\n".join(linhas), encoding="utf-8")


def _separar_rotulos(valores: Sequence[float], distancia: float) -> List[float]:
    """Afasta rótulos vizinhos sem mudar a ordem deles."""
    ordem = sorted(range(len(valores)), key=lambda i: valores[i])
    ajustados = list(valores)
    for anterior, atual in zip(ordem, ordem[1:]):
        if ajustados[atual] - ajustados[anterior] < distancia:
            ajustados[atual] = ajustados[anterior] + distancia
    return ajustados


def desenhar(cenarios: Sequence[Cenario], focos: Sequence[Bloco], rotulo: str, pasta: Path) -> None:
    """Três painéis, um por limiar: se as linhas se cruzam, a ordem mudou."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    nomes = _nomes_de_foco(focos)
    pesos_x = [peso for peso, _ in PESOS]
    figura, eixos = plt.subplots(1, len(LIMIARES), figsize=(9.5, 4.2), sharey=True)
    tinta, tinta_fraca, grade = "#0b0b0b", "#52514e", "#e7e6e1"

    todos = [m for c in cenarios for m in c.medias.values() if m is not None]
    amplitude = max(max(todos) - min(todos), 1.0) if todos else 1.0

    for eixo, limiar in zip(eixos, LIMIARES):
        finais = []
        for posicao, bloco in enumerate(focos):
            serie = [
                next(
                    c.medias[bloco.indice]
                    for c in cenarios
                    if c.limiar == limiar and c.peso_ocular == peso
                )
                for peso in pesos_x
            ]
            indice_estilo = posicao % len(CORES)
            eixo.plot(
                pesos_x,
                [float("nan") if valor is None else valor for valor in serie],
                color=CORES[indice_estilo],
                marker=MARCADORES[indice_estilo],
                linestyle=TRACOS[indice_estilo],
                linewidth=2,
                markersize=8,
                markeredgecolor="white",
                markeredgewidth=1.2,
                label=nomes[bloco.indice],
            )
            if serie[-1] is not None:
                finais.append((serie[-1], nomes[bloco.indice]))

        eixo.set_title(f"Olho fechado: {limiar:.0%} do EAR neutro", fontsize=10, color=tinta)
        eixo.set_xticks(pesos_x)
        eixo.set_xticklabels([_br(peso, 1) for peso in pesos_x])
        eixo.set_xlim(pesos_x[0] - 0.03, pesos_x[-1] + 0.06)
        eixo.set_xlabel("Peso dos olhos", fontsize=9, color=tinta_fraca)
        eixo.grid(axis="y", color=grade, linewidth=0.8)
        eixo.set_axisbelow(True)
        eixo.tick_params(colors=tinta_fraca, labelsize=9, length=0)
        for lado in ("top", "right", "left"):
            eixo.spines[lado].set_visible(False)
        eixo.spines["bottom"].set_color(grade)

        if len(focos) <= 4 and finais:
            posicoes = _separar_rotulos([valor for valor, _ in finais], amplitude * 0.07)
            for y, (_, nome) in zip(posicoes, finais):
                eixo.text(pesos_x[-1] + 0.012, y, nome, fontsize=8.5, color=tinta, va="center")

    eixos[0].set_ylabel("IEE médio do bloco", fontsize=9, color=tinta_fraca)
    alcas, nomes_legenda = eixos[0].get_legend_handles_labels()
    figura.legend(
        alcas, nomes_legenda, loc="lower center", ncol=min(len(focos), 8), frameon=False, fontsize=9
    )
    diferentes = len(cenarios_com_ordem_diferente(cenarios))
    figura.suptitle(
        f"{rotulo}: a ordem dos blocos mudou em {diferentes} de {len(cenarios)} cenários",
        fontsize=11,
        color=tinta,
    )
    figura.tight_layout(rect=(0, 0.07, 1, 0.95))

    figura.savefig(Path(pasta) / "sensibilidade_iee.png", dpi=300, facecolor="white")
    figura.savefig(Path(pasta) / "sensibilidade_iee.svg", facecolor="white")
    plt.close(figura)


def analisar(sessao: Path, arquivo_blocos: Path, rotulo: str, pasta: Path) -> str:
    """Valida, calcula e grava os artefatos. Devolve a conclusão."""
    dados = _ler_json(sessao)
    leituras = ler_leituras(dados)
    focos = blocos_de_foco(ler_blocos(_ler_json(arquivo_blocos)))

    validacao = validar(reproduzir(leituras, *CENARIO_PADRAO), dados)
    if not validacao.aprovada:
        raise ErroDeEntrada(
            "o cenário 0,6/0,4/50% não reproduziu a sessão gravada "
            f"({validacao.dentro} de {validacao.pares} pontos dentro da tolerância). "
            "Confira se o gravador foi colado antes de iniciar a sessão e se o build gravado "
            "usa os mesmos parâmetros de backend/app/analista.py."
        )

    cenarios = calcular_cenarios(leituras, focos)
    avisos = divergencias_do_relatorio(focos, cenario_padrao(cenarios))

    Path(pasta).mkdir(parents=True, exist_ok=True)
    escrever_csv(cenarios, focos, Path(pasta) / "resultado.csv")
    escrever_relatorio(cenarios, focos, validacao, avisos, rotulo, Path(pasta) / "relatorio.md")
    desenhar(cenarios, focos, rotulo, Path(pasta))
    return conclusao(cenarios, focos)


def main(argv: Optional[Sequence[str]] = None) -> int:
    analisador = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    analisador.add_argument("--sessao", type=Path, required=True)
    analisador.add_argument("--blocos", type=Path, required=True)
    analisador.add_argument("--rotulo", default="Sessão real 1")
    analisador.add_argument(
        "-o", "--saida", type=Path, default=Path(__file__).parent / "artefatos_sensibilidade"
    )
    argumentos = analisador.parse_args(argv)

    try:
        print(analisar(argumentos.sessao, argumentos.blocos, argumentos.rotulo, argumentos.saida))
    except ErroDeEntrada as erro:
        print(f"sensibilidade_iee: {erro}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
