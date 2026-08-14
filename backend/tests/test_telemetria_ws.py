"""Testes do canal de telemetria por WebSocket (ticket 6, seam B).

O JWT chega na **primeira mensagem** depois do connect, não na URL: token em
query string vaza para log de servidor, proxy e histórico do navegador, o que
seria incoerente num projeto cujo eixo é privacidade. O navegador tampouco
permite mandar header `Authorization` num WebSocket, então a primeira
mensagem é o único lugar limpo que sobra.
"""
import pytest

from app import sessoes

PAYLOAD_ALUNO = {"nome": "Ana Souza", "email": "ana@exemplo.com", "senha": "senhaSegura123"}


def _registrar_e_logar(client, payload=PAYLOAD_ALUNO):
    client.post("/auth/registro", json=payload)
    resposta = client.post(
        "/auth/login", json={"email": payload["email"], "senha": payload["senha"]}
    )
    return resposta.json()["access_token"]


@pytest.fixture(name="token")
def token_fixture(client):
    return _registrar_e_logar(client)


@pytest.fixture(name="com_sessao_ativa")
def com_sessao_ativa_fixture(client, token):
    client.post("/sessoes", headers={"Authorization": f"Bearer {token}"})
    return token


def test_autentica_pela_primeira_mensagem(client, com_sessao_ativa):
    with client.websocket_connect("/telemetria") as ws:
        ws.send_json({"token": com_sessao_ativa})
        assert ws.receive_json() == {"tipo": "autenticado"}


def test_recusa_token_invalido(client, com_sessao_ativa):
    with client.websocket_connect("/telemetria") as ws:
        ws.send_json({"token": "token-que-nao-vale-nada"})
        resposta = ws.receive_json()

    assert resposta["tipo"] == "erro"
    assert resposta["motivo"] == "nao-autenticado"


def _id_da_sessao_ativa(client, token):
    return client.get("/sessoes/ativa", headers={"Authorization": f"Bearer {token}"}).json()["id"]


def test_payload_de_metricas_devolve_score_e_persiste_log(client, com_sessao_ativa, session):
    from app import telemetria

    id_sessao = _id_da_sessao_ativa(client, com_sessao_ativa)

    with client.websocket_connect("/telemetria") as ws:
        ws.send_json({"token": com_sessao_ativa})
        ws.receive_json()

        # Olhos plenamente abertos e cabeça de frente: score máximo pela fórmula
        # provisória acordada.
        ws.send_json({"ear": 0.30, "yaw": 0.0, "rosto_detectado": True})
        resposta = ws.receive_json()

    assert resposta["tipo"] == "score"
    assert resposta["score"] == pytest.approx(100.0)

    logs = telemetria.buscar_logs(session, id_sessao=id_sessao)
    assert len(logs) == 1
    assert logs[0].score == pytest.approx(100.0)


def test_cada_payload_vira_um_ponto_da_serie(client, com_sessao_ativa, session):
    from app import telemetria

    id_sessao = _id_da_sessao_ativa(client, com_sessao_ativa)

    with client.websocket_connect("/telemetria") as ws:
        ws.send_json({"token": com_sessao_ativa})
        ws.receive_json()

        for ear in (0.30, 0.15, 0.0):
            ws.send_json({"ear": ear, "yaw": 0.0, "rosto_detectado": True})
            ws.receive_json()

    # 100, 70 e 40 pela fórmula: a série tem que preservar a queda, senão o
    # gráfico da ticket 9 e o relatório da 11 mostrariam uma linha achatada.
    assert [log.score for log in telemetria.buscar_logs(session, id_sessao=id_sessao)] == [
        pytest.approx(100.0),
        pytest.approx(70.0),
        pytest.approx(40.0),
    ]


def test_recusa_conexao_sem_sessao_de_estudo_em_andamento(client, token):
    # Sem sessão não há onde gravar. Aceitar em silêncio faria o aluno acreditar
    # que está sendo medido.
    with client.websocket_connect("/telemetria") as ws:
        ws.send_json({"token": token})
        resposta = ws.receive_json()

    assert resposta == {"tipo": "erro", "motivo": "sem-sessao-ativa"}


def test_nao_aceita_metricas_antes_de_autenticar(client, com_sessao_ativa):
    with client.websocket_connect("/telemetria") as ws:
        ws.send_json({"ear": 0.3, "yaw": 0.0})
        resposta = ws.receive_json()

    assert resposta["motivo"] == "nao-autenticado"


def test_payload_invalido_nao_derruba_a_conexao(client, com_sessao_ativa, session):
    from app import telemetria

    id_sessao = _id_da_sessao_ativa(client, com_sessao_ativa)

    with client.websocket_connect("/telemetria") as ws:
        ws.send_json({"token": com_sessao_ativa})
        ws.receive_json()

        ws.send_json({"ear": "abacaxi", "yaw": None})
        erro = ws.receive_json()

        # A conexão precisa sobreviver: um payload estranho no meio de uma
        # sessão de uma hora não pode custar a sessão inteira.
        ws.send_json({"ear": 0.30, "yaw": 0.0, "rosto_detectado": True})
        depois = ws.receive_json()

    assert erro == {"tipo": "erro", "motivo": "payload-invalido"}
    assert depois["tipo"] == "score"

    # E o payload inválido não pode ter virado um ponto na série.
    assert len(telemetria.buscar_logs(session, id_sessao=id_sessao)) == 1


def test_telemetria_conta_como_atividade_da_sessao(client, com_sessao_ativa, session):
    from app.models import SessaoEstudo

    id_sessao = _id_da_sessao_ativa(client, com_sessao_ativa)
    antes = session.get(SessaoEstudo, id_sessao).ultima_atividade

    with client.websocket_connect("/telemetria") as ws:
        ws.send_json({"token": com_sessao_ativa})
        ws.receive_json()
        ws.send_json({"ear": 0.30, "yaw": 0.0, "rosto_detectado": True})
        ws.receive_json()

    session.expire_all()
    depois = session.get(SessaoEstudo, id_sessao).ultima_atividade

    # Quem está mandando telemetria está estudando. Sem isso, uma sessão de
    # estudo silenciosa seria encerrada por "inatividade" no meio da medição.
    assert depois > antes
