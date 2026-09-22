"""Tetos de entrada: tamanho de campo, tamanho da mensagem de erro, tamanho do corpo.

Os números esperados são calculados **à mão a partir da definição**, e nunca
lidos da constante que estão verificando: um teste que afirma
`LIMITE_CODIGO_DE_METODO == LIMITE_CODIGO_DE_METODO` passa com qualquer valor,
inclusive com o valor errado do dia em que alguém mexer sem querer.
"""
import asyncio

import pytest
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient
from sqlmodel import select

from app import blocos, metodos
from app.limites import LIMITE_DE_CORPO_BYTES, LimiteDeCorpo
from app.models import Aluno, SessaoEstudo
from app.routers.sessoes import LIMITE_DE_ECO_DO_VALOR, _recortado
from app.schemas import (
    LIMITE_CODIGO_DE_METODO,
    LIMITE_DE_ECO_CARACTERES,
    LIMITE_NOME_CARACTERES,
    LIMITE_ORIGEM_DE_BLOCO,
    LIMITE_TIPO_DE_BLOCO,
)

#: Os dois tamanhos que a auditoria usou. A pergunta que eles respondem juntos
#: não é "o servidor recusa?", é "a recusa do segundo custa mais que a do
#: primeiro?" — que é a definição de amplificação por reflexão.
GRANDE = 5_000

#: Grande o bastante para estourar qualquer teto de campo, e **pequeno o
#: bastante para caber no teto de corpo** (`LIMITE_DE_CORPO_BYTES`, 64 KB).
#:
#: Os dois tetos defendem coisas diferentes e é preciso exercitar os dois. O de
#: corpo recusa antes de o pydantic ver qualquer coisa, então um valor acima
#: dele nunca chegaria ao corte de campo — e estes testes, que existem para
#: medir o corte de campo, passariam a medir o middleware sem ninguém notar.
#: O 413 tem teste próprio, em `TestTetoDeCorpo`.
ABSURDO = 20_000


