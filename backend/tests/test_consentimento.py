"""Aceite, revogação, correção e exclusão: o que o termo promete ao titular.

Cada teste corresponde a uma frase do Apêndice A do TCC. Se um deles cair, o
texto voltou a afirmar algo que o sistema não faz.
"""
from datetime import datetime, timezone

import pytest
from jose import jwt
from sqlmodel import select

from app import consentimento, telemetria
from app.config import settings
from app.models import Aluno, BlocoEstudo, LogEngajamento, ResumoSessao, SessaoEstudo
from app.security import hash_senha
from tests.apoio import ACEITE_DO_TERMO

ANA = {"nome": "Ana Souza", "email": "ana@exemplo.com", "senha": "senhaSegura123", **ACEITE_DO_TERMO}
RUI = {"nome": "Rui Lima", "email": "rui@exemplo.com", "senha": "senhaSegura456", **ACEITE_DO_TERMO}
LEITURA = {"ear": 0.30, "yaw": 0.0, "rosto_detectado": True}


def _token(client, dados):
    resposta = client.post("/auth/login", json={"email": dados["email"], "senha": dados["senha"]})
    return resposta.json()["access_token"]


def _cabecalhos(token):
    return {"Authorization": f"Bearer {token}"}


def _cadastrar(client, dados):
    assert client.post("/auth/registro", json=dados).status_code == 201
    return _cabecalhos(_token(client, dados))


def _sessao_com_dados(client, session, cabecalhos):
    """Uma sessão encerrada com ponto, bloco e resumo: uma linha em cada tabela."""
    id_sessao = client.post("/sessoes", headers=cabecalhos, json={"metodo": "pomodoro"}).json()["id"]
    telemetria.registrar_log(session, id_sessao=id_sessao, score=80.0)
    resposta = client.post(
        f"/sessoes/{id_sessao}/blocos",
        headers=cabecalhos,
        json={"tipo": "foco", "origem": "metodo"},
    )
    assert resposta.status_code in (200, 201), resposta.text
    assert client.post(f"/sessoes/{id_sessao}/encerrar", headers=cabecalhos).status_code == 200
    return id_sessao


def _linhas(session, modelo, id_sessao):
    return session.exec(select(modelo).where(modelo.id_sessao == id_sessao)).all()


@pytest.mark.parametrize(
    "alteracao",
    [
        {"aceitou_termo": False},
        {"declarou_maioridade": False},
        {"versao_termo": "0.9"},
    ],
    ids=["sem-aceite", "menor-de-idade", "versao-antiga"],
)
def test_cadastro_sem_aceite_valido_e_recusado(client, session, alteracao):
    assert client.post("/auth/registro", json={**ANA, **alteracao}).status_code == 422
    assert session.exec(select(Aluno)).all() == []


@pytest.mark.parametrize("campo", ["aceitou_termo", "declarou_maioridade", "versao_termo"])
def test_cadastro_sem_o_campo_e_recusado(client, campo):
    dados = {chave: valor for chave, valor in ANA.items() if chave != campo}
    assert client.post("/auth/registro", json=dados).status_code == 422


def test_cadastro_registra_o_aceite_e_a_versao(client, session):
    corpo = client.post("/auth/registro", json=ANA).json()

    assert corpo["consentimento_vigente"] is True
    assert corpo["termo_versao"] == consentimento.VERSAO_TERMO
    aluno = session.exec(select(Aluno)).one()
    assert aluno.termo_aceito_em is not None
    assert aluno.consentimento_revogado_em is None


@pytest.fixture(name="conta_antiga")
def conta_antiga_fixture(client, session):
    """Conta anterior ao termo: existe, faz login e nunca aceitou nada."""
    session.add(Aluno(nome="Bia", email="bia@exemplo.com", senha_hash=hash_senha("senhaSegura789")))
    session.commit()
    return _cabecalhos(_token(client, {"email": "bia@exemplo.com", "senha": "senhaSegura789"}))


def test_conta_anterior_ao_termo_precisa_aceitar_antes_da_sessao(client, conta_antiga):
    assert client.get("/auth/me", headers=conta_antiga).json()["consentimento_vigente"] is False
    assert client.post("/sessoes", headers=conta_antiga).status_code == 403

    resposta = client.post("/auth/consentimento", headers=conta_antiga, json=ACEITE_DO_TERMO)

    assert resposta.json()["consentimento_vigente"] is True
    assert client.post("/sessoes", headers=conta_antiga).status_code == 201


