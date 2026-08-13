from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from app.database import get_session
from app.deps import get_aluno_atual
from app.models import Aluno
from app.schemas import AlunoLogin, AlunoPublico, AlunoRegistro, Token
from app.security import criar_token_acesso, hash_senha, verificar_senha

router = APIRouter(prefix="/auth", tags=["autenticação"])


@router.post("/registro", response_model=AlunoPublico, status_code=status.HTTP_201_CREATED)
def registrar(dados: AlunoRegistro, session: Session = Depends(get_session)) -> Aluno:
    email_existente = session.exec(select(Aluno).where(Aluno.email == dados.email)).first()
    if email_existente is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="E-mail já cadastrado"
        )

    aluno = Aluno(nome=dados.nome, email=dados.email, senha_hash=hash_senha(dados.senha))
    session.add(aluno)
    session.commit()
    session.refresh(aluno)
    return aluno


@router.post("/login", response_model=Token)
def login(dados: AlunoLogin, session: Session = Depends(get_session)) -> Token:
    aluno = session.exec(select(Aluno).where(Aluno.email == dados.email)).first()
    if aluno is None or not verificar_senha(dados.senha, aluno.senha_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="E-mail ou senha inválidos"
        )

    token = criar_token_acesso(aluno.email)
    return Token(access_token=token)


@router.get("/me", response_model=AlunoPublico)
def perfil(aluno_atual: Aluno = Depends(get_aluno_atual)) -> Aluno:
    """Endpoint de exemplo protegido — usado para provar que a autenticação bloqueia acesso sem token."""
    return aluno_atual
