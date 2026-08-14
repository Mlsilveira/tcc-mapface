"""Treino e validação do Random Forest baseline (ticket 2).

Recebe o dataset por clipe da ticket 1 (contrato em `esquema.py`) e devolve um
`ResultadoTreino`: o estimador treinado, as métricas de cada split, a
importância das features e os parâmetros usados. Nada é impresso aqui — quem
formata é `relatorio.py`, quem imprime seria um CLI.

**O split é o do DAiSEE, não um `train_test_split` aleatório.** O dataset já vem
particionado em `Train`/`Validation`/`Test` e o particionamento é
*subject-independent*: um mesmo `user_id` nunca aparece em dois splits. Sortear
as linhas de novo colocaria clipes do mesmo sujeito nos dois lados da avaliação,
e a floresta aprenderia a reconhecer o rosto — a acurácia subiria sem que o
modelo tivesse melhorado em nada. `verifica_independencia_de_sujeito` checa essa
propriedade e falha alto se ela for violada, porque o sintoma do vazamento é uma
métrica *boa*, e métrica boa ninguém investiga.

**Alvo.** O DAiSEE rotula quatro dimensões em quatro níveis (0–3). O alvo
primário desta PoC é `engagement`, em dois modos:

- `MODO_MULTICLASSE` — os quatro níveis originais, útil para inspecionar onde o
  modelo confunde o quê;
- `MODO_BINARIO` (padrão) — engajado vs. não engajado, com corte em
  `engagement >= 2`.

O binário é o modo defensável para o critério "precisão > 80%" da ticket por
dois motivos. Primeiro, os níveis 0 e 1 juntos não chegam a 5% dos clipes: no
multiclasse a floresta praticamente não vê exemplos deles, e as métricas por
classe ficam instáveis a ponto de não sustentarem afirmação nenhuma. Segundo, é
o binário que corresponde ao uso real — a ticket 8 quer saber *se* há queda de
engajamento para penalizar o IEE, não em qual dos quatro degraus o aluno está.
O corte é parâmetro (`corte`), e não constante escondida, porque ele é uma
decisão de produto: `corte=3` significa exigir engajamento "muito alto".

**Acurácia engana neste dataset.** Com ~85% dos clipes engajados, responder
"engajado" para tudo já dá ~85% de acurácia. Por isso `class_weight="balanced"`
na floresta e por isso `relatorio.py` reporta tudo por classe e em macro-average.

**NaN.** O extrator produz NaN nas features de clipes em que nenhum rosto foi
detectado (e em `*_desvio` de clipes de um frame só). Descartar esses clipes
seria o pior negócio possível — clipe sem rosto detectado é justamente o clipe do
aluno que saiu da frente da câmera, o caso mais informativo de desengajamento; o
modelo ficaria cego para ele. Então eles ficam, e as features ausentes passam por
um `SimpleImputer` de mediana **do treino**, dentro do `Pipeline` para a mediana
ser aprendida só no `Train` e não vazar. `keep_empty_features=True` impede que
uma coluna inteiramente NaN no treino seja removida.

Uma ressalva que vale para quem for mexer nisto: **a imputação não é obrigatória
nesta versão**. Desde o scikit-learn 1.4 os modelos baseados em árvore tratam
valores ausentes nativamente, e o `RandomForestClassifier` da 1.5.2 fixada no
`requirements.txt` treina e prevê com NaN sem imputador nenhum — verificado. Há
inclusive um argumento de que o tratamento nativo seria *melhor* aqui: a árvore
aprende para que lado mandar a amostra ausente, enquanto a mediana finge que o
clipe teve EAR típico, que é exatamente o sinal que se queria preservar. O que
segura a decisão em pé hoje é robustez, não necessidade: com o imputador o
artefato continua funcionando se alguém trocar a floresta por um classificador
que não tolere NaN. Trocar de estratégia muda o modelo treinado, então é decisão
de quem tocar a ticket 2, não mudança silenciosa.
"""
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Union

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline

from esquema import (
    COLUNA_SPLIT,
    COLUNA_USUARIO,
    COLUNAS_ROTULOS,
    NIVEIS_ROTULO,
    SPLITS_VALIDOS,
    EsquemaInvalido,
    colunas_features,
    valida_clipes,
)
from relatorio import Metricas, calcula_metricas

MODO_BINARIO = "binario"
MODO_MULTICLASSE = "multiclasse"
MODOS_VALIDOS = (MODO_BINARIO, MODO_MULTICLASSE)

#: Corte padrão da binarização: níveis 2 e 3 do DAiSEE são "high"/"very high"
#: engagement, 0 e 1 são "very low"/"low". A fronteira do dataset é essa.
CORTE_BINARIO_PADRAO = 2

