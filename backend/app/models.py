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

    As colunas de fadiga entraram depois da ticket 8: o fator já era calculado e
    devolvido ao navegador, mas não era gravado — e o relatório da ticket 11
    precisa dos "alertas de fadiga registrados", que só existem se alguém os
    tiver registrado.

    **`flag_fadiga` e `fator_fadiga` convivem de propósito.** O spec previa só o
    booleano, e ele é o que responde "houve fadiga nesta sessão?" numa consulta
    direta. Mas um booleano não distingue um bocejo isolado de meia hora de
    pálpebra pesada, e é essa diferença que vira indicador-chave no relatório.
    O flag é sempre `fator_fadiga > 0`; há um teste que trava essa relação.
    """

    __tablename__ = "log_engajamento"

    id: Optional[int] = Field(default=None, primary_key=True)
    id_sessao: int = Field(foreign_key="sessao_estudo.id")
    horario_registro: datetime = Field(default_factory=agora_utc)
    score: float

    #: Houve penalidade de fadiga neste instante.
    flag_fadiga: bool = Field(default=False)

    #: Quanto a fadiga descontou do score, em pontos da escala de 0 a 100.
    fator_fadiga: float = Field(default=0.0)

    #: Motivos separados por vírgula (`palpebras-pesadas`, `bocejos`, ...), ou
    #: `None` quando não houve alerta. Coluna de texto e não booleana porque a
    #: ticket 10 grava aqui a "Incerteza de Captura" pelo mesmo canal — o spec
    #: chamou de `alerta_gerado`, no singular, mas o campo sempre foi o lugar de
    #: registrar *o que* o sistema quis dizer ao aluno naquele segundo.
    alerta_gerado: Optional[str] = Field(default=None)

    #: Desvio do yaw em relação à pose neutra do aluno, em graus, com sinal.
    #: É o desvio, e não o yaw absoluto: a mesma normalização que o IEE usa, e a
    #: única forma de a série significar a mesma coisa entre alunos que sentam
    #: de jeitos diferentes. `None` quando não havia rosto.
    direcao_olhar: Optional[float] = Field(default=None)
