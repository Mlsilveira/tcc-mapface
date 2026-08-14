"""Contrato de dados da trilha ML (tickets 1 e 2).

Este módulo é a fronteira entre a extração de features (ticket 1) e o treino do
Random Forest (ticket 2). Os dois lados importam daqui os nomes de coluna, então
renomear uma feature é uma mudança em um arquivo só — e o teste de contrato
quebra antes do pipeline.

São dois artefatos tabulares, não um:

- **frames** — uma linha por frame de vídeo. É a saída crua do MediaPipe, e
  existe porque o critério da ticket 1 pede EAR/Head Pose/MAR *por frame*, e
  porque a ticket 8 vai precisar de sequências temporais para detectar fadiga
  (pálpebra fechada prolongada, bocejo) — coisa que a média por clipe apaga.
- **clipes** — uma linha por clipe de 10s, com as features agregadas e os quatro
  rótulos do DAiSEE. É o que o Random Forest treina, porque o DAiSEE rotula por
  clipe, não por frame.
"""
from typing import List

import pandas as pd

# --- Identidade ------------------------------------------------------------

#: Identificador do clipe no DAiSEE (nome do arquivo sem extensão, ex. "1100011002").
COLUNA_CLIPE = "clip_id"

#: Sujeito que aparece no clipe. O split do DAiSEE é *subject-independent*: um
#: mesmo usuário nunca aparece em dois splits. Guardamos para poder auditar isso.
COLUNA_USUARIO = "user_id"

#: "Train", "Validation" ou "Test", conforme a pasta de origem no DAiSEE.
COLUNA_SPLIT = "split"

COLUNAS_IDENTIDADE: List[str] = [COLUNA_CLIPE, COLUNA_USUARIO, COLUNA_SPLIT]

SPLITS_VALIDOS = ("Train", "Validation", "Test")

# --- Rótulos ---------------------------------------------------------------

#: Os quatro rótulos originais do DAiSEE, cada um no intervalo inteiro 0..3.
#: Preservados como vêm do dataset: qualquer binarização é decisão do treino
#: (ticket 2), não da extração (ticket 1).
COLUNAS_ROTULOS: List[str] = ["engagement", "boredom", "confusion", "frustration"]

NIVEIS_ROTULO = (0, 1, 2, 3)

# --- Métricas por frame ----------------------------------------------------

#: Métricas cruas calculadas a partir dos 468 landmarks de um único frame.
#: Quando nenhum rosto é detectado, `face_detectada` é False e todas as demais
#: são NaN — nunca 0, que seria indistinguível de um olho de fato fechado.
COLUNAS_METRICAS: List[str] = [
    "ear_esq",   # eye aspect ratio do olho esquerdo
    "ear_dir",   # eye aspect ratio do olho direito
    "ear",       # média dos dois olhos
    "mar",       # mouth aspect ratio (proxy de bocejo)
    "yaw",       # rotação da cabeça em torno do eixo vertical, em graus
    "pitch",     # inclinação para cima/baixo, em graus
    "roll",      # inclinação lateral, em graus
]

COLUNAS_FRAMES: List[str] = [
    COLUNA_CLIPE,
    "frame_idx",
    "face_detectada",
] + COLUNAS_METRICAS

# --- Features por clipe ----------------------------------------------------

#: Agregações aplicadas a cada métrica dentro de um clipe. A mediana entra no
#: lugar da média para yaw/pitch/roll ser robusta a frames em que o MediaPipe
#: erra a pose; o desvio captura inquietação; min/max capturam extremos que a
#: média esconde (um único bocejo some numa média de 300 frames).
AGREGACOES = ("media", "desvio", "mediana", "min", "max")

#: Limiar de EAR abaixo do qual consideramos o olho fechado. Valor clássico da
#: literatura (Soukupová & Čech). Vive aqui, e não no extrator, porque o treino
#: precisa do mesmo número para interpretar `prop_olhos_fechados`.
LIMIAR_OLHOS_FECHADOS = 0.20

#: Limiar de MAR acima do qual a boca está aberta o suficiente para ser bocejo.
LIMIAR_BOCA_ABERTA = 0.60


def colunas_agregadas() -> List[str]:
    """Nomes das colunas agregadas, no formato `<metrica>_<agregacao>`."""
    return [f"{metrica}_{agg}" for metrica in COLUNAS_METRICAS for agg in AGREGACOES]


#: Features derivadas que não são simples agregações de uma métrica.
COLUNAS_DERIVADAS: List[str] = [
    "prop_frames_com_rosto",   # fração de frames em que houve rosto detectado
    "prop_olhos_fechados",     # fração de frames (com rosto) com ear < LIMIAR_OLHOS_FECHADOS
    "prop_boca_aberta",        # fração de frames (com rosto) com mar > LIMIAR_BOCA_ABERTA
    "n_frames",                # total de frames lidos do clipe
]


def colunas_features() -> List[str]:
    """Todas as colunas que o Random Forest recebe como entrada.

    A ordem é estável: o modelo serializado da ticket 2 é carregado pelo backend
    na ticket 8, e sklearn casa features por posição quando recebe um array.
    """
    return colunas_agregadas() + COLUNAS_DERIVADAS


def colunas_clipes() -> List[str]:
    """Todas as colunas do dataset por clipe, na ordem canônica."""
    return COLUNAS_IDENTIDADE + colunas_features() + COLUNAS_ROTULOS


class EsquemaInvalido(Exception):
    """O DataFrame não bate com o contrato — colunas faltando ou sobrando."""


def _valida(df: pd.DataFrame, esperadas: List[str], nome: str) -> None:
    faltando = [c for c in esperadas if c not in df.columns]
    if faltando:
        raise EsquemaInvalido(f"{nome}: colunas faltando: {faltando}")


def valida_frames(df: pd.DataFrame) -> None:
    """Levanta `EsquemaInvalido` se o DataFrame de frames não seguir o contrato."""
    _valida(df, COLUNAS_FRAMES, "frames")


def valida_clipes(df: pd.DataFrame) -> None:
    """Levanta `EsquemaInvalido` se o DataFrame de clipes não seguir o contrato."""
    _valida(df, colunas_clipes(), "clipes")
