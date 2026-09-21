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


class TestRenovacaoDeCredencial:
    """A janela deslizante com teto absoluto (`POST /auth/renovar`).

    Os valores esperados aqui são calculados à mão a partir da definição, e não
    copiados da implementação:

    - `exp` de um token emitido em `t` é `t + access_token_expire_minutes`;
    - `iat` é o início da **sessão de credencial**, que não se move na renovação;
    - a renovação é recusada quando `agora - iat > teto_de_credencial_horas`.

    O relógio de `app.security` é substituído nos testes que precisam avançar o
    tempo. O relógio que valida assinatura e `exp` dentro do `jwt.decode`
    continua sendo o real, de propósito: é ele que prova que o token usado na
    renovação estava de fato vivo.
    """

    def _claims(self, token):
        return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])

    def _com_relogio(self, monkeypatch, instante):
        from app import security

        monkeypatch.setattr(security, "agora_utc", lambda: instante)

    def test_login_carimba_o_inicio_da_sessao_de_credencial(self, client, monkeypatch):
        t0 = datetime.now(timezone.utc).replace(microsecond=0)
        self._com_relogio(monkeypatch, t0)
        registrar(client)

        claims = self._claims(login(client).json()["access_token"])

        assert claims["iat"] == int(t0.timestamp())
        # exp = instante da emissão + a janela configurada.
        assert claims["exp"] == int(
            (t0 + timedelta(minutes=settings.access_token_expire_minutes)).timestamp()
        )

    def test_renovacao_preserva_o_inicio_da_sessao_de_credencial(
        self, client, monkeypatch
    ):
        """É este carimbo que separa "desliza" de "nunca expira".

        Se a renovação recarimbasse o início, o teto jamais seria alcançado:
        bastaria um request a cada 29 minutos — e o heartbeat de 60 s faz isso
        sozinho, com a aba aberta e ninguém na frente dela.
        """
        registrar(client)
        t0 = datetime.now(timezone.utc).replace(microsecond=0)
        self._com_relogio(monkeypatch, t0)
        token = login(client).json()["access_token"]

        self._com_relogio(monkeypatch, t0 + timedelta(minutes=20))
        resposta = client.post("/auth/renovar", headers={"Authorization": f"Bearer {token}"})

        assert resposta.status_code == 200
        claims = self._claims(resposta.json()["access_token"])
        assert claims["iat"] == int(t0.timestamp())
        assert claims["sub"] == PAYLOAD_PADRAO["email"]

    def test_o_token_renovado_vale_ate_mais_tarde_que_o_anterior(
        self, client, monkeypatch
    ):
        registrar(client)
        t0 = datetime.now(timezone.utc).replace(microsecond=0)
        self._com_relogio(monkeypatch, t0)
        token = login(client).json()["access_token"]

        self._com_relogio(monkeypatch, t0 + timedelta(minutes=20))
        renovado = client.post(
            "/auth/renovar", headers={"Authorization": f"Bearer {token}"}
        ).json()["access_token"]

        janela = timedelta(minutes=settings.access_token_expire_minutes)
        # Emitido aos 20 min, vale até 20 min + a janela; o anterior valia até a
        # janela contada de t0. A diferença entre os dois é exatamente os 20 min.
        assert self._claims(renovado)["exp"] == int((t0 + timedelta(minutes=20) + janela).timestamp())
        assert self._claims(renovado)["exp"] > self._claims(token)["exp"]

    def test_recusa_renovacao_depois_do_teto_de_credencial(self, client, monkeypatch):
        """Passado o teto, a linhagem acaba — o aluno faz login de novo.

        O token apresentado aqui continua **válido**: ele é aceito por
        `get_aluno_atual` e só é recusado pela regra do teto. É essa combinação
        que se quer provar, porque é ela que diferencia "credencial vencida" de
        "credencial que já viveu o bastante".
        """
        registrar(client)
        t0 = datetime.now(timezone.utc).replace(microsecond=0)
        self._com_relogio(monkeypatch, t0)
        token = login(client).json()["access_token"]

        # Um minuto além do teto: 12 h + 1 min desde o login.
        self._com_relogio(
            monkeypatch,
            t0 + timedelta(hours=settings.teto_de_credencial_horas, minutes=1),
        )
        resposta = client.post("/auth/renovar", headers={"Authorization": f"Bearer {token}"})

        assert resposta.status_code == 401

    def test_renovacao_ainda_e_concedida_dentro_do_teto(self, client, monkeypatch):
        # O par do teste acima: um minuto **antes** do teto ainda renova. Sem
        # este, um teto de zero passaria no teste anterior.
        registrar(client)
        t0 = datetime.now(timezone.utc).replace(microsecond=0)
        self._com_relogio(monkeypatch, t0)
        token = login(client).json()["access_token"]

        self._com_relogio(
            monkeypatch,
            t0 + timedelta(hours=settings.teto_de_credencial_horas) - timedelta(minutes=1),
        )
        resposta = client.post("/auth/renovar", headers={"Authorization": f"Bearer {token}"})

        assert resposta.status_code == 200

    def test_token_expirado_nao_ressuscita(self, client):
        """Renovação exige credencial viva.

        Aceitar um token vencido faria de qualquer token roubado uma credencial
        permanente — o access token viraria um refresh token sem nenhuma das
        garantias de um.
        """
        registrar(client)
        token_expirado = jwt.encode(
            {
                "sub": PAYLOAD_PADRAO["email"],
                "iat": datetime.now(timezone.utc) - timedelta(minutes=31),
                "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
            },
            settings.secret_key,
            algorithm=settings.algorithm,
        )

        resposta = client.post(
            "/auth/renovar", headers={"Authorization": f"Bearer {token_expirado}"}
        )

        assert resposta.status_code == 401

    def test_sem_token_nao_renova(self, client):
        assert client.post("/auth/renovar").status_code == 401

    def test_token_de_aluno_removido_nao_renova(self, client, session: Session):
        # Assinatura perfeita e dentro do teto, mas a conta não existe mais.
        registrar(client)
        token = login(client).json()["access_token"]
        aluno = session.exec(select(Aluno).where(Aluno.email == PAYLOAD_PADRAO["email"])).first()
        session.delete(aluno)
        session.commit()

        resposta = client.post("/auth/renovar", headers={"Authorization": f"Bearer {token}"})

        assert resposta.status_code == 401

    def test_token_anterior_ao_recurso_renova_sem_ganhar_teto_maior(
        self, client, monkeypatch
    ):
        """Token sem `iat` é o que a versão anterior emitia.

        Ele não pode ser tratado como "sessão de credencial que começa agora":
        isso daria ao token legado um teto maior que o de quem acabou de logar.
        O início é reconstruído de `exp` menos a janela — exato, porque o único
        emissor sempre usou essa janela.
        """
        from app import security

        registrar(client)
        agora = datetime.now(timezone.utc).replace(microsecond=0)
        janela = timedelta(minutes=settings.access_token_expire_minutes)
        # Emitido "há 29 minutos" pela versão antiga: sem `iat`, e vencendo em 1 min.
        token_legado = jwt.encode(
            {"sub": PAYLOAD_PADRAO["email"], "exp": agora + timedelta(minutes=1)},
            settings.secret_key,
            algorithm=settings.algorithm,
        )

        # O início reconstruído é `exp - janela`. Passado o teto contado dali, a
        # renovação tem de ser recusada como a de qualquer outro token.
        inicio_reconstruido = agora + timedelta(minutes=1) - janela
        monkeypatch.setattr(
            security,
            "agora_utc",
            lambda: inicio_reconstruido
            + timedelta(hours=settings.teto_de_credencial_horas, minutes=1),
        )
        assert (
            client.post(
                "/auth/renovar", headers={"Authorization": f"Bearer {token_legado}"}
            ).status_code
            == 401
        )

        # E dentro do teto ele renova normalmente, ganhando `iat` explícito.
        monkeypatch.setattr(security, "agora_utc", lambda: agora)
        resposta = client.post(
            "/auth/renovar", headers={"Authorization": f"Bearer {token_legado}"}
        )
        assert resposta.status_code == 200
        claims = jwt.decode(
            resposta.json()["access_token"],
            settings.secret_key,
            algorithms=[settings.algorithm],
        )
        assert claims["iat"] == int(inicio_reconstruido.timestamp())


