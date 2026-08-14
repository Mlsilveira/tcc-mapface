"""Métricas e relatório do Random Forest baseline (ticket 2).

Duas coisas moram aqui: o **cálculo** das métricas (estruturas de dados, nunca
impressão) e a **renderização** delas em Markdown e JSON. O Markdown é o que vai
versionado no repositório e citado no TCC; o JSON existe para que duas execuções
possam ser comparadas com `diff` sem ninguém precisar ler tabela.

Por que reportar tanta coisa em vez de um número só: o DAiSEE é fortemente
desbalanceado — os níveis 0 e 1 de engajamento juntos não chegam a 5% dos
clipes. Um classificador que responda "engajado" para tudo acerta perto de 85%
das amostras e não aprendeu absolutamente nada. Então a **acurácia sozinha é
enganosa** aqui, e todo número aparece em três formas: por classe, macro
(cada classe pesa igual — é onde a classe rara aparece) e ponderada (cada classe
pesa pelo seu suporte — é onde ela some).

Por isso a comparação com a meta de 80% da ticket usa a **precisão macro**, e
não a precisão da classe positiva: num alvo com ~85% de positivos, a precisão da
classe majoritária já nasce perto de 0,85 sem mérito nenhum do modelo. A macro
só passa de 0,80 se o modelo acertar também a classe minoritária, que é
justamente a que interessa detectar (o aluno desengajado).
"""
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, List, Mapping, Optional, Sequence

import numpy as np
from sklearn.metrics import accuracy_score, confusion_matrix, precision_recall_fscore_support

if TYPE_CHECKING:  # pragma: no cover - evita import circular em tempo de execução
    from treino import ResultadoTreino

#: Meta de precisão da ticket 2. Vive aqui porque é critério de aceite, não
#: hiperparâmetro: mudar esse número é mudar o que a ticket promete.
META_PRECISAO = 0.80

#: Split sobre o qual a meta é julgada. Validation serve para escolher o modelo;
#: quem responde "o modelo é bom?" é o Test, tocado uma vez só.
SPLIT_META = "Test"

#: Casas decimais no JSON. Arredondar evita que ruído de ponto flutuante vire
#: linha de diff entre execuções que deveriam ser idênticas.
CASAS = 6


class MetricasInvalidas(Exception):
    """Não dá para calcular métricas com o que foi passado (vazio, tamanhos diferentes)."""


class RotulosInconsistentes(MetricasInvalidas):
    """Apareceu um rótulo que não está na lista declarada de rótulos."""


@dataclass(frozen=True)
class Media:
    """Precisão, recall e F1 agregados de uma das formas (macro ou ponderada)."""

    precisao: float
    recall: float
    f1: float


@dataclass(frozen=True)
class MetricasClasse:
    """Desempenho em uma única classe, com o suporte que a contextualiza."""

    rotulo: int
    nome: str
    precisao: float
    recall: float
    f1: float
    suporte: int


@dataclass(frozen=True)
class Metricas:
    """Tudo o que se sabe sobre um split avaliado."""

    acuracia: float
    por_classe: List[MetricasClasse]
    macro: Media
    ponderada: Media
    matriz_confusao: List[List[int]]
    rotulos: List[int]
    n_amostras: int


@dataclass(frozen=True)
class AvaliacaoMeta:
    """O veredito sobre o critério "precisão > 80%" da ticket 2."""

    meta: float
    precisao_macro: float
    precisao_ponderada: float
    atingida: bool
    criterio: str


