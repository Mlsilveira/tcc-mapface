"""Testes do que o parecer do TC2 pediu para tornar mensurável (F01 e F02).

Três coisas, e nenhuma muda o que o aluno vê:

- o canal devolve o **tempo de processamento** de cada payload e o **carimbo**
  que o cliente mandou, para a latência ser medida no ambiente publicado sem
  somar duas vezes o que já está dentro do RTT;
- uma linha de log por conexão resume a distribuição desse tempo;
- o `/health` diz **qual build** está respondendo.
"""
import logging

import pytest

from app.routers.telemetria import percentil

PAYLOAD = {"ear": 0.30, "yaw": 0.0, "rosto_detectado": True}


@pytest.fixture(name="token")
def token_fixture(client):
    dados = {"nome": "Medida", "email": "medida@exemplo.com", "senha": "senha-forte-123"}
    client.post("/auth/registro", json=dados)
    resposta = client.post("/auth/login", json={"email": dados["email"], "senha": dados["senha"]})
    return resposta.json()["access_token"]


@pytest.fixture(name="canal")
def canal_fixture(client, token):
    client.post("/sessoes", headers={"Authorization": f"Bearer {token}"})
    with client.websocket_connect("/telemetria") as ws:
        ws.send_json({"token": token})
        assert ws.receive_json() == {"tipo": "autenticado"}
        yield ws


# --- O canal ---------------------------------------------------------------


def test_cada_score_traz_o_tempo_de_processamento(canal):
    canal.send_json(PAYLOAD)
    resposta = canal.receive_json()

    assert resposta["tipo"] == "score"
    assert isinstance(resposta["processamento_ms"], float)
    assert resposta["processamento_ms"] >= 0


def test_o_carimbo_do_cliente_volta_intacto(canal):
    """O servidor não interpreta o carimbo: nem sabe em que relógio ele está.

    Quem enviou é quem subtrai. Devolver exatamente o que veio é o que permite
    ao cliente parear cada resposta com o seu envio, sem depender da ordem.
    """
    canal.send_json({**PAYLOAD, "t0": 1730995200123.456})

    assert canal.receive_json()["t0"] == 1730995200123.456


def test_sem_carimbo_o_campo_volta_nulo(canal):
    """O navegador de todo dia não manda carimbo, e continua funcionando igual."""
    canal.send_json(PAYLOAD)

    assert canal.receive_json()["t0"] is None


@pytest.mark.parametrize("ruim", [True, "123", None, [1], {"x": 1}])
def test_carimbo_malformado_e_ignorado_sem_custar_a_leitura(canal, ruim):
    """Um carimbo torto não pode custar o score do segundo."""
    canal.send_json({**PAYLOAD, "t0": ruim})
    resposta = canal.receive_json()

    assert resposta["tipo"] == "score"
    assert resposta["t0"] is None


def test_a_conexao_deixa_uma_linha_de_latencia_no_log(client, token, caplog):
    """Uma por conexão, e não uma por payload: a 1 Hz, isso afogaria o log."""
    client.post("/sessoes", headers={"Authorization": f"Bearer {token}"})

    with caplog.at_level(logging.INFO, logger="app.routers.telemetria"):
        with client.websocket_connect("/telemetria") as ws:
            ws.send_json({"token": token})
            ws.receive_json()
            for _ in range(3):
                ws.send_json(PAYLOAD)
                ws.receive_json()

    linhas = [r.getMessage() for r in caplog.records if "latencia do canal" in r.getMessage()]
    assert len(linhas) == 1
    assert "n=3" in linhas[0]
    assert "p95=" in linhas[0] and "max=" in linhas[0]


def test_conexao_sem_nenhum_payload_nao_loga_nada(client, token, caplog):
    """Sem medição não há distribuição — e uma linha com n=0 seria ruído."""
    client.post("/sessoes", headers={"Authorization": f"Bearer {token}"})

    with caplog.at_level(logging.INFO, logger="app.routers.telemetria"):
        with client.websocket_connect("/telemetria") as ws:
            ws.send_json({"token": token})
            ws.receive_json()

    assert not [r for r in caplog.records if "latencia do canal" in r.getMessage()]


# --- O percentil -----------------------------------------------------------


def test_percentil_e_sempre_uma_das_medicoes():
    """Sem interpolar: o p95 tem de ser um pacote que existiu, para quem lê o
    relatório poder apontar o segundo em que ele aconteceu."""
    valores = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]

    assert percentil(valores, 50) == 50.0
    assert percentil(valores, 95) == 100.0
    assert percentil(valores, 95) in valores


def test_percentil_nao_depende_da_ordem_de_chegada():
    assert percentil([30.0, 10.0, 20.0], 50) == 20.0


def test_percentil_de_lista_vazia_e_nulo():
    assert percentil([], 95) is None


def test_percentil_de_uma_medicao_so():
    assert percentil([42.0], 50) == 42.0
    assert percentil([42.0], 95) == 42.0


# --- O build ---------------------------------------------------------------


def test_o_health_diz_qual_build_esta_respondendo(client):
    """Toda evidência do ambiente publicado precisa dizer de qual código veio."""
    resposta = client.get("/health").json()

    assert resposta["status"] == "ok"
    assert "build" in resposta


def test_o_build_vem_da_variavel_gravada_na_imagem(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "build_commit", "563e1da")

    assert client.get("/health").json()["build"] == "563e1da"