def test_aceite_exige_as_duas_declaracoes(client, conta_antiga):
    resposta = client.post(
        "/auth/consentimento",
        headers=conta_antiga,
        json={**ACEITE_DO_TERMO, "declarou_maioridade": False},
    )
    assert resposta.status_code == 422


def test_nova_versao_do_termo_exige_novo_aceite():
    aceito = datetime(2026, 11, 8, tzinfo=timezone.utc)

    assert consentimento.vigente(consentimento.VERSAO_TERMO, aceito, None) is True
    assert consentimento.vigente("1.0", aceito, None) is False
    assert consentimento.vigente(consentimento.VERSAO_TERMO, aceito, aceito) is False
    assert consentimento.vigente(consentimento.VERSAO_TERMO, None, None) is False


def test_revogar_impede_nova_sessao_e_fecha_a_aberta(client, session):
    cabecalhos = _cadastrar(client, ANA)
    id_sessao = client.post("/sessoes", headers=cabecalhos).json()["id"]

    corpo = client.delete("/auth/consentimento", headers=cabecalhos).json()

    assert corpo["consentimento_vigente"] is False
    assert corpo["consentimento_revogado_em"] is not None
    assert session.get(SessaoEstudo, id_sessao).fim is not None
    assert client.get("/sessoes/ativa", headers=cabecalhos).json() is None
    assert client.post("/sessoes", headers=cabecalhos).status_code == 403


def test_revogar_nao_apaga_o_que_ja_foi_tratado(client, session):
    cabecalhos = _cadastrar(client, ANA)
    id_sessao = _sessao_com_dados(client, session, cabecalhos)

    client.delete("/auth/consentimento", headers=cabecalhos)

    assert _linhas(session, LogEngajamento, id_sessao)
    assert client.get(f"/sessoes/{id_sessao}/relatorio", headers=cabecalhos).status_code == 200


def test_revogar_de_novo_nao_move_a_data(client):
    cabecalhos = _cadastrar(client, ANA)
    primeira = client.delete("/auth/consentimento", headers=cabecalhos).json()
    segunda = client.delete("/auth/consentimento", headers=cabecalhos).json()

    assert segunda["consentimento_revogado_em"] == primeira["consentimento_revogado_em"]


def test_aceitar_de_novo_devolve_o_acesso(client):
    cabecalhos = _cadastrar(client, ANA)
    client.delete("/auth/consentimento", headers=cabecalhos)

    corpo = client.post("/auth/consentimento", headers=cabecalhos, json=ACEITE_DO_TERMO).json()

    assert corpo["consentimento_vigente"] is True
    assert corpo["consentimento_revogado_em"] is None
    assert client.post("/sessoes", headers=cabecalhos).status_code == 201


def test_excluir_apaga_tudo_do_titular_e_nada_de_outro(client, session):
    ana = _cadastrar(client, ANA)
    rui = _cadastrar(client, RUI)
    sessao_ana = _sessao_com_dados(client, session, ana)
    sessao_rui = _sessao_com_dados(client, session, rui)
    for modelo in (LogEngajamento, BlocoEstudo, ResumoSessao):
        assert _linhas(session, modelo, sessao_ana), modelo

    resposta = client.request("DELETE", "/auth/conta", headers=ana, json={"senha": ANA["senha"]})

    assert resposta.status_code == 204
    session.expire_all()
    for modelo in (LogEngajamento, BlocoEstudo, ResumoSessao):
        assert _linhas(session, modelo, sessao_ana) == []
        assert _linhas(session, modelo, sessao_rui) != []
    assert session.get(SessaoEstudo, sessao_ana) is None
    assert session.exec(select(Aluno).where(Aluno.email == ANA["email"])).first() is None
    assert client.get("/auth/me", headers=rui).status_code == 200


def test_token_de_conta_excluida_nao_vale(client):
    cabecalhos = _cadastrar(client, ANA)
    client.request("DELETE", "/auth/conta", headers=cabecalhos, json={"senha": ANA["senha"]})

    assert client.get("/auth/me", headers=cabecalhos).status_code == 401


def test_excluir_com_senha_errada_nao_apaga(client, session):
    cabecalhos = _cadastrar(client, ANA)

    resposta = client.request("DELETE", "/auth/conta", headers=cabecalhos, json={"senha": "errada"})

    # 403, e não 401: o interceptor do frontend trata 401 como credencial vencida.
    assert resposta.status_code == 403
    assert session.exec(select(Aluno)).first() is not None