def calcula_metricas(
    y_true: Sequence[int],
    y_pred: Sequence[int],
    rotulos: Sequence[int],
    nomes: Optional[Mapping[int, str]] = None,
) -> Metricas:
    """Acurácia, precisão, recall, F1 e matriz de confusão de um split.

    `rotulos` é obrigatório e fixa a ordem de tudo: uma classe rara pode
    simplesmente não cair no split de teste, e nesse caso ela precisa aparecer no
    relatório com suporte 0 em vez de desaparecer da tabela — sumir com a linha
    esconderia exatamente o caso que o desbalanceamento torna interessante.
    """
    verdadeiro = np.asarray(list(y_true))
    previsto = np.asarray(list(y_pred))

    if len(verdadeiro) == 0:
        raise MetricasInvalidas("nenhuma amostra para avaliar")
    if len(verdadeiro) != len(previsto):
        raise MetricasInvalidas(
            f"y_true e y_pred têm tamanhos diferentes: {len(verdadeiro)} != {len(previsto)}"
        )

    conhecidos = set(int(r) for r in rotulos)
    desconhecidos = sorted(set(int(v) for v in np.concatenate([verdadeiro, previsto])) - conhecidos)
    if desconhecidos:
        raise RotulosInconsistentes(
            f"rótulos fora dos declarados {sorted(conhecidos)}: {desconhecidos}"
        )

    ordem = [int(r) for r in rotulos]
    nomes = dict(nomes or {})

    precisao, recall, f1, suporte = precision_recall_fscore_support(
        verdadeiro, previsto, labels=ordem, zero_division=0
    )
    por_classe = [
        MetricasClasse(
            rotulo=rotulo,
            nome=nomes.get(rotulo, str(rotulo)),
            precisao=float(precisao[i]),
            recall=float(recall[i]),
            f1=float(f1[i]),
            suporte=int(suporte[i]),
        )
        for i, rotulo in enumerate(ordem)
    ]

    return Metricas(
        acuracia=float(accuracy_score(verdadeiro, previsto)),
        por_classe=por_classe,
        macro=_media(verdadeiro, previsto, ordem, "macro"),
        ponderada=_media(verdadeiro, previsto, ordem, "weighted"),
        matriz_confusao=confusion_matrix(verdadeiro, previsto, labels=ordem).tolist(),
        rotulos=ordem,
        n_amostras=int(len(verdadeiro)),
    )


def _media(
    y_true: np.ndarray, y_pred: np.ndarray, rotulos: List[int], average: str
) -> Media:
    precisao, recall, f1, _ = precision_recall_fscore_support(
        y_true, y_pred, labels=rotulos, average=average, zero_division=0
    )
    return Media(precisao=float(precisao), recall=float(recall), f1=float(f1))


def avalia_meta(metricas: Metricas, meta: float = META_PRECISAO) -> AvaliacaoMeta:
    """Compara a precisão obtida com a meta da ticket, pelo critério macro."""
    return AvaliacaoMeta(
        meta=meta,
        precisao_macro=metricas.macro.precisao,
        precisao_ponderada=metricas.ponderada.precisao,
        atingida=bool(metricas.macro.precisao > meta),
        criterio="precisão macro no split Test",
    )


# --- renderização ----------------------------------------------------------


