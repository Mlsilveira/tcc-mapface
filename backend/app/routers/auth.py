from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from app.database import get_session
from app.deps import get_aluno_atual, oauth2_scheme
from app.models import Aluno
from app.schemas import AlunoLogin, AlunoPublico, AlunoRegistro, Token
from app.security import criar_token_acesso, hash_senha, renovar_token, verificar_senha

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


@router.post("/renovar", response_model=Token)
def renovar(
    aluno_atual: Aluno = Depends(get_aluno_atual),
    token: str = Depends(oauth2_scheme),
) -> Token:
    """Devolve um token novo em troca de um ainda válido (janela deslizante).

    Um endpoint só e um tipo de token só. O par access+refresh, que seria a
    resposta canônica, foi descartado porque o ganho dele é poder **revogar**, e
    revogação exige estado no servidor que este projeto não tem — sem isso,
    dois tokens são um token com cerimônia. O raciocínio inteiro, com as quatro
    alternativas, está no docstring de `app.security`.

    `get_aluno_atual` está aqui por dois motivos, e o segundo não é redundante
    com `renovar_token`: ele garante que **token expirado não ressuscita** (401
    antes de qualquer coisa) e que o aluno ainda existe no banco — um token
    perfeitamente assinado de uma conta removida não deve render credencial
    nova.

    O 401 devolvido daqui significa outra coisa que o 401 de `/auth/me`: não é
    "sua credencial não vale", é "sua credencial vale mas chegou ao teto de
    tempo desde o login". Para o cliente o desfecho é o mesmo — voltar à tela de
    login —, e por isso não ganha um código próprio.
    """
    novo_token = renovar_token(token)
    if novo_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credencial expirada: faça login novamente",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return Token(access_token=novo_token)


@router.get("/me", response_model=AlunoPublico)
def perfil(aluno_atual: Aluno = Depends(get_aluno_atual)) -> Aluno:
    """Endpoint de exemplo protegido — usado para provar que a autenticação bloqueia acesso sem token."""
    return aluno_atual
