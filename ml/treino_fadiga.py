"""Treino e validação do classificador de sonolência (UTA-RLDD).

Irmão de `treino.py`, que treina engajamento no DAiSEE. Os dois consomem as
**mesmas 39 features** e compartilham as métricas de `relatorio.py`; o que muda
é o alvo e o desenho da avaliação.

**Por que um módulo novo em vez de um parâmetro no antigo.** O `treino.py` está
amarrado ao desenho do DAiSEE em três pontos que não são opcionais lá: o split
vem de uma coluna `split` com três valores fixos, o alvo é um de quatro rótulos
0–3, e a independência de sujeito é verificada contra `user_id`. Aqui o split é
validação cruzada por fold, o alvo tem três níveis com espaçamento próprio
(0/5/10) e a unidade de independência é o participante. Encaixar os dois no
mesmo código produziria uma função cheia de `if dataset ==`, e o `treino.py` já
está em produção — mexer nele arrisca o que já funciona sem ganhar nada.

**A avaliação é leave-one-fold-out, com os folds dos autores.** O UTA-RLDD vem
distribuído em cinco grupos de doze participantes, disjuntos por construção.
Treinar em quatro e testar no quinto, cinco vezes, dá cinco medidas
independentes em vez de uma — e com 60 participantes a variação entre folds é
informação, não ruído a esconder atrás de uma média. Sortear nossos próprios
splits jogaria fora a comparabilidade com a literatura e abriria a porta para o
mesmo participante cair nos dois lados.

**Normalização por sessão: é aqui que o offline encontra o produto.** A trilha
do DAiSEE descobriu que o único ganho real vinha de subtrair de cada feature a
mediana da própria pessoa — a floresta estava aprendendo "este é o fulano" antes
de "fulano está sonolento". A aplicação já faz exatamente isso ao vivo: a
calibração de 60 segundos da ticket 7. Então a normalização aqui replica o
produto em vez de inventar um pré-processamento que não teria como existir em
produção: a mediana vem das **primeiras janelas de cada gravação**, e não do
participante inteiro.

A diferença importa. Normalizar pelo participante inteiro usaria as três
gravações dele — inclusive a sonolenta — para calibrar o que é "normal" naquela
pessoa; em produção não existe o futuro da sessão. Normalizar pelo começo da
própria gravação usa só o passado, que é o que o navegador tem. O preço está
escrito: se a pessoa já começa sonolenta, a baseline é de uma pessoa sonolenta.
É verdade no dataset e é verdade no produto — um aluno que senta exausto calibra
exausto —, então a limitação é a mesma nos dois lados, o que é o melhor que se
pode pedir de uma avaliação offline.
"""
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import (
    ExtraTreesClassifier,
    HistGradientBoostingClassifier,
    RandomForestClassifier,
)
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import balanced_accuracy_score, f1_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from esquema import colunas_features
from esquema_rldd import (
    ALERTA,
    COLUNA_FOLD,
    COLUNA_INDICE_JANELA,
    COLUNA_JANELA,
    COLUNA_PARTE,
    COLUNA_PARTICIPANTE,
    COLUNA_SONOLENCIA,
    SONOLENTO,
    VIGILANCIA_BAIXA,
    valida_janelas,
)
from relatorio import Metricas, calcula_metricas

RANDOM_STATE = 42

# --- Alvos -----------------------------------------------------------------

#: Sonolento (10) contra alerta (0), descartando a vigilância baixa (5).
#: É o alvo principal, e o corte é do próprio dataset: os autores tratam o 5
#: como estado intermediário justamente por ele não ter fronteira nítida com
#: nenhum dos dois. É também o alvo mais usado na literatura sobre o RLDD, o
#: que torna o número comparável.
ALVO_BINARIO = "binario"

#: Sonolento **ou** vigilância baixa (10 e 5) contra alerta (0). Mais próximo do
#: uso no produto — o que o IEE quer penalizar é "deixou de estar alerta", não
#: "está dormindo" — e mais difícil, porque joga a fronteira para dentro do
#: estado ambíguo.
ALVO_BINARIO_AMPLO = "binario_amplo"

#: Os três níveis como o dataset os declara.
ALVO_TERNARIO = "ternario"

ALVOS_VALIDOS = (ALVO_BINARIO, ALVO_BINARIO_AMPLO, ALVO_TERNARIO)

NOMES_BINARIO: Dict[int, str] = {0: "alerta", 1: "sonolento"}
NOMES_BINARIO_AMPLO: Dict[int, str] = {0: "alerta", 1: "alerta_reduzido"}
NOMES_TERNARIO: Dict[int, str] = {0: "alerta", 1: "vigilancia_baixa", 2: "sonolento"}

