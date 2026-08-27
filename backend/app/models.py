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


class LogEngajamento(SQLModel, table=True):
    """Um registro de score de engajamento dentro de uma sessão (ticket 6).

    Não existe — e não pode passar a existir — nenhuma coluna de imagem, vídeo
    ou landmark bruto aqui. Os landmarks são calculados e descartados no
    navegador; o que chega ao banco é o score derivado deles. Há um teste que
    trava a lista de colunas exatamente para forçar essa conversa quando alguém
    quiser adicionar campo novo.

    `fadiga` e `alerta` são as colunas que o spec chama de `flag_fadiga` e
    `alerta_gerado`. Entraram na ticket 10, e não na 8, porque quem precisa
    delas gravadas é o relatório da ticket 11: o fator `F` já era calculado e
    devolvido ao navegador desde a 8, mas morria na conexão.
    """

    __tablename__ = "log_engajamento"

    id: Optional[int] = Field(default=None, primary_key=True)
    id_sessao: int = Field(foreign_key="sessao_estudo.id")
    horario_registro: datetime = Field(default_factory=agora_utc)

    #: `None` quando a captura foi descartada por incerteza (ticket 10). Não é o
    #: mesmo que zero: zero é "o aluno não estava lá", `None` é "não dá para
    #: afirmar nada sobre este segundo". Gravar um número inventado aqui seria
    #: exatamente o score enganoso que a ticket 10 existe para evitar.
    score: Optional[float] = Field(default=None)

    #: Quanto o fator de fadiga descontou deste ponto, em pontos do IEE.
    fadiga: float = Field(default=0.0)

    #: Rótulo curto do que houve de anormal: o motivo da incerteza quando
    #: `score is None`, ou o motivo dominante da fadiga quando há score. Os dois
    #: casos nunca se confundem porque `score` os separa.
    alerta: Optional[str] = Field(default=None)
