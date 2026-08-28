"""Testes do ciclo de vida da sessão de estudo (ticket 4).

Cobrem os critérios de aceite:
- tabela `sessao_estudo` (id, id_aluno, inicio, fim)
- iniciar sessão associada ao aluno autenticado
- encerrar sessão manualmente
- encerramento automático em caso de inatividade prolongada

Os testes de inatividade batem direto no módulo `app.sessoes`, injetando o
instante "agora": é lá que mora a regra, e testá-la por HTTP exigiria congelar
o relógio do processo inteiro.
"""
from datetime import datetime, timedelta

import pytest
from sqlmodel import Session, select

from app import sessoes
from app.models import Aluno
from app.tempo import agora_utc, como_utc

PAYLOAD_ALUNO = {"nome": "Ana Souza", "email": "ana@exemplo.com", "senha": "senhaSegura123"}
PAYLOAD_OUTRO_ALUNO = {"nome": "Rui Lima", "email": "rui@exemplo.com", "senha": "senhaSegura456"}


def _registrar_e_logar(client, payload):
    client.post("/auth/registro", json=payload)
    resposta = client.post(
        "/auth/login", json={"email": payload["email"], "senha": payload["senha"]}
    )
    return {"Authorization": f"Bearer {resposta.json()['access_token']}"}


@pytest.fixture(name="cabecalhos")
def cabecalhos_fixture(client):
    return _registrar_e_logar(client, PAYLOAD_ALUNO)


@pytest.fixture(name="cabecalhos_outro_aluno")
def cabecalhos_outro_aluno_fixture(client):
    return _registrar_e_logar(client, PAYLOAD_OUTRO_ALUNO)


@pytest.fixture(name="aluno")
def aluno_fixture(client, cabecalhos, session: Session) -> Aluno:
    return session.exec(select(Aluno).where(Aluno.email == PAYLOAD_ALUNO["email"])).one()


class TestIniciarSessao:
    def test_cria_sessao_em_andamento_para_o_aluno_autenticado(self, client, cabecalhos, aluno):
        resposta = client.post("/sessoes", headers=cabecalhos)

        assert resposta.status_code == 201
        corpo = resposta.json()
        assert corpo["id_aluno"] == aluno.id
        assert corpo["inicio"] is not None
        assert corpo["fim"] is None

    def test_sem_token_retorna_401(self, client):
        assert client.post("/sessoes").status_code == 401

    def test_rejeita_segunda_sessao_enquanto_a_primeira_esta_em_andamento(
        self, client, cabecalhos
    ):
        client.post("/sessoes", headers=cabecalhos)

        assert client.post("/sessoes", headers=cabecalhos).status_code == 409

    def test_alunos_diferentes_podem_ter_sessoes_simultaneas(
        self, client, cabecalhos, cabecalhos_outro_aluno
    ):
        client.post("/sessoes", headers=cabecalhos)

        assert client.post("/sessoes", headers=cabecalhos_outro_aluno).status_code == 201

    def test_permite_nova_sessao_depois_de_encerrar_a_anterior(self, client, cabecalhos):
        sessao_id = client.post("/sessoes", headers=cabecalhos).json()["id"]
        client.post(f"/sessoes/{sessao_id}/encerrar", headers=cabecalhos)

        assert client.post("/sessoes", headers=cabecalhos).status_code == 201


class TestSessaoAtiva:
    def test_retorna_nulo_quando_o_aluno_nao_tem_sessao_em_andamento(self, client, cabecalhos):
        resposta = client.get("/sessoes/ativa", headers=cabecalhos)

        assert resposta.status_code == 200
        assert resposta.json() is None

    def test_retorna_a_sessao_em_andamento(self, client, cabecalhos):
        sessao_id = client.post("/sessoes", headers=cabecalhos).json()["id"]

        resposta = client.get("/sessoes/ativa", headers=cabecalhos)

        assert resposta.status_code == 200
        assert resposta.json()["id"] == sessao_id

    def test_nao_enxerga_a_sessao_de_outro_aluno(
        self, client, cabecalhos, cabecalhos_outro_aluno
    ):
        client.post("/sessoes", headers=cabecalhos)

        resposta = client.get("/sessoes/ativa", headers=cabecalhos_outro_aluno)

        assert resposta.json() is None

    def test_sem_token_retorna_401(self, client):
        assert client.get("/sessoes/ativa").status_code == 401


