"""Os dois datasets na mesma mesa: DAiSEE e UTA-RLDD.

As 39 features são as mesmas nos dois, calculadas pelo mesmo extrator sobre a
mesma unidade de 10 segundos. Isso permite três coisas que um dataset sozinho
não permite, e este módulo existe para cada uma delas:

1. **Comparar o domínio.** O DAiSEE é webcam de notebook a 640x480; o UTA-RLDD é
   celular em HD, gravado pelo próprio participante. Se as distribuições das
   features forem muito diferentes, qualquer transferência entre os dois falha
   por motivo de câmera, não de comportamento — e confundir as duas coisas seria
   o erro mais fácil de cometer aqui.

2. **Transferir.** Treinar sonolência no RLDD e aplicar no DAiSEE, perguntando
   se a sonolência prevista acompanha o **tédio** que anotadores humanos
   marcaram. Nenhum rótulo de sonolência existe no DAiSEE, então isto não é
   avaliação de acurácia: é evidência de validade de construto. Se um modelo que
   nunca viu o DAiSEE atribui mais sonolência justamente aos clipes que humanos
   acharam entediantes, ele aprendeu algo sobre pessoas — e não sobre a câmera
   de um dataset.

3. **Treinar junto.** Empilhar as linhas dos dois sob um alvo compartilhado de
   "baixo alerta" e medir se isso melhora cada dataset em relação ao modelo
   treinado só nele.

**Sobre o alvo compartilhado, e a honestidade dele.** Sonolência e desengajamento
não são a mesma coisa. Uma pessoa pode estar entediada e bem acordada; pode
estar exausta e concentrada. Empilhar os dois datasets sob um rótulo só é uma
**aposta explícita** de que os dois estados compartilham assinatura facial
suficiente para um modelo se beneficiar de ver ambos. A aposta pode dar errado,
e o desenho da avaliação é o que garante que a gente saiba: cada dataset é
avaliado no **seu próprio** teste, por sujeitos que não entraram em treino
nenhum, contra o modelo treinado apenas naquele dataset. Se o conjunto não
ganhar, o número dirá isso.

**A normalização é o que torna a comparação possível.** Em valor absoluto, o EAR
médio de um dataset e do outro diferem por resolução, distância da câmera e
lente — diferenças reais que não têm nada a ver com o estado da pessoa. Medindo
cada pessoa contra ela mesma, boa parte disso cancela. É a mesma razão pela qual
a aplicação calibra o aluno nos primeiros 60 segundos.
"""
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from sklearn.metrics import balanced_accuracy_score, roc_auc_score

import treino_fadiga as tf
from esquema import COLUNA_CLIPE, COLUNA_USUARIO, colunas_features
from esquema_rldd import ALERTA, COLUNA_PARTICIPANTE, COLUNA_SONOLENCIA, SONOLENTO

#: De qual dataset a linha veio. Entra como coluna, nunca como feature: o
#: modelo aprenderia a responder "é DAiSEE, então engajado" em vez de olhar o
#: rosto, e a métrica subiria sem nada ter melhorado.
COLUNA_FONTE = "fonte"

#: Sujeito, unificado entre os dois. O DAiSEE chama de `user_id` e o RLDD de
#: `participante`; o prefixo evita que o usuário "01" de um vire o mesmo do
#: outro — o que faria a verificação de independência passar num vazamento.
COLUNA_SUJEITO = "sujeito"

#: Alvo compartilhado: 1 = estado de alerta/engajamento reduzido.
COLUNA_BAIXO_ALERTA = "baixo_alerta"

FONTE_DAISEE = "daisee"
FONTE_RLDD = "rldd"

#: Corte do DAiSEE para "desengajado". Níveis 0 e 1 são "very low" e "low"; é a
#: fronteira que o próprio dataset desenha, e a mesma que `treino.py` usa.
CORTE_DESENGAJADO = 2

#: Corte do DAiSEE para "entediado", usado só no teste de transferência. Níveis
#: 2 e 3 são "high" e "very high" boredom.
CORTE_ENTEDIADO = 2


class CombinacaoInvalida(Exception):
    """Os datasets não batem — coluna faltando, ou recorte vazio."""


# --- Harmonização ----------------------------------------------------------


def _so_as_colunas_uteis(df: pd.DataFrame, extras: List[str]) -> pd.DataFrame:
    faltando = [c for c in colunas_features() + extras if c not in df.columns]
    if faltando:
        raise CombinacaoInvalida(f"colunas faltando: {faltando}")
    return df[colunas_features() + extras].copy()


def harmoniza_daisee(clipes: pd.DataFrame) -> pd.DataFrame:
    """DAiSEE no formato comum, com o alvo de baixo alerta derivado do engajamento."""
    tabela = _so_as_colunas_uteis(clipes, [COLUNA_CLIPE, COLUNA_USUARIO, "engagement", "boredom"])
    tabela[COLUNA_FONTE] = FONTE_DAISEE
    tabela[COLUNA_SUJEITO] = FONTE_DAISEE + "-" + tabela[COLUNA_USUARIO].astype(str)
    tabela[COLUNA_BAIXO_ALERTA] = (tabela["engagement"] < CORTE_DESENGAJADO).astype(int)
    return tabela


