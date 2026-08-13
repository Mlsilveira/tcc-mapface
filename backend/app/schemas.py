from pydantic import BaseModel, EmailStr, Field


class AlunoRegistro(BaseModel):
    nome: str = Field(min_length=1)
    email: EmailStr
    senha: str = Field(min_length=8)


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
