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

from app import analista, blocos, sessoes
from app.models import Aluno, BlocoEstudo, SessaoEstudo
from app.tempo import agora_utc, como_utc

def _limite_sem_metodo() -> timedelta:
    """O limite de ausência de uma sessão sem método declarado.

    Estes testes abrem sessão pelo endpoint, que ainda não recebe método, então
    todas caem no valor legado. Perguntar ao próprio módulo, em vez de repetir
    "10 minutos" aqui, mantém o teste medindo a regra e não uma cópia dela.
    """
    return sessoes.limite_de_ausencia_da(SessaoEstudo())


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
    def test_heartbeat_nao_segura_mais_uma_sessao_sem_presenca(
        self, client, cabecalhos, aluno, session
    ):
        """A aba aberta deixou de ser evidência de que alguém está estudando.

        Este teste afirmava exatamente o contrário até os métodos de estudo
        entrarem — e o que ele protegia era o bug. O heartbeat bate a cada 60 s
        enquanto a aba existir, com ou sem aluno na cadeira, então uma sessão
        abandonada com a janela aberta era renovada indefinidamente.

        O que o heartbeat faz agora é descobrir que o servidor já encerrou: a
        exceção abaixo é o 409 que a tela recebe e usa para ressincronizar.
        """
        sessao_id = client.post("/sessoes", headers=cabecalhos).json()["id"]
        passado_o_limite = agora_utc() + _limite_sem_metodo() + timedelta(minutes=1)

        with pytest.raises(sessoes.SessaoJaEncerrada):
            sessoes.registrar_atividade(session, sessao_id, aluno.id, agora=passado_o_limite)

        assert sessoes.buscar_ativa(session, aluno.id, agora=passado_o_limite) is None

    def test_presenca_na_camera_adia_o_encerramento_automatico(
        self, client, cabecalhos, aluno, session
    ):
        """Rosto na câmera é o que segura a sessão — e é só isso que segura."""
        sessao_id = client.post("/sessoes", headers=cabecalhos).json()["id"]
        quase_no_limite = agora_utc() + _limite_sem_metodo() - timedelta(seconds=30)

        sessoes.registrar_presenca(
            session, session.get(SessaoEstudo, sessao_id), agora=quase_no_limite
        )
        depois = quase_no_limite + timedelta(seconds=45)
        sessoes.encerrar_inativas(session, agora=depois)

        assert sessoes.buscar_ativa(session, aluno.id, agora=depois) is not None

    def test_o_heartbeat_responde_a_sessao_viva(self, client, cabecalhos, session):
        """O caminho feliz do heartbeat, que passou a carregar mais do que carregava.

        Ele não segura mais a sessão (quem faz isso é o rosto na câmera), mas
        continua sendo a única requisição periódica de um aluno que lê sem tocar
        no teclado — e é nela que a renovação de credencial pega carona. Um 200
        aqui é o que mantém o aluno logado numa sessão longa de leitura.
        """
        sessao_id = client.post("/sessoes", headers=cabecalhos).json()["id"]

        resposta = client.post(f"/sessoes/{sessao_id}/atividade", headers=cabecalhos)

        assert resposta.status_code == 200
        assert resposta.json()["id"] == sessao_id
        assert resposta.json()["fim"] is None

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
    def test_sessao_sem_presenca_alem_do_limite_e_encerrada(self, client, cabecalhos, aluno, session):
        client.post("/sessoes", headers=cabecalhos)
        muito_depois = agora_utc() + _limite_sem_metodo() + timedelta(minutes=1)

        sessoes.encerrar_inativas(session, agora=muito_depois)

        assert sessoes.buscar_ativa(session, aluno.id, agora=muito_depois) is None

    def test_fim_registrado_e_a_ultima_presenca_e_nao_o_instante_da_varredura(
        self, client, cabecalhos, aluno, session
    ):
        # O tempo de cadeira vazia não conta como estudo: uma sessão abandonada
        # às 10h e varrida às 15h precisa terminar às 10h, senão o relatório da
        # ticket 11 infla a duração com horas em que não havia ninguém.
        sessao_id = client.post("/sessoes", headers=cabecalhos).json()["id"]
        ultima_presenca = agora_utc() + timedelta(minutes=5)
        sessoes.registrar_presenca(
            session, session.get(SessaoEstudo, sessao_id), agora=ultima_presenca
        )

        encerradas = sessoes.encerrar_inativas(
            session, agora=ultima_presenca + timedelta(hours=5)
        )

        assert [como_utc(s.fim) for s in encerradas] == [ultima_presenca]

    def test_sessao_que_nunca_viu_rosto_e_contada_a_partir_do_inicio(
        self, client, cabecalhos, aluno, session
    ):
        """`ultima_presenca` nula não é buraco: é sessão em que ninguém apareceu.

        Webcam negada, modelo que não carregou, aluno que abriu e saiu. Contar a
        partir de `inicio` encerra essa sessão no tempo certo — e, na migração,
        é o que impede que tratar nulo como ausência infinita mate toda sessão
        viva no primeiro boot.
        """
        sessao_id = client.post("/sessoes", headers=cabecalhos).json()["id"]
        inicio = como_utc(session.get(SessaoEstudo, sessao_id).inicio)

        encerradas = sessoes.encerrar_inativas(
            session, agora=inicio + _limite_sem_metodo() + timedelta(minutes=1)
        )

        assert [como_utc(s.fim) for s in encerradas] == [inicio]

    def test_o_limite_vem_do_metodo_declarado_na_sessao(self, client, cabecalhos, aluno, session):
        """Uma pausa de 15 min derruba a sessão sem método e não a do 52/17.

        É a razão inteira de o limite ser por sessão: quem declarou um método
        tem direito à pausa que o método prescreve. O 52/17 tolera 17 + 3 = 20
        min de ausência; a sessão sem método, 10.
        """
        sem_metodo = sessoes.iniciar(session, aluno.id)
        com_metodo = SessaoEstudo(
            id_aluno=aluno.id, inicio=sem_metodo.inicio, pausa_maxima_s=17 * 60
        )
        session.add(com_metodo)
        session.commit()
        session.refresh(com_metodo)

        quinze_minutos_depois = como_utc(sem_metodo.inicio) + timedelta(minutes=15)
        encerradas = sessoes.encerrar_inativas(session, agora=quinze_minutos_depois)

        assert [s.id for s in encerradas] == [sem_metodo.id]

    def test_sessao_dentro_do_limite_permanece_aberta(self, client, cabecalhos, aluno, session):
        client.post("/sessoes", headers=cabecalhos)
        ainda_dentro = agora_utc() + _limite_sem_metodo() - timedelta(seconds=30)

        sessoes.encerrar_inativas(session, agora=ainda_dentro)

        assert sessoes.buscar_ativa(session, aluno.id, agora=ainda_dentro) is not None

    def test_iniciar_sessao_varre_as_inativas_e_libera_a_vaga(self, client, cabecalhos, aluno, session):
        antiga_id = client.post("/sessoes", headers=cabecalhos).json()["id"]
        muito_depois = agora_utc() + _limite_sem_metodo() + timedelta(minutes=1)

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
        muito_depois = agora_utc() + _limite_sem_metodo() + timedelta(minutes=1)

        encerradas = sessoes.encerrar_inativas(session, agora=muito_depois)

        assert len(encerradas) == 2

    def test_sessao_exatamente_no_limite_e_encerrada(self, client, cabecalhos, aluno, session):
        # O limite é inclusivo: parado há exatamente 10 minutos já conta como
        # ausente. Fixar isso evita que um ajuste no corte passe despercebido.
        client.post("/sessoes", headers=cabecalhos)
        no_limite = agora_utc() + _limite_sem_metodo()

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


