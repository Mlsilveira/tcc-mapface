"""Persistência da série de engajamento de uma sessão (ticket 6).

Como `app/sessoes.py`, este módulo não conhece HTTP nem WebSocket.

O **cálculo** do score morava aqui na ticket 6, como fórmula provisória contra
constantes iguais para todo mundo. A ticket 7 o moveu para `app/analista.py`,
onde ele passou a ser medido contra a baseline calibrada de cada aluno. O que
sobra aqui é o que sempre foi de persistência: gravar e ler os pontos da série.
"""

from datetime import datetime
from typing import List, Optional, Sequence

from sqlmodel import Session, select

from app.models import LogEngajamento
from app.tempo import agora_utc


def registrar_log(
    db: Session,
    id_sessao: int,
    score: float,
    agora: Optional[datetime] = None,
    fator_fadiga: float = 0.0,
    alertas: Sequence[str] = (),
    direcao_olhar: Optional[float] = None,
    ear: Optional[float] = None,
    mar: Optional[float] = None,
) -> LogEngajamento:
    """Grava um ponto da série de engajamento da sessão.

    Tudo além de `score` tem default porque a série continua fazendo sentido sem
    esses campos: um payload sem `mar` não produz alerta de bocejo, e um instante
    sem rosto não produz direção de olhar. Gravar zero ou vazio ali é registrar o
    que de fato se observou, e não um buraco.

    `alertas` chega como sequência e é achatado numa string separada por vírgula.
    A alternativa — uma tabela de alertas por log — seria a modelagem correta se
    alertas tivessem atributos próprios; eles não têm, são rótulos. Uma tabela
    para guardar rótulo custaria um join em toda leitura do relatório para não
    guardar nada a mais.
    """
    log = LogEngajamento(
        id_sessao=id_sessao,
        score=score,
        horario_registro=agora or agora_utc(),
        fator_fadiga=fator_fadiga,
        # O flag é derivado aqui, num lugar só, para não haver como gravar uma
        # linha em que ele discorde do fator.
        flag_fadiga=fator_fadiga > 0,
        alerta_gerado=",".join(alertas) or None,
        direcao_olhar=direcao_olhar,
        ear=ear,
        mar=mar,
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
