"""Testes do treino de sonolência.

Nenhum teste toca o UTA-RLDD: as janelas são sintéticas, montadas com o mesmo
contrato de `esquema_rldd`. O que se afirma aqui é o comportamento do código —
recorte do alvo, normalização, independência de participante entre folds — e
não o desempenho do modelo, que é medição e sai no relatório.

O dataset sintético tem um sinal plantado de propósito (`ear_media` menor nas
gravações sonolentas), então um teste que exercita a validação cruzada pode
afirmar que o modelo aprende **alguma** coisa sem afirmar quanto.
"""
import numpy as np
import pandas as pd
import pytest

import treino_fadiga as tf
from esquema import colunas_features
from esquema_rldd import (
    COLUNA_FOLD,
    COLUNA_INDICE_JANELA,
    COLUNA_JANELA,
    COLUNA_PARTE,
    COLUNA_PARTICIPANTE,
    COLUNA_SONOLENCIA,
    colunas_janelas,
)

FEATURES = colunas_features()


def monta_janelas(
    n_participantes: int = 10,
    janelas_por_gravacao: int = 12,
    deriva: float = 0.012,
    degrau: float = 0.0,
    semente: int = 7,
) -> pd.DataFrame:
    """Janelas sintéticas com deslocamento por pessoa e sinal na sonolência.

    Três ingredientes, cada um com um papel:

    - **deslocamento por pessoa** — o EAR neutro de cada um é diferente. Sem ele
      o teste da normalização passaria por vacuidade, porque não haveria o que
      remover.
    - **deriva** — dentro da gravação sonolenta o olho vai fechando ao longo do
      tempo. É o sinal realista: ninguém adormece instantaneamente, e é essa
      variação *dentro* da sessão que a calibração por sessão consegue ver.
    - **degrau** — um deslocamento constante do começo ao fim da gravação. É o
      sinal que a calibração por sessão **não** consegue ver, e existe aqui para
      um teste poder afirmar isso.
    """
    rng = np.random.default_rng(semente)
    linhas = []

    for i in range(n_participantes):
        participante = f"{i + 1:02d}"
        fold = i % 5 + 1
        deslocamento = rng.normal(0, 0.05)

        for estado in (0, 5, 10):
            intensidade = estado / 10
            for indice in range(janelas_por_gravacao):
                valores = {
                    nome: float(rng.normal(0.3, 0.005) + deslocamento) for nome in FEATURES
                }
                # Olho fechando ao longo da gravação, proporcional ao estado.
                valores["ear_media"] -= deriva * intensidade * indice
                valores["ear_media"] -= degrau * intensidade
                linhas.append(
                    {
                        COLUNA_JANELA: f"rldd-{participante}-{estado}-1-{indice:04d}",
                        COLUNA_PARTICIPANTE: participante,
                        COLUNA_FOLD: fold,
                        COLUNA_PARTE: 1,
                        COLUNA_INDICE_JANELA: indice,
                        COLUNA_SONOLENCIA: estado,
                        **valores,
                    }
                )

    return pd.DataFrame(linhas)[colunas_janelas()]


@pytest.fixture
def janelas() -> pd.DataFrame:
    return monta_janelas()


# --- Alvos -----------------------------------------------------------------


def test_o_alvo_binario_descarta_a_vigilancia_baixa(janelas: pd.DataFrame) -> None:
    """Empurrar o 5 para um dos lados seria decidir o que o dataset deixou aberto."""
    recorte, y, nomes = tf.rotula(janelas, tf.ALVO_BINARIO)

    assert set(recorte[COLUNA_SONOLENCIA]) == {0, 10}
    assert set(y) == {0, 1}
    assert y.sum() == (recorte[COLUNA_SONOLENCIA] == 10).sum()
    assert nomes == tf.NOMES_BINARIO


def test_o_alvo_binario_amplo_mantem_tudo(janelas: pd.DataFrame) -> None:
    recorte, y, _ = tf.rotula(janelas, tf.ALVO_BINARIO_AMPLO)

    assert len(recorte) == len(janelas)
    assert y.sum() == (janelas[COLUNA_SONOLENCIA] != 0).sum()


def test_o_alvo_ternario_preserva_os_tres_niveis(janelas: pd.DataFrame) -> None:
    _, y, nomes = tf.rotula(janelas, tf.ALVO_TERNARIO)

    assert sorted(y.unique()) == [0, 1, 2]
    assert nomes[2] == "sonolento"


