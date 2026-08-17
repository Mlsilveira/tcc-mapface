"""Persistência da série de engajamento de uma sessão (tickets 6 e 7).

Como `app/sessoes.py`, este módulo não conhece HTTP nem WebSocket — é onde os
testes de comportamento batem.

O `calcular_score` provisório da ticket 6 **não mora mais aqui**: ele existia
para provar o pipeline ponta a ponta antes da fórmula real, e a ticket 7 o
substituiu pelo `AnalistaEngajamento` de `app/analista.py`, que normaliza contra
a baseline calibrada de cada aluno em vez de contra constantes iguais para todo
mundo. O que sobrou neste módulo é só a gravação e a leitura dos logs.
"""

from datetime import datetime
from typing import List, Optional

from sqlmodel import Session, select

from app.models import LogEngajamento
from app.tempo import agora_utc


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
