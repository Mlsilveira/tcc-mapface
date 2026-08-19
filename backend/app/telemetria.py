"""Persistência da série de engajamento de uma sessão (ticket 6).

Como `app/sessoes.py`, este módulo não conhece HTTP nem WebSocket.

O **cálculo** do score morava aqui na ticket 6, como fórmula provisória contra
constantes iguais para todo mundo. A ticket 7 o moveu para `app/analista.py`,
onde ele passou a ser medido contra a baseline calibrada de cada aluno. O que
sobra aqui é o que sempre foi de persistência: gravar e ler os pontos da série.
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
