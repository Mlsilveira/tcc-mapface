from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from jose import JWTError, jwt

from app.config import settings
from app.schemas import LIMITE_SENHA_BYTES


def hash_senha(senha: str) -> str:
    return bcrypt.hashpw(senha.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verificar_senha(senha: str, senha_hash: str) -> bool:
    senha_bytes = senha.encode("utf-8")
    # O registro rejeita senhas acima do limite, então nenhum hash armazenado
    # pode corresponder a uma. Sem esta guarda o bcrypt levanta ValueError e o
    # login vira 500 em vez de 401.
    if len(senha_bytes) > LIMITE_SENHA_BYTES:
        return False
    return bcrypt.checkpw(senha_bytes, senha_hash.encode("utf-8"))


def criar_token_acesso(email: str) -> str:
    expira_em = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    payload = {"sub": email, "exp": expira_em}
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def decodificar_token(token: str) -> Optional[str]:
    """Retorna o e-mail (subject) do token, ou None se inválido/expirado."""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except JWTError:
        return None
    return payload.get("sub")