RANDOM_STATE_PADRAO = 42
N_ESTIMATORS_PADRAO = 300

NOMES_BINARIOS: Dict[int, str] = {0: "nao_engajado", 1: "engajado"}
NOMES_MULTICLASSE: Dict[int, str] = {
    0: "muito_baixo",
    1: "baixo",
    2: "alto",
    3: "muito_alto",
}

PASSO_IMPUTACAO = "imputacao"
PASSO_FLORESTA = "floresta"


class TreinoInvalido(Exception):
    """Base das recusas do treino — nenhuma delas deve chegar como `KeyError`."""


class VazamentoDeSujeito(TreinoInvalido):
    """Um mesmo `user_id` aparece em mais de um split: a avaliação está contaminada."""


class SplitAusente(TreinoInvalido):
    """Falta um dos splits do contrato — sem ele não há como treinar ou avaliar."""


class SplitInvalido(TreinoInvalido):
    """A coluna `split` tem valor fora de `SPLITS_VALIDOS`."""


class ClasseUnica(TreinoInvalido):
    """O treino ficou com uma classe só — não há o que classificar."""


class AlvoInvalido(TreinoInvalido):
    """O alvo pedido não é um rótulo do DAiSEE, ou tem nível fora de 0–3."""


class ModoInvalido(TreinoInvalido):
    """Modo de alvo desconhecido."""


class CorteInvalido(TreinoInvalido):
    """O corte da binarização deixaria uma das classes vazia por construção."""


class ArtefatoInvalido(Exception):
    """O `.joblib` não é um artefato desta ticket."""


class VersaoSklearnDiferente(UserWarning):
    """O modelo foi treinado com outra versão do scikit-learn."""


@dataclass(frozen=True)
class ParametrosTreino:
    """Tudo que é preciso saber para reproduzir um treino."""

    alvo: str
    modo: str
    corte: Optional[int]
    random_state: int
    n_estimators: int
    class_weight: str
    estrategia_nan: str


@dataclass(frozen=True)
class ResultadoTreino:
    """O modelo treinado e o que se descobriu sobre ele."""

    estimador: Pipeline
    parametros: ParametrosTreino
    metricas: Dict[str, Metricas]
    importancias: Dict[str, float]
    distribuicao: Dict[str, Dict[int, int]]
    colunas: List[str]
    rotulos: List[int]
    nomes_rotulos: Dict[int, str]
    versao_sklearn: str


@dataclass(frozen=True)
class ModeloSalvo:
    """Um artefato carregado do disco, com o contexto necessário para usá-lo.

    O backend (ticket 8) recebe isto, e não o estimador nu: sem a ordem das
    features um `DataFrame` com as mesmas colunas em outra ordem produz predições
    silenciosamente erradas.
    """

    estimador: Pipeline
    colunas: List[str]
    rotulos: List[int]
    nomes_rotulos: Dict[int, str]
    parametros: ParametrosTreino
    versao_sklearn: str

    def _matriz(self, clipes: pd.DataFrame) -> pd.DataFrame:
        faltando = [c for c in self.colunas if c not in clipes.columns]
        if faltando:
            raise EsquemaInvalido(f"features faltando para predizer: {faltando}")
        return clipes[self.colunas]

    def preve(self, clipes: pd.DataFrame) -> np.ndarray:
        """Prediz reordenando as colunas para a ordem com que o modelo treinou."""
        return self.estimador.predict(self._matriz(clipes))

    def preve_probabilidades(self, clipes: pd.DataFrame) -> np.ndarray:
        """Probabilidade por rótulo, na ordem de `rotulos`."""
        return self.estimador.predict_proba(self._matriz(clipes))


# --- verificações ----------------------------------------------------------


def verifica_independencia_de_sujeito(clipes: pd.DataFrame) -> None:
    """Falha se algum `user_id` aparecer em mais de um split.

    É a propriedade que sustenta a avaliação inteira. O DAiSEE já a garante pela
    organização em pastas; o que pode quebrá-la é alguém "melhorar" o pipeline
    com um `train_test_split` aleatório, ou concatenar splits na ordem errada.
    """
    por_usuario = clipes.groupby(COLUNA_USUARIO)[COLUNA_SPLIT].nunique()
    vazados = sorted(str(u) for u in por_usuario[por_usuario > 1].index)
    if vazados:
        raise VazamentoDeSujeito(
            "user_id em mais de um split (a avaliação mediria memorização de rosto,"
            f" não engajamento): {vazados[:10]}"
            + (f" e mais {len(vazados) - 10}" if len(vazados) > 10 else "")
        )