@pytest.fixture(name="cabecalhos")
def cabecalhos_fixture(client):
    client.post(
        "/auth/registro",
        json={"nome": "Aluna de Teste", "email": "aluna@exemplo.com", "senha": "senha12345"},
    )
    token = client.post(
        "/auth/login", json={"email": "aluna@exemplo.com", "senha": "senha12345"}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _campos_recusados(resposta):
    """Os campos que o pydantic recusou, ou `[]` se a recusa não veio dele.

    A recusa por teto de campo e a recusa por vocabulário chegam as duas como
    422, e é por isso que os testes daqui olham a forma do corpo: o pydantic
    devolve `detail` como lista de erros com `loc`; as mensagens escritas à mão
    em `app/routers/sessoes.py` devolvem `detail` como uma frase.
    """
    detalhe = resposta.json()["detail"]
    if not isinstance(detalhe, list):
        return []
    return [erro["loc"] for erro in detalhe]


class TestTetosDerivadosDoVocabulario:
    """`metodo`, `tipo` e `origem` não são texto livre: o teto sai do catálogo."""

    def test_o_maior_codigo_de_metodo_do_catalogo_tem_dez_caracteres(self):
        """A conta à mão: pomodoro(8), 52-17(5), flow(4), timeboxing(10), livre(5)."""
        assert max(metodos.METODOS, key=len) == "timeboxing"
        assert len("timeboxing") == 10

    def test_o_teto_do_codigo_de_metodo_e_o_dobro_do_maior_codigo(self):
        assert LIMITE_CODIGO_DE_METODO == 20

    def test_o_teto_do_tipo_de_bloco_e_o_dobro_de_pausa(self):
        """`foco`(4) e `pausa`(5); o maior tem 5, o teto é 10."""
        assert blocos.TIPOS == {"foco", "pausa"}
        assert LIMITE_TIPO_DE_BLOCO == 10

    def test_o_teto_da_origem_de_bloco_e_o_dobro_de_metodo(self):
        """`metodo`(6) e `aluno`(5); o maior tem 6, o teto é 12."""
        assert blocos.ORIGENS == {"metodo", "aluno"}
        assert LIMITE_ORIGEM_DE_BLOCO == 12

    def test_todo_valor_do_vocabulario_cabe_no_proprio_teto(self):
        """A trava: um método novo de código longo não pode nascer irrecebível."""
        for codigo in metodos.METODOS:
            assert len(codigo) <= LIMITE_CODIGO_DE_METODO
        for tipo in blocos.TIPOS:
            assert len(tipo) <= LIMITE_TIPO_DE_BLOCO
        for origem in blocos.ORIGENS:
            assert len(origem) <= LIMITE_ORIGEM_DE_BLOCO


class TestNomeNoCadastro:
    """`POST /auth/registro` é o único corpo desta API aberto a quem não tem token."""

    def _registrar(self, client, nome):
        return client.post(
            "/auth/registro",
            json={"nome": nome, "email": "nova@exemplo.com", "senha": "senha12345"},
        )

    def test_nome_exatamente_no_teto_e_aceito(self, client):
        assert self._registrar(client, "a" * LIMITE_NOME_CARACTERES).status_code == 201

    def test_nome_um_caractere_acima_do_teto_e_recusado(self, client):
        assert self._registrar(client, "a" * (LIMITE_NOME_CARACTERES + 1)).status_code == 422

    def test_nome_absurdo_nao_chega_ao_banco(self, client, session):
        """O defeito medido: 201, 200 mil caracteres gravados, e devolvidos em
        toda resposta que trouxesse o aluno dali em diante."""
        resposta = self._registrar(client, "a" * ABSURDO)

        assert resposta.status_code == 422
        assert session.exec(select(Aluno)).all() == []

    def test_a_recusa_do_nome_nao_cresce_com_o_que_foi_mandado(self, client):
        """O teto de campo sozinho não resolveria isto.

        O 422 do pydantic repete o valor recebido inteiro no campo `input`: com
        `max_length` e mais nada, os 200 KB parariam de ser gravados e passariam
        a ser **devolvidos**. É o que `CorpoRecebido` existe para impedir.
        """
        grande = self._registrar(client, "a" * GRANDE)
        absurdo = self._registrar(client, "a" * ABSURDO)

        assert grande.status_code == absurdo.status_code == 422
        assert len(grande.content) == len(absurdo.content)

    def test_a_recusa_do_email_absurdo_tambem_nao_cresce(self, client):
        """O recorte é do corpo inteiro, e não de um campo: o e-mail entra junto."""
        respostas = [
            client.post(
                "/auth/registro",
                json={"nome": "Aluna", "email": "a" * tamanho, "senha": "senha12345"},
            )
            for tamanho in (GRANDE, ABSURDO)
        ]

        assert [r.status_code for r in respostas] == [422, 422]
        assert len(respostas[0].content) == len(respostas[1].content)

    def test_corpo_que_nao_e_objeto_json_nao_quebra_o_recorte(self, client):
        """Uma lista no lugar do objeto tem que sair como 422, e não como 500.

        O recorte roda antes de tudo, inclusive antes de alguém ter conferido
        que o corpo é um objeto — e um middleware de segurança que estoura com
        entrada torta troca um defeito de disponibilidade por outro.
        """
        resposta = client.post("/auth/registro", json=["a" * ABSURDO])

        assert resposta.status_code == 422

    def test_o_recorte_nao_transforma_senha_invalida_em_valida(self, client):
        """O corte deixa 321 caracteres, e 321 caracteres continuam acima de 72 bytes.

        É a única coisa que um recorte antes da validação poderia estragar:
        encurtar um valor até ele caber num teto que ele não respeitava.
        """
        resposta = client.post(
            "/auth/registro",
            json={"nome": "Aluna", "email": "nova@exemplo.com", "senha": "s" * ABSURDO},
        )

        assert resposta.status_code == 422
        assert LIMITE_DE_ECO_CARACTERES + 1 > 72


class TestMetodoTipoEOrigem:
    def test_metodo_exatamente_no_teto_chega_a_mensagem_boa(self, client, cabecalhos):
        """Vinte caracteres não são método nenhum, e o aluno precisa ler *por quê*.

        Se o teto recusasse antes, a resposta seria "String should have at most
        20 characters" — verdadeira, inútil e sem o ponteiro para `GET /metodos`.
        """
        resposta = client.post(
            "/sessoes", headers=cabecalhos, json={"metodo": "p" * LIMITE_CODIGO_DE_METODO}
        )

        assert resposta.status_code == 422
        assert "GET /metodos" in resposta.json()["detail"]

    def test_metodo_acima_do_teto_para_no_campo_e_nao_no_catalogo(self, client, cabecalhos):
        """Quem recusa precisa ser o teto, e dá para saber pela forma da resposta.

        O 422 do catálogo tem `detail` de texto ("Método de estudo
        desconhecido..."); o do teto tem `detail` de lista, com o campo em
        `loc`. Sem o teto, um código de 21 caracteres ainda daria 422 — o do
        catálogo — e o teste passaria sem provar nada.
        """
        resposta = client.post(
            "/sessoes", headers=cabecalhos, json={"metodo": "p" * (LIMITE_CODIGO_DE_METODO + 1)}
        )

        assert resposta.status_code == 422
        assert _campos_recusados(resposta) == [["body", "metodo"]]

    def test_tipo_acima_do_teto_para_no_campo_e_nao_no_vocabulario(self, client, cabecalhos):
        id_sessao = client.post("/sessoes", headers=cabecalhos).json()["id"]

        resposta = client.post(
            f"/sessoes/{id_sessao}/blocos",
            headers=cabecalhos,
            json={"tipo": "f" * (LIMITE_TIPO_DE_BLOCO + 1)},
        )

        assert resposta.status_code == 422
        assert _campos_recusados(resposta) == [["body", "tipo"]]

    def test_origem_acima_do_teto_para_no_campo_e_nao_no_vocabulario(self, client, cabecalhos):
        id_sessao = client.post("/sessoes", headers=cabecalhos).json()["id"]

        resposta = client.post(
            f"/sessoes/{id_sessao}/blocos",
            headers=cabecalhos,
            json={"tipo": "foco", "origem": "m" * (LIMITE_ORIGEM_DE_BLOCO + 1)},
        )

        assert resposta.status_code == 422
        assert _campos_recusados(resposta) == [["body", "origem"]]

    def test_nenhum_dos_tres_abre_sessao_nem_bloco(self, client, cabecalhos, session):
        client.post("/sessoes", headers=cabecalhos, json={"metodo": "p" * ABSURDO})

        assert session.exec(select(SessaoEstudo)).all() == []

    @pytest.mark.parametrize("campo", ["metodo", "tipo", "origem"])
    def test_a_recusa_nao_cresce_com_o_valor_recebido(self, client, cabecalhos, campo):
        """5.000 caracteres davam 5.097 bytes de resposta; 200 mil davam 200.097.

        O custo de mandar é do cliente e o de responder era do servidor, o que
        faz da recusa um amplificador. Depois do teto, os dois tamanhos de
        request produzem exatamente a mesma resposta.
        """
        id_sessao = client.post("/sessoes", headers=cabecalhos).json()["id"]

        def recusar(tamanho):
            if campo == "metodo":
                return client.post(
                    "/sessoes", headers=cabecalhos, json={"metodo": "p" * tamanho}
                )
            corpo = {"tipo": "foco", "origem": "metodo"}
            corpo[campo] = "x" * tamanho
            return client.post(
                f"/sessoes/{id_sessao}/blocos", headers=cabecalhos, json=corpo
            )

        grande, absurdo = recusar(GRANDE), recusar(ABSURDO)

        # 422 vem do teto do campo; 413 vem do teto de corpo, que recusa antes
        # de o pydantic ver qualquer coisa. Os dois são recusa, e é isso que o
        # teste afirma — fixar o código exato aqui obrigaria a reescrever este
        # teste toda vez que a ordem dos tetos mudasse, sem medir nada a mais.
        assert grande.status_code in (413, 422)
        assert absurdo.status_code in (413, 422)

        # A propriedade que importa: a resposta não cresce com o que foi
        # mandado. Antes, 5 mil caracteres davam 5.097 bytes e 200 mil davam
        # 200.097 — o custo de mandar era do cliente e o de responder, do
        # servidor. Agora as duas são pequenas e o teto de uma não depende da
        # outra.
        assert len(grande.content) < 1000
        assert len(absurdo.content) < 1000


class TestAMensagemDeErroContinuaUtil:
    """Nada disto pode ter sido comprado com uma mensagem pior para quem errou."""

    def test_metodo_desconhecido_cita_o_codigo_e_aponta_o_catalogo(self, client, cabecalhos):
        detalhe = client.post(
            "/sessoes", headers=cabecalhos, json={"metodo": "feynman"}
        ).json()["detail"]

        assert "feynman" in detalhe
        assert "GET /metodos" in detalhe

    def test_tipo_desconhecido_cita_o_valor_e_os_dois_tipos(self, client, cabecalhos):
        id_sessao = client.post("/sessoes", headers=cabecalhos).json()["id"]

        detalhe = client.post(
            f"/sessoes/{id_sessao}/blocos", headers=cabecalhos, json={"tipo": "descanso"}
        ).json()["detail"]

        assert "descanso" in detalhe
        assert "foco" in detalhe and "pausa" in detalhe

    def test_origem_desconhecida_cita_o_valor_e_as_duas_origens(self, client, cabecalhos):
        id_sessao = client.post("/sessoes", headers=cabecalhos).json()["id"]

        detalhe = client.post(
            f"/sessoes/{id_sessao}/blocos",
            headers=cabecalhos,
            json={"tipo": "foco", "origem": "servidor"},
        ).json()["detail"]

        assert "servidor" in detalhe
        assert "metodo" in detalhe and "aluno" in detalhe

    def test_o_valor_curto_aparece_inteiro_e_entre_aspas(self):
        """As aspas não são enfeite: são o que separa `'foco '` de `'foco'`."""
        assert _recortado("feynman") == "'feynman'"
        assert _recortado("foco ") == "'foco '"

    def test_o_valor_longo_sai_cortado_e_marcado(self):
        """Tamanho calculado à mão: 24 caracteres + `…` + as duas aspas do repr."""
        recortado = _recortado("p" * 1_000)

        assert len(recortado) == LIMITE_DE_ECO_DO_VALOR + 1 + 2
        assert recortado.endswith("…'")

    def test_o_tamanho_do_recorte_nao_depende_do_que_entrou(self):
        assert len(_recortado("p" * GRANDE)) == len(_recortado("p" * ABSURDO))


class TestLimiteDeCorpo:
    """O middleware ASGI, exercitado direto — ele ainda não está montado no `app`.

    Montado numa aplicação mínima de propósito: o que se verifica aqui é a regra
    do middleware, e ela não deve depender de qual rota está atrás dele.
    """

    @staticmethod
    def _app_com_limite(limite_bytes):
        interna = FastAPI()

        @interna.post("/eco")
        def eco(corpo: dict) -> dict:
            return {"recebido": len(corpo)}

        @interna.websocket("/ws")
        async def ws(websocket: WebSocket):
            await websocket.accept()
            await websocket.send_text("vivo")
            await websocket.close()

        interna.add_middleware(LimiteDeCorpo, limite_bytes=limite_bytes)
        return interna

    def test_o_teto_padrao_e_de_64_kb(self):
        """Calculado à mão: 64 * 1024."""
        assert LIMITE_DE_CORPO_BYTES == 65_536

    def test_corpo_no_teto_passa(self):
        cliente = TestClient(self._app_com_limite(200))
        corpo = {"a": "x" * 100}

        assert cliente.post("/eco", json=corpo).status_code == 200

    def test_corpo_acima_do_teto_recebe_413(self):
        cliente = TestClient(self._app_com_limite(200))

        resposta = cliente.post("/eco", json={"a": "x" * 500})

        assert resposta.status_code == 413
        assert "limite" in resposta.json()["detail"]

    def test_o_corpo_grande_nao_chega_a_aplicacao(self):
        """A aplicação devolveria 200: o 413 prova que ela não foi chamada."""
        cliente = TestClient(self._app_com_limite(200))

        assert cliente.post("/eco", json={"a": "x" * 500}).json() != {"recebido": 1}

    def test_request_sem_corpo_passa(self):
        """Sem `Content-Length` não há o que comparar, e `GET` é a maioria da API."""
        cliente = TestClient(self._app_com_limite(200))

        assert cliente.get("/eco").status_code == 405

    def test_o_websocket_atravessa_o_middleware_intacto(self):
        """A telemetria é um WebSocket de vida longa; middleware que só entende
        HTTP é exatamente como se quebra um."""
        cliente = TestClient(self._app_com_limite(200))

        with cliente.websocket_connect("/ws") as canal:
            assert canal.receive_text() == "vivo"

    def test_content_length_ilegivel_segue_para_o_servidor_http(self):
        """Malformado é erro de protocolo (400), e não corpo grande (413).

        Chamado como ASGI puro porque nenhum cliente HTTP de verdade deixaria
        montar este request — que é justamente o motivo de o caminho existir.
        """
        chamou = []

        async def aplicacao(scope, receive, send):
            chamou.append(scope["path"])

        middleware = LimiteDeCorpo(aplicacao, limite_bytes=10)
        escopo = {
            "type": "http",
            "path": "/eco",
            "headers": [(b"content-length", b"abacaxi")],
        }

        asyncio.run(middleware(escopo, None, None))

        assert chamou == ["/eco"]

    def test_o_413_carrega_os_cabecalhos_de_cors(self):
        """Montado **dentro** do CORS, senão o navegador vê erro de rede no lugar
        de um 413 que ele saberia explicar ao aluno."""
        interna = self._app_com_limite(200)
        interna.add_middleware(
            CORSMiddleware, allow_origins=["https://exemplo.test"], allow_credentials=True
        )
        cliente = TestClient(interna)

        resposta = cliente.post(
            "/eco", json={"a": "x" * 500}, headers={"Origin": "https://exemplo.test"}
        )

        assert resposta.status_code == 413
        assert resposta.headers["access-control-allow-origin"] == "https://exemplo.test"


class TestTetoDeCorpo:
    """O teto de corpo, que recusa antes de o pydantic ver qualquer coisa.

    É a segunda linha, e defende outra coisa que o teto de campo: o teto de
    campo impede um valor absurdo de ser gravado ou ecoado; este impede que a
    memória da instância seja escolhida por um desconhecido. Numa topologia de
    uma réplica, a diferença entre os dois é a diferença entre uma resposta 422
    e o processo morrer sem responder nada a ninguém.
    """

    def test_corpo_acima_do_teto_e_recusado_antes_da_validacao(self, client):
        # 200 KB contra o teto de 64 KB. A resposta é minúscula de propósito:
        # o middleware nem monta detalhe de campo, porque não leu campo nenhum.
        resposta = client.post(
            "/auth/registro",
            json={"nome": "a" * 200_000, "email": "x@y.co", "senha": "senhaSegura123"},
        )

        assert resposta.status_code == 413
        assert len(resposta.content) < 200

    def test_o_cadastro_legitimo_continua_passando(self, client):
        resposta = client.post(
            "/auth/registro",
            json={"nome": "Ana Souza", "email": "ana@exemplo.com", "senha": "senhaSegura123"},
        )

        assert resposta.status_code == 201
