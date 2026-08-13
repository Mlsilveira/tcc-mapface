from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel

from app.tempo import agora_utc


class Aluno(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    nome: str
    email: str = Field(index=True, unique=True)
    senha_hash: str


class SessaoEstudo(SQLModel, table=True):
    """Uma sessão de estudo monitorada, do "iniciar" ao "encerrar".

    `ultima_atividade` não está no schema do spec (id, id_aluno, inicio, fim):
    é uma coluna operacional, necessária para detectar inatividade prolongada e
    encerrar a sessão automaticamente. A partir da ticket 6 ela passa a ser
    atualizada também pelos payloads de telemetria.
    """

    __tablename__ = "sessao_estudo"

    id: Optional[int] = Field(default=None, primary_key=True)
    id_aluno: int = Field(foreign_key="aluno.id", index=True)
    inicio: datetime = Field(default_factory=agora_utc)
    fim: Optional[datetime] = Field(default=None)
    ultima_atividade: datetime = Field(default_factory=agora_utc)