def harmoniza_rldd(janelas: pd.DataFrame, so_extremos: bool = True) -> pd.DataFrame:
    """UTA-RLDD no formato comum.

    `so_extremos` descarta a vigilância baixa, pelo mesmo motivo de
    `tf.ALVO_BINARIO`: o estado intermediário não tem fronteira nítida com
    nenhum dos dois, e empurrá-lo para um lado decidiria por dentro do código
    algo que o dataset deixou aberto.
    """
    tabela = _so_as_colunas_uteis(janelas, [COLUNA_CLIPE, COLUNA_PARTICIPANTE, COLUNA_SONOLENCIA])
    if so_extremos:
        tabela = tabela[tabela[COLUNA_SONOLENCIA].isin([ALERTA, SONOLENTO])].copy()

    tabela[COLUNA_FONTE] = FONTE_RLDD
    tabela[COLUNA_SUJEITO] = FONTE_RLDD + "-" + tabela[COLUNA_PARTICIPANTE].astype(str)
    tabela[COLUNA_BAIXO_ALERTA] = (tabela[COLUNA_SONOLENCIA] != ALERTA).astype(int)
    return tabela


def normaliza_por_sujeito(tabela: pd.DataFrame) -> pd.DataFrame:
    """Subtrai de cada feature a mediana do próprio sujeito.

    Para o DAiSEE é o mais próximo que existe da calibração por sessão: o
    dataset não agrupa clipes em sessões, só em usuários. Para o RLDD isto usa
    as três gravações da pessoa, o que é mais informação do que o produto teria
    — então serve para **comparar domínios**, e não para reportar desempenho de
    produção, que é medido em `treino_fadiga` com a calibração por gravação.
    """
    features = colunas_features()
    saida = tabela.copy()
    saida[features] = saida[features] - saida.groupby(COLUNA_SUJEITO)[features].transform("median")
    return saida


def empilha(daisee: pd.DataFrame, rldd: pd.DataFrame) -> pd.DataFrame:
    """Une as duas tabelas harmonizadas numa só, em ordem estável."""
    comuns = colunas_features() + [COLUNA_CLIPE, COLUNA_FONTE, COLUNA_SUJEITO, COLUNA_BAIXO_ALERTA]
    junto = pd.concat([daisee[comuns], rldd[comuns]], ignore_index=True)
    return junto.sort_values([COLUNA_FONTE, COLUNA_CLIPE]).reset_index(drop=True)


# --- 1. Comparação de domínio ----------------------------------------------


def compara_dominios(daisee: pd.DataFrame, rldd: pd.DataFrame) -> pd.DataFrame:
    """Média e desvio de cada feature nos dois datasets, com a diferença padronizada.

    A coluna `d_de_cohen` é a diferença das médias dividida pelo desvio
    agrupado: acima de ~0,8 a separação entre os dois datasets é maior que a
    variação dentro de cada um, e ali a feature está descrevendo a câmera mais
    que a pessoa.
    """
    linhas = []
    for feature in colunas_features():
        a, b = daisee[feature].dropna(), rldd[feature].dropna()
        if a.empty or b.empty:
            continue
        agrupado = np.sqrt((a.var(ddof=1) + b.var(ddof=1)) / 2)
        linhas.append(
            {
                "feature": feature,
                "daisee_media": float(a.mean()),
                "rldd_media": float(b.mean()),
                "daisee_desvio": float(a.std(ddof=1)),
                "rldd_desvio": float(b.std(ddof=1)),
                "d_de_cohen": float(abs(a.mean() - b.mean()) / agrupado) if agrupado else np.nan,
            }
        )
    return pd.DataFrame(linhas).sort_values("d_de_cohen", ascending=False).reset_index(drop=True)


# --- 2. Transferência ------------------------------------------------------


@dataclass(frozen=True)
class Transferencia:
    """O que se aprende ao soltar o modelo de sonolência sobre o DAiSEE.

    `auc_tedio` é a pergunta central: a sonolência prevista ordena os clipes de
    acordo com o tédio que humanos anotaram? 0,5 é moeda; acima disso há
    concordância, e ela não pode vir de ajuste ao DAiSEE, porque o modelo nunca
    viu uma linha dele.
    """

    n_clipes: int
    auc_tedio: float
    auc_desengajamento: float
    media_prevista_entediado: float
    media_prevista_nao_entediado: float

    @property
    def concorda_com_humanos(self) -> bool:
        return self.auc_tedio > 0.5