# --- Normalização ----------------------------------------------------------

#: Nenhuma: as features entram em valor absoluto, como saíram do extrator.
SEM_NORMALIZACAO = "nenhuma"

#: Mediana das primeiras janelas de **cada gravação** — o análogo exato da
#: calibração de 60 segundos que a aplicação faz no início de cada sessão.
NORMALIZACAO_SESSAO = "sessao"

#: Mediana de **todas** as janelas do participante. Usa o futuro da sessão e por
#: isso não é reproduzível em produção; fica como teto de comparação, para medir
#: quanto a versão honesta deixa na mesa.
NORMALIZACAO_PARTICIPANTE = "participante"

NORMALIZACOES_VALIDAS = (SEM_NORMALIZACAO, NORMALIZACAO_SESSAO, NORMALIZACAO_PARTICIPANTE)

#: Quantas janelas do início de cada gravação formam a baseline. Seis janelas de
#: 10s são os mesmos 60 segundos de `analista.DURACAO_CALIBRACAO`.
JANELAS_DE_CALIBRACAO = 6


class TreinoInvalido(Exception):
    """Base das recusas — nenhuma deve chegar como `KeyError` ou `IndexError`."""


class VazamentoDeParticipante(TreinoInvalido):
    """Um participante aparece no treino e no teste: a avaliação está contaminada."""


class AlvoInvalido(TreinoInvalido):
    """Alvo fora de `ALVOS_VALIDOS`, ou sem as duas classes no recorte pedido."""


# --- Preparação do alvo ----------------------------------------------------


def rotula(janelas: pd.DataFrame, alvo: str) -> Tuple[pd.DataFrame, pd.Series, Dict[int, str]]:
    """Recorta as linhas do alvo e devolve `(janelas, y, nomes_das_classes)`.

    O recorte faz parte do alvo: `ALVO_BINARIO` **descarta** as gravações de
    vigilância baixa em vez de encaixá-las num dos lados. Empurrá-las para
    "alerta" ou para "sonolento" seria decidir por dentro do código uma questão
    que o dataset deixou aberta de propósito, e o efeito apareceria como métrica
    pior sem explicação visível.
    """
    if alvo not in ALVOS_VALIDOS:
        raise AlvoInvalido(f"alvo desconhecido: {alvo!r} (esperado um de {list(ALVOS_VALIDOS)})")

    niveis = janelas[COLUNA_SONOLENCIA]

    if alvo == ALVO_BINARIO:
        recorte = janelas[niveis.isin([ALERTA, SONOLENTO])].copy()
        y = (recorte[COLUNA_SONOLENCIA] == SONOLENTO).astype(int)
        nomes = NOMES_BINARIO
    elif alvo == ALVO_BINARIO_AMPLO:
        recorte = janelas.copy()
        y = (recorte[COLUNA_SONOLENCIA] != ALERTA).astype(int)
        nomes = NOMES_BINARIO_AMPLO
    else:
        recorte = janelas.copy()
        escala = {ALERTA: 0, VIGILANCIA_BAIXA: 1, SONOLENTO: 2}
        y = recorte[COLUNA_SONOLENCIA].map(escala).astype(int)
        nomes = NOMES_TERNARIO

    if y.nunique() < 2:
        raise AlvoInvalido(f"alvo {alvo!r} deixou uma classe só no recorte")

    return recorte.reset_index(drop=True), y.reset_index(drop=True), nomes


# --- Normalização ----------------------------------------------------------


def _chave_da_gravacao(janelas: pd.DataFrame) -> pd.Series:
    """Participante + estado + parte: identifica uma gravação, que é a sessão."""
    return (
        janelas[COLUNA_PARTICIPANTE].astype(str)
        + "-"
        + janelas[COLUNA_SONOLENCIA].astype(str)
        + "-"
        + janelas[COLUNA_PARTE].astype(str)
    )


def normaliza(janelas: pd.DataFrame, modo: str) -> pd.DataFrame:
    """Subtrai de cada feature a mediana da baseline, conforme o modo.

    Nenhum rótulo entra no cálculo em nenhum dos modos — é o que mantém a
    operação legítima mesmo sendo feita sobre o dataset inteiro antes do split.
    O que distingue os modos é **de onde** vem a mediana, e a diferença é sobre
    reprodutibilidade em produção, não sobre vazamento.
    """
    if modo not in NORMALIZACOES_VALIDAS:
        raise TreinoInvalido(
            f"normalização desconhecida: {modo!r} (esperado uma de {list(NORMALIZACOES_VALIDAS)})"
        )
    if modo == SEM_NORMALIZACAO:
        return janelas.copy()

    features = colunas_features()
    saida = janelas.copy()

    if modo == NORMALIZACAO_PARTICIPANTE:
        base = saida.groupby(COLUNA_PARTICIPANTE)[features].transform("median")
    else:
        chave = _chave_da_gravacao(saida)
        inicio = saida[COLUNA_INDICE_JANELA] < JANELAS_DE_CALIBRACAO
        medianas = saida[inicio].groupby(chave[inicio])[features].median()
        # `reindex` em vez de `join`: uma gravação curta demais para ter as seis
        # janelas de calibração sai com mediana NaN, e subtrair NaN apaga a
        # linha inteira. Sem baseline não há o que normalizar, e a linha precisa
        # cair fora com barulho — ver `descarta_sem_baseline`.
        base = medianas.reindex(chave).set_index(saida.index)

    saida[features] = saida[features] - base
    return saida


