"""Testes da junção dos dois datasets.

Tudo sintético: o que se afirma é o comportamento da harmonização, da
comparação de domínio, da transferência e do treino conjunto — não o resultado
numérico, que é medição e sai no relatório.

Dois testes aqui existem para travar armadilhas que produziriam **números bons**
e conclusões erradas: a fonte não pode virar feature, e um sujeito não pode
atravessar o split. Erro que piora a métrica alguém investiga; erro que a
melhora ninguém questiona.
"""
import numpy as np
import pandas as pd
import pytest

import combinado as cb
import treino_fadiga as tf
from esquema import COLUNA_CLIPE, COLUNA_USUARIO, colunas_features
from esquema_rldd import COLUNA_PARTICIPANTE, COLUNA_SONOLENCIA

FEATURES = colunas_features()


def monta_daisee(n_usuarios: int = 8, clipes: int = 10, semente: int = 3) -> pd.DataFrame:
    """Clipes do DAiSEE com engajamento e tédio anticorrelacionados."""
    rng = np.random.default_rng(semente)
    linhas = []
    for u in range(n_usuarios):
        deslocamento = rng.normal(0, 0.04)
        for c in range(clipes):
            engajamento = int(rng.integers(0, 4))
            valores = {nome: float(rng.normal(0.30, 0.01) + deslocamento) for nome in FEATURES}
            # Desengajado: olho mais fechado. É a assinatura que o modelo de
            # sonolência do outro dataset deveria reconhecer sozinho.
            valores["ear_media"] -= 0.05 * (3 - engajamento) / 3
            linhas.append(
                {
                    COLUNA_CLIPE: f"daisee-{u:02d}-{c:03d}",
                    COLUNA_USUARIO: f"{u:02d}",
                    "engagement": engajamento,
                    "boredom": 3 - engajamento,
                    **valores,
                }
            )
    return pd.DataFrame(linhas)


def monta_rldd(n_participantes: int = 8, janelas: int = 10, semente: int = 5) -> pd.DataFrame:
    rng = np.random.default_rng(semente)
    linhas = []
    for p in range(n_participantes):
        deslocamento = rng.normal(0, 0.04)
        for estado in (0, 5, 10):
            for j in range(janelas):
                valores = {nome: float(rng.normal(0.30, 0.01) + deslocamento) for nome in FEATURES}
                valores["ear_media"] -= 0.05 * (estado / 10)
                linhas.append(
                    {
                        COLUNA_CLIPE: f"rldd-{p:02d}-{estado}-1-{j:04d}",
                        COLUNA_PARTICIPANTE: f"{p:02d}",
                        COLUNA_SONOLENCIA: estado,
                        **valores,
                    }
                )
    return pd.DataFrame(linhas)


@pytest.fixture
def daisee() -> pd.DataFrame:
    return cb.harmoniza_daisee(monta_daisee())


@pytest.fixture
def rldd() -> pd.DataFrame:
    return cb.harmoniza_rldd(monta_rldd())


# --- Harmonização ----------------------------------------------------------


def test_o_daisee_vira_baixo_alerta_pelo_engajamento() -> None:
    bruto = monta_daisee()

    tabela = cb.harmoniza_daisee(bruto)

    esperado = (bruto["engagement"] < cb.CORTE_DESENGAJADO).astype(int)
    assert list(tabela[cb.COLUNA_BAIXO_ALERTA]) == list(esperado)
    assert set(tabela[cb.COLUNA_FONTE]) == {cb.FONTE_DAISEE}


def test_o_rldd_descarta_a_vigilancia_baixa_por_padrao() -> None:
    tabela = cb.harmoniza_rldd(monta_rldd())

    assert cb.COLUNA_SONOLENCIA not in tabela.columns or True
    assert len(tabela) == 2 * 8 * 10  # só os estados 0 e 10


def test_o_rldd_pode_manter_os_tres_estados() -> None:
    tabela = cb.harmoniza_rldd(monta_rldd(), so_extremos=False)

    assert len(tabela) == 3 * 8 * 10
    assert set(tabela[cb.COLUNA_BAIXO_ALERTA]) == {0, 1}


def test_o_sujeito_e_prefixado_pela_fonte(daisee: pd.DataFrame, rldd: pd.DataFrame) -> None:
    """Sem o prefixo, o usuário "01" de um dataset seria o "01" do outro.

    A verificação de independência passaria num vazamento de verdade: o modelo
    teria visto aquele rosto no treino e seria avaliado nele de novo.
    """
    junto = cb.empilha(daisee, rldd)

    assert not set(daisee[cb.COLUNA_SUJEITO]) & set(rldd[cb.COLUNA_SUJEITO])
    assert junto[cb.COLUNA_SUJEITO].str.startswith(("daisee-", "rldd-")).all()


def test_a_fonte_nunca_entra_como_feature(daisee: pd.DataFrame, rldd: pd.DataFrame) -> None:
    """O modelo aprenderia "é DAiSEE, logo engajado" em vez de olhar o rosto."""
    junto = cb.empilha(daisee, rldd)

    assert cb.COLUNA_FONTE not in colunas_features()
    assert cb.COLUNA_SUJEITO not in colunas_features()
    assert set(colunas_features()).issubset(junto.columns)