class TestContextoDeclaradoNaSessao:
    """O que o aluno declara na tela inicial: método, assunto e meta (passo 8)."""

    def test_grava_o_metodo_o_assunto_e_a_meta(self, client, cabecalhos):
        resposta = client.post(
            "/sessoes",
            headers=cabecalhos,
            json={
                "metodo": "pomodoro",
                "assunto": "Cálculo II, integrais por partes",
                "meta_de_blocos": 4,
            },
        )

        assert resposta.status_code == 201
        corpo = resposta.json()
        assert corpo["metodo"] == "pomodoro"
        assert corpo["assunto"] == "Cálculo II, integrais por partes"
        assert corpo["meta_de_blocos"] == 4

    def test_o_nome_legivel_do_metodo_viaja_junto_do_codigo(self, client, cabecalhos):
        """A tela mostra "Pomodoro", não "pomodoro" — e sem tabela de tradução.

        Mesmo contrato de `AlertaPublico`: código para a máquina, nome para a
        pessoa, os dois no mesmo objeto.
        """
        corpo = client.post("/sessoes", headers=cabecalhos, json={"metodo": "52-17"}).json()

        assert (corpo["metodo"], corpo["metodo_nome"]) == ("52-17", "52/17")

    def test_a_pausa_maxima_e_resolvida_no_servidor_a_partir_do_catalogo(
        self, client, cabecalhos, session
    ):
        """O cliente manda o código; o número sai do catálogo.

        Pomodoro declara pausa curta de 5 min — 300 s —, e é esse valor que tem
        de estar congelado na linha da sessão. A conta é a do catálogo, feita à
        mão: 5 × 60.
        """
        aberta = client.post("/sessoes", headers=cabecalhos, json={"metodo": "pomodoro"})

        assert session.get(SessaoEstudo, aberta.json()["id"]).pausa_maxima_s == 5 * 60

    def test_pausa_maxima_mandada_pelo_cliente_e_ignorada(self, client, cabecalhos, session):
        """"Sessão que nunca encerra" não pode ser um campo de request.

        Se o número viesse do corpo, bastaria um curl com
        `pausa_maxima_s: 999999` para manter uma sessão viva para sempre. O
        campo simplesmente não existe no DTO, e o que chega junto é descartado.
        """
        sessao_id = client.post(
            "/sessoes",
            headers=cabecalhos,
            json={"metodo": "pomodoro", "pausa_maxima_s": 999999},
        ).json()["id"]

        assert session.get(SessaoEstudo, sessao_id).pausa_maxima_s == 5 * 60

    def test_metodo_desconhecido_e_recusado_sem_abrir_sessao(
        self, client, cabecalhos, aluno, session
    ):
        resposta = client.post("/sessoes", headers=cabecalhos, json={"metodo": "feynman"})

        assert resposta.status_code == 422
        assert "feynman" in resposta.json()["detail"]
        assert sessoes.buscar_ativa(session, aluno.id) is None

    def test_sessao_sem_corpo_continua_valendo_e_fica_sem_metodo(
        self, client, cabecalhos, session
    ):
        """`NULL` é "não declarou", e não `"livre"`.

        Colapsar os dois faria o relatório afirmar uma escolha que ninguém fez —
        a mesma distinção que a migração protege para as sessões antigas.
        """
        sessao_id = client.post("/sessoes", headers=cabecalhos).json()["id"]

        assert session.get(SessaoEstudo, sessao_id).metodo is None

    def test_sem_metodo_declarado_e_diferente_de_metodo_nulo(self, client, cabecalhos, session):
        aberta = client.post("/sessoes", headers=cabecalhos, json={"metodo": "livre"})

        assert session.get(SessaoEstudo, aberta.json()["id"]).metodo == "livre"

    def test_assunto_acima_do_teto_e_recusado(self, client, cabecalhos):
        from app.schemas import LIMITE_ASSUNTO_CARACTERES

        resposta = client.post(
            "/sessoes",
            headers=cabecalhos,
            json={"assunto": "a" * (LIMITE_ASSUNTO_CARACTERES + 1)},
        )

        assert resposta.status_code == 422

    def test_assunto_exatamente_no_teto_passa(self, client, cabecalhos):
        from app.schemas import LIMITE_ASSUNTO_CARACTERES

        resposta = client.post(
            "/sessoes", headers=cabecalhos, json={"assunto": "a" * LIMITE_ASSUNTO_CARACTERES}
        )

        assert resposta.status_code == 201

    def test_espaco_em_branco_no_fim_nao_consome_o_teto(self, client, cabecalhos):
        """A limpeza vem antes da medida, senão um espaço sobrando reprova um
        assunto que cabe."""
        from app.schemas import LIMITE_ASSUNTO_CARACTERES

        resposta = client.post(
            "/sessoes",
            headers=cabecalhos,
            json={"assunto": "a" * LIMITE_ASSUNTO_CARACTERES + "   "},
        )

        assert resposta.status_code == 201

    def test_assunto_explicitamente_nulo_continua_nulo(self, client, cabecalhos, session):
        """O cliente que manda `"assunto": null` não pode receber erro.

        É o que a tela envia quando o aluno apaga o campo antes de começar, e a
        limpeza de espaços precisa atravessar o nulo sem tropeçar nele.
        """
        aberta = client.post("/sessoes", headers=cabecalhos, json={"assunto": None})

        assert session.get(SessaoEstudo, aberta.json()["id"]).assunto is None

    def test_assunto_so_de_espacos_vira_nulo(self, client, cabecalhos, session):
        """"   " não é traço nem é assunto: é um terceiro estado que nenhuma
        tela sabe desenhar."""
        aberta = client.post("/sessoes", headers=cabecalhos, json={"assunto": "   "})

        assert session.get(SessaoEstudo, aberta.json()["id"]).assunto is None

    @pytest.mark.parametrize("meta", [0, -1, 13])
    def test_meta_de_blocos_fora_da_faixa_e_recusada(self, client, cabecalhos, meta):
        """De 1 a 12. Sem teto, o relatório leria em voz alta "você planejou
        900000 blocos, foram executados 3"."""
        resposta = client.post("/sessoes", headers=cabecalhos, json={"meta_de_blocos": meta})

        assert resposta.status_code == 422

    def test_o_historico_mostra_o_metodo_e_o_assunto(self, client, cabecalhos):
        sessao_id = client.post(
            "/sessoes", headers=cabecalhos, json={"metodo": "pomodoro", "assunto": "Redes"}
        ).json()["id"]
        client.post(f"/sessoes/{sessao_id}/encerrar", headers=cabecalhos)

        linha = client.get("/sessoes/historico", headers=cabecalhos).json()[0]

        assert (linha["metodo"], linha["metodo_nome"], linha["assunto"]) == (
            "pomodoro",
            "Pomodoro",
            "Redes",
        )

    def test_sessao_sem_metodo_aparece_no_historico_sem_nome_inventado(self, client, cabecalhos):
        """`null`, e não "Sem método": o histórico desenha traço para o que não
        foi declarado."""
        sessao_id = client.post("/sessoes", headers=cabecalhos).json()["id"]
        client.post(f"/sessoes/{sessao_id}/encerrar", headers=cabecalhos)

        linha = client.get("/sessoes/historico", headers=cabecalhos).json()[0]

        assert linha["metodo"] is None
        assert linha["metodo_nome"] is None