def descarta_sem_baseline(janelas: pd.DataFrame) -> pd.DataFrame:
    """Remove as linhas que a normalização deixou totalmente em NaN.

    Só acontece com gravação curta demais para as seis janelas de calibração —
    o que no material real não ocorre, já que toda gravação passa de dez
    minutos. Existe para o caso não passar em silêncio se um dia ocorrer.
    """
    features = colunas_features()
    return janelas[~janelas[features].isna().all(axis=1)].reset_index(drop=True)


# --- Modelos ---------------------------------------------------------------


def _com_imputacao(estimador, escalona: bool = False) -> Pipeline:
    """Envolve o estimador na imputação (e no escalonamento, quando precisa).

    A imputação fica **dentro** do pipeline para a mediana ser aprendida só no
    treino de cada fold. Calculá-la fora, no dataset inteiro, faria a estatística
    do teste entrar no treino — vazamento silencioso, que sobe a métrica sem
    melhorar o modelo.
    """
    passos = [("imputacao", SimpleImputer(strategy="median", keep_empty_features=True))]
    if escalona:
        passos.append(("escala", StandardScaler()))
    passos.append(("modelo", estimador))
    return Pipeline(passos)


def catalogo_de_modelos() -> Dict[str, Callable[[], Pipeline]]:
    """Os modelos comparados, do chão de referência para cima.

    O `chute_majoritario` não é enfeite: no DAiSEE foi ele que revelou que a
    floresta baseline não fazia nada — 0,4753 de precisão macro nos dois. Aqui
    as classes são equilibradas por construção (cada participante gravou os três
    estados), então o chão fica em 0,50 de acurácia balanceada, e qualquer
    modelo que não o supere com folga está dizendo que o sinal não existe.
    """
    return {
        "chute_majoritario": lambda: _com_imputacao(
            DummyClassifier(strategy="most_frequent")
        ),
        "regressao_logistica": lambda: _com_imputacao(
            LogisticRegression(max_iter=2000, class_weight="balanced", random_state=RANDOM_STATE),
            escalona=True,
        ),
        "floresta_baseline": lambda: _com_imputacao(
            RandomForestClassifier(
                n_estimators=300, class_weight="balanced", random_state=RANDOM_STATE, n_jobs=-1
            )
        ),
        "floresta_regularizada": lambda: _com_imputacao(
            RandomForestClassifier(
                n_estimators=300,
                max_depth=10,
                min_samples_leaf=20,
                max_features="sqrt",
                class_weight="balanced",
                random_state=RANDOM_STATE,
                n_jobs=-1,
            )
        ),
        "arvores_extremamente_aleatorias": lambda: _com_imputacao(
            ExtraTreesClassifier(
                n_estimators=300,
                max_depth=12,
                min_samples_leaf=10,
                class_weight="balanced",
                random_state=RANDOM_STATE,
                n_jobs=-1,
            )
        ),
        "gradiente_histograma": lambda: _com_imputacao(
            HistGradientBoostingClassifier(
                max_depth=6, learning_rate=0.1, random_state=RANDOM_STATE
            )
        ),
    }


# --- Avaliação -------------------------------------------------------------


@dataclass(frozen=True)
class ResultadoDoFold:
    """O que se sabe depois de treinar em quatro folds e testar no quinto."""

    fold: int
    n_treino: int
    n_teste: int
    acuracia_balanceada: float
    f1_macro: float
    metricas: Metricas


