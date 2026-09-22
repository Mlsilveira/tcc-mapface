"""Quem entra, quantas vezes pode tentar, e quanto a porta da frente aceita gastar.

Três defeitos desta versão moram aqui, e os três têm o mesmo agravante: são
alcançáveis **sem credencial nenhuma**, por qualquer pessoa que tenha a URL.

1. `POST /auth/registro` era público — sem convite, sem verificação de e-mail.
   Uma aplicação que liga a webcam de quem entra, com cadastro aberto à
   internet, é um problema de outra ordem que o resto deste projeto.
2. `POST /auth/login` aceitava tentativas ilimitadas, e cada tentativa paga um
   bcrypt cost 12 (~300 ms de CPU) num threadpool que `/pronto` divide com ela.
   Algumas dezenas de chamadas simultâneas derrubam a sonda, e o orquestrador
   recicla uma task sã — derrubando a sessão de estudo de todo mundo ao mesmo
   tempo.
3. O login respondia **na hora** para e-mail inexistente e **em 300 ms** para
   e-mail existente. A diferença é medível de fora e responde "esta pessoa usa
   o sistema?". É o mesmo oráculo de existência que as rotas de sessão evitam
   com o 404 uniforme, e que faltava na porta da frente.

Os números esperados aqui são calculados à mão a partir da configuração do
teste, nunca lidos da implementação: com `tentativas_de_autenticacao = 3`, a
terceira tentativa ainda é julgada e a quarta é recusada.
"""
from datetime import timedelta

import pytest
from sqlmodel import Session, select

from app import contencao, security
from app.config import configuracao_temporaria
from app.contencao import JanelaDeTentativas, TrabalhoSimultaneo, vaga_de_autenticacao
from app.models import Aluno
from app.tempo import agora_utc

ANA = {"nome": "Ana Souza", "email": "ana@exemplo.br", "senha": "senhaSegura123"}
BRUNO = {"nome": "Bruno Lima", "email": "bruno@exemplo.br", "senha": "outraSenha456"}

SENHA_ERRADA = "naoEhEssaSenha999"


def registrar(client, dados):
    return client.post("/auth/registro", json=dados)


def entrar(client, dados, senha=None):
    return client.post(
        "/auth/login", json={"email": dados["email"], "senha": senha or dados["senha"]}
    )


class TestCadastroFechado:
    """A lista de e-mails autorizados, e o que ela responde a quem não está nela."""

    def test_quem_nao_esta_na_lista_nao_se_cadastra(self, client, session: Session):
        with configuracao_temporaria(emails_autorizados=ANA["email"]):
            resposta = registrar(client, BRUNO)

        assert resposta.status_code == 403
        # E nada foi gravado: um 403 que criasse a conta assim mesmo seria o
        # pior dos dois mundos.
        assert session.exec(select(Aluno).where(Aluno.email == BRUNO["email"])).first() is None

    def test_quem_esta_na_lista_se_cadastra(self, client):
        with configuracao_temporaria(
            emails_autorizados="{}, {}".format(ANA["email"], BRUNO["email"])
        ):
            assert registrar(client, ANA).status_code == 201
            assert registrar(client, BRUNO).status_code == 201

    def test_a_lista_nao_distingue_maiusculas(self, client):
        """`Ana@Exemplo.BR` e `ana@exemplo.br` são a mesma caixa postal.

        Uma lista sensível a maiúsculas produziria um "não estou autorizado"
        incompreensível para quem está com o próprio e-mail na mão.
        """
        with configuracao_temporaria(emails_autorizados="ANA@EXEMPLO.BR"):
            assert registrar(client, ANA).status_code == 201

    def test_lista_vazia_deixa_o_cadastro_aberto(self, client):
        """O default que mantém `git clone && uvicorn` e a suíte funcionando.

        Em produção esta mesma configuração faz a aplicação recusar subir — ver
        `test_configuracao.TestListaDeAutorizados`. É o par que permite ao
        default ser permissivo sem ser o modo de produção por esquecimento.
        """
        with configuracao_temporaria(emails_autorizados=""):
            assert registrar(client, ANA).status_code == 201

    def test_de_fora_da_lista_nem_o_email_ja_cadastrado_vaza(self, client):
        """O 403 vem antes da consulta ao banco, e é por isso que ele não é oráculo.

        O 409 de "e-mail já cadastrado" é um confirmador público de que uma
        pessoa usa o sistema. Com a ordem invertida, bastaria uma tentativa de
        cadastro para descobrir quem está lá dentro; com esta, quem está fora da
        lista recebe a mesma resposta para um e-mail cadastrado e para um livre.
        """
        with configuracao_temporaria(emails_autorizados=""):
            assert registrar(client, ANA).status_code == 201

        with configuracao_temporaria(emails_autorizados=BRUNO["email"]):
            resposta = registrar(client, ANA)

        assert resposta.status_code == 403
        assert resposta.json()["detail"] != "E-mail já cadastrado"