class TestCatalogoDeMetodos:
    def test_sem_token_retorna_401(self, client):
        assert client.get("/metodos").status_code == 401

    def test_devolve_o_catalogo_com_nome_legivel(self, client, cabecalhos):
        """Todo método gravável tem nome — espelha a trava de `NOMES_DE_ALERTA`.

        Sem isso, acrescentar um método ao catálogo o faria aparecer na tela
        inicial como `52-17`.
        """
        catalogo = client.get("/metodos", headers=cabecalhos).json()

        assert [m["codigo"] for m in catalogo] == [
            "pomodoro",
            "52-17",
            "flow",
            "timeboxing",
            "livre",
        ]
        assert all(m["nome"] and m["nome"] != m["codigo"] for m in catalogo)

    def test_traz_os_parametros_que_o_cronometro_precisa(self, client, cabecalhos):
        # Pomodoro: 25 min de foco, 5 de pausa curta, 4 ciclos, 15 de pausa longa.
        catalogo = client.get("/metodos", headers=cabecalhos).json()
        pomodoro = next(m for m in catalogo if m["codigo"] == "pomodoro")

        assert pomodoro["foco_s"] == 25 * 60
        assert pomodoro["pausa_s"] == 5 * 60
        assert pomodoro["ciclos_ate_pausa_longa"] == 4
        assert pomodoro["pausa_longa_s"] == 15 * 60

    def test_metodo_sem_duracao_de_bloco_vem_com_foco_nulo(self, client, cabecalhos):
        """Nulo, e não zero: a tela não pode desenhar contagem regressiva a
        partir de zero para quem escolheu Flow."""
        catalogo = client.get("/metodos", headers=cabecalhos).json()

        assert next(m for m in catalogo if m["codigo"] == "flow")["foco_s"] is None


