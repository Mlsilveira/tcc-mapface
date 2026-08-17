"""A calibração de baseline atravessando o WebSocket (ticket 7).

`test_analista.py` já prova a regra do IEE isolada, e `test_calibracao.py` já
prova a persistência. O que só se vê aqui é a **costura**: que o router traduz
cada `Resultado` para a gravação certa, e que a calibração de 60 segundos
sobrevive ao que a ticket 6 faz de verdade — cair e reconectar.

Essa última é a afirmação arquitetural da ticket, e é por isso que ela tem
teste. A alternativa que rejeitamos — acumulador na memória da conexão — passaria
em todos os testes de unidade e falharia exatamente aqui.

O relógio entra por monkeypatch em `agora_utc` do router: é o único ponto do
caminho que ainda lê o tempo do sistema, já que `AnalistaEngajamento.processar`
recebe `agora` por parâmetro. Sem isso, testar a janela de 60s custaria 60s.
"""
from datetime import timedelta

import pytest

from app import calibracao
from app.tempo import agora_utc

PAYLOAD_ALUNO = {"nome": "Ana Souza", "email": "ana@exemplo.com", "senha": "senhaSegura123"}

#: O aluno de óculos da história 13 do spec: a armação e o reflexo achatam o
#: EAR, e contra um padrão "típico" ele pareceria permanentemente sonolento.
EAR_NEUTRO_DE_OCULOS = 0.18


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


def _id_da_sessao_ativa(client, token):
    return client.get("/sessoes/ativa", headers={"Authorization": f"Bearer {token}"}).json()["id"]


@pytest.fixture(name="relogio")
def relogio_fixture(monkeypatch):
    """Um relógio que só anda quando o teste manda."""

    class Relogio:
        def __init__(self):
            self.agora = agora_utc()

        def avancar(self, segundos):
            self.agora = self.agora + timedelta(seconds=segundos)

    relogio = Relogio()
    monkeypatch.setattr("app.routers.telemetria.agora_utc", lambda: relogio.agora)
    return relogio


def _abrir(client, token):
    ws = client.websocket_connect("/telemetria").__enter__()
    ws.send_json({"token": token})
    ws.receive_json()
    return ws


def _enviar(ws, ear=0.30, yaw=0.0, pitch=0.0, rosto_detectado=True):
    ws.send_json({"ear": ear, "yaw": yaw, "pitch": pitch, "rosto_detectado": rosto_detectado})
    return ws.receive_json()


# --- Durante a janela de calibração -----------------------------------------


def test_primeiro_minuto_responde_marcado_como_calibrando(client, com_sessao_ativa, relogio):
    with client.websocket_connect("/telemetria") as ws:
        ws.send_json({"token": com_sessao_ativa})
        ws.receive_json()

        resposta = _enviar(ws, ear=EAR_NEUTRO_DE_OCULOS)

    assert resposta["calibrando"] is True
    # "Silenciosa" é o aluno não ser interrogado, não o score sumir: o dashboard
    # da ticket 9 mostra número desde o primeiro segundo.
    assert resposta["tipo"] == "score"
    assert isinstance(resposta["score"], float)


def test_calibracao_acumula_no_banco_a_cada_payload(
    client, com_sessao_ativa, session, relogio
):
    id_sessao = _id_da_sessao_ativa(client, com_sessao_ativa)

    with client.websocket_connect("/telemetria") as ws:
        ws.send_json({"token": com_sessao_ativa})
        ws.receive_json()

        for _ in range(3):
            _enviar(ws, ear=0.20)
            relogio.avancar(1)

    leitura = calibracao.carregar(session, id_sessao)
    assert leitura.em_andamento
    assert leitura.estado.amostras == 3
    assert leitura.estado.soma_ear == pytest.approx(0.60)


# --- O fechamento da janela --------------------------------------------------


def test_apos_60s_a_baseline_do_aluno_passa_a_valer(
    client, com_sessao_ativa, session, relogio
):
    id_sessao = _id_da_sessao_ativa(client, com_sessao_ativa)

    with client.websocket_connect("/telemetria") as ws:
        ws.send_json({"token": com_sessao_ativa})
        ws.receive_json()

        _enviar(ws, ear=EAR_NEUTRO_DE_OCULOS)
        relogio.avancar(60)
        resposta = _enviar(ws, ear=EAR_NEUTRO_DE_OCULOS)

    assert resposta["calibrando"] is False

    leitura = calibracao.carregar(session, id_sessao)
    assert leitura.concluida
    assert leitura.baseline.ear_neutro == pytest.approx(EAR_NEUTRO_DE_OCULOS)