def _valida_splits(clipes: pd.DataFrame) -> None:
    presentes = set(clipes[COLUNA_SPLIT].unique())

    desconhecidos = sorted(str(s) for s in presentes - set(SPLITS_VALIDOS))
    if desconhecidos:
        raise SplitInvalido(
            f"valores fora de {list(SPLITS_VALIDOS)} na coluna {COLUNA_SPLIT!r}: {desconhecidos}"
        )

    faltando = [s for s in SPLITS_VALIDOS if s not in presentes]
    if faltando:
        raise SplitAusente(f"splits sem nenhuma linha: {faltando}")


def _valida_alvo(clipes: pd.DataFrame, alvo: str) -> None:
    if alvo not in COLUNAS_ROTULOS:
        raise AlvoInvalido(f"alvo desconhecido: {alvo!r} (esperado um de {COLUNAS_ROTULOS})")

    ausentes = int(clipes[alvo].isna().sum())
    if ausentes:
        # Clipe sem rótulo é falha de junção na ticket 1, não amostra a imputar:
        # inventar um rótulo é inventar a verdade contra a qual se mede o modelo.
        raise AlvoInvalido(f"{alvo}: {ausentes} clipe(s) sem rótulo")

    fora = sorted(set(clipes[alvo].astype(int)) - set(NIVEIS_ROTULO))
    if fora:
        raise AlvoInvalido(f"{alvo}: níveis fora de {list(NIVEIS_ROTULO)}: {fora}")


def _valida_modo(modo: str, corte: int) -> None:
    if modo not in MODOS_VALIDOS:
        raise ModoInvalido(f"modo desconhecido: {modo!r} (esperado um de {list(MODOS_VALIDOS)})")
    if modo == MODO_BINARIO and corte not in NIVEIS_ROTULO[1:]:
        raise CorteInvalido(
            f"corte {corte} deixaria uma das classes vazia; use um de {list(NIVEIS_ROTULO[1:])}"
        )


# --- treino ----------------------------------------------------------------


def binariza(niveis: pd.Series, corte: int = CORTE_BINARIO_PADRAO) -> pd.Series:
    """Converte os níveis 0–3 em 1 (engajado) se `nivel >= corte`, senão 0."""
    return (niveis.astype(int) >= corte).astype(int)


def monta_pipeline(
    random_state: int = RANDOM_STATE_PADRAO,
    n_estimators: int = N_ESTIMATORS_PADRAO,
    estrategia_nan: str = "median",
    class_weight: str = "balanced",
    n_jobs: Optional[int] = None,
) -> Pipeline:
    """Imputação + floresta, num objeto só.

    O artefato serializado é este pipeline inteiro, e não o classificador: o
    backend não pode ser obrigado a saber com que mediana imputar.
    """
    return Pipeline(
        [
            (
                PASSO_IMPUTACAO,
                SimpleImputer(strategy=estrategia_nan, keep_empty_features=True),
            ),
            (
                PASSO_FLORESTA,
                RandomForestClassifier(
                    n_estimators=n_estimators,
                    class_weight=class_weight,
                    random_state=random_state,
                    n_jobs=n_jobs,
                ),
            ),
        ]
    )


