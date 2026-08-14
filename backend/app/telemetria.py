"""Regra de telemetria: das métricas faciais ao score de engajamento (ticket 6).

Como `app/sessoes.py`, este módulo não conhece HTTP, WebSocket nem banco — é
onde os testes de comportamento batem, e é o embrião do `AnalistaEngajamento`
das tickets 7 e 8.

O score aqui é **provisório**, e existe para provar o pipeline ponta a ponta
antes da fórmula real do IEE. A estrutura de pesos já é a definitiva (0,6 para
abertura ocular, 0,4 para orientação da cabeça); o que muda na ticket 7 é a
origem das referências: hoje são as constantes abaixo, iguais para todo mundo,
e lá passam a ser a baseline calibrada de cada aluno nos primeiros 60 segundos.
"""

from datetime import datetime
from typing import List, Optional

from sqlmodel import Session, select

from app.models import LogEngajamento
from app.tempo import agora_utc

PESO_OCULAR = 0.6
PESO_ORIENTACAO = 0.4

#: EAR considerado "olho plenamente aberto". Constante provisória — na ticket 7
#: vira o EAR neutro medido do próprio aluno.
EAR_DE_REFERENCIA = 0.30

#: Desvio de yaw, em graus, a partir do qual a orientação não contribui mais.
#: Também provisório: a ticket 7 calibra contra a pose neutra do aluno.
YAW_MAXIMO_GRAUS = 45.0


def _normalizar(valor: float, referencia: float) -> float:
    """Leva `valor` para [0, 1] relativo a `referencia`."""
    if referencia <= 0:
        return 0.0
    return max(0.0, min(valor / referencia, 1.0))


def calcular_score(ear: float, yaw: float, rosto_detectado: bool = True) -> float:
    """Score provisório de engajamento, de 0 a 100.

    `rosto_detectado=False` zera o score: é o `P(t) = 0` do spec. Sem rosto não
    há comportamento observável, e devolver qualquer outro número seria invenção.
    """
    if not rosto_detectado:
        return 0.0

    ocular = _normalizar(ear, EAR_DE_REFERENCIA)
    orientacao = 1.0 - _normalizar(abs(yaw), YAW_MAXIMO_GRAUS)

    return 100.0 * (PESO_OCULAR * ocular + PESO_ORIENTACAO * orientacao)


def registrar_log(
    db: Session, id_sessao: int, score: float, agora: Optional[datetime] = None
) -> LogEngajamento:
    """Grava um ponto da série de engajamento da sessão."""
    log = LogEngajamento(
        id_sessao=id_sessao,
        score=score,
        horario_registro=agora or agora_utc(),
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


def buscar_logs(db: Session, id_sessao: int) -> List[LogEngajamento]:
    """Série de engajamento de uma sessão, em ordem cronológica."""
    return db.exec(
        select(LogEngajamento)
        .where(LogEngajamento.id_sessao == id_sessao)
        .order_by(LogEngajamento.horario_registro)
    ).all()