class TestEncerrarSessao:
    def test_encerramento_manual_registra_o_fim(self, client, cabecalhos):
        sessao_id = client.post("/sessoes", headers=cabecalhos).json()["id"]

        resposta = client.post(f"/sessoes/{sessao_id}/encerrar", headers=cabecalhos)

        assert resposta.status_code == 200
        assert resposta.json()["fim"] is not None
        assert client.get("/sessoes/ativa", headers=cabecalhos).json() is None

    def test_encerrar_duas_vezes_retorna_409(self, client, cabecalhos):
        sessao_id = client.post("/sessoes", headers=cabecalhos).json()["id"]
        client.post(f"/sessoes/{sessao_id}/encerrar", headers=cabecalhos)

        assert client.post(f"/sessoes/{sessao_id}/encerrar", headers=cabecalhos).status_code == 409

    def test_sessao_inexistente_retorna_404(self, client, cabecalhos):
        assert client.post("/sessoes/999/encerrar", headers=cabecalhos).status_code == 404

    def test_nao_encerra_sessao_de_outro_aluno(self, client, cabecalhos, cabecalhos_outro_aluno):
        sessao_id = client.post("/sessoes", headers=cabecalhos).json()["id"]

        resposta = client.post(f"/sessoes/{sessao_id}/encerrar", headers=cabecalhos_outro_aluno)

        assert resposta.status_code == 404
        assert client.get("/sessoes/ativa", headers=cabecalhos).json()["id"] == sessao_id

    def test_sem_token_retorna_401(self, client, cabecalhos):
        sessao_id = client.post("/sessoes", headers=cabecalhos).json()["id"]

        assert client.post(f"/sessoes/{sessao_id}/encerrar").status_code == 401


class TestAtividade:
    def test_heartbeat_adia_o_encerramento_automatico(self, client, cabecalhos, aluno, session):
        sessao_id = client.post("/sessoes", headers=cabecalhos).json()["id"]
        quase_no_limite = agora_utc() + sessoes.limite_inatividade() - timedelta(seconds=30)

        sessoes.registrar_atividade(session, sessao_id, aluno.id, agora=quase_no_limite)
        sessoes.encerrar_inativas(session, agora=quase_no_limite + timedelta(seconds=45))

        assert sessoes.buscar_ativa(session, aluno.id) is not None

    def test_heartbeat_em_sessao_encerrada_retorna_409(self, client, cabecalhos):
        sessao_id = client.post("/sessoes", headers=cabecalhos).json()["id"]
        client.post(f"/sessoes/{sessao_id}/encerrar", headers=cabecalhos)

        assert client.post(f"/sessoes/{sessao_id}/atividade", headers=cabecalhos).status_code == 409

    def test_nao_registra_atividade_em_sessao_de_outro_aluno(
        self, client, cabecalhos, cabecalhos_outro_aluno
    ):
        sessao_id = client.post("/sessoes", headers=cabecalhos).json()["id"]

        resposta = client.post(f"/sessoes/{sessao_id}/atividade", headers=cabecalhos_outro_aluno)

        assert resposta.status_code == 404