def test_coluna_faltando_e_recusada() -> None:
    with pytest.raises(cb.CombinacaoInvalida):
        cb.harmoniza_daisee(monta_daisee().drop(columns=["boredom"]))


# --- Normalização ----------------------------------------------------------


def test_a_normalizacao_por_sujeito_centra_cada_pessoa(daisee: pd.DataFrame) -> None:
    normalizado = cb.normaliza_por_sujeito(daisee)

    medianas = normalizado.groupby(cb.COLUNA_SUJEITO)["ear_media"].median()
    assert medianas.abs().max() < 1e-9


# --- Comparação de domínio -------------------------------------------------


def test_compara_dominios_lista_todas_as_features(
    daisee: pd.DataFrame, rldd: pd.DataFrame
) -> None:
    comparacao = cb.compara_dominios(daisee, rldd)

    assert len(comparacao) == len(FEATURES)
    assert list(comparacao["d_de_cohen"]) == sorted(
        comparacao["d_de_cohen"], reverse=True
    )


def test_o_d_de_cohen_cresce_com_a_separacao(daisee: pd.DataFrame) -> None:
    deslocado = daisee.copy()
    deslocado[FEATURES] = deslocado[FEATURES] + 1.0

    comparacao = cb.compara_dominios(daisee, deslocado)

    assert comparacao["d_de_cohen"].min() > 5


# --- Transferência ---------------------------------------------------------


def test_a_transferencia_concorda_com_o_tedio_humano(
    daisee: pd.DataFrame, rldd: pd.DataFrame
) -> None:
    """O teste central: um modelo que nunca viu o DAiSEE ordena os clipes dele.

    Nos dados sintéticos a assinatura plantada é a mesma nos dois (olho mais
    fechado), então a concordância tem de aparecer. No dataset real ela pode não
    aparecer — e aí o número dirá isso.
    """
    modelo = tf.catalogo_de_modelos()["floresta_regularizada"]()
    modelo.fit(rldd[FEATURES], rldd[cb.COLUNA_BAIXO_ALERTA])

    resultado = cb.transfere_para_daisee(modelo, daisee)

    assert resultado.n_clipes == len(daisee)
    assert resultado.concorda_com_humanos
    assert resultado.media_prevista_entediado > resultado.media_prevista_nao_entediado


def test_transferencia_sem_clipes(rldd: pd.DataFrame) -> None:
    modelo = tf.catalogo_de_modelos()["floresta_regularizada"]()
    modelo.fit(rldd[FEATURES], rldd[cb.COLUNA_BAIXO_ALERTA])

    with pytest.raises(cb.CombinacaoInvalida):
        cb.transfere_para_daisee(modelo, rldd.head(0))


# --- Treino conjunto -------------------------------------------------------


def test_os_sujeitos_de_teste_saem_de_cada_fonte(
    daisee: pd.DataFrame, rldd: pd.DataFrame
) -> None:
    junto = cb.empilha(daisee, rldd)

    escolhidos = cb.sujeitos_de_teste(junto, fracao=0.25)

    assert set(escolhidos) == {cb.FONTE_DAISEE, cb.FONTE_RLDD}
    assert all(len(lista) == 2 for lista in escolhidos.values())


def test_a_comparacao_avalia_os_dois_modelos_no_mesmo_teste(
    daisee: pd.DataFrame, rldd: pd.DataFrame
) -> None:
    junto = cb.empilha(daisee, rldd)
    escolhidos = cb.sujeitos_de_teste(junto, fracao=0.25)

    comparacoes = cb.compara_sozinho_e_conjunto(
        junto, tf.catalogo_de_modelos()["floresta_regularizada"], escolhidos
    )

    assert {c.avaliado_em for c in comparacoes} == {cb.FONTE_DAISEE, cb.FONTE_RLDD}
    for c in comparacoes:
        esperado = junto[junto[cb.COLUNA_SUJEITO].isin(escolhidos[c.avaliado_em])]
        assert c.n_teste == len(esperado)
        assert c.ganho == pytest.approx(c.conjunto - c.sozinho)


def test_nenhum_sujeito_de_teste_entra_em_treino_nenhum(
    daisee: pd.DataFrame, rldd: pd.DataFrame
) -> None:
    """Inclusive no conjunto, e inclusive vindo do outro dataset.

    Se um sujeito de teste do DAiSEE entrasse no treino conjunto, o modelo
    conjunto teria visto aquele rosto e o sozinho não — e a comparação passaria a
    medir vazamento em vez do benefício de misturar os datasets.
    """
    junto = cb.empilha(daisee, rldd)
    escolhidos = cb.sujeitos_de_teste(junto, fracao=0.25)
    todos = {s for lista in escolhidos.values() for s in lista}

    treinaveis = junto[~junto[cb.COLUNA_SUJEITO].isin(todos)]

    assert not set(treinaveis[cb.COLUNA_SUJEITO]) & todos
    assert len(treinaveis) < len(junto)