class TestLimiteDeTentativas:
    """A adivinhação de senha é um ataque paciente, e o contador é por e-mail."""

    def test_passado_o_limite_a_tentativa_seguinte_e_recusada(self, client):
        # Três tentativas cabem na janela; a quarta não. O esperado sai da
        # configuração deste teste, não do código.
        with configuracao_temporaria(tentativas_de_autenticacao=3):
            registrar(client, ANA)
            for _ in range(3):
                assert entrar(client, ANA, senha=SENHA_ERRADA).status_code == 401

            resposta = entrar(client, ANA, senha=SENHA_ERRADA)

        assert resposta.status_code == 429
        # `Retry-After` é o cabeçalho que um cliente sabe ler sem interpretar a
        # frase em português.
        assert resposta.headers["retry-after"] == "300"

    def test_a_senha_certa_tambem_e_recusada_depois_do_limite(self, client):
        """O limite não é sobre acertar, é sobre quantas vezes se tentou.

        Se a senha correta passasse por cima do contador, um ataque de
        dicionário não seria limitado em nada: a última tentativa — a que
        importa — seria justamente a que passaria.
        """
        with configuracao_temporaria(tentativas_de_autenticacao=1):
            registrar(client, ANA)
            assert entrar(client, ANA, senha=SENHA_ERRADA).status_code == 401

            assert entrar(client, ANA).status_code == 429

    def test_o_contador_de_cada_email_e_independente(self, client):
        """A turma inteira entrando junta não é uma turma se punindo junta.

        Este é o motivo de a contagem ser por e-mail e não por IP: atrás de um
        balanceador, o IP de todos os alunos é o mesmo IP, e um limite por IP
        seria uma interrupção coletiva no meio da apresentação.
        """
        with configuracao_temporaria(tentativas_de_autenticacao=1):
            registrar(client, ANA)
            registrar(client, BRUNO)
            assert entrar(client, ANA, senha=SENHA_ERRADA).status_code == 401
            assert entrar(client, ANA, senha=SENHA_ERRADA).status_code == 429

            # Bruno não gastou nada do dele.
            assert entrar(client, BRUNO).status_code == 200

    def test_entrar_com_sucesso_zera_o_contador(self, client):
        """Quem acertou a senha provou não ser quem o limite persegue.

        Sem isto, o aluno que erra algumas vezes de manhã levaria 429 à tarde,
        no meio de uma sessão de estudo.
        """
        with configuracao_temporaria(tentativas_de_autenticacao=3):
            registrar(client, ANA)
            assert entrar(client, ANA, senha=SENHA_ERRADA).status_code == 401
            assert entrar(client, ANA).status_code == 200

            # Zerado: as três tentativas seguintes cabem inteiras de novo.
            for _ in range(3):
                assert entrar(client, ANA, senha=SENHA_ERRADA).status_code == 401

    def test_a_janela_desliza(self, client, monkeypatch):
        """Passada a janela, as tentativas antigas deixam de contar.

        Um bloqueio que não expirasse sozinho precisaria de alguém para
        destravar a conta — e, num estudo conduzido por uma pessoa só, "alguém"
        é a mesma pessoa que está apresentando.
        """
        t0 = agora_utc()
        monkeypatch.setattr(contencao, "agora_utc", lambda: t0)

        with configuracao_temporaria(tentativas_de_autenticacao=1, janela_de_tentativas_minutos=5):
            registrar(client, ANA)
            assert entrar(client, ANA, senha=SENHA_ERRADA).status_code == 401
            assert entrar(client, ANA, senha=SENHA_ERRADA).status_code == 429

            # Cinco minutos e um segundo depois: a tentativa de t0 saiu da
            # janela, e a conta recomeça do zero.
            monkeypatch.setattr(
                contencao, "agora_utc", lambda: t0 + timedelta(minutes=5, seconds=1)
            )
            assert entrar(client, ANA).status_code == 200

    def test_o_registro_tambem_e_contado(self, client):
        """O cadastro paga o mesmo bcrypt que o login, e é igualmente anônimo.

        Com a lista de autorizados vazia — que é o estado de desenvolvimento e
        o de quem esqueceu de preenchê-la —, o contador é a única coisa entre a
        rota e um laço de cadastros. Ele é por e-mail, então não impede uma
        varredura com endereços distintos: quem faz isso esbarra no teto de
        trabalho em voo, que é a defesa desenhada para esse caso.
        """
        with configuracao_temporaria(tentativas_de_autenticacao=1, emails_autorizados=""):
            assert registrar(client, ANA).status_code == 201

            # Segunda tentativa com o mesmo e-mail: recusada pelo contador,
            # antes mesmo de virar o 409 que seria a resposta natural.
            resposta = registrar(client, ANA)

        assert resposta.status_code == 429

    def test_renovar_credencial_nao_entra_no_limite(self, client):
        """A rota que o cliente chama em laço não pode ser a que trava o aluno.

        `POST /auth/renovar` é chamada enquanto a sessão de estudo está aberta.
        Ela já exige um token válido e não paga bcrypt — limitá-la seria pagar
        com a sessão de estudo por um ataque que ela não sofre.
        """
        with configuracao_temporaria(tentativas_de_autenticacao=1):
            registrar(client, ANA)
            token = entrar(client, ANA).json()["access_token"]
            cabecalho = {"Authorization": "Bearer {}".format(token)}

            for _ in range(5):
                assert client.post("/auth/renovar", headers=cabecalho).status_code == 200


