"""CLI do classificador de sonolência: grade de experimentos, artefato e relatório.

Irmão de `treinar.py`. Roda a bateria inteira em vez de um treino só, porque a
lição do DAiSEE foi justamente essa: um número isolado não distingue "o modelo
aprendeu" de "o modelo respondeu sempre a mesma coisa e o dataset é
desbalanceado". Aqui cada configuração é medida contra o chute fixo, em cinco
folds disjuntos por participante, e tudo vai para o relatório — inclusive o que
não funcionou.

O que ele produz em `artefatos_fadiga/`:

    random_forest_fadiga.joblib   o modelo, com a ordem das features e o modo
                                  de normalização que ele espera
    relatorio.md                  a leitura humana
    relatorio.json                os mesmos números, para citar no TCC

Uso:

    python treinar_fadiga.py
    python treinar_fadiga.py --janelas dados_rldd/janelas.parquet --daisee dados/clipes.parquet
    python treinar_fadiga.py --rapido      # só os modelos principais, para conferir o caminho
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import pandas as pd

import combinado as cb
import relatorio_fadiga as rf
import treino_fadiga as tf
from esquema import COLUNAS_METRICAS, colunas_features
from esquema_rldd import COLUNA_PARTICIPANTE, COLUNA_SONOLENCIA

AQUI = Path(__file__).parent
JANELAS_PADRAO = AQUI / "dados_rldd" / "janelas.parquet"
DAISEE_PADRAO = AQUI / "dados" / "clipes.parquet"
SAIDA_PADRAO = AQUI / "artefatos_fadiga"

NOME_MODELO = "random_forest_fadiga.joblib"

#: Os modelos que entram na grade no modo rápido — o chão e a floresta contida.
MODELOS_RAPIDOS = ("chute_majoritario", "floresta_regularizada")

#: Subconjuntos de features testados na ablação. Cada um responde a uma pergunta
#: concreta sobre de onde vem o sinal.
def conjuntos_de_features() -> Dict[str, List[str]]:
    todas = colunas_features()
    por_metrica = lambda prefixos: [
        c for c in todas if any(c.startswith(f"{p}_") for p in prefixos)
    ]
    derivadas = [c for c in todas if not any(c.startswith(f"{m}_") for m in COLUNAS_METRICAS)]

    return {
        "todas": todas,
        "so_olhos": por_metrica(["ear", "ear_esq", "ear_dir"]),
        "so_boca": por_metrica(["mar"]),
        "so_cabeca": por_metrica(["yaw", "pitch", "roll"]),
        "sem_cabeca": [c for c in todas if c not in por_metrica(["yaw", "pitch", "roll"])],
        "so_derivadas": derivadas,
    }


def carrega_janelas(caminho: Path, fala) -> pd.DataFrame:
    if not caminho.is_file():
        raise SystemExit(
            f"{caminho} não existe. Rode `extrair_rldd.py` antes — ou aponte --janelas."
        )
    janelas = pd.read_parquet(caminho)
    fala(
        f"{len(janelas)} janelas de {janelas[COLUNA_PARTICIPANTE].nunique()} participantes; "
        f"estados {janelas[COLUNA_SONOLENCIA].value_counts().sort_index().to_dict()}"
    )
    return janelas


def roda_grade(
    janelas: pd.DataFrame,
    modelos: Iterable[str],
    normalizacoes: Iterable[str],
    alvo: str,
    fala,
) -> List[tf.ResultadoDaValidacao]:
    """Cada modelo contra cada normalização, no mesmo alvo."""
    catalogo = tf.catalogo_de_modelos()
    resultados: List[tf.ResultadoDaValidacao] = []

    for normalizacao in normalizacoes:
        for nome in modelos:
            fala(f"  {nome} / {normalizacao} / {alvo}")
            resultado = tf.valida_cruzado(
                janelas, catalogo[nome], nome, alvo=alvo, normalizacao=normalizacao
            )
            fala(
                f"    acuracia_balanceada={resultado.acuracia_balanceada_media:.4f} "
                f"+-{resultado.acuracia_balanceada_desvio:.4f}"
            )
            resultados.append(resultado)

    return resultados


def melhor(
    resultados: List[tf.ResultadoDaValidacao], so_reproduziveis: bool = True
) -> tf.ResultadoDaValidacao:
    """A configuração de maior média, com o desvio como critério de desempate.

    Entre duas médias iguais vence a mais estável entre folds: com 60 pessoas,
    um modelo que varia muito de um grupo para outro promete um desempenho que
    não vai se repetir com o próximo aluno.

    **`so_reproduziveis` é o que impede um artefato impossível de alimentar.** A
    normalização por participante costuma ganhar da por sessão — ela usa as três
    gravações da pessoa, inclusive o futuro da sessão em curso. Escolher a
    melhor da grade sem filtro salvaria um modelo que espera uma entrada que o
    navegador não tem como produzir, e que em produção receberia números de
    outra distribuição sem reclamar de nada.
    """
    elegiveis = [
        r
        for r in resultados
        if not so_reproduziveis or r.normalizacao in tf.NORMALIZACOES_REPRODUZIVEIS
    ]
    if not elegiveis:
        raise SystemExit("nenhuma configuração reproduzível em produção na grade")

    return max(
        elegiveis,
        key=lambda r: (round(r.acuracia_balanceada_media, 4), -r.acuracia_balanceada_desvio),
    )


def roda_ablacao(
    janelas: pd.DataFrame, nome_do_modelo: str, normalizacao: str, alvo: str, fala
) -> pd.DataFrame:
    """Mede quanto cada grupo de features carrega, tirando-os um por vez."""
    catalogo = tf.catalogo_de_modelos()
    linhas = []

    for nome, colunas in conjuntos_de_features().items():
        if not colunas:
            continue
        fala(f"  ablacao: {nome} ({len(colunas)} colunas)")
        resultado = tf.valida_cruzado(
            janelas,
            catalogo[nome_do_modelo],
            nome_do_modelo,
            alvo=alvo,
            normalizacao=normalizacao,
            features=colunas,
        )
        linhas.append(
            {
                "conjunto": nome,
                "n_features": len(colunas),
                "acuracia_balanceada": resultado.acuracia_balanceada_media,
                "desvio_entre_folds": resultado.acuracia_balanceada_desvio,
            }
        )

    return pd.DataFrame(linhas).sort_values("acuracia_balanceada", ascending=False)


def roda_combinacao(
    janelas: pd.DataFrame, caminho_daisee: Path, pipeline, fala
) -> Optional[Dict[str, object]]:
    """Comparação de domínio, transferência e treino conjunto com o DAiSEE."""
    if not caminho_daisee.is_file():
        fala(f"{caminho_daisee} não existe; pulando a seção do DAiSEE")
        return None

    clipes = pd.read_parquet(caminho_daisee)
    fala(f"DAiSEE: {len(clipes)} clipes")

    daisee = cb.harmoniza_daisee(clipes)
    rldd = cb.harmoniza_rldd(janelas)

    fala("  comparando domínios")
    dominio_cru = cb.compara_dominios(daisee, rldd)
    dominio_normalizado = cb.compara_dominios(
        cb.normaliza_por_sujeito(daisee), cb.normaliza_por_sujeito(rldd)
    )

    fala("  transferindo para o DAiSEE")
    transferencia = cb.transfere_para_daisee(pipeline, daisee)

    fala("  treino conjunto")
    junto = cb.empilha(cb.normaliza_por_sujeito(daisee), cb.normaliza_por_sujeito(rldd))
    escolhidos = cb.sujeitos_de_teste(junto)
    comparacoes = cb.compara_sozinho_e_conjunto(
        junto, tf.catalogo_de_modelos()["floresta_regularizada"], escolhidos
    )

    return {
        "dominio_cru": dominio_cru,
        "dominio_normalizado": dominio_normalizado,
        "transferencia": transferencia,
        "comparacoes": comparacoes,
        "n_daisee": len(daisee),
        "n_rldd": len(rldd),
    }


def monta_relatorio(
    janelas: pd.DataFrame,
    grade: List[tf.ResultadoDaValidacao],
    escolhido: tf.ResultadoDaValidacao,
    outros_alvos: List[tf.ResultadoDaValidacao],
    ablacao: pd.DataFrame,
    ranking: Dict[str, float],
    combinacao: Optional[Dict[str, object]],
) -> str:
    nomes = {
        tf.ALVO_BINARIO: tf.NOMES_BINARIO,
        tf.ALVO_BINARIO_AMPLO: tf.NOMES_BINARIO_AMPLO,
        tf.ALVO_TERNARIO: tf.NOMES_TERNARIO,
    }[escolhido.alvo]

    pior = min(escolhido.folds, key=lambda f: f.acuracia_balanceada)

    partes = [
        "# Classificador de sonolência — UTA-RLDD",
        "",
        "Relatório gerado por `treinar_fadiga.py`. Todos os números vêm de validação "
        "cruzada nos cinco folds oficiais do dataset, disjuntos por participante: "
        "nenhuma pessoa aparece no treino e no teste da mesma medição.",
        "",
        "## O dataset",
        "",
        rf.tabela(
            pd.DataFrame(
                [
                    {
                        "janelas": len(janelas),
                        "participantes": janelas[COLUNA_PARTICIPANTE].nunique(),
                        "gravacoes": janelas.groupby(
                            [COLUNA_PARTICIPANTE, COLUNA_SONOLENCIA]
                        ).ngroups,
                        "segundos_por_janela": 10,
                    }
                ]
            )
        ),
        "",
        "Distribuição por estado declarado:",
        "",
        rf.tabela(
            janelas[COLUNA_SONOLENCIA]
            .value_counts()
            .sort_index()
            .rename_axis("estado")
            .reset_index(name="janelas")
        ),
        "",
        "**O rótulo é da gravação inteira, e a janela herda.** Ninguém fica sonolento "
        "em todos os segundos de dez minutos, então uma janela de um vídeo `10` pode "
        "mostrar a pessoa acordada. É ruído de rótulo inerente ao dataset, e é a "
        "primeira coisa que explica um teto de acurácia.",
        "",
        "## A grade de experimentos",
        "",
        rf.tabela(rf.grade_para_tabela(grade)),
        "",
        "O `chute_majoritario` é o chão: ele ignora a entrada. Qualquer configuração "
        "que não o supere com folga está dizendo que o sinal não está nas features.",
        "",
        "**A coluna `reproduzivel` é a que decide o que vai para produção.** A "
        "normalização `participante` usa as três gravações da pessoa para definir o "
        "que é normal nela — inclusive as que, do ponto de vista de uma sessão em "
        "curso, ainda não aconteceram. Ela fica na grade como **teto**: a distância "
        "entre ela e a `sessao` é exatamente o que se perde por só poder olhar para "
        "o passado. O artefato salvo nunca vem dela.",
        "",
        _nota_do_teto(grade),
        "",
        "## A configuração escolhida",
        "",
        f"`{escolhido.modelo}`, normalização `{escolhido.normalizacao}`, alvo "
        f"`{escolhido.alvo}`. É a melhor entre as reproduzíveis em produção.",
        "",
        rf.veredito(escolhido),
        "",
        "### Por fold",
        "",
        rf.tabela(rf.folds_para_tabela(escolhido)),
        "",
        f"### Métricas no pior fold ({pior.fold})",
        "",
        "O pior fold, e não a média: é ele que diz o que acontece quando o grupo de "
        "participantes do teste é o mais desfavorável dos cinco.",
        "",
        rf.tabela(rf.metricas_para_tabela(pior.metricas)),
        "",
        rf.tabela(rf.confusao_para_tabela(pior.metricas, nomes)),
        "",
        "## Os outros alvos",
        "",
        rf.tabela(rf.grade_para_tabela(outros_alvos)),
        "",
        "`binario` separa sonolento de alerta e descarta a vigilância baixa — é o "
        "corte dos autores e o mais usado na literatura. `binario_amplo` joga a "
        "fronteira para dentro do estado ambíguo e é mais próximo do que o produto "
        "quer penalizar: deixar de estar alerta, não dormir.",
        "",
        "## De onde vem o sinal",
        "",
        rf.tabela(ablacao),
        "",
        "### Importância das features",
        "",
        rf.tabela(rf.importancias_para_tabela(ranking)),
        "",
    ]

    if combinacao:
        partes += _secao_daisee(combinacao)

    partes += [
        "## Limitações",
        "",
        "1. **O rótulo é por gravação.** Toda janela de um vídeo `10` conta como "
        "sonolenta, inclusive as em que a pessoa está claramente acordada. O teto "
        "de acurácia mede isso junto com a dificuldade real.",
        "2. **A calibração por sessão é cega a estado constante.** A baseline sai "
        "das primeiras seis janelas da própria gravação; se a pessoa já começa "
        "sonolenta, a baseline é de uma pessoa sonolenta. É a mesma cegueira que o "
        "produto tem com um aluno que senta exausto — e a alternativa, comparar "
        "contra constante igual para todos, é o que a ticket 7 recusa.",
        "3. **Sonolência não é desengajamento.** O modelo aqui responde sobre estado "
        "físico. Usá-lo como medida de engajamento seria afirmar o que ele não mede.",
        "4. **60 participantes.** É o que o dataset tem. O desvio entre folds é o "
        "intervalo de confiança honesto do número, e está na tabela.",
        "",
    ]

    return "\n".join(partes)


def _nota_do_teto(grade: List[tf.ResultadoDaValidacao]) -> str:
    """Quanto a calibração por sessão deixa na mesa, em uma frase com número."""
    reproduziveis = [r for r in grade if r.normalizacao in tf.NORMALIZACOES_REPRODUZIVEIS]
    teto = [r for r in grade if r.normalizacao == tf.NORMALIZACAO_PARTICIPANTE]
    if not reproduziveis or not teto:
        return ""

    melhor_reproduzivel = max(reproduziveis, key=lambda r: r.acuracia_balanceada_media)
    melhor_teto = max(teto, key=lambda r: r.acuracia_balanceada_media)
    diferenca = melhor_teto.acuracia_balanceada_media - melhor_reproduzivel.acuracia_balanceada_media

    return (
        f"Medido nesta execução: o teto fica em {melhor_teto.acuracia_balanceada_media:.4f} "
        f"e o melhor reproduzível em {melhor_reproduzivel.acuracia_balanceada_media:.4f} — "
        f"uma diferença de {diferenca:.4f}. É o preço de calibrar com o passado, e ele "
        "é o mesmo que o produto paga: um aluno que senta já cansado calibra cansado."
    )


def _secao_daisee(c: Dict[str, object]) -> List[str]:
    t = c["transferencia"]
    dominio_cru: pd.DataFrame = c["dominio_cru"]
    dominio_norm: pd.DataFrame = c["dominio_normalizado"]

    comparacoes = pd.DataFrame(
        [
            {
                "avaliado_em": x.avaliado_em,
                "n_teste": x.n_teste,
                "treinado_so_nele": x.sozinho,
                "treinado_nos_dois": x.conjunto,
                "ganho": x.ganho,
            }
            for x in c["comparacoes"]
        ]
    )

    return [
        "## Os dois datasets juntos",
        "",
        f"{c['n_daisee']} clipes do DAiSEE e {c['n_rldd']} janelas do UTA-RLDD, com as "
        "mesmas 39 features.",
        "",
        "### Quanto os domínios diferem",
        "",
        "O DAiSEE é webcam de notebook a 640x480; o UTA-RLDD é celular em HD. Se as "
        "features separarem os datasets mais do que separam as pessoas dentro de "
        "cada um, qualquer transferência falha por motivo de câmera, não de "
        "comportamento. `d_de_cohen` acima de ~0,8 é onde isso começa a doer.",
        "",
        "As cinco features mais deslocadas, em valor absoluto:",
        "",
        rf.tabela(dominio_cru.head(5)),
        "",
        "E depois de medir cada pessoa contra ela mesma:",
        "",
        rf.tabela(dominio_norm.head(5)),
        "",
        "### Transferência: o modelo de sonolência aplicado ao DAiSEE",
        "",
        "O DAiSEE **não tem rótulo de sonolência** — ninguém perguntou aos anotadores "
        "se a pessoa estava com sono. Então isto não é acurácia: é a pergunta de se "
        "duas leituras independentes do mesmo rosto, um modelo treinado noutro "
        "dataset e um humano marcando tédio, apontam para o mesmo lado.",
        "",
        rf.tabela(
            pd.DataFrame(
                [
                    {
                        "clipes": t.n_clipes,
                        "auc_vs_tedio": t.auc_tedio,
                        "auc_vs_desengajamento": t.auc_desengajamento,
                        "sonolencia_prevista_entediado": t.media_prevista_entediado,
                        "sonolencia_prevista_nao_entediado": t.media_prevista_nao_entediado,
                    }
                ]
            )
        ),
        "",
        "AUC de 0,50 é moeda. Acima disso há concordância, e ela não pode vir de "
        "ajuste ao DAiSEE: o modelo nunca viu uma linha dele.",
        "",
        "### Treino conjunto",
        "",
        "Os dois datasets empilhados sob um alvo compartilhado de **baixo alerta**, "
        "com cada um avaliado no seu próprio teste — os mesmos sujeitos nas duas "
        "medições, fora de todos os treinos.",
        "",
        rf.tabela(comparacoes),
        "",
        "**Sonolência e desengajamento não são a mesma coisa.** Empilhar os dois é "
        "uma aposta explícita de que os estados compartilham assinatura facial "
        "suficiente. O `ganho` é o veredito: positivo, ver o outro dataset ajudou; "
        "negativo, atrapalhou.",
        "",
    ]


def _argumentos(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Treina e avalia o classificador de sonolência do UTA-RLDD."
    )
    parser.add_argument("--janelas", type=Path, default=JANELAS_PADRAO)
    parser.add_argument("--daisee", type=Path, default=DAISEE_PADRAO)
    parser.add_argument("--saida", type=Path, default=SAIDA_PADRAO)
    parser.add_argument("--rapido", action="store_true", help="só o chão e a floresta contida")
    parser.add_argument("--sem-daisee", action="store_true", help="pula a seção combinada")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = _argumentos(argv)
    fala = lambda msg: print(msg, file=sys.stderr, flush=True)

    janelas = carrega_janelas(args.janelas, fala)
    modelos = MODELOS_RAPIDOS if args.rapido else tuple(tf.catalogo_de_modelos())

    fala("grade de experimentos:")
    grade = roda_grade(
        janelas, modelos, tf.NORMALIZACOES_VALIDAS, tf.ALVO_BINARIO, fala
    )
    escolhido = melhor(grade)
    fala(f"escolhido: {escolhido.modelo} / {escolhido.normalizacao}")

    fala("outros alvos:")
    outros_alvos = [
        tf.valida_cruzado(
            janelas,
            tf.catalogo_de_modelos()[escolhido.modelo],
            escolhido.modelo,
            alvo=alvo,
            normalizacao=escolhido.normalizacao,
        )
        for alvo in (tf.ALVO_BINARIO, tf.ALVO_BINARIO_AMPLO, tf.ALVO_TERNARIO)
    ]

    fala("ablação de features:")
    ablacao = roda_ablacao(
        janelas, escolhido.modelo, escolhido.normalizacao, escolhido.alvo, fala
    )

    fala("treino final no dataset inteiro")
    pipeline, _, y = tf.treina_final(
        janelas,
        tf.catalogo_de_modelos()[escolhido.modelo],
        alvo=escolhido.alvo,
        normalizacao=escolhido.normalizacao,
    )
    ranking = tf.importancias(pipeline)

    combinacao = None
    if not args.sem_daisee:
        combinacao = roda_combinacao(janelas, args.daisee, pipeline, fala)

    args.saida.mkdir(parents=True, exist_ok=True)
    parametros = tf.ParametrosFadiga(
        modelo=escolhido.modelo,
        alvo=escolhido.alvo,
        normalizacao=escolhido.normalizacao,
        janelas_de_calibracao=tf.JANELAS_DE_CALIBRACAO,
        segundos_por_janela=10,
    )
    caminho_modelo = tf.salva_modelo(
        pipeline, parametros, sorted(y.unique()), tf.NOMES_BINARIO, args.saida / NOME_MODELO
    )

    markdown = monta_relatorio(
        janelas, grade, escolhido, outros_alvos, ablacao, ranking, combinacao
    )
    (args.saida / "relatorio.md").write_text(markdown, encoding="utf-8")

    resumo = {
        "parametros": asdict(parametros),
        "grade": rf.grade_para_tabela(grade).to_dict(orient="records"),
        "escolhido": {
            "modelo": escolhido.modelo,
            "normalizacao": escolhido.normalizacao,
            "alvo": escolhido.alvo,
            "acuracia_balanceada": escolhido.acuracia_balanceada_media,
            "desvio_entre_folds": escolhido.acuracia_balanceada_desvio,
            "f1_macro": escolhido.f1_macro_medio,
            "por_fold": rf.folds_para_tabela(escolhido).to_dict(orient="records"),
        },
        "outros_alvos": rf.grade_para_tabela(outros_alvos).to_dict(orient="records"),
        "ablacao": ablacao.to_dict(orient="records"),
        "importancias": ranking,
    }
    if combinacao:
        resumo["combinado"] = {
            "transferencia": asdict(combinacao["transferencia"]),
            "treino_conjunto": [asdict(c) for c in combinacao["comparacoes"]],
            "dominio_cru": combinacao["dominio_cru"].head(10).to_dict(orient="records"),
            "dominio_normalizado": combinacao["dominio_normalizado"]
            .head(10)
            .to_dict(orient="records"),
        }
    (args.saida / "relatorio.json").write_text(
        json.dumps(resumo, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    fala(f"{caminho_modelo}")
    fala(f"{args.saida / 'relatorio.md'}")
    fala(f"{args.saida / 'relatorio.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