def test_aluno_de_oculos_no_proprio_neutro_nao_e_penalizado(
    client, com_sessao_ativa, relogio
):
    """História 13 do spec, ponta a ponta.

    Um EAR de 0,18 contra o padrão genérico de 0,30 daria 0,6 na parcela ocular
    — 76 pontos, o alerta injusto. Contra a própria baseline, o mesmo aluno na
    mesma postura tira 100. É esse delta que a calibração individual existe para
    eliminar.
    """
    with client.websocket_connect("/telemetria") as ws:
        ws.send_json({"token": com_sessao_ativa})
        ws.receive_json()

        durante = _enviar(ws, ear=EAR_NEUTRO_DE_OCULOS)
        relogio.avancar(60)
        _enviar(ws, ear=EAR_NEUTRO_DE_OCULOS)
        depois = _enviar(ws, ear=EAR_NEUTRO_DE_OCULOS)

    assert durante["score"] == pytest.approx(76.0)
    assert depois["score"] == pytest.approx(100.0)


# --- A afirmação arquitetural: reconexão -------------------------------------


def test_reconexao_no_meio_da_calibracao_nao_recomeca_a_janela(
    client, com_sessao_ativa, session, relogio
):
    """O acumulador vive no banco justamente para sobreviver a isto.

    Se ele morasse na conexão, a queda abaixo zeraria os 30 segundos já medidos
    e, numa rede ruim, a calibração nunca terminaria.
    """
    id_sessao = _id_da_sessao_ativa(client, com_sessao_ativa)

    with client.websocket_connect("/telemetria") as ws:
        ws.send_json({"token": com_sessao_ativa})
        ws.receive_json()
        for _ in range(30):
            _enviar(ws, ear=0.30)
            relogio.avancar(1)

    antes = calibracao.carregar(session, id_sessao).estado
    assert antes.amostras == 30

    # Nova conexão, como faz a reconexão automática da ticket 6.
    with client.websocket_connect("/telemetria") as ws:
        ws.send_json({"token": com_sessao_ativa})
        ws.receive_json()
        _enviar(ws, ear=0.30)

    depois = calibracao.carregar(session, id_sessao).estado
    assert depois.amostras == 31
    # O início é o do primeiro payload, não o da reconexão: a janela continua
    # de onde parou em vez de recomeçar.
    assert depois.inicio == antes.inicio


# --- Recalibração por ausência ------------------------------------------------


def test_ausencia_durante_a_calibracao_descarta_o_acumulado(
    client, com_sessao_ativa, session, relogio
):
    id_sessao = _id_da_sessao_ativa(client, com_sessao_ativa)

    with client.websocket_connect("/telemetria") as ws:
        ws.send_json({"token": com_sessao_ativa})
        ws.receive_json()

        for _ in range(10):
            _enviar(ws, ear=0.30)
            relogio.avancar(1)
        assert calibracao.carregar(session, id_sessao).estado.amostras == 10

        resposta = _enviar(ws, rosto_detectado=False)

    assert resposta["score"] == 0.0
    assert calibracao.carregar(session, id_sessao).nao_iniciada


def test_janela_recomeca_do_zero_quando_o_rosto_volta(
    client, com_sessao_ativa, session, relogio
):
    id_sessao = _id_da_sessao_ativa(client, com_sessao_ativa)

    with client.websocket_connect("/telemetria") as ws:
        ws.send_json({"token": com_sessao_ativa})
        ws.receive_json()

        _enviar(ws, ear=0.30)
        relogio.avancar(30)
        _enviar(ws, rosto_detectado=False)
        relogio.avancar(1)
        _enviar(ws, ear=0.30)
        # Os 30 segundos do acumulado descartado não contam: se contassem, esta
        # janela fecharia cedo e a baseline sairia de um único payload.
        relogio.avancar(31)
        resposta = _enviar(ws, ear=0.30)

    assert resposta["calibrando"] is True
    assert calibracao.carregar(session, id_sessao).em_andamento


# --- P(t) = 0 depois de calibrado --------------------------------------------


def test_sem_rosto_depois_de_calibrado_zera_sem_perder_a_baseline(
    client, com_sessao_ativa, session, relogio
):
    """A ausência zera o score, mas não joga fora o minuto já calibrado."""
    id_sessao = _id_da_sessao_ativa(client, com_sessao_ativa)

    with client.websocket_connect("/telemetria") as ws:
        ws.send_json({"token": com_sessao_ativa})
        ws.receive_json()

        _enviar(ws, ear=0.30)
        relogio.avancar(60)
        _enviar(ws, ear=0.30)

        ausente = _enviar(ws, rosto_detectado=False)
        de_volta = _enviar(ws, ear=0.30)

    assert ausente["score"] == 0.0
    assert de_volta["score"] == pytest.approx(100.0)
    assert calibracao.carregar(session, id_sessao).concluida


# --- O pitch, que a ticket 7 acrescentou -------------------------------------


