"""O que o titular pode fazer com a própria conta: aceitar, revogar, excluir.

Fica fora de `app/routers/auth.py` pelo mesmo motivo de `app/sessoes.py`: a
regra é testável sem subir HTTP, e o router só traduz o resultado.

**Revogar e excluir são coisas diferentes, e o termo diz isso.** A revogação
impede novas sessões e não apaga nada: o que foi tratado antes dela continua
sendo do titular, que ainda pode abrir seus relatórios. A exclusão apaga tudo.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import delete
from sqlmodel import Session, select

from app import analista, consentimento, sessoes
from app.models import Aluno, BlocoEstudo, LogEngajamento, ResumoSessao, SessaoEstudo
from app.tempo import agora_utc


def registrar_aceite(aluno: Aluno, agora: Optional[datetime] = None) -> None:
    """Carimba o aceite da versão atual. Quem chama é que grava.

    Limpa a revogação: aceitar de novo depois de revogar é o caminho de volta
    que o termo oferece, e a data antiga não pode continuar bloqueando a conta.
    """
    aluno.termo_versao = consentimento.VERSAO_TERMO
    aluno.termo_aceito_em = agora or agora_utc()
    aluno.consentimento_revogado_em = None


def aceitar(db: Session, aluno: Aluno, agora: Optional[datetime] = None) -> Aluno:
    registrar_aceite(aluno, agora)
    db.add(aluno)
    db.commit()
    db.refresh(aluno)
    return aluno


def _encerrar_ativa(db: Session, id_aluno: int, agora: datetime) -> None:
    ativa = sessoes.buscar_ativa(db, id_aluno)
    if ativa is not None:
        sessoes.encerrar(db, ativa.id, id_aluno, agora)


def revogar(db: Session, aluno: Aluno, agora: Optional[datetime] = None) -> Aluno:
    """Retira o consentimento e fecha a sessão que estiver aberta.

    A revogação é gravada **antes** de fechar a sessão: na ordem inversa, um
    `POST /sessoes` entre os dois passos abriria uma sessão nova com o aceite
    ainda valendo. É idempotente: revogar de novo não move a data original.
    """
    agora = agora or agora_utc()

    if aluno.termo_aceito_em is not None and aluno.consentimento_revogado_em is None:
        aluno.consentimento_revogado_em = agora
        db.add(aluno)
        db.commit()
        db.refresh(aluno)

    _encerrar_ativa(db, aluno.id, agora)
    return aluno


def excluir(db: Session, aluno: Aluno, agora: Optional[datetime] = None) -> None:
    """Apaga a conta e tudo o que está ligado a ela, numa transação só.

    A ordem é a das chaves estrangeiras, que não têm `ON DELETE CASCADE`: o
    PostgreSQL recusaria apagar a sessão com pontos ainda apontando para ela.

    A sessão aberta é encerrada primeiro, em commit próprio: é o que faz o canal
    de telemetria parar de gravar (`sessoes.em_andamento`) antes de as linhas
    começarem a sumir. O que estiver nas cópias automáticas de segurança do banco
    só sai quando elas vencem, e o termo diz isso.
    """
    agora = agora or agora_utc()
    _encerrar_ativa(db, aluno.id, agora)

    ids = list(db.exec(select(SessaoEstudo.id).where(SessaoEstudo.id_aluno == aluno.id)).all())

    if ids:
        db.exec(delete(LogEngajamento).where(LogEngajamento.id_sessao.in_(ids)))
        db.exec(delete(BlocoEstudo).where(BlocoEstudo.id_sessao.in_(ids)))
        db.exec(delete(ResumoSessao).where(ResumoSessao.id_sessao.in_(ids)))
        db.exec(delete(SessaoEstudo).where(SessaoEstudo.id.in_(ids)))

    db.delete(aluno)
    db.commit()

    for id_sessao in ids:
        analista.registro.descartar(id_sessao)
