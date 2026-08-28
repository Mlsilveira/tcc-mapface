from datetime import datetime
from typing import Annotated, Optional

from pydantic import AfterValidator, BaseModel, EmailStr, Field, field_validator

from app.tempo import como_utc

# bcrypt não aceita segredos acima de 72 bytes. O limite é em bytes, não em
# caracteres: acentos ocupam 2 bytes em UTF-8.
LIMITE_SENHA_BYTES = 72


def _dentro_do_limite_do_bcrypt(senha: str) -> str:
    if len(senha.encode("utf-8")) > LIMITE_SENHA_BYTES:
        raise ValueError(f"a senha não pode passar de {LIMITE_SENHA_BYTES} bytes")
    return senha


Senha = Annotated[str, Field(min_length=8), AfterValidator(_dentro_do_limite_do_bcrypt)]


class AlunoRegistro(BaseModel):
    nome: str = Field(min_length=1)
    email: EmailStr
    senha: Senha


class AlunoLogin(BaseModel):
    email: EmailStr
    senha: str


class AlunoPublico(BaseModel):
    id: int
    nome: str
    email: EmailStr

    model_config = {"from_attributes": True}


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ItemDoHistoricoPublico(BaseModel):
    """Uma sessão na lista de histórico (ticket 12).

    Traz o suficiente para o aluno escolher qual relatório abrir, sem que a
    lista precise carregar a série de cada sessão. O relatório completo continua
    em `GET /sessoes/{id}/relatorio`.
    """

    id_sessao: int
    inicio: datetime
    fim: Optional[datetime] = None
    #: `True` enquanto a sessão não foi encerrada — inclusive a que corre agora.
    parcial: bool
    duracao_s: float
    n_leituras: int
    score_medio: float
    teve_fadiga: bool

    model_config = {"from_attributes": True}


class IndicadoresPublicos(BaseModel):
    """Os números-chave da sessão (ticket 11)."""

    n_leituras: int
    duracao_s: float
    score_medio: float
    score_minimo: float
    score_maximo: float
    score_inicio: float
    score_fim: float
    prop_com_rosto: float
    prop_com_fadiga: float
    fadiga_maxima: float
    desvio_olhar_medio: float

    model_config = {"from_attributes": True}


class PontoDaSeriePublico(BaseModel):
    """Um instante do gráfico do IEE."""

    horario: datetime
    score: float
    fadiga: float
    alerta: Optional[str] = None

    model_config = {"from_attributes": True}


class RelatorioPublico(BaseModel):
    """Relatório de autopercepção de uma sessão.

    `parcial` é `True` quando a sessão não foi encerrada formalmente — queda de
    conexão, aba fechada. O relatório existe do mesmo jeito, com o que foi
    medido até ali, e a interface precisa poder dizer isso ao aluno em vez de
    apresentar dados incompletos como se fossem a sessão inteira.
    """

    id_sessao: int
    inicio: datetime
    fim: Optional[datetime] = None
    parcial: bool
    indicadores: IndicadoresPublicos
    serie: list[PontoDaSeriePublico]
    alertas: dict[str, int]
    recomendacoes: list[str]

    model_config = {"from_attributes": True}


class SessaoPublica(BaseModel):
    id: int
    id_aluno: int
    inicio: datetime
    fim: Optional[datetime] = None

    model_config = {"from_attributes": True}

    @field_validator("inicio", "fim")
    @classmethod
    def _explicitar_utc(cls, valor: Optional[datetime]) -> Optional[datetime]:
        # Sem fuso explícito, o navegador interpretaria o instante como hora
        # local e o horário da sessão apareceria deslocado na interface.
        return como_utc(valor) if valor is not None else None