def test_pitch_entra_no_desvio_de_head_pose(client, com_sessao_ativa, relogio):
    """Cabeça baixa tem que derrubar o score tanto quanto cabeça virada.

    Sem pitch no payload, um aluno de cabeça baixa e um de cabeça reta seriam
    indistinguíveis — e são sinais de engajamento opostos.
    """
    with client.websocket_connect("/telemetria") as ws:
        ws.send_json({"token": com_sessao_ativa})
        ws.receive_json()

        _enviar(ws, ear=0.30, yaw=0.0, pitch=0.0)
        relogio.avancar(60)
        _enviar(ws, ear=0.30, yaw=0.0, pitch=0.0)

        reto = _enviar(ws, ear=0.30, yaw=0.0, pitch=0.0)
        cabeca_baixa = _enviar(ws, ear=0.30, yaw=0.0, pitch=45.0)

    assert reto["score"] == pytest.approx(100.0)
    assert cabeca_baixa["score"] == pytest.approx(60.0)


def test_cliente_antigo_sem_pitch_continua_sendo_medido(client, com_sessao_ativa, relogio):
    """Um cliente ainda na versão da ticket 6 não pode ter os payloads recusados."""
    with client.websocket_connect("/telemetria") as ws:
        ws.send_json({"token": com_sessao_ativa})
        ws.receive_json()

        ws.send_json({"ear": 0.30, "yaw": 0.0, "rosto_detectado": True})
        resposta = ws.receive_json()

    assert resposta["tipo"] == "score"
    assert resposta["score"] == pytest.approx(100.0)


def test_pitch_invalido_e_payload_torto(client, com_sessao_ativa, relogio):
    with client.websocket_connect("/telemetria") as ws:
        ws.send_json({"token": com_sessao_ativa})
        ws.receive_json()

        ws.send_json({"ear": 0.30, "yaw": 0.0, "pitch": "meio torto"})
        resposta = ws.receive_json()

    assert resposta["tipo"] == "erro"
    assert resposta["motivo"] == "payload-invalido"


# --- Coerência da linha gravada ----------------------------------------------


def test_linha_da_baseline_fica_internamente_coerente(
    client, com_sessao_ativa, session, relogio
):
    """`soma / amostras` tem que bater com o neutro gravado.

    O payload que fecha a janela entra na média mas não chega a ser acumulado —
    o analista devolve `estado=None` porque acabou de fechar. Sem reconstruir as
    somas, a linha ficaria uma amostra atrasada, e o relatório da ticket 11 leria
    as somas como evidência de uma baseline que elas não produzem.
    """
    from sqlmodel import select

    from app.models import Calibracao

    id_sessao = _id_da_sessao_ativa(client, com_sessao_ativa)

    with client.websocket_connect("/telemetria") as ws:
        ws.send_json({"token": com_sessao_ativa})
        ws.receive_json()
        for _ in range(61):
            _enviar(ws, ear=0.20)
            relogio.avancar(1)

    linha = session.exec(select(Calibracao).where(Calibracao.id_sessao == id_sessao)).first()

    assert linha.concluida_em is not None
    assert linha.soma_ear / linha.amostras == pytest.approx(linha.ear_neutro)
    assert linha.soma_yaw / linha.amostras == pytest.approx(linha.yaw_neutro)
    assert linha.soma_pitch / linha.amostras == pytest.approx(linha.pitch_neutro)


def test_calibracao_concluida_por_outra_conexao_nao_derruba_esta(
    client, com_sessao_ativa, session, relogio, monkeypatch
):
    """A corrida entre duas abas da mesma sessão não pode matar o socket.

    A janela da corrida é estreita e fica *dentro* de um único `_analisar`: esta
    conexão lê "ainda calibrando", outra fecha a baseline, e só então esta grava.
    Encená-la com dois `send` sequenciais não funciona — o router relê o estado a
    cada payload e já veria a baseline pronta. Por isso a leitura obsoleta é
    injetada: é o único jeito determinístico de pôr o código na janela real.
    """
    from app.analista import Baseline, EstadoCalibracao

    id_sessao = _id_da_sessao_ativa(client, com_sessao_ativa)

    # A outra conexão já fechou a janela no banco.
    calibracao.salvar_baseline(
        session,
        id_sessao,
        Baseline(ear_neutro=0.30, yaw_neutro=0.0, pitch_neutro=0.0, amostras=60),
    )

    # Esta conexão, porém, carrega a leitura de antes disso.
    obsoleta = calibracao.LeituraCalibracao(
        baseline=None,
        estado=EstadoCalibracao(
            inicio=agora_utc(), soma_ear=3.0, soma_yaw=0.0, soma_pitch=0.0, amostras=10
        ),
    )
    monkeypatch.setattr(
        "app.routers.telemetria.calibracao.carregar", lambda db, id_: obsoleta
    )

    with client.websocket_connect("/telemetria") as ws:
        ws.send_json({"token": com_sessao_ativa})
        ws.receive_json()
        resposta = _enviar(ws, ear=0.30)

    assert resposta["tipo"] == "score"