class TestLeituraDoToken:
    """Os ramos de `app.security` que o endpoint não alcança sozinho.

    `POST /auth/renovar` é guardado por `get_aluno_atual`, então token
    malformado morre antes de chegar em `renovar_token`. Testar as funções
    diretamente é o que impede que essas guardas virem código morto — elas
    existem para quem chamar o módulo sem passar pela rota, e é assim que o
    WebSocket de telemetria o chama.
    """

    def test_expiracao_de_token_ilegivel_e_desconhecida(self):
        from app.security import expiracao_do_token

        assert expiracao_do_token("isto-nao-e-um-jwt") is None

    def test_expiracao_de_token_sem_exp_e_desconhecida(self):
        # `None` aqui significa "não dá para afirmar até quando vale", e quem
        # reavalia trata isso como credencial inválida. É a mesma disciplina de
        # ausência de medida não virar zero que o resto do projeto segue.
        from app.security import expiracao_do_token

        token = jwt.encode(
            {"sub": PAYLOAD_PADRAO["email"]}, settings.secret_key, algorithm=settings.algorithm
        )

        assert expiracao_do_token(token) is None

    def test_token_ilegivel_nao_renova(self):
        from app.security import renovar_token

        assert renovar_token("isto-nao-e-um-jwt") is None

    def test_token_sem_subject_nao_renova(self):
        # Sem `sub` não há para quem emitir o token novo. Emitir mesmo assim
        # produziria uma credencial de dono indefinido.
        from app.security import renovar_token

        token = jwt.encode(
            {"exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
            settings.secret_key,
            algorithm=settings.algorithm,
        )

        assert renovar_token(token) is None

    def test_token_sem_iat_e_sem_exp_comeca_a_contar_agora(self):
        """O último recurso do início reconstruído.

        Um token sem `iat` e sem `exp` não foi emitido por este sistema — não há
        de onde reconstruir o início. Contar de agora é o que sobra, e é seguro
        porque ele ainda precisa ter assinatura válida para chegar até aqui.
        """
        from app.security import renovar_token

        token = jwt.encode(
            {"sub": PAYLOAD_PADRAO["email"]}, settings.secret_key, algorithm=settings.algorithm
        )

        renovado = renovar_token(token)

        assert renovado is not None
        claims = jwt.decode(renovado, settings.secret_key, algorithms=[settings.algorithm])
        assert claims["sub"] == PAYLOAD_PADRAO["email"]