def relatorio_markdown(resultado: "ResultadoTreino", top_features: int = 10) -> str:
    """Relatório completo em Markdown, pronto para virar arquivo versionado."""
    p = resultado.parametros
    metricas_meta = resultado.metricas[SPLIT_META]
    avaliacao = avalia_meta(metricas_meta)

    linhas: List[str] = [
        "# Relatório do Random Forest baseline (ticket 2)",
        "",
        f"Alvo: **{p.alvo}** — modo **{p.modo}**"
        + (f", corte em `>= {p.corte}`" if p.corte is not None else "")
        + ".",
        "",
        "## Parâmetros",
        "",
        "| Parâmetro | Valor |",
        "| --- | --- |",
        f"| `alvo` | {p.alvo} |",
        f"| `modo` | {p.modo} |",
        f"| `corte` | {p.corte if p.corte is not None else '—'} |",
        f"| `random_state` | {p.random_state} |",
        f"| `n_estimators` | {p.n_estimators} |",
        f"| `class_weight` | {p.class_weight} |",
        f"| imputação de NaN | `SimpleImputer(strategy=\"{p.estrategia_nan}\")` dentro do pipeline |",
        f"| features | {len(resultado.colunas)} colunas de `esquema.colunas_features()` |",
        f"| scikit-learn | {resultado.versao_sklearn} |",
        "",
        "`random_state` fixo em todas as etapas: duas execuções sobre o mesmo dataset"
        " produzem exatamente o mesmo modelo e o mesmo relatório.",
        "",
        "## Split",
        "",
        "O split é o **do próprio DAiSEE** (`Train`/`Validation`/`Test`, lido da coluna"
        " `split`), e não um `train_test_split` aleatório. O particionamento do dataset é"
        " *subject-independent*: um mesmo `user_id` nunca aparece em dois splits. Um split"
        " aleatório colocaria clipes do mesmo sujeito nos dois lados, e o modelo passaria a"
        " reconhecer o rosto em vez do engajamento — a métrica subiria sem o modelo ter"
        " melhorado. `treino.verifica_independencia_de_sujeito` falha alto se essa"
        " propriedade for violada.",
        "",
        "| Split | Amostras |",
        "| --- | --- |",
    ]
    for split, metricas in resultado.metricas.items():
        linhas.append(f"| {split} | {metricas.n_amostras} |")

    linhas += ["", "## Distribuição de classes", "", _tabela_distribuicao(resultado), ""]
    linhas += [
        "Classes desbalanceadas são a regra no DAiSEE — por isso"
        f" `class_weight=\"{p.class_weight}\"` na floresta, e por isso as métricas abaixo"
        " aparecem por classe e em macro-average, não só agregadas.",
        "",
        "## Métricas por split",
        "",
    ]
    for split, metricas in resultado.metricas.items():
        linhas += [f"### {split}", "", _tabela_metricas(metricas), ""]

    linhas += ["## Matriz de confusão", ""]
    for split, metricas in resultado.metricas.items():
        linhas += [
            f"### {split}",
            "",
            "Linhas: rótulo verdadeiro. Colunas: rótulo previsto.",
            "",
            _tabela_confusao(metricas, resultado.nomes_rotulos),
            "",
        ]

    linhas += [
        "## Importância das features",
        "",
        f"As {top_features} features de maior importância (impureza média) na floresta:",
        "",
        "| Feature | Importância |",
        "| --- | --- |",
    ]
    for feature, importancia in list(resultado.importancias.items())[:top_features]:
        linhas.append(f"| `{feature}` | {importancia:.4f} |")

    linhas += [
        "",
        "## Meta de precisão",
        "",
        f"A ticket 2 pede precisão acima de **{avaliacao.meta:.0%}**. O número comparado é a"
        f" **{avaliacao.criterio}**: com ~{_prop_majoritaria(metricas_meta):.0%} das amostras"
        " na classe majoritária, a precisão ponderada (e a acurácia) sobem quase de graça,"
        " enquanto a macro só passa da meta se a classe minoritária também for acertada.",
        "",
        "| Medida | Valor |",
        "| --- | --- |",
        f"| Precisão macro ({SPLIT_META}) | {avaliacao.precisao_macro:.4f} |",
        f"| Precisão ponderada ({SPLIT_META}) | {avaliacao.precisao_ponderada:.4f} |",
        f"| Acurácia ({SPLIT_META}) | {metricas_meta.acuracia:.4f} |",
        f"| Meta | {avaliacao.meta:.2f} |",
        "",
        f"- **Meta atingida:** {'sim' if avaliacao.atingida else 'não'}",
        "",
    ]
    if not avaliacao.atingida:
        linhas += [
            "Desvio em relação à meta. Leituras possíveis, em ordem de custo:"
            " (a) o alvo multiclasse 0–3 é mais difícil que o binário — verifique se o modo"
            " usado foi `binario`; (b) as features agregadas por clipe podem estar apagando"
            " o sinal temporal (pálpebra fechada prolongada, bocejo), que é justamente o que"
            " a ticket 8 vai explorar em sequência; (c) o desbalanceamento pode exigir mais"
            " que `class_weight` — reamostragem ou ajuste do limiar de decisão.",
            "",
        ]

    return "\n".join(linhas)


def _prop_majoritaria(metricas: Metricas) -> float:
    if metricas.n_amostras == 0:
        return 0.0
    return max((c.suporte for c in metricas.por_classe), default=0) / metricas.n_amostras


def _tabela_distribuicao(resultado: "ResultadoTreino") -> str:
    nomes = [_nome(resultado.nomes_rotulos, r) for r in resultado.rotulos]
    linhas = ["| Split | " + " | ".join(nomes) + " | Total |", "| --- |" + " --- |" * (len(nomes) + 1)]
    for split, contagens in resultado.distribuicao.items():
        valores = [contagens.get(rotulo, 0) for rotulo in resultado.rotulos]
        linhas.append(
            f"| {split} | " + " | ".join(str(v) for v in valores) + f" | {sum(valores)} |"
        )
    return "\n".join(linhas)