def treina(
    clipes: pd.DataFrame,
    alvo: str = "engagement",
    modo: str = MODO_BINARIO,
    corte: int = CORTE_BINARIO_PADRAO,
    random_state: int = RANDOM_STATE_PADRAO,
    n_estimators: int = N_ESTIMATORS_PADRAO,
    estrategia_nan: str = "median",
    class_weight: str = "balanced",
    n_jobs: Optional[int] = None,
) -> ResultadoTreino:
    """Treina no `Train` do DAiSEE e avalia nos três splits.

    O `Train` também é avaliado, e de propósito: a diferença entre o desempenho
    nele e no `Test` é o que denuncia overfitting da floresta.
    """
    valida_clipes(clipes)
    _valida_splits(clipes)
    _valida_alvo(clipes, alvo)
    _valida_modo(modo, corte)
    verifica_independencia_de_sujeito(clipes)

    features = colunas_features()
    y = _alvo_transformado(clipes[alvo], modo, corte)
    rotulos = [0, 1] if modo == MODO_BINARIO else list(NIVEIS_ROTULO)
    nomes = NOMES_BINARIOS if modo == MODO_BINARIO else NOMES_MULTICLASSE

    partes = {split: (clipes[COLUNA_SPLIT] == split).to_numpy() for split in SPLITS_VALIDOS}
    y_treino = y[partes["Train"]]
    if y_treino.nunique() < 2:
        raise ClasseUnica(
            f"o split Train tem uma classe só ({sorted(y_treino.unique())}) para o alvo"
            f" {alvo!r} no modo {modo!r}"
        )

    pipeline = monta_pipeline(
        random_state=random_state,
        n_estimators=n_estimators,
        estrategia_nan=estrategia_nan,
        class_weight=class_weight,
        n_jobs=n_jobs,
    )
    pipeline.fit(clipes.loc[partes["Train"], features], y_treino)

    metricas: Dict[str, Metricas] = {}
    distribuicao: Dict[str, Dict[int, int]] = {}
    for split, mascara in partes.items():
        verdadeiro = y[mascara]
        previsto = pipeline.predict(clipes.loc[mascara, features])
        metricas[split] = calcula_metricas(verdadeiro, previsto, rotulos=rotulos, nomes=nomes)
        distribuicao[split] = {
            rotulo: int((verdadeiro == rotulo).sum()) for rotulo in rotulos
        }

    return ResultadoTreino(
        estimador=pipeline,
        parametros=ParametrosTreino(
            alvo=alvo,
            modo=modo,
            corte=corte if modo == MODO_BINARIO else None,
            random_state=random_state,
            n_estimators=n_estimators,
            class_weight=class_weight,
            estrategia_nan=estrategia_nan,
        ),
        metricas=metricas,
        importancias=_importancias(pipeline, features),
        distribuicao=distribuicao,
        colunas=features,
        rotulos=rotulos,
        nomes_rotulos=dict(nomes),
        versao_sklearn=sklearn.__version__,
    )


def _alvo_transformado(niveis: pd.Series, modo: str, corte: int) -> pd.Series:
    if modo == MODO_BINARIO:
        return binariza(niveis, corte)
    return niveis.astype(int)


def _importancias(pipeline: Pipeline, features: List[str]) -> Dict[str, float]:
    """Importâncias por feature, da maior para a menor.

    A ordem decrescente é o que o relatório consome; o desempate é pelo nome,
    para que duas execuções idênticas gerem o mesmo relatório.
    """
    valores = pipeline.named_steps[PASSO_FLORESTA].feature_importances_
    pares = sorted(zip(features, valores), key=lambda par: (-par[1], par[0]))
    return {feature: float(valor) for feature, valor in pares}


# --- serialização ----------------------------------------------------------

#: Chaves obrigatórias do `.joblib`. Um artefato que seja só o estimador nu não
#: é aceito: sem ordem de features e sem parâmetros ele vira armadilha na ticket 8.
CHAVES_ARTEFATO = (
    "estimador",
    "colunas",
    "rotulos",
    "nomes_rotulos",
    "parametros",
    "versao_sklearn",
)


def salva_modelo(resultado: ResultadoTreino, caminho: Union[str, Path]) -> Path:
    """Serializa o pipeline **com** o contexto de uso, via joblib."""
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)

    joblib.dump(
        {
            "estimador": resultado.estimador,
            "colunas": list(resultado.colunas),
            "rotulos": list(resultado.rotulos),
            "nomes_rotulos": dict(resultado.nomes_rotulos),
            "parametros": resultado.parametros,
            "versao_sklearn": resultado.versao_sklearn,
        },
        caminho,
    )
    return caminho


def carrega_modelo(caminho: Union[str, Path]) -> ModeloSalvo:
    """Carrega um artefato salvo por `salva_modelo`.

    Avisa — não falha — quando a versão do scikit-learn mudou desde o treino: o
    modelo costuma continuar funcionando, mas a incompatibilidade silenciosa de
    pickle entre versões é conhecida o bastante para merecer barulho.
    """
    artefato = joblib.load(Path(caminho))

    if not isinstance(artefato, dict) or any(c not in artefato for c in CHAVES_ARTEFATO):
        raise ArtefatoInvalido(
            f"{caminho} não é um artefato da ticket 2 (esperado um dict com"
            f" {list(CHAVES_ARTEFATO)})"
        )

    if artefato["versao_sklearn"] != sklearn.__version__:
        warnings.warn(
            f"modelo treinado com scikit-learn {artefato['versao_sklearn']},"
            f" carregado com {sklearn.__version__}",
            VersaoSklearnDiferente,
            stacklevel=2,
        )

    return ModeloSalvo(
        estimador=artefato["estimador"],
        colunas=list(artefato["colunas"]),
        rotulos=list(artefato["rotulos"]),
        nomes_rotulos=dict(artefato["nomes_rotulos"]),
        parametros=artefato["parametros"],
        versao_sklearn=artefato["versao_sklearn"],
    )
