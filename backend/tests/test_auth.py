"""Testes do fluxo de cadastro e login (ticket 3).

Cobrem os critérios de aceite:
- registro com hashing bcrypt
- login retornando JWT
- rota protegida exige token válido (e rejeita token expirado/ausente)
"""
from datetime import datetime, timedelta, timezone

from jose import jwt
from sqlmodel import Session, select

from app.config import settings
from app.models import Aluno

PAYLOAD_PADRAO = {"nome": "Ana Souza", "email": "ana@exemplo.com", "senha": "senhaSegura123"}


def registrar(client, payload=None):
    return client.post("/auth/registro", json=payload or PAYLOAD_PADRAO)


def login(client, email=None, senha=None):
    dados = {
        "email": email or PAYLOAD_PADRAO["email"],
        "senha": senha or PAYLOAD_PADRAO["senha"],
    }
    return client.post("/auth/login", json=dados)


class TestRegistro:
    def test_cria_aluno_e_nao_retorna_a_senha(self, client):
        resposta = registrar(client)

        assert resposta.status_code == 201
        corpo = resposta.json()
        assert corpo["email"] == PAYLOAD_PADRAO["email"]
        assert "senha" not in corpo
        assert "senha_hash" not in corpo

    def test_senha_e_armazenada_com_hash_bcrypt(self, client, session: Session):
        registrar(client)

        aluno = session.exec(
            select(Aluno).where(Aluno.email == PAYLOAD_PADRAO["email"])
        ).first()

        assert aluno is not None
        assert aluno.senha_hash != PAYLOAD_PADRAO["senha"]
        assert aluno.senha_hash.startswith("$2b$")

    def test_rejeita_email_duplicado(self, client):
        registrar(client)
        resposta_duplicada = registrar(client)

        assert resposta_duplicada.status_code == 409

    def test_rejeita_senha_curta_demais(self, client):
        resposta = registrar(client, {**PAYLOAD_PADRAO, "senha": "curta"})

        assert resposta.status_code == 422

    def test_rejeita_senha_acima_do_limite_do_bcrypt(self, client):
        # bcrypt rejeita segredos acima de 72 bytes. Sem um limite explícito no
        # schema, a senha vaza para o hash e derruba o endpoint com 500.
        resposta = registrar(client, {**PAYLOAD_PADRAO, "senha": "a" * 73})

        assert resposta.status_code == 422

    def test_limite_da_senha_e_medido_em_bytes_e_nao_em_caracteres(self, client):
        # 40 caracteres, mas 80 bytes em UTF-8: um limite por caractere deixaria
        # passar e o bcrypt estouraria. Cenário realista em português.
        senha = "çã" * 20

        assert len(senha) == 40 and len(senha.encode("utf-8")) == 80
        assert registrar(client, {**PAYLOAD_PADRAO, "senha": senha}).status_code == 422

    def test_aceita_senha_exatamente_no_limite_de_72_bytes(self, client):
        resposta = registrar(client, {**PAYLOAD_PADRAO, "senha": "a" * 72})

        assert resposta.status_code == 201


class TestLogin:
    def test_credenciais_corretas_retornam_jwt(self, client):
        registrar(client)

        resposta = login(client)

        assert resposta.status_code == 200
        corpo = resposta.json()
        assert corpo["token_type"] == "bearer"
        assert corpo["access_token"]

    def test_senha_incorreta_retorna_401(self, client):
        registrar(client)

        resposta = login(client, senha="senhaErrada123")

        assert resposta.status_code == 401

    def test_email_inexistente_retorna_401(self, client):
        resposta = login(client, email="naoexiste@exemplo.com")

        assert resposta.status_code == 401

    def test_senha_absurdamente_longa_nao_derruba_o_endpoint(self, client):
        # Alcançável sem autenticação: se a senha chegar crua no bcrypt, um
        # request anônimo vira 500 em vez de 401.
        registrar(client)

        resposta = login(client, senha="a" * 500)

        assert resposta.status_code == 401


class TestRotaProtegida:
    def test_sem_token_retorna_401(self, client):
        resposta = client.get("/auth/me")

        assert resposta.status_code == 401

    def test_token_valido_retorna_dados_do_aluno_autenticado(self, client):
        registrar(client)
        token = login(client).json()["access_token"]

        resposta = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

        assert resposta.status_code == 200
        assert resposta.json()["email"] == PAYLOAD_PADRAO["email"]

    def test_token_malformado_retorna_401(self, client):
        resposta = client.get("/auth/me", headers={"Authorization": "Bearer token-invalido"})

        assert resposta.status_code == 401

    def test_token_expirado_retorna_401(self, client):
        token_expirado = jwt.encode(
            {
                "sub": PAYLOAD_PADRAO["email"],
                "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
            },
            settings.secret_key,
            algorithm=settings.algorithm,
        )

        resposta = client.get(
            "/auth/me", headers={"Authorization": f"Bearer {token_expirado}"}
        )

        assert resposta.status_code == 401
