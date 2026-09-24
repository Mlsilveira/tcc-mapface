"""Contrato de dados do UTA-RLDD — o dataset de sonolência.

Módulo **novo e separado** de `esquema`, de propósito. O contrato do DAiSEE já
está em produção: ele descreve clipes de 10s com quatro rótulos de 0 a 3, e
qualquer coisa que se mexa lá arrisca o pipeline que já rodou ponta a ponta.
Aqui o espaço de rótulo é outro — um único rótulo de sonolência, com três
níveis — e misturar os dois num arquivo só faria cada leitor ter de descobrir,
coluna a coluna, qual metade se aplica ao seu dataset.

**O que os dois contratos compartilham é justamente o que interessa:** as 39
features de `esquema.colunas_features()` são as mesmas, calculadas pelo mesmo
extrator e pela mesma agregação. É isso que permite treinar nos dois datasets
com o mesmo código, comparar resultados entre eles, e — se um dia fizer sentido
— juntar as linhas.

**O que o UTA-RLDD é.** 60 participantes, três vídeos de ~10 minutos cada,
gravados pelos próprios participantes em ambiente real (não encenado em
laboratório, e é isso que o nome "Real-Life" quer dizer). O nome do arquivo é o
rótulo: `0` alerta, `5` vigilância baixa, `10` sonolento — a escala KSS
condensada em três pontos pelos autores.

**O rótulo é do vídeo inteiro, e a janela herda.** Ninguém fica sonolento em
todos os segundos de dez minutos, então uma janela de 10s de um vídeo `10` pode
perfeitamente mostrar a pessoa acordada. Isso é ruído de rótulo, é inerente ao
dataset, e todo trabalho publicado sobre ele carrega o mesmo — mas precisa estar
escrito, porque é a primeira coisa que explica um teto de acurácia.
"""
from typing import List

import pandas as pd

from esquema import EsquemaInvalido, colunas_features

# --- Identidade ------------------------------------------------------------

#: Identificador da janela. Formato `rldd-<participante>-<estado>-<parte>-<janela>`,
#: por exemplo `rldd-01-10-1-0003`. O id carrega tudo o que define a linha, então
#: o catálogo de rótulos é reconstruível a partir dos frames extraídos — não é
#: preciso um CSV à parte que possa sair de sincronia.
COLUNA_JANELA = "clip_id"

#: Participante, de "01" a "60". É a unidade de independência: nenhum
#: participante pode aparecer em dois lados de um split, senão o modelo aprende
#: o rosto em vez do estado.
COLUNA_PARTICIPANTE = "participante"

#: Fold oficial do dataset, de 1 a 5. Os autores já distribuíram os 60
#: participantes em cinco grupos disjuntos — usar os folds deles em vez de
#: sortear os nossos é o que torna o resultado comparável com a literatura.
COLUNA_FOLD = "fold"

#: Alguns participantes têm o vídeo de sonolência partido em dois arquivos
#: (`10_1`, `10_2`). A parte entra na identidade para os ids não colidirem.
COLUNA_PARTE = "parte"

#: Índice da janela dentro da gravação, começando em 0. Guarda a ordem temporal,
#: que uma análise de sequência vai querer.
COLUNA_INDICE_JANELA = "indice_janela"

COLUNAS_IDENTIDADE: List[str] = [
    COLUNA_JANELA,
    COLUNA_PARTICIPANTE,
    COLUNA_FOLD,
    COLUNA_PARTE,
    COLUNA_INDICE_JANELA,
]

# --- Rótulo ----------------------------------------------------------------

#: Nível de sonolência declarado pelo participante para a gravação inteira.
COLUNA_SONOLENCIA = "sonolencia"

COLUNAS_ROTULOS: List[str] = [COLUNA_SONOLENCIA]

#: Os três níveis, preservados como o dataset os nomeia. Binarizar é decisão do
#: treino, não da extração — a mesma regra que vale para o DAiSEE.
ALERTA = 0
VIGILANCIA_BAIXA = 5
SONOLENTO = 10

NIVEIS_SONOLENCIA = (ALERTA, VIGILANCIA_BAIXA, SONOLENTO)

NOMES_DOS_NIVEIS = {
    ALERTA: "alerta",
    VIGILANCIA_BAIXA: "vigilancia_baixa",
    SONOLENTO: "sonolento",
}


def colunas_janelas() -> List[str]:
    """Todas as colunas do dataset por janela, na ordem canônica."""
    return COLUNAS_IDENTIDADE + colunas_features() + COLUNAS_ROTULOS


def valida_janelas(df: pd.DataFrame) -> None:
    """Levanta `EsquemaInvalido` se o DataFrame não seguir o contrato."""
    faltando = [coluna for coluna in colunas_janelas() if coluna not in df.columns]
    if faltando:
        raise EsquemaInvalido(f"janelas: colunas faltando: {faltando}")