class TestEncerramentoAutomaticoPorInatividade:
    def test_sessao_sem_atividade_alem_do_limite_e_encerrada(self, client, cabecalhos, aluno, session):
        client.post("/sessoes", headers=cabecalhos)
        muito_depois = agora_utc() + sessoes.limite_inatividade() + timedelta(minutes=1)

        sessoes.encerrar_inativas(session, agora=muito_depois)

        assert sessoes.buscar_ativa(session, aluno.id, agora=muito_depois) is None

    def test_fim_registrado_e_a_ultima_atividade_e_nao_o_instante_da_varredura(
        self, client, cabecalhos, aluno, session
    ):
        # O tempo ocioso não conta como estudo: uma sessão abandonada às 10h e
        # varrida às 15h precisa terminar às 10h, senão o relatório da ticket 11
        # infla a duração com horas em que ninguém estava na frente da tela.
        sessao_id = client.post("/sessoes", headers=cabecalhos).json()["id"]
        ultima_atividade = agora_utc() + timedelta(minutes=5)
        sessoes.registrar_atividade(session, sessao_id, aluno.id, agora=ultima_atividade)

        encerradas = sessoes.encerrar_inativas(
            session, agora=ultima_atividade + timedelta(hours=5)
        )

        assert [como_utc(s.fim) for s in encerradas] == [ultima_atividade]

    def test_sessao_dentro_do_limite_permanece_aberta(self, client, cabecalhos, aluno, session):
        client.post("/sessoes", headers=cabecalhos)
        ainda_dentro = agora_utc() + sessoes.limite_inatividade() - timedelta(seconds=30)

        sessoes.encerrar_inativas(session, agora=ainda_dentro)

        assert sessoes.buscar_ativa(session, aluno.id, agora=ainda_dentro) is not None

    def test_iniciar_sessao_varre_as_inativas_e_libera_a_vaga(self, client, cabecalhos, aluno, session):
        antiga_id = client.post("/sessoes", headers=cabecalhos).json()["id"]
        muito_depois = agora_utc() + sessoes.limite_inatividade() + timedelta(minutes=1)

        nova = sessoes.iniciar(session, aluno.id, agora=muito_depois)

        assert nova.id != antiga_id
        # A antiga saiu de cena: a única em andamento agora é a nova.
        assert sessoes.buscar_ativa(session, aluno.id, agora=muito_depois).id == nova.id

    def test_nao_mexe_em_sessoes_ja_encerradas(self, client, cabecalhos, aluno, session):
        sessao_id = client.post("/sessoes", headers=cabecalhos).json()["id"]
        client.post(f"/sessoes/{sessao_id}/encerrar", headers=cabecalhos)

        encerradas = sessoes.encerrar_inativas(session, agora=agora_utc() + timedelta(days=1))

        assert encerradas == []

    def test_varredura_encerra_sessoes_de_alunos_diferentes_de_uma_vez(
        self, client, cabecalhos, cabecalhos_outro_aluno, session
    ):
        client.post("/sessoes", headers=cabecalhos)
        client.post("/sessoes", headers=cabecalhos_outro_aluno)
        muito_depois = agora_utc() + sessoes.limite_inatividade() + timedelta(minutes=1)

        encerradas = sessoes.encerrar_inativas(session, agora=muito_depois)

        assert len(encerradas) == 2

    def test_sessao_exatamente_no_limite_e_encerrada(self, client, cabecalhos, aluno, session):
        # O limite é inclusivo: parado há exatamente 10 minutos já conta como
        # ausente. Fixar isso evita que um ajuste no corte passe despercebido.
        client.post("/sessoes", headers=cabecalhos)
        no_limite = agora_utc() + sessoes.limite_inatividade()

        assert sessoes.buscar_ativa(session, aluno.id, agora=no_limite) is None


class TestPersistencia:
    def test_o_inicio_gravado_e_o_instante_real_da_chamada(self, client, cabecalhos):
        # Round-trip pelo banco: o SQLite devolve datetime sem fuso, então um
        # deslize na normalização apareceria como um instante fora da janela.
        antes = agora_utc()

        corpo = client.post("/sessoes", headers=cabecalhos).json()

        # fromisoformat só entende o sufixo "Z" a partir do Python 3.11.
        inicio = datetime.fromisoformat(corpo["inicio"].replace("Z", "+00:00"))
        assert antes <= inicio <= agora_utc()

    def test_resposta_serializa_o_inicio_com_fuso_explicito(self, client, cabecalhos):
        corpo = client.post("/sessoes", headers=cabecalhos).json()

        assert corpo["inicio"].endswith("Z") or "+00:00" in corpo["inicio"]