class TestTrabalhoSimultaneo:
    """O teto de requisições em voo, que é o que protege a sonda `/pronto`."""

    def test_sem_vaga_o_login_e_recusado_sem_pagar_bcrypt(self, client, monkeypatch):
        """Recusar na hora é o ponto: esperar por vaga seguraria a thread.

        A thread é justamente o recurso que este teto existe para preservar —
        um limitador que enfileirasse produziria a mesma fila que ele deveria
        impedir.
        """
        chamadas = []
        monkeypatch.setattr(
            security, "verificar_senha", lambda *args: chamadas.append(args) or False
        )

        with configuracao_temporaria(autenticacoes_simultaneas=1):
            registrar(client, ANA)
            assert contencao.autenticacoes.ocupar() is True

            resposta = entrar(client, ANA)

        assert resposta.status_code == 429
        assert resposta.headers["retry-after"] == "2"
        assert chamadas == []

    def test_sem_vaga_o_registro_tambem_e_recusado(self, client):
        with configuracao_temporaria(autenticacoes_simultaneas=1):
            assert contencao.autenticacoes.ocupar() is True

            assert registrar(client, ANA).status_code == 429

    def test_a_vaga_volta_quando_a_requisicao_termina(self, client):
        with configuracao_temporaria(autenticacoes_simultaneas=1):
            registrar(client, ANA)
            assert contencao.autenticacoes.em_voo == 0

            assert entrar(client, ANA).status_code == 200

        assert contencao.autenticacoes.em_voo == 0

    def test_a_vaga_volta_quando_a_requisicao_falha(self, client):
        """O `finally` que impede o mecanismo de ficar pior que a ausência dele.

        Uma vaga não devolvida a cada erro faria o teto encolher até ninguém
        mais conseguir entrar — e o sintoma seria "o sistema parou de aceitar
        login", horas depois da causa.
        """
        with configuracao_temporaria(autenticacoes_simultaneas=1):
            registrar(client, ANA)

            assert entrar(client, ANA, senha=SENHA_ERRADA).status_code == 401
            assert contencao.autenticacoes.em_voo == 0

            # E a vaga devolvida serve para a próxima requisição de verdade.
            assert entrar(client, ANA).status_code == 200


class TestOraculoDeExistencia:
    """O login custa o mesmo para quem existe e para quem não existe."""

    def test_email_inexistente_paga_a_mesma_verificacao(self, client, monkeypatch):
        """A prova é a chamada, não o cronômetro.

        Medir tempo num teste produziria a asserção mais instável da suíte. O
        que se afirma aqui é a propriedade que gera o tempo igual: os dois
        caminhos passam por `verificar_senha`. O curto-circuito do `or` — que
        pularia o bcrypt exatamente no caso que precisa pagá-lo — é o defeito
        que este teste tranca.
        """
        verificacoes = []
        original = security.verificar_senha

        def espiao(senha, senha_hash):
            verificacoes.append(senha_hash)
            return original(senha, senha_hash)

        monkeypatch.setattr("app.routers.auth.verificar_senha", espiao)
        registrar(client, ANA)

        assert entrar(client, BRUNO).status_code == 401
        assert len(verificacoes) == 1
        assert verificacoes[0] == security.hash_inalcancavel()

    def test_o_hash_inalcancavel_e_um_bcrypt_que_nenhuma_senha_acerta(self):
        inalcancavel = security.hash_inalcancavel()

        assert inalcancavel.startswith("$2b$")
        assert security.verificar_senha("senhaSegura123", inalcancavel) is False
        # Estável no processo: recalculá-lo a cada login custaria os mesmos
        # 300 ms de CPU que ele existe para igualar.
        assert security.hash_inalcancavel() is inalcancavel