class TestBlocosDeclarados:
    def test_iniciar_nao_abre_bloco_nenhum(self, client, cabecalhos):
        """O primeiro bloco é declarado, como todos os outros.

        Entre o `POST /sessoes` e o primeiro segundo de estudo há a permissão da
        webcam, o MediaPipe carregando e 60 s de calibração. Abrir um bloco aqui
        inflaria o primeiro bloco de toda sessão, sempre para o mesmo lado.
        """
        sessao_id = client.post("/sessoes", headers=cabecalhos).json()["id"]

        assert client.get(f"/sessoes/{sessao_id}/blocos", headers=cabecalhos).json() == []

    def test_declarar_foco_abre_o_bloco_um(self, client, cabecalhos):
        sessao_id = client.post("/sessoes", headers=cabecalhos).json()["id"]

        resposta = client.post(
            f"/sessoes/{sessao_id}/blocos", headers=cabecalhos, json={"tipo": "foco"}
        )

        assert resposta.status_code == 200
        corpo = resposta.json()
        assert (corpo["indice"], corpo["tipo"], corpo["fim"]) == (1, "foco", None)
        assert corpo["origem"] == "metodo"

    def test_a_transicao_e_uma_borda_so(self, client, cabecalhos):
        """O `fim` do bloco que acaba é o `inicio` do que começa.

        Sem buraco e sem sobreposição: qualquer folga entre os dois seria tempo
        de sessão que não pertence a bloco nenhum, e o relatório teria de
        explicar de onde ele veio.
        """
        sessao_id = client.post("/sessoes", headers=cabecalhos).json()["id"]
        client.post(f"/sessoes/{sessao_id}/blocos", headers=cabecalhos, json={"tipo": "foco"})
        client.post(f"/sessoes/{sessao_id}/blocos", headers=cabecalhos, json={"tipo": "pausa"})

        primeiro, segundo = client.get(f"/sessoes/{sessao_id}/blocos", headers=cabecalhos).json()

        assert primeiro["fim"] == segundo["inicio"]
        assert (primeiro["indice"], segundo["indice"]) == (1, 2)

    def test_declarar_de_novo_o_mesmo_tipo_nao_parte_o_bloco_em_dois(
        self, client, cabecalhos
    ):
        """Retentativa de rede e segunda aba dizem a mesma coisa duas vezes.

        Abrir um segundo bloco transformaria uma pausa em duas, a primeira de
        duração zero — um artefato do transporte virando fato no relatório. O
        instante preservado é o da primeira declaração, que é a que o aluno fez.
        """
        sessao_id = client.post("/sessoes", headers=cabecalhos).json()["id"]
        primeiro = client.post(
            f"/sessoes/{sessao_id}/blocos", headers=cabecalhos, json={"tipo": "foco"}
        ).json()

        repetido = client.post(
            f"/sessoes/{sessao_id}/blocos", headers=cabecalhos, json={"tipo": "foco"}
        ).json()

        assert repetido == primeiro
        assert len(client.get(f"/sessoes/{sessao_id}/blocos", headers=cabecalhos).json()) == 1

    def test_a_origem_declarada_pelo_aluno_e_gravada(self, client, cabecalhos):
        """É a única coisa que separa "seguiu o método" de "reescreveu o método
        no meio" — e só o cliente, que tem o cronômetro, sabe qual foi."""
        sessao_id = client.post("/sessoes", headers=cabecalhos).json()["id"]

        corpo = client.post(
            f"/sessoes/{sessao_id}/blocos",
            headers=cabecalhos,
            json={"tipo": "pausa", "origem": "aluno"},
        ).json()

        assert corpo["origem"] == "aluno"

    def test_tipo_fora_do_vocabulario_retorna_422(self, client, cabecalhos):
        sessao_id = client.post("/sessoes", headers=cabecalhos).json()["id"]

        resposta = client.post(
            f"/sessoes/{sessao_id}/blocos", headers=cabecalhos, json={"tipo": "descanso"}
        )

        assert resposta.status_code == 422

    def test_origem_fora_do_vocabulario_retorna_422(self, client, cabecalhos):
        sessao_id = client.post("/sessoes", headers=cabecalhos).json()["id"]

        resposta = client.post(
            f"/sessoes/{sessao_id}/blocos",
            headers=cabecalhos,
            json={"tipo": "foco", "origem": "servidor"},
        )

        assert resposta.status_code == 422

    def test_nao_declara_bloco_em_sessao_de_outro_aluno(
        self, client, cabecalhos, cabecalhos_outro_aluno
    ):
        sessao_id = client.post("/sessoes", headers=cabecalhos).json()["id"]

        resposta = client.post(
            f"/sessoes/{sessao_id}/blocos", headers=cabecalhos_outro_aluno, json={"tipo": "foco"}
        )

        assert resposta.status_code == 404

    def test_nao_declara_bloco_em_sessao_encerrada(self, client, cabecalhos):
        sessao_id = client.post("/sessoes", headers=cabecalhos).json()["id"]
        client.post(f"/sessoes/{sessao_id}/encerrar", headers=cabecalhos)

        resposta = client.post(
            f"/sessoes/{sessao_id}/blocos", headers=cabecalhos, json={"tipo": "foco"}
        )

        assert resposta.status_code == 409

    def test_nao_lista_blocos_de_sessao_de_outro_aluno(
        self, client, cabecalhos, cabecalhos_outro_aluno
    ):
        sessao_id = client.post("/sessoes", headers=cabecalhos).json()["id"]

        resposta = client.get(f"/sessoes/{sessao_id}/blocos", headers=cabecalhos_outro_aluno)

        assert resposta.status_code == 404