def test_alvo_desconhecido(janelas: pd.DataFrame) -> None:
    with pytest.raises(tf.AlvoInvalido):
        tf.rotula(janelas, "qualquer_coisa")


def test_alvo_com_uma_classe_so(janelas: pd.DataFrame) -> None:
    """Dataset só de alertas não treina — e falhar aqui é melhor que no `fit`."""
    so_alerta = janelas[janelas[COLUNA_SONOLENCIA] == 0]

    with pytest.raises(tf.AlvoInvalido):
        tf.rotula(so_alerta, tf.ALVO_BINARIO)


# --- Normalização ----------------------------------------------------------


def test_sem_normalizacao_as_features_nao_mudam(janelas: pd.DataFrame) -> None:
    igual = tf.normaliza(janelas, tf.SEM_NORMALIZACAO)

    pd.testing.assert_frame_equal(igual[FEATURES], janelas[FEATURES])


def test_a_normalizacao_por_sessao_zera_o_comeco_da_gravacao(janelas: pd.DataFrame) -> None:
    """A baseline sai das primeiras janelas, então elas ficam centradas em zero.

    É o mesmo que a aplicação faz nos primeiros 60 segundos da sessão: o aluno
    passa a ser medido contra ele mesmo, e não contra uma constante.
    """
    normalizado = tf.normaliza(janelas, tf.NORMALIZACAO_SESSAO)

    comeco = normalizado[normalizado[COLUNA_INDICE_JANELA] < tf.JANELAS_DE_CALIBRACAO]
    assert comeco["ear_media"].abs().median() < 0.02


def test_a_normalizacao_por_sessao_so_olha_para_o_proprio_video(janelas: pd.DataFrame) -> None:
    """Cada gravação calibra sozinha — em produção não existe o futuro da sessão.

    Se a baseline viesse do participante inteiro, ela usaria a gravação sonolenta
    para definir o que é "normal" naquela pessoa, e nada equivalente existiria no
    navegador.
    """
    normalizado = tf.normaliza(janelas, tf.NORMALIZACAO_SESSAO)

    por_gravacao = normalizado.groupby([COLUNA_PARTICIPANTE, COLUNA_SONOLENCIA])
    primeiras = por_gravacao.apply(
        lambda g: g.nsmallest(tf.JANELAS_DE_CALIBRACAO, COLUNA_INDICE_JANELA)["ear_media"].median(),
        include_groups=False,
    )
    assert primeiras.abs().max() < 0.02


def test_a_normalizacao_por_participante_remove_o_deslocamento_da_pessoa(
    janelas: pd.DataFrame,
) -> None:
    normalizado = tf.normaliza(janelas, tf.NORMALIZACAO_PARTICIPANTE)

    medias = normalizado.groupby(COLUNA_PARTICIPANTE)["ear_media"].median()
    assert medias.abs().max() < 1e-9

    cruas = janelas.groupby(COLUNA_PARTICIPANTE)["ear_media"].median()
    assert cruas.std() > 0.01, "o dataset sintético precisa ter variação entre pessoas"


def test_normalizacao_desconhecida(janelas: pd.DataFrame) -> None:
    with pytest.raises(tf.TreinoInvalido):
        tf.normaliza(janelas, "por_lua_cheia")


# --- Independência de participante -----------------------------------------


def test_participante_nos_dois_lados_e_recusado(janelas: pd.DataFrame) -> None:
    """O sintoma do vazamento é uma métrica boa, e métrica boa ninguém investiga."""
    with pytest.raises(tf.VazamentoDeParticipante):
        tf.verifica_independencia(janelas, janelas)


def test_a_validacao_cruzada_nunca_mistura_participantes(janelas: pd.DataFrame) -> None:
    """Se misturasse, `valida_cruzado` levantaria — o teste é a ausência de erro.

    Confirmado também pela contagem: cinco folds, cinco medidas.
    """
    resultado = tf.valida_cruzado(
        janelas, tf.catalogo_de_modelos()["floresta_regularizada"], "floresta_regularizada"
    )

    assert [f.fold for f in resultado.folds] == [1, 2, 3, 4, 5]
    assert all(f.n_treino > f.n_teste for f in resultado.folds)


# --- Validação cruzada -----------------------------------------------------


def test_o_chute_majoritario_fica_na_moeda(janelas: pd.DataFrame) -> None:
    """O chão de referência. Qualquer modelo que não o supere não achou sinal."""
    resultado = tf.valida_cruzado(
        janelas, tf.catalogo_de_modelos()["chute_majoritario"], "chute_majoritario"
    )

    assert resultado.acuracia_balanceada_media == pytest.approx(0.5, abs=1e-9)