class TestJanelaDeTentativas:
    """A contagem em si, sem HTTP — como `app.presenca` e `app.sessoes`."""

    def test_as_recusadas_tambem_contam(self):
        """Insistir não devolve a janela.

        Se a tentativa recusada não fosse registrada, o limite viraria "10 a
        cada 5 minutos *aceitas*", com quantas recusadas o atacante quisesse no
        meio — e o número configurado deixaria de significar o que diz.
        """
        janela = JanelaDeTentativas()

        with configuracao_temporaria(tentativas_de_autenticacao=2):
            assert [janela.cobrar("a") for _ in range(4)] == [True, True, False, False]
            # Nenhuma vaga apareceu por insistência: a quinta continua recusada.
            assert janela.cobrar("a") is False

    def test_perdoar_apaga_so_a_chave_pedida(self):
        janela = JanelaDeTentativas()

        with configuracao_temporaria(tentativas_de_autenticacao=1):
            janela.cobrar("a")
            janela.cobrar("b")
            janela.perdoar("a")

            assert janela.cobrar("a") is True
            assert janela.cobrar("b") is False

    def test_chaves_expiradas_sao_esquecidas_quando_o_dicionario_cresce(
        self, monkeypatch
    ):
        """A chave vem de fora, então o dicionário não pode só crescer.

        Uma varredura com e-mails inventados criaria uma entrada por e-mail. A
        limpeza acontece quando o dicionário passa do teto — O(n) a cada n
        inserções, que é o mesmo trabalho de varrer sempre, diluído.
        """
        t0 = agora_utc()
        monkeypatch.setattr(contencao, "agora_utc", lambda: t0)
        janela = JanelaDeTentativas(chaves_antes_da_limpeza=2)

        with configuracao_temporaria(janela_de_tentativas_minutos=5):
            for numero in range(3):
                janela.cobrar("antiga-{}".format(numero))

            # Passada a janela, a próxima cobrança encontra o dicionário acima
            # do teto e descarta as três, sobrando só a recém-criada.
            monkeypatch.setattr(
                contencao, "agora_utc", lambda: t0 + timedelta(minutes=5, seconds=1)
            )
            janela.cobrar("nova")

        assert list(janela._instantes) == ["nova"]


class TestTetoDeTrabalho:
    """O semáforo que não espera, isolado do HTTP."""

    def test_o_teto_e_o_numero_configurado(self):
        teto = TrabalhoSimultaneo()

        with configuracao_temporaria(autenticacoes_simultaneas=2):
            assert [teto.ocupar() for _ in range(3)] == [True, True, False]
            assert teto.em_voo == 2

    def test_liberar_devolve_uma_vaga_por_vez(self):
        teto = TrabalhoSimultaneo()

        with configuracao_temporaria(autenticacoes_simultaneas=1):
            teto.ocupar()
            teto.liberar()

            assert teto.em_voo == 0
            assert teto.ocupar() is True

    def test_liberar_a_mais_nao_cria_vaga_do_nada(self):
        """Um contador negativo viraria teto maior que o configurado.

        É o tipo de erro que só apareceria sob carga, que é exatamente quando
        este mecanismo precisa estar certo.
        """
        teto = TrabalhoSimultaneo()

        teto.liberar()
        teto.liberar()

        assert teto.em_voo == 0

    def test_a_vaga_e_devolvida_mesmo_com_excecao_no_bloco(self):
        with configuracao_temporaria(autenticacoes_simultaneas=1):
            with pytest.raises(ZeroDivisionError):
                with vaga_de_autenticacao() as vaga:
                    assert vaga is True
                    1 / 0

            assert contencao.autenticacoes.em_voo == 0

    def test_sem_vaga_o_bloco_roda_sabendo_que_nao_tem(self):
        """Rende `False` em vez de levantar: quem chama é que conhece HTTP."""
        with configuracao_temporaria(autenticacoes_simultaneas=1):
            contencao.autenticacoes.ocupar()

            with vaga_de_autenticacao() as vaga:
                assert vaga is False

            # A vaga que não foi concedida também não é devolvida — senão o
            # bloco recusado liberaria a vaga de quem está usando.
            assert contencao.autenticacoes.em_voo == 1