class TestIntegridadeDosBlocosNoEncerramento:
    """Bloco com `fim` nulo dentro de sessão encerrada é dado corrompido.

    Não estoura em lugar nenhum e não aparece em teste de rota: só se manifesta
    semanas depois, como um bloco de duração infinita no relatório de alguém.
    """

    def test_encerrar_fecha_o_bloco_aberto_com_o_fim_da_sessao(self, client, cabecalhos, session):
        sessao_id = client.post("/sessoes", headers=cabecalhos).json()["id"]
        client.post(f"/sessoes/{sessao_id}/blocos", headers=cabecalhos, json={"tipo": "foco"})

        encerrada = client.post(f"/sessoes/{sessao_id}/encerrar", headers=cabecalhos).json()
        bloco = client.get(f"/sessoes/{sessao_id}/blocos", headers=cabecalhos).json()[0]

        assert bloco["fim"] == encerrada["fim"]

    def test_a_varredura_de_ausencia_tambem_fecha_o_bloco(
        self, client, cabecalhos, aluno, session
    ):
        """O caminho em que esquecer disso seria mais fácil e mais caro.

        A sessão derrubada por queda de conexão é exatamente a que ninguém fecha
        à mão, e ela ficaria para sempre com um bloco aberto dentro.
        """
        sessao = sessoes.iniciar(session, aluno.id)
        sessoes.declarar_bloco(session, sessao.id, aluno.id, tipo=blocos.TIPO_FOCO)
        # Cinco minutos de rosto na câmera e então o silêncio: o `fim` da sessão
        # será essa última presença, que é posterior ao início do bloco.
        ultima_presenca = como_utc(sessao.inicio) + timedelta(minutes=5)
        sessoes.registrar_presenca(session, sessao, agora=ultima_presenca)
        muito_depois = ultima_presenca + _limite_sem_metodo() + timedelta(minutes=1)

        (encerrada,) = sessoes.encerrar_inativas(session, agora=muito_depois)
        bloco = sessoes.listar_blocos(session, sessao.id)[0]

        assert bloco.fim is not None
        assert como_utc(bloco.fim) == como_utc(encerrada.fim)

    def test_bloco_declarado_depois_da_ultima_presenca_nao_termina_antes_de_comecar(
        self, client, cabecalhos, aluno, session
    ):
        """O aluno declarou a pausa e não voltou mais.

        A varredura grava `fim = ultima_presenca`, um instante anterior ao
        `inicio` do bloco. Fechar o bloco com esse valor o deixaria terminando
        antes de começar — duração negativa no relatório. A leitura certa é
        duração zero: declarado e não executado.
        """
        sessao = sessoes.iniciar(session, aluno.id)
        presenca_em = como_utc(sessao.inicio) + timedelta(minutes=2)
        sessoes.registrar_presenca(session, sessao, agora=presenca_em)
        declarado_em = presenca_em + timedelta(seconds=30)
        sessoes.declarar_bloco(
            session, sessao.id, aluno.id, tipo=blocos.TIPO_PAUSA, agora=declarado_em
        )

        sessoes.encerrar_inativas(
            session, agora=declarado_em + _limite_sem_metodo() + timedelta(minutes=1)
        )
        bloco = sessoes.listar_blocos(session, sessao.id)[0]

        assert como_utc(bloco.fim) == declarado_em
        assert blocos.duracao(bloco) == timedelta(0)

    def test_nenhuma_sessao_encerrada_fica_com_bloco_aberto(self, client, cabecalhos, session):
        """A invariante, verificada de uma vez sobre as duas formas de encerrar."""
        manual_id = client.post("/sessoes", headers=cabecalhos).json()["id"]
        client.post(f"/sessoes/{manual_id}/blocos", headers=cabecalhos, json={"tipo": "foco"})
        client.post(f"/sessoes/{manual_id}/encerrar", headers=cabecalhos)

        varrida_id = client.post("/sessoes", headers=cabecalhos).json()["id"]
        client.post(f"/sessoes/{varrida_id}/blocos", headers=cabecalhos, json={"tipo": "foco"})
        sessoes.encerrar_inativas(
            session, agora=agora_utc() + _limite_sem_metodo() + timedelta(minutes=1)
        )

        abertos = session.exec(
            select(BlocoEstudo, SessaoEstudo)
            .where(BlocoEstudo.id_sessao == SessaoEstudo.id)
            .where(BlocoEstudo.fim.is_(None), SessaoEstudo.fim.is_not(None))
        ).all()

        assert abertos == []