def _tabela_metricas(metricas: Metricas) -> str:
    linhas = [
        "| Classe | Precisão | Recall | F1 | Suporte |",
        "| --- | --- | --- | --- | --- |",
    ]
    for classe in metricas.por_classe:
        linhas.append(
            f"| {classe.nome} ({classe.rotulo}) | {classe.precisao:.4f} |"
            f" {classe.recall:.4f} | {classe.f1:.4f} | {classe.suporte} |"
        )
    linhas += [
        f"| **macro** | {metricas.macro.precisao:.4f} | {metricas.macro.recall:.4f} |"
        f" {metricas.macro.f1:.4f} | {metricas.n_amostras} |",
        f"| **ponderada** | {metricas.ponderada.precisao:.4f} |"
        f" {metricas.ponderada.recall:.4f} | {metricas.ponderada.f1:.4f} |"
        f" {metricas.n_amostras} |",
        "",
        f"Acurácia: **{metricas.acuracia:.4f}** em {metricas.n_amostras} amostras.",
    ]
    return "\n".join(linhas)


def _tabela_confusao(metricas: Metricas, nomes: Mapping[int, str]) -> str:
    cabecalho = [_nome(nomes, r) for r in metricas.rotulos]
    linhas = [
        "| verdadeiro \\ previsto | " + " | ".join(cabecalho) + " |",
        "| --- |" + " --- |" * len(cabecalho),
    ]
    for rotulo, linha in zip(metricas.rotulos, metricas.matriz_confusao):
        linhas.append(f"| **{_nome(nomes, rotulo)}** | " + " | ".join(str(v) for v in linha) + " |")
    return "\n".join(linhas)


def _nome(nomes: Mapping[int, str], rotulo: int) -> str:
    return nomes.get(rotulo, str(rotulo))


# --- json ------------------------------------------------------------------


def metricas_para_dict(metricas: Metricas) -> Dict[str, object]:
    return {
        "acuracia": round(metricas.acuracia, CASAS),
        "n_amostras": metricas.n_amostras,
        "rotulos": metricas.rotulos,
        "por_classe": [
            {
                "rotulo": c.rotulo,
                "nome": c.nome,
                "precisao": round(c.precisao, CASAS),
                "recall": round(c.recall, CASAS),
                "f1": round(c.f1, CASAS),
                "suporte": c.suporte,
            }
            for c in metricas.por_classe
        ],
        "macro": _media_para_dict(metricas.macro),
        "ponderada": _media_para_dict(metricas.ponderada),
        "matriz_confusao": metricas.matriz_confusao,
    }


def _media_para_dict(media: Media) -> Dict[str, float]:
    return {
        "precisao": round(media.precisao, CASAS),
        "recall": round(media.recall, CASAS),
        "f1": round(media.f1, CASAS),
    }


def resultado_para_dict(resultado: "ResultadoTreino") -> Dict[str, object]:
    """Forma serializável do resultado — só tipos nativos, para o JSON diffar limpo."""
    p = resultado.parametros
    avaliacao = avalia_meta(resultado.metricas[SPLIT_META])

    return {
        "parametros": {
            "alvo": p.alvo,
            "modo": p.modo,
            "corte": p.corte,
            "random_state": p.random_state,
            "n_estimators": p.n_estimators,
            "class_weight": p.class_weight,
            "estrategia_nan": p.estrategia_nan,
        },
        "versao_sklearn": resultado.versao_sklearn,
        "colunas": list(resultado.colunas),
        "rotulos": list(resultado.rotulos),
        "nomes_rotulos": {str(k): v for k, v in resultado.nomes_rotulos.items()},
        "distribuicao": {
            split: {str(rotulo): int(n) for rotulo, n in contagens.items()}
            for split, contagens in resultado.distribuicao.items()
        },
        "metricas": {
            split: metricas_para_dict(metricas) for split, metricas in resultado.metricas.items()
        },
        "importancias": {
            feature: round(float(valor), CASAS)
            for feature, valor in resultado.importancias.items()
        },
        "meta": {
            "meta": avaliacao.meta,
            "criterio": avaliacao.criterio,
            "split": SPLIT_META,
            "precisao_macro": round(avaliacao.precisao_macro, CASAS),
            "precisao_ponderada": round(avaliacao.precisao_ponderada, CASAS),
            "atingida": avaliacao.atingida,
        },
    }


def relatorio_json(resultado: "ResultadoTreino", indent: int = 2) -> str:
    """Métricas em JSON, estáveis o bastante para `diff` entre execuções."""
    return json.dumps(resultado_para_dict(resultado), indent=indent, ensure_ascii=False)