def test_excluir_com_sessao_aberta(client, session):
    cabecalhos = _cadastrar(client, ANA)
    id_sessao = client.post("/sessoes", headers=cabecalhos).json()["id"]

    resposta = client.request("DELETE", "/auth/conta", headers=cabecalhos, json={"senha": ANA["senha"]})

    assert resposta.status_code == 204
    session.expire_all()
    assert session.get(SessaoEstudo, id_sessao) is None


def test_corrigir_nome_nao_troca_a_credencial(client):
    cabecalhos = _cadastrar(client, ANA)

    corpo = client.patch("/auth/me", headers=cabecalhos, json={"nome": "Ana S."}).json()

    assert corpo["nome"] == "Ana S."
    assert corpo["access_token"] is None
    assert client.get("/auth/me", headers=cabecalhos).status_code == 200


def test_corrigir_email_devolve_credencial_nova_sem_estender_o_teto(client):
    cabecalhos = _cadastrar(client, ANA)
    token_antigo = cabecalhos["Authorization"].split()[1]

    corpo = client.patch("/auth/me", headers=cabecalhos, json={"email": "nova@exemplo.com"}).json()

    assert corpo["email"] == "nova@exemplo.com"
    novo = corpo["access_token"]
    assert client.get("/auth/me", headers=_cabecalhos(novo)).status_code == 200
    assert client.get("/auth/me", headers=cabecalhos).status_code == 401

    def iat(token):
        return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])["iat"]

    assert iat(novo) == iat(token_antigo)


def test_corrigir_para_email_em_uso_e_recusado(client):
    cabecalhos = _cadastrar(client, ANA)
    _cadastrar(client, RUI)

    resposta = client.patch("/auth/me", headers=cabecalhos, json={"email": RUI["email"]})

    assert resposta.status_code == 409
    assert client.get("/auth/me", headers=cabecalhos).json()["email"] == ANA["email"]


def _canal_autenticado(ws, token):
    ws.send_json({"token": token})
    assert ws.receive_json() == {"tipo": "autenticado"}


def test_canal_aberto_para_de_gravar_apos_a_revogacao(client, session):
    cabecalhos = _cadastrar(client, ANA)
    id_sessao = client.post("/sessoes", headers=cabecalhos).json()["id"]
    token = cabecalhos["Authorization"].split()[1]

    with client.websocket_connect("/telemetria") as ws:
        _canal_autenticado(ws, token)
        ws.send_json(LEITURA)
        assert ws.receive_json()["tipo"] == "score"

        client.delete("/auth/consentimento", headers=cabecalhos)
        ws.send_json(LEITURA)
        assert ws.receive_json() == {"tipo": "erro", "motivo": "sem-sessao-ativa"}

    assert len(_linhas(session, LogEngajamento, id_sessao)) == 1


def test_canal_aberto_para_de_gravar_apos_a_exclusao(client, session):
    cabecalhos = _cadastrar(client, ANA)
    id_sessao = client.post("/sessoes", headers=cabecalhos).json()["id"]
    token = cabecalhos["Authorization"].split()[1]

    with client.websocket_connect("/telemetria") as ws:
        _canal_autenticado(ws, token)
        client.request("DELETE", "/auth/conta", headers=cabecalhos, json={"senha": ANA["senha"]})
        ws.send_json(LEITURA)
        assert ws.receive_json() == {"tipo": "erro", "motivo": "sem-sessao-ativa"}

    assert _linhas(session, LogEngajamento, id_sessao) == []


def test_canal_nao_abre_sem_consentimento_vigente(client, session):
    """Sessão aberta antes do deploy do termo, por uma conta que nunca aceitou."""
    aluno = Aluno(nome="Bia", email="bia@exemplo.com", senha_hash=hash_senha("senhaSegura789"))
    session.add(aluno)
    session.commit()
    session.refresh(aluno)
    session.add(SessaoEstudo(id_aluno=aluno.id))
    session.commit()
    token = _token(client, {"email": "bia@exemplo.com", "senha": "senhaSegura789"})

    with client.websocket_connect("/telemetria") as ws:
        ws.send_json({"token": token})
        assert ws.receive_json() == {"tipo": "erro", "motivo": "sem-sessao-ativa"}
