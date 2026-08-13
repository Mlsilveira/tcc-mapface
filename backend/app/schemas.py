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