def test_o_modelo_acha_o_sinal_plantado(janelas: pd.DataFrame) -> None:
    resultado = tf.valida_cruzado(
        janelas, tf.catalogo_de_modelos()["floresta_regularizada"], "floresta_regularizada"
    )

    assert resultado.acuracia_balanceada_media > 0.7


def test_sinal_constante_na_sessao_some_na_calibracao_por_sessao() -> None:
    """A limitação que a calibração por sessão carrega, escrita como teste.

    Se o estado não varia do primeiro ao último segundo da gravação, a baseline
    tirada do começo já contém o estado inteiro, e subtraí-la zera o sinal junto
    com o deslocamento da pessoa. O modelo fica cego — e não por falta de dado,
    mas porque a medida é relativa por construção.

    **Isto não é um defeito a consertar: é a mesma coisa que acontece no
    produto.** Um aluno que senta já exausto calibra exausto, e o IEE passa a
    medi-lo contra o próprio cansaço. A alternativa — comparar com uma constante
    igual para todo mundo — é o que a ticket 7 existe para recusar, porque
    trocaria essa cegueira por uma pior: a de confundir a fisiologia de cada
    pessoa com engajamento.

    O que salva o caso real é que sonolência raramente é constante: a pessoa vai
    fechando o olho ao longo do tempo, e é essa deriva que a calibração enxerga.
    """
    so_degrau = monta_janelas(deriva=0.0, degrau=0.08)

    cega = tf.valida_cruzado(
        so_degrau,
        tf.catalogo_de_modelos()["floresta_regularizada"],
        "floresta_regularizada",
        normalizacao=tf.NORMALIZACAO_SESSAO,
    )
    crua = tf.valida_cruzado(
        so_degrau,
        tf.catalogo_de_modelos()["floresta_regularizada"],
        "floresta_regularizada",
        normalizacao=tf.SEM_NORMALIZACAO,
    )

    assert cega.acuracia_balanceada_media < 0.6
    # A versão crua não chega a 1,0: o deslocamento entre pessoas é maior que o
    # degrau, e é exatamente por isso que a normalização existe. O que o teste
    # afirma é o contraste — o sinal estava lá, e a calibração por sessão o
    # apagou junto com o deslocamento.
    assert crua.acuracia_balanceada_media > cega.acuracia_balanceada_media + 0.25


def test_o_resultado_guarda_cada_fold_e_nao_so_a_media(janelas: pd.DataFrame) -> None:
    """Com 60 pessoas, a variação entre folds é o intervalo de confiança honesto."""
    resultado = tf.valida_cruzado(
        janelas, tf.catalogo_de_modelos()["floresta_regularizada"], "floresta_regularizada"
    )

    assert len(resultado.folds) == 5
    assert resultado.acuracia_balanceada_desvio >= 0
    assert len(resultado.piores_folds) == 2
    assert all(f.metricas.n_amostras == f.n_teste for f in resultado.folds)


# --- Treino final ----------------------------------------------------------


def test_o_treino_final_usa_o_dataset_inteiro(janelas: pd.DataFrame) -> None:
    """Quem mede é a validação cruzada; quem entrega é esta função."""
    pipeline, recorte, y = tf.treina_final(
        janelas, tf.catalogo_de_modelos()["floresta_regularizada"]
    )

    esperado = (janelas[COLUNA_SONOLENCIA].isin([0, 10])).sum()
    assert len(recorte) == esperado
    assert len(y) == esperado
    assert pipeline.predict(recorte[FEATURES].head(3)).shape == (3,)


def test_importancias_saem_ordenadas(janelas: pd.DataFrame) -> None:
    pipeline, _, _ = tf.treina_final(janelas, tf.catalogo_de_modelos()["floresta_regularizada"])

    ranking = tf.importancias(pipeline)

    assert len(ranking) == len(FEATURES)
    assert list(ranking.values()) == sorted(ranking.values(), reverse=True)
    # O sinal foi plantado em `ear_media`; a floresta tem de encontrá-lo.
    assert list(ranking)[0] == "ear_media"


def test_modelo_sem_introspeccao_devolve_vazio(janelas: pd.DataFrame) -> None:
    """A comparação entre modelos não pode depender de todos exporem o mesmo."""
    pipeline, _, _ = tf.treina_final(janelas, tf.catalogo_de_modelos()["regressao_logistica"])

    assert tf.importancias(pipeline) == {}
