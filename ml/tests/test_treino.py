"""Testes do treino do Random Forest (ticket 2).

O DAiSEE real tem ~2.7 GB e exige formulário de acesso, e a saída da ticket 1
ainda está sendo construída — então todo teste roda sobre um dataset sintético
que obedece ao contrato de `esquema.colunas_clipes()`, com sinal aprendível
plantado de propósito, `user_id` disjunto entre splits e NaN espalhados nos
clipes "sem rosto".

Por isso as asserções são sobre **propriedades** (o vazamento de sujeito é
detectado, NaN não quebra o treino, o round-trip do artefato preserva as
predições), e não sobre números específicos do modelo: o número que sair daqui
não diz nada sobre o dataset real.
"""
import warnings
from typing import Dict, Optional

import numpy as np
import pandas as pd
import pytest

import treino
from esquema import (
    COLUNA_CLIPE,
    COLUNA_SPLIT,
    COLUNA_USUARIO,
    COLUNAS_ROTULOS,
    EsquemaInvalido,
    colunas_agregadas,
    colunas_clipes,
    colunas_features,
)

TAMANHOS_PADRAO = {"Train": 240, "Validation": 80, "Test": 80}

#: Distribuição de níveis parecida com a do DAiSEE: 0 e 1 são raros.
PROBS_NIVEL = (0.05, 0.13, 0.47, 0.35)


