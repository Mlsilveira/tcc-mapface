"""Regras do ciclo de vida da sessão de estudo (ticket 4).

Concentra as decisões de negócio — quando uma sessão pode começar, quando ela
termina e o que conta como inatividade prolongada — fora do FastAPI, para que
sejam testáveis sem HTTP e reaproveitáveis pelo canal de telemetria da ticket 6.

O encerramento automático é uma varredura preguiçosa: roda a cada operação de
sessão, em vez de depender de um scheduler. Isso mantém a PoC sem processo de
background e ainda garante que ninguém observe uma sessão inativa como aberta —
quem consulta é justamente quem dispara a varredura.
"""
from datetime import datetime, timedelta
from typing import List, Optional

from sqlmodel import Session, select

from app.config import settings
from app.models import SessaoEstudo
from app.tempo import agora_utc, como_utc


class SessaoAtivaJaExiste(Exception):
    """O aluno já tem uma sessão em andamento — só se estuda uma de cada vez."""


class SessaoNaoEncontrada(Exception):
    """A sessão não existe, ou não pertence ao aluno que pediu."""


class SessaoJaEncerrada(Exception):
    """A sessão já tem `fim` registrado (manualmente ou por inatividade)."""


def limite_inatividade() -> timedelta:
    return timedelta(minutes=settings.sessao_inatividade_minutos)


def encerrar_inativas(db: Session, agora: Optional[datetime] = None) -> List[SessaoEstudo]:
    """Encerra toda sessão aberta cuja última atividade passou do limite.

    O `fim` gravado é a última atividade, não o instante da varredura: o tempo
    ocioso não é tempo de estudo e não pode inflar a duração da sessão.
    """
    agora = agora or agora_utc()
    corte = agora - limite_inatividade()

    abertas = db.exec(select(SessaoEstudo).where(SessaoEstudo.fim.is_(None))).all()
    encerradas = [s for s in abertas if como_utc(s.ultima_atividade) <= corte]

    for sessao in encerradas:
        sessao.fim = sessao.ultima_atividade
        db.add(sessao)

    if encerradas:
        db.commit()
        for sessao in encerradas:
            db.refresh(sessao)

    return encerradas


def buscar_ativa(
    db: Session, id_aluno: int, agora: Optional[datetime] = None
) -> Optional[SessaoEstudo]:
    agora = agora or agora_utc()
    encerrar_inativas(db, agora=agora)

    return db.exec(
        select(SessaoEstudo).where(
            SessaoEstudo.id_aluno == id_aluno, SessaoEstudo.fim.is_(None)
        )
    ).first()


def iniciar(db: Session, id_aluno: int, agora: Optional[datetime] = None) -> SessaoEstudo:
    agora = agora or agora_utc()

    if buscar_ativa(db, id_aluno, agora=agora) is not None:
        raise SessaoAtivaJaExiste

    sessao = SessaoEstudo(id_aluno=id_aluno, inicio=agora, ultima_atividade=agora)
    db.add(sessao)
    db.commit()
    db.refresh(sessao)
    return sessao


def registrar_atividade(
    db: Session, id_sessao: int, id_aluno: int, agora: Optional[datetime] = None
) -> SessaoEstudo:
    """Marca que o aluno continua presente, adiando o encerramento automático."""
    agora = agora or agora_utc()
    sessao = _buscar_em_andamento(db, id_sessao, id_aluno, agora)

    sessao.ultima_atividade = agora
    db.add(sessao)
    db.commit()
    db.refresh(sessao)
    return sessao


def encerrar(
    db: Session, id_sessao: int, id_aluno: int, agora: Optional[datetime] = None
) -> SessaoEstudo:
    agora = agora or agora_utc()
    sessao = _buscar_em_andamento(db, id_sessao, id_aluno, agora)

    sessao.fim = agora
    db.add(sessao)
    db.commit()
    db.refresh(sessao)
    return sessao


def _buscar_em_andamento(
    db: Session, id_sessao: int, id_aluno: int, agora: datetime
) -> SessaoEstudo:
    encerrar_inativas(db, agora=agora)

    sessao = db.get(SessaoEstudo, id_sessao)
    if sessao is None or sessao.id_aluno != id_aluno:
        # Sessão de outro aluno é indistinguível de sessão inexistente: nada
        # sobre os dados de um estudante vaza para outro.
        raise SessaoNaoEncontrada
    if sessao.fim is not None:
        raise SessaoJaEncerrada

    return sessao