def transfere_para_daisee(pipeline, daisee: pd.DataFrame) -> Transferencia:
    """Aplica o modelo de sonolência ao DAiSEE e confronta com os rótulos humanos.

    **Não é medida de acurácia, e dizer que é seria erro grave.** O DAiSEE não
    tem rótulo de sonolência: ninguém perguntou aos anotadores se a pessoa estava
    com sono. O que se mede é se duas leituras independentes do mesmo rosto — um
    modelo treinado noutro dataset e um humano marcando tédio — apontam para o
    mesmo lado.
    """
    features = colunas_features()
    if daisee.empty:
        raise CombinacaoInvalida("nenhum clipe do DAiSEE para transferir")

    probabilidade = pipeline.predict_proba(daisee[features])[:, 1]
    entediado = (daisee["boredom"] >= CORTE_ENTEDIADO).astype(int)
    desengajado = (daisee["engagement"] < CORTE_DESENGAJADO).astype(int)

    return Transferencia(
        n_clipes=len(daisee),
        auc_tedio=_auc(entediado, probabilidade),
        auc_desengajamento=_auc(desengajado, probabilidade),
        media_prevista_entediado=float(probabilidade[entediado == 1].mean())
        if (entediado == 1).any()
        else float("nan"),
        media_prevista_nao_entediado=float(probabilidade[entediado == 0].mean())
        if (entediado == 0).any()
        else float("nan"),
    )


def _auc(verdadeiro: pd.Series, escore: np.ndarray) -> float:
    """AUC, ou NaN quando só existe uma classe — caso em que ela não é definida."""
    if verdadeiro.nunique() < 2:
        return float("nan")
    return float(roc_auc_score(verdadeiro, escore))


# --- 3. Treino conjunto ----------------------------------------------------


@dataclass(frozen=True)
class ComparacaoDeTreino:
    """Um dataset avaliado com dois modelos: o dele sozinho e o conjunto.

    O ganho é a diferença. Positivo significa que ver o outro dataset ajudou;
    negativo significa que atrapalhou, e esse número precisa aparecer com o
    mesmo destaque do outro.
    """

    avaliado_em: str
    n_teste: int
    sozinho: float
    conjunto: float

    @property
    def ganho(self) -> float:
        return self.conjunto - self.sozinho


def compara_sozinho_e_conjunto(
    junto: pd.DataFrame,
    construtor,
    sujeitos_de_teste: Dict[str, List[str]],
) -> List[ComparacaoDeTreino]:
    """Treina duas vezes por dataset e mede a diferença no teste daquele dataset.

    O teste é **sempre** o mesmo nas duas medições — os mesmos sujeitos, o mesmo
    recorte. O que muda é só o que entrou no treino. Comparar contra testes
    diferentes não mediria nada.

    Os sujeitos de teste ficam de fora dos dois treinos, inclusive do conjunto:
    do contrário o modelo conjunto teria visto, no material do outro dataset,
    algo que o modelo sozinho não viu — e a comparação seria sobre quantidade de
    dado, não sobre o benefício de misturar.
    """
    features = colunas_features()
    resultados: List[ComparacaoDeTreino] = []
    todos_de_teste = {s for lista in sujeitos_de_teste.values() for s in lista}

    for fonte, sujeitos in sujeitos_de_teste.items():
        teste = junto[junto[COLUNA_SUJEITO].isin(sujeitos)]
        if teste.empty or teste[COLUNA_BAIXO_ALERTA].nunique() < 2:
            continue

        fora_do_teste = junto[~junto[COLUNA_SUJEITO].isin(todos_de_teste)]
        so_deste = fora_do_teste[fora_do_teste[COLUNA_FONTE] == fonte]

        sozinho = construtor()
        sozinho.fit(so_deste[features], so_deste[COLUNA_BAIXO_ALERTA])

        conjunto = construtor()
        conjunto.fit(fora_do_teste[features], fora_do_teste[COLUNA_BAIXO_ALERTA])

        resultados.append(
            ComparacaoDeTreino(
                avaliado_em=fonte,
                n_teste=len(teste),
                sozinho=float(
                    balanced_accuracy_score(
                        teste[COLUNA_BAIXO_ALERTA], sozinho.predict(teste[features])
                    )
                ),
                conjunto=float(
                    balanced_accuracy_score(
                        teste[COLUNA_BAIXO_ALERTA], conjunto.predict(teste[features])
                    )
                ),
            )
        )

    return resultados


def sujeitos_de_teste(junto: pd.DataFrame, fracao: float = 0.2, semente: int = 42) -> Dict[str, List[str]]:
    """Sorteia sujeitos de teste em cada dataset, sem nunca partir um sujeito.

    O sorteio é por **sujeito**, não por linha: partir as janelas de uma pessoa
    entre treino e teste faria o modelo reconhecer o rosto, e a métrica subiria
    sem nada ter melhorado.
    """
    rng = np.random.default_rng(semente)
    escolhidos: Dict[str, List[str]] = {}

    for fonte, grupo in junto.groupby(COLUNA_FONTE):
        sujeitos = np.array(sorted(grupo[COLUNA_SUJEITO].unique()))
        quantos = max(1, int(round(len(sujeitos) * fracao)))
        escolhidos[str(fonte)] = sorted(
            rng.choice(sujeitos, size=quantos, replace=False).tolist()
        )

    return escolhidos
