from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlmodel import Session, select

from app.database import get_session
from app.models import Aluno
from app.security import decodificar_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")


def get_aluno_atual(
    token: str = Depends(oauth2_scheme),
    session: Session = Depends(get_session),
) -> Aluno:
    credenciais_invalidas = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Não foi possível validar as credenciais",
        headers={"WWW-Authenticate": "Bearer"},
    )

    email = decodificar_token(token)
    if email is None:
        raise credenciais_invalidas

    aluno = session.exec(select(Aluno).where(Aluno.email == email)).first()
    if aluno is None:
        raise credenciais_invalidas

    return aluno
