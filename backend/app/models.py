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

    As colunas de fadiga e alerta previstas no spec entram na ticket 8, junto
    com o modelo que as produz.
    """

    __tablename__ = "log_engajamento"

    id: Optional[int] = Field(default=None, primary_key=True)
    id_sessao: int = Field(foreign_key="sessao_estudo.id")
    horario_registro: datetime = Field(default_factory=agora_utc)
    score: float


class Calibracao(SQLModel, table=True):
    """A calibração de baseline de uma sessão de estudo (ticket 7).

    Vale aqui a mesma regra da `LogEngajamento`: nenhuma coluna de imagem, vídeo
    ou landmark bruto. O que atravessa a rede são as métricas já derivadas no
    navegador (EAR, yaw, pitch), e o que fica no banco são somas delas — não dá
    para reconstruir um rosto a partir de três acumuladores.

    Por que uma tabela, e não estado em memória: a calibração leva 60 segundos e
    o WebSocket da ticket 6 reconecta sozinho. Um acumulador preso à conexão
    recomeçaria do zero a cada queda, e numa rede ruim nunca terminaria. Some-se
    a isso o deploy em ECS Fargate da ticket 15, com mais de uma instância: nada
    que viva na memória de um processo sobrevive ao roteamento da reconexão.

    `id_sessao` é único: uma sessão tem no máximo uma calibração. A restrição
    está no schema, e não só no código, porque a corrida que a violaria é real —
    dois payloads quase simultâneos da mesma sessão, cada um vendo "ainda não
    existe". O banco recusa o segundo INSERT e `app/calibracao.py` converte a
    recusa em atualização.

    A baseline concluída mora em colunas próprias (`ear_neutro`, `yaw_neutro`,
    `pitch_neutro`) em vez de ser derivada das somas na leitura. Custa três
    colunas e paga duas coisas: o relatório da ticket 11 precisa explicar o
    score, e para isso tem que ler a baseline que de fato valeu — não uma
    divisão refeita depois, sujeita a arredondamento diferente do que rodou ao
    vivo. E as somas continuam ao lado como a evidência de onde ela saiu.

    "Ainda calibrando" e "concluída" se distinguem por `concluida_em`: nulo
    enquanto acumula, preenchido quando fecha. Deduzir isso de
    `amostras >= alguma coisa` seria ambíguo — uma sessão com 60 amostras em 20
    segundos não terminou a janela — e o instante do fechamento é justamente um
    dado que a ticket 11 vai querer mostrar.
    """

    __tablename__ = "calibracao"

    id: Optional[int] = Field(default=None, primary_key=True)
    id_sessao: int = Field(foreign_key="sessao_estudo.id", index=True, unique=True)
    inicio: datetime = Field(default_factory=agora_utc)
    soma_ear: float = Field(default=0.0)
    soma_yaw: float = Field(default=0.0)
    soma_pitch: float = Field(default=0.0)
    amostras: int = Field(default=0)
    concluida_em: Optional[datetime] = Field(default=None)
    ear_neutro: Optional[float] = Field(default=None)
    yaw_neutro: Optional[float] = Field(default=None)
    pitch_neutro: Optional[float] = Field(default=None)