class TestBaselineDescartadaNoEncerramento:
    """`RegistroDeAnalistas.descartar` era público e ninguém o chamava.

    Cada sessão encerrada deixava a própria baseline em memória até vencer pelo
    TTL — que passou a ser o teto de ausência, 20 min. Com sessões longas e uma
    turma inteira, é vazamento que só cresce.
    """

    def test_encerrar_descarta_a_baseline_da_sessao(self, client, cabecalhos, aluno, session):
        sessao = sessoes.iniciar(session, aluno.id)
        durante = analista.registro.obter(sessao.id)

        sessoes.encerrar(session, sessao.id, aluno.id)

        assert analista.registro.obter(sessao.id) is not durante

    def test_a_varredura_tambem_descarta(self, client, cabecalhos, aluno, session):
        sessao = sessoes.iniciar(session, aluno.id)
        durante = analista.registro.obter(sessao.id)

        sessoes.encerrar_inativas(
            session, agora=como_utc(sessao.inicio) + _limite_sem_metodo() + timedelta(minutes=1)
        )

        assert analista.registro.obter(sessao.id) is not durante

    def test_a_baseline_sobrevive_enquanto_a_sessao_esta_viva(
        self, client, cabecalhos, aluno, session
    ):
        """A trava do outro lado: descartar cedo demais faria o aluno recalibrar
        no meio da sessão, que é o problema que o registro existe para evitar."""
        sessao = sessoes.iniciar(session, aluno.id)
        durante = analista.registro.obter(sessao.id)

        sessoes.encerrar_inativas(session, agora=como_utc(sessao.inicio) + timedelta(minutes=1))

        assert analista.registro.obter(sessao.id) is durante