class TestRelatorioDaSessao:
    """Endpoint do relatório de autopercepção (ticket 11).

    A regra vive em `app/relatorio.py` e é testada em `test_relatorio.py`. O que
    se afirma aqui é o que só existe no nível HTTP: quem pode ler o quê.
    """

    def test_relatorio_de_sessao_encerrada(self, client, cabecalhos):
        sessao_id = client.post("/sessoes", headers=cabecalhos).json()["id"]
        client.post(f"/sessoes/{sessao_id}/encerrar", headers=cabecalhos)

        resposta = client.get(f"/sessoes/{sessao_id}/relatorio", headers=cabecalhos)

        assert resposta.status_code == 200
        corpo = resposta.json()
        assert corpo["id_sessao"] == sessao_id
        assert corpo["parcial"] is False
        assert corpo["recomendacoes"]

    def test_relatorio_de_sessao_ainda_aberta_vem_marcado_como_parcial(
        self, client, cabecalhos
    ):
        # É o relatório parcial da ticket 11: sessão interrompida por queda de
        # conexão nunca recebe `fim`, e o aluno não pode perder o que foi medido.
        sessao_id = client.post("/sessoes", headers=cabecalhos).json()["id"]

        corpo = client.get(f"/sessoes/{sessao_id}/relatorio", headers=cabecalhos).json()

        assert corpo["parcial"] is True
        assert corpo["fim"] is None

    def test_relatorio_de_outro_aluno_e_indistinguivel_de_inexistente(
        self, client, cabecalhos, cabecalhos_outro_aluno
    ):
        """Requisito de privacidade do spec: os dados de um estudante são
        visíveis apenas para ele. Responder 403 já entregaria que a sessão
        existe — 404 não conta nada."""
        sessao_id = client.post("/sessoes", headers=cabecalhos).json()["id"]

        resposta = client.get(
            f"/sessoes/{sessao_id}/relatorio", headers=cabecalhos_outro_aluno
        )

        assert resposta.status_code == 404

    def test_relatorio_exige_autenticacao(self, client, cabecalhos):
        sessao_id = client.post("/sessoes", headers=cabecalhos).json()["id"]

        assert client.get(f"/sessoes/{sessao_id}/relatorio").status_code == 401

    def test_relatorio_de_sessao_inexistente(self, client, cabecalhos):
        assert client.get("/sessoes/9999/relatorio", headers=cabecalhos).status_code == 404


class TestHistoricoDeSessoes:
    """Endpoint do histórico (ticket 12).

    A regra vive em `sessoes.listar`, `telemetria.agregar_por_sessao` e
    `relatorio.historico`, e é testada em `test_historico.py`. O que se afirma
    aqui é o que só existe no nível HTTP: quem enxerga o quê.
    """

    def test_lista_as_sessoes_do_aluno(self, client, cabecalhos):
        sessao_id = client.post("/sessoes", headers=cabecalhos).json()["id"]
        client.post(f"/sessoes/{sessao_id}/encerrar", headers=cabecalhos)

        resposta = client.get("/sessoes", headers=cabecalhos)

        assert resposta.status_code == 200
        corpo = resposta.json()
        assert [item["id_sessao"] for item in corpo] == [sessao_id]
        assert corpo[0]["parcial"] is False

    def test_o_historico_de_um_aluno_nao_mostra_a_sessao_de_outro(
        self, client, cabecalhos, cabecalhos_outro_aluno
    ):
        """Requisito de privacidade do spec: os dados de um estudante são
        visíveis apenas para ele. O `id_aluno` vem do token, nunca da URL."""
        client.post("/sessoes", headers=cabecalhos)

        assert client.get("/sessoes", headers=cabecalhos_outro_aluno).json() == []

    def test_historico_exige_autenticacao(self, client):
        assert client.get("/sessoes").status_code == 401

    def test_aluno_sem_sessao_recebe_lista_vazia(self, client, cabecalhos):
        assert client.get("/sessoes", headers=cabecalhos).json() == []

    def test_cada_item_permite_abrir_o_relatorio_daquela_sessao(self, client, cabecalhos):
        # É o segundo critério da ticket: acesso ao relatório completo de cada
        # sessão anterior. O item traz o id, e o id abre o relatório.
        sessao_id = client.post("/sessoes", headers=cabecalhos).json()["id"]
        client.post(f"/sessoes/{sessao_id}/encerrar", headers=cabecalhos)

        (item,) = client.get("/sessoes", headers=cabecalhos).json()
        relatorio = client.get(f"/sessoes/{item['id_sessao']}/relatorio", headers=cabecalhos)

        assert relatorio.status_code == 200
        assert relatorio.json()["id_sessao"] == sessao_id