def dataset_sintetico(
    tamanhos: Optional[Dict[str, int]] = None,
    semente: int = 7,
    prop_sem_rosto: float = 0.06,
    forca_sinal: float = 1.0,
) -> pd.DataFrame:
    """Um dataset de clipes conforme o contrato, com sinal plantado.

    `ear_media` alta, `prop_olhos_fechados` baixa e `mar_max` baixo puxam o
    engajamento para cima; todas as demais features são ruído puro. Os `user_id`
    recebem prefixo do split, de modo que nenhum sujeito aparece em dois splits.
    """
    tamanhos = tamanhos or TAMANHOS_PADRAO
    rng = np.random.default_rng(semente)
    features = colunas_features()
    linhas = []

    for split, n in tamanhos.items():
        niveis = rng.choice([0, 1, 2, 3], size=n, p=PROBS_NIVEL)
        usuarios = max(1, n // 4)  # ~4 clipes por sujeito, como no DAiSEE
        for i, nivel in enumerate(niveis):
            linha = {
                COLUNA_CLIPE: f"{split.lower()}_{i:04d}",
                COLUNA_USUARIO: f"{split.lower()}_u{i % usuarios}",
                COLUNA_SPLIT: split,
            }
            for coluna in features:
                linha[coluna] = float(rng.normal())

            linha["ear_media"] = 0.15 + 0.02 * nivel * forca_sinal + rng.normal(0, 0.012)
            linha["prop_olhos_fechados"] = float(
                np.clip(0.45 - 0.12 * nivel * forca_sinal + rng.normal(0, 0.05), 0.0, 1.0)
            )
            linha["mar_max"] = float(
                np.clip(0.80 - 0.15 * nivel * forca_sinal + rng.normal(0, 0.10), 0.0, 2.0)
            )
            linha["prop_frames_com_rosto"] = 1.0
            linha["prop_boca_aberta"] = float(np.clip(rng.normal(0.1, 0.05), 0.0, 1.0))
            linha["n_frames"] = 300.0

            linha["engagement"] = int(nivel)
            for rotulo in COLUNAS_ROTULOS:
                if rotulo != "engagement":
                    linha[rotulo] = int(rng.integers(0, 4))
            linhas.append(linha)

    clipes = pd.DataFrame(linhas)[colunas_clipes()]

    n_sem_rosto = int(len(clipes) * prop_sem_rosto)
    if n_sem_rosto:
        sem_rosto = rng.choice(clipes.index, size=n_sem_rosto, replace=False)
        clipes.loc[sem_rosto, colunas_agregadas()] = np.nan
        clipes.loc[sem_rosto, ["prop_olhos_fechados", "prop_boca_aberta"]] = np.nan
        clipes.loc[sem_rosto, "prop_frames_com_rosto"] = 0.0

    return clipes


def dataset_sem_sinal(semente: int = 3) -> pd.DataFrame:
    """Mesmo dataset, com os rótulos embaralhados: nenhum sinal a aprender."""
    clipes = dataset_sintetico(semente=semente)
    rng = np.random.default_rng(semente)
    clipes["engagement"] = rng.permutation(clipes["engagement"].to_numpy())
    return clipes


@pytest.fixture(scope="module")
def clipes() -> pd.DataFrame:
    return dataset_sintetico()


@pytest.fixture(scope="module")
def resultado(clipes: pd.DataFrame) -> "treino.ResultadoTreino":
    return treino.treina(clipes)


# --- independência de sujeito ---------------------------------------------


def test_verifica_independencia_aceita_split_do_daisee(clipes: pd.DataFrame) -> None:
    treino.verifica_independencia_de_sujeito(clipes)  # não levanta


def test_verifica_independencia_detecta_sujeito_em_dois_splits(clipes: pd.DataFrame) -> None:
    vazado = clipes.copy()
    usuario_de_treino = vazado.loc[vazado[COLUNA_SPLIT] == "Train", COLUNA_USUARIO].iloc[0]
    linha_de_teste = vazado.index[vazado[COLUNA_SPLIT] == "Test"][0]
    vazado.loc[linha_de_teste, COLUNA_USUARIO] = usuario_de_treino

    with pytest.raises(treino.VazamentoDeSujeito) as erro:
        treino.verifica_independencia_de_sujeito(vazado)

    assert usuario_de_treino in str(erro.value)


def test_treina_falha_alto_com_vazamento_de_sujeito(clipes: pd.DataFrame) -> None:
    vazado = clipes.copy()
    usuario_de_treino = vazado.loc[vazado[COLUNA_SPLIT] == "Train", COLUNA_USUARIO].iloc[0]
    vazado.loc[vazado.index[vazado[COLUNA_SPLIT] == "Validation"][0], COLUNA_USUARIO] = (
        usuario_de_treino
    )

    with pytest.raises(treino.VazamentoDeSujeito):
        treino.treina(vazado)


# --- treino ----------------------------------------------------------------


def test_treina_avalia_os_tres_splits(resultado: "treino.ResultadoTreino") -> None:
    assert set(resultado.metricas) == {"Train", "Validation", "Test"}
    assert resultado.metricas["Test"].n_amostras == TAMANHOS_PADRAO["Test"]


def test_treina_aprende_o_sinal_plantado(resultado: "treino.ResultadoTreino") -> None:
    assert resultado.metricas["Test"].macro.precisao > 0.6
    assert resultado.metricas["Test"].acuracia > 0.6


def test_treina_sem_sinal_nao_aprende() -> None:
    """Controle: com rótulos embaralhados a precisão macro fica perto do acaso."""
    resultado = treino.treina(dataset_sem_sinal())

    assert resultado.metricas["Test"].macro.precisao < 0.7


def test_treina_e_reprodutivel(clipes: pd.DataFrame) -> None:
    a = treino.treina(clipes, random_state=11)
    b = treino.treina(clipes, random_state=11)

    teste = clipes[clipes[COLUNA_SPLIT] == "Test"]
    assert np.array_equal(a.estimador.predict(teste[colunas_features()]),
                          b.estimador.predict(teste[colunas_features()]))
    assert a.parametros.random_state == 11


def test_treina_registra_parametros(resultado: "treino.ResultadoTreino") -> None:
    p = resultado.parametros
    assert p.alvo == "engagement"
    assert p.modo == treino.MODO_BINARIO
    assert p.corte == treino.CORTE_BINARIO_PADRAO
    assert p.random_state == treino.RANDOM_STATE_PADRAO
    assert p.class_weight == "balanced"
    assert p.estrategia_nan == "median"


def test_importancias_cobrem_todas_as_features(resultado: "treino.ResultadoTreino") -> None:
    assert set(resultado.importancias) == set(colunas_features())
    valores = list(resultado.importancias.values())
    assert valores == sorted(valores, reverse=True)
    assert pytest.approx(sum(valores), abs=1e-6) == 1.0


def test_features_plantadas_ficam_no_topo(resultado: "treino.ResultadoTreino") -> None:
    topo = list(resultado.importancias)[:5]
    assert "prop_olhos_fechados" in topo
    assert "ear_media" in topo


def test_distribuicao_por_classe_bate_com_o_dataset(
    resultado: "treino.ResultadoTreino", clipes: pd.DataFrame
) -> None:
    treino_df = clipes[clipes[COLUNA_SPLIT] == "Train"]
    engajados = int((treino_df["engagement"] >= treino.CORTE_BINARIO_PADRAO).sum())

    assert resultado.distribuicao["Train"][1] == engajados
    assert resultado.distribuicao["Train"][0] == len(treino_df) - engajados


# --- modos de alvo ---------------------------------------------------------


def test_modo_multiclasse_usa_os_quatro_niveis(clipes: pd.DataFrame) -> None:
    resultado = treino.treina(clipes, modo=treino.MODO_MULTICLASSE)

    assert resultado.rotulos == [0, 1, 2, 3]
    assert [m.rotulo for m in resultado.metricas["Test"].por_classe] == [0, 1, 2, 3]


def test_modo_binario_tem_dois_rotulos_nomeados(resultado: "treino.ResultadoTreino") -> None:
    assert resultado.rotulos == [0, 1]
    assert resultado.nomes_rotulos == {0: "nao_engajado", 1: "engajado"}


def test_corte_binario_e_parametrizavel(clipes: pd.DataFrame) -> None:
    padrao = treino.treina(clipes, corte=2)
    exigente = treino.treina(clipes, corte=3)

    assert exigente.parametros.corte == 3
    assert exigente.distribuicao["Train"][1] < padrao.distribuicao["Train"][1]


def test_binariza_usa_o_corte(clipes: pd.DataFrame) -> None:
    binario = treino.binariza(pd.Series([0, 1, 2, 3]), corte=2)

    assert list(binario) == [0, 0, 1, 1]


def test_treina_aceita_outro_alvo(clipes: pd.DataFrame) -> None:
    resultado = treino.treina(clipes, alvo="boredom")

    assert resultado.parametros.alvo == "boredom"


# --- NaN -------------------------------------------------------------------


def test_nan_nas_features_nao_quebra_o_treino() -> None:
    clipes = dataset_sintetico(prop_sem_rosto=0.35)

    resultado = treino.treina(clipes)

    teste = clipes[clipes[COLUNA_SPLIT] == "Test"]
    assert len(resultado.estimador.predict(teste[colunas_features()])) == len(teste)


def test_coluna_inteiramente_nan_no_treino_preserva_o_contrato_de_features(
    clipes: pd.DataFrame, tmp_path
) -> None:
    """Uma coluna toda-NaN no treino não altera o contrato de entrada do artefato.

    O que está sob teste é a coerência entre o que o `.joblib` **anuncia**
    (`colunas`) e o que o estimador dentro dele **aceita**. Se as duas contagens
    divergirem, a ticket 8 quebra na predição — não no treino, onde alguém
    estaria olhando. Verificado por mutação: treinar com `features[:-1]` mantendo
    o artefato anunciando 39 faz este teste falhar.

    Note que trocar `keep_empty_features` **não** quebra isto, e é o certo: a
    imputação descarta a coluna no treino e na predição, então o pipeline segue
    coerente e o contrato de 39 colunas na entrada continua valendo. Era isso que
    a versão anterior deste teste afirmava, espiando `named_steps[...].n_features_in_`
    — um invariante interno sem sintoma observável pela interface.
    """
    com_buraco = clipes.copy()
    com_buraco["roll_desvio"] = np.nan

    resultado = treino.treina(com_buraco)
    modelo = treino.carrega_modelo(
        treino.salva_modelo(resultado, tmp_path / "modelo.joblib")
    )

    assert modelo.colunas == colunas_features()
    teste = com_buraco[com_buraco[COLUNA_SPLIT] == "Test"]
    assert len(modelo.preve(teste)) == len(teste)


def test_modelo_carregado_preve_com_nan_sem_o_chamador_imputar(
    resultado: "treino.ResultadoTreino", tmp_path
) -> None:
    """O contrato da ticket 8: o backend manda o que tem, NaN inclusive.

    O que está sob teste é a **tolerância a NaN do artefato que vai para
    produção**, não a imputação. Como a tolerância é obtida — `SimpleImputer` no
    pipeline ou o suporte nativo a valores ausentes que as árvores do sklearn têm
    desde a 1.4 — é detalhe de implementação, e um teste que amarrasse isso
    quebraria em toda troca de estratégia sem nada ter mudado para quem chama.

    Verificado por mutação: trocar a floresta por um `LogisticRegression` sem
    imputação faz este teste falhar. Ele *não* falha ao remover só o
    `SimpleImputer`, e isso é informação, não fraqueza — ver a nota sobre NaN na
    docstring de `treino.py`.
    """
    modelo = treino.carrega_modelo(
        treino.salva_modelo(resultado, tmp_path / "modelo.joblib")
    )

    clipe_sem_rosto = pd.DataFrame([{coluna: np.nan for coluna in colunas_features()}])
    clipe_sem_rosto["prop_frames_com_rosto"] = 0.0

    previsoes = modelo.preve(clipe_sem_rosto)

    assert len(previsoes) == 1
    assert previsoes[0] in modelo.rotulos


# --- validação de entrada --------------------------------------------------


def test_treina_rejeita_dataset_fora_do_contrato(clipes: pd.DataFrame) -> None:
    with pytest.raises(EsquemaInvalido):
        treino.treina(clipes.drop(columns=["ear_media"]))


def test_treina_rejeita_split_ausente(clipes: pd.DataFrame) -> None:
    sem_teste = clipes[clipes[COLUNA_SPLIT] != "Test"]

    with pytest.raises(treino.SplitAusente) as erro:
        treino.treina(sem_teste)

    assert "Test" in str(erro.value)


def test_treina_rejeita_split_desconhecido(clipes: pd.DataFrame) -> None:
    bagunca = clipes.copy()
    bagunca.loc[bagunca.index[0], COLUNA_SPLIT] = "treino"

    with pytest.raises(treino.SplitInvalido):
        treino.treina(bagunca)


def test_treina_rejeita_classe_unica_no_treino(clipes: pd.DataFrame) -> None:
    degenerado = clipes.copy()
    degenerado.loc[degenerado[COLUNA_SPLIT] == "Train", "engagement"] = 3

    with pytest.raises(treino.ClasseUnica):
        treino.treina(degenerado)


def test_treina_rejeita_alvo_desconhecido(clipes: pd.DataFrame) -> None:
    with pytest.raises(treino.AlvoInvalido):
        treino.treina(clipes, alvo="engajamento")


def test_treina_rejeita_modo_desconhecido(clipes: pd.DataFrame) -> None:
    with pytest.raises(treino.ModoInvalido):
        treino.treina(clipes, modo="regressao")


def test_treina_rejeita_corte_fora_dos_niveis(clipes: pd.DataFrame) -> None:
    with pytest.raises(treino.CorteInvalido):
        treino.treina(clipes, corte=0)


def test_treina_rejeita_rotulo_ausente(clipes: pd.DataFrame) -> None:
    """Clipe sem rótulo é falha de junção na ticket 1, não amostra a imputar."""
    sem_rotulo = clipes.copy()
    sem_rotulo["engagement"] = sem_rotulo["engagement"].astype(float)
    sem_rotulo.loc[sem_rotulo.index[0], "engagement"] = np.nan

    with pytest.raises(treino.AlvoInvalido):
        treino.treina(sem_rotulo)


def test_treina_rejeita_rotulo_fora_de_0_a_3(clipes: pd.DataFrame) -> None:
    invalido = clipes.copy()
    invalido.loc[invalido.index[0], "engagement"] = 9

    with pytest.raises(treino.AlvoInvalido):
        treino.treina(invalido)


# --- serialização ----------------------------------------------------------


def test_round_trip_preserva_as_predicoes(
    resultado: "treino.ResultadoTreino", clipes: pd.DataFrame, tmp_path
) -> None:
    caminho = tmp_path / "modelo.joblib"
    treino.salva_modelo(resultado, caminho)

    modelo = treino.carrega_modelo(caminho)
    teste = clipes[clipes[COLUNA_SPLIT] == "Test"]

    esperado = resultado.estimador.predict(teste[colunas_features()])
    assert np.array_equal(modelo.preve(teste), esperado)


def test_artefato_carrega_contexto_junto_do_estimador(
    resultado: "treino.ResultadoTreino", tmp_path
) -> None:
    caminho = tmp_path / "modelo.joblib"
    treino.salva_modelo(resultado, caminho)

    modelo = treino.carrega_modelo(caminho)

    assert modelo.colunas == colunas_features()
    assert modelo.rotulos == [0, 1]
    assert modelo.nomes_rotulos == {0: "nao_engajado", 1: "engajado"}
    assert modelo.parametros == resultado.parametros
    assert modelo.versao_sklearn


def test_preve_ignora_a_ordem_das_colunas_do_chamador(
    resultado: "treino.ResultadoTreino", clipes: pd.DataFrame, tmp_path
) -> None:
    caminho = tmp_path / "modelo.joblib"
    treino.salva_modelo(resultado, caminho)
    modelo = treino.carrega_modelo(caminho)

    teste = clipes[clipes[COLUNA_SPLIT] == "Test"]
    embaralhado = teste[list(reversed(colunas_clipes()))]

    assert np.array_equal(modelo.preve(embaralhado), modelo.preve(teste))


def test_preve_probabilidades_devolve_uma_coluna_por_rotulo(
    resultado: "treino.ResultadoTreino", clipes: pd.DataFrame, tmp_path
) -> None:
    caminho = tmp_path / "modelo.joblib"
    treino.salva_modelo(resultado, caminho)
    modelo = treino.carrega_modelo(caminho)

    teste = clipes[clipes[COLUNA_SPLIT] == "Test"]
    proba = modelo.preve_probabilidades(teste)

    assert proba.shape == (len(teste), 2)
    assert np.allclose(proba.sum(axis=1), 1.0)


def test_preve_rejeita_dataframe_sem_as_features(
    resultado: "treino.ResultadoTreino", clipes: pd.DataFrame, tmp_path
) -> None:
    caminho = tmp_path / "modelo.joblib"
    treino.salva_modelo(resultado, caminho)
    modelo = treino.carrega_modelo(caminho)

    with pytest.raises(EsquemaInvalido):
        modelo.preve(clipes.drop(columns=["ear_media"]))


def test_salva_modelo_cria_a_pasta(resultado: "treino.ResultadoTreino", tmp_path) -> None:
    caminho = tmp_path / "artefatos" / "modelo.joblib"

    assert treino.salva_modelo(resultado, caminho).exists()


def test_carrega_modelo_avisa_quando_a_versao_do_sklearn_mudou(
    resultado: "treino.ResultadoTreino", tmp_path
) -> None:
    import joblib

    caminho = tmp_path / "modelo.joblib"
    treino.salva_modelo(resultado, caminho)
    artefato = joblib.load(caminho)
    artefato["versao_sklearn"] = "0.0.0"
    joblib.dump(artefato, caminho)

    with pytest.warns(treino.VersaoSklearnDiferente):
        treino.carrega_modelo(caminho)


def test_carrega_modelo_rejeita_artefato_estranho(tmp_path) -> None:
    import joblib

    caminho = tmp_path / "nu.joblib"
    joblib.dump({"apenas": "um dicionário qualquer"}, caminho)

    with pytest.raises(treino.ArtefatoInvalido):
        treino.carrega_modelo(caminho)


def test_carrega_modelo_de_artefato_valido_nao_avisa(
    resultado: "treino.ResultadoTreino", tmp_path
) -> None:
    caminho = tmp_path / "modelo.joblib"
    treino.salva_modelo(resultado, caminho)

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        treino.carrega_modelo(caminho)