@dataclass
class ResultadoDaValidacao:
    """A validação cruzada inteira, com os folds preservados individualmente.

    A média sozinha esconde o que mais interessa num dataset de 60 pessoas: se
    um fold vai a 0,80 e outro a 0,55, o desvio entre eles é o intervalo de
    confiança honesto do número, e reportar só a média afirmaria uma precisão
    que a medição não tem.
    """

    modelo: str
    alvo: str
    normalizacao: str
    folds: List[ResultadoDoFold] = field(default_factory=list)

    @property
    def acuracia_balanceada_media(self) -> float:
        return float(np.mean([f.acuracia_balanceada for f in self.folds]))

    @property
    def acuracia_balanceada_desvio(self) -> float:
        return float(np.std([f.acuracia_balanceada for f in self.folds]))

    @property
    def f1_macro_medio(self) -> float:
        return float(np.mean([f.f1_macro for f in self.folds]))

    @property
    def piores_folds(self) -> List[int]:
        ordem = sorted(self.folds, key=lambda f: f.acuracia_balanceada)
        return [f.fold for f in ordem[:2]]


def verifica_independencia(treino: pd.DataFrame, teste: pd.DataFrame) -> None:
    """Falha alto se um participante aparecer dos dois lados.

    O sintoma do vazamento é uma métrica **boa**, e métrica boa ninguém
    investiga. Por isso a checagem é uma exceção e não um aviso.
    """
    comuns = set(treino[COLUNA_PARTICIPANTE]) & set(teste[COLUNA_PARTICIPANTE])
    if comuns:
        raise VazamentoDeParticipante(
            f"participantes nos dois lados do split: {sorted(comuns)[:5]}"
        )


def valida_cruzado(
    janelas: pd.DataFrame,
    construtor: Callable[[], Pipeline],
    nome_do_modelo: str,
    alvo: str = ALVO_BINARIO,
    normalizacao: str = NORMALIZACAO_SESSAO,
    folds: Optional[Sequence[int]] = None,
) -> ResultadoDaValidacao:
    """Leave-one-fold-out sobre os folds oficiais do dataset."""
    valida_janelas(janelas)

    preparado = descarta_sem_baseline(normaliza(janelas, normalizacao))
    recorte, y, nomes = rotula(preparado, alvo)
    features = colunas_features()
    rotulos = sorted(y.unique())

    resultado = ResultadoDaValidacao(
        modelo=nome_do_modelo, alvo=alvo, normalizacao=normalizacao
    )

    for fold in folds or sorted(recorte[COLUNA_FOLD].unique()):
        e_teste = recorte[COLUNA_FOLD] == fold
        treino, teste = recorte[~e_teste], recorte[e_teste]
        if teste.empty or treino.empty:
            continue
        verifica_independencia(treino, teste)

        pipeline = construtor()
        pipeline.fit(treino[features], y[~e_teste])
        previsto = pipeline.predict(teste[features])

        verdadeiro = y[e_teste]
        resultado.folds.append(
            ResultadoDoFold(
                fold=int(fold),
                n_treino=len(treino),
                n_teste=len(teste),
                acuracia_balanceada=float(balanced_accuracy_score(verdadeiro, previsto)),
                f1_macro=float(f1_score(verdadeiro, previsto, average="macro", zero_division=0)),
                metricas=calcula_metricas(verdadeiro, previsto, rotulos, nomes),
            )
        )

    if not resultado.folds:
        raise TreinoInvalido("nenhum fold avaliável no dataset recebido")
    return resultado


def treina_final(
    janelas: pd.DataFrame,
    construtor: Callable[[], Pipeline],
    alvo: str = ALVO_BINARIO,
    normalizacao: str = NORMALIZACAO_SESSAO,
) -> Tuple[Pipeline, pd.DataFrame, pd.Series]:
    """Treina no dataset inteiro, para o artefato que vai para produção.

    A validação cruzada acima é quem **mede**; esta função é quem **entrega**.
    São passos separados de propósito: o número que se reporta tem de vir de
    dados que o modelo entregue nunca viu, e o modelo entregue deve usar tudo o
    que existe. Reportar a métrica deste treino seria medir no treino.
    """
    preparado = descarta_sem_baseline(normaliza(janelas, normalizacao))
    recorte, y, _ = rotula(preparado, alvo)
    features = colunas_features()

    pipeline = construtor()
    pipeline.fit(recorte[features], y)
    return pipeline, recorte, y


def importancias(pipeline: Pipeline, features: Optional[List[str]] = None) -> Dict[str, float]:
    """Importância por feature, quando o estimador final oferece uma.

    Modelo sem `feature_importances_` (a regressão logística, o chute) devolve
    dicionário vazio em vez de erro: a comparação entre modelos não pode
    depender de todos exporem a mesma introspecção.
    """
    features = features or colunas_features()
    modelo = pipeline.named_steps.get("modelo")
    valores = getattr(modelo, "feature_importances_", None)
    if valores is None:
        return {}
    return dict(
        sorted(
            ((nome, float(v)) for nome, v in zip(features, valores)),
            key=lambda par: par[1],
            reverse=True,
        )
    )
