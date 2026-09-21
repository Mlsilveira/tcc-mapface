"""O que o log registra, o que ele recusa registrar, e o que o cliente vê numa
falha não prevista (§2.3, §2.4).

Os testes de privacidade daqui são da mesma família do
`test_telemetria.py::test_schema_do_log_nao_tem_campo_de_imagem_ou_video`: eles
não verificam que uma função funciona, verificam que uma informação **não
aparece** onde não deve. O eixo do TCC é privacidade, e log é o caminho mais
curto entre "vou só depurar isso rápido" e um arquivo do que cada pessoa estuda.
"""
import json
import logging
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, create_engine

from app import database, main, observabilidade, sessoes
from app.models import Aluno, SessaoEstudo
from app.observabilidade import FormatadorJson, banco_sem_segredo, obter_logger, registrar
from app.tempo import agora_utc, como_utc

#: Texto autoral de aluno. Serve de isca: se ele aparecer em qualquer linha de
#: log, a asserção de privacidade falha.
ASSUNTO_DO_ALUNO = "Cálculo II — integrais por partes, lista 4"
EMAIL_DO_ALUNO = "ana@exemplo.com"


def _linhas(caplog) -> list:
    """As linhas capturadas, formatadas como sairiam de verdade e já em dict.

    Passa pelo `FormatadorJson` de propósito, em vez de olhar os atributos do
    `LogRecord`: o que vaza é o texto que chega ao agregador, e um campo pode
    estar no registro sem estar na saída (ou o contrário, se o formatador
    ganhar um campo novo algum dia).
    """
    formatador = FormatadorJson()
    return [json.loads(formatador.format(registro)) for registro in caplog.records]


class TestFormatoDaLinha:
    def test_toda_linha_traz_os_quatro_campos_fixos(self, caplog):
        logger = obter_logger("exemplo")

        with caplog.at_level(logging.INFO):
            registrar(logger, logging.INFO, "algo aconteceu", {"id_sessao": 7})

        linha = _linhas(caplog)[0]
        assert linha["nivel"] == "INFO"
        assert linha["origem"] == "mapface.exemplo"
        assert linha["mensagem"] == "algo aconteceu"
        assert linha["id_sessao"] == 7
        assert "instante" in linha

    def test_contexto_nao_sobrescreve_campo_fixo(self, caplog):
        """Senão `nivel` significaria coisas diferentes em linhas diferentes.

        Um log em que o cabeçalho é negociável não serve para filtrar, que é a
        única razão de ele ser estruturado.
        """
        logger = obter_logger("exemplo")

        with caplog.at_level(logging.INFO):
            registrar(logger, logging.INFO, "verdadeira", {"nivel": "FALSO"})

        assert _linhas(caplog)[0]["nivel"] == "INFO"

    def test_a_excecao_entra_na_linha_quando_pedida(self, caplog):
        logger = obter_logger("exemplo")

        with caplog.at_level(logging.ERROR):
            try:
                raise ValueError("estourou")
            except ValueError:
                registrar(logger, logging.ERROR, "falhou", {}, exc_info=True)

        assert "ValueError: estourou" in _linhas(caplog)[0]["excecao"]

    def test_configurar_logs_duas_vezes_nao_duplica_a_saida(self):
        """O lifespan e o import podem configurar no mesmo processo.

        Sem a limpeza dos handlers anteriores, cada configuração acrescentaria
        uma saída e a mesma linha sairia duas, três, quatro vezes.
        """
        observabilidade.configurar_logs("INFO")
        observabilidade.configurar_logs("INFO")

        assert len(logging.getLogger(observabilidade.RAIZ).handlers) == 1


class TestSenhaDoBanco:
    def test_a_senha_da_url_nao_sobrevive(self):
        # Esperado escrito à mão: usuário, host, porta e base permanecem; o
        # trecho entre ":" e "@" some.
        limpa = banco_sem_segredo(
            "postgresql+psycopg://mapface:s3nh4-do-rds@db.interna:5432/mapface"
        )

        assert limpa == "postgresql+psycopg://mapface:***@db.interna:5432/mapface"
        assert "s3nh4-do-rds" not in limpa

    def test_url_sem_senha_passa_inteira(self):
        assert banco_sem_segredo("sqlite:///./app.db") == "sqlite:///./app.db"

    def test_url_ilegivel_vira_marcador_em_vez_de_passar_direto(self):
        """Devolver a original "porque não deu para limpar" vazaria justamente
        no caso em que menos se sabe o que ela contém."""
        assert banco_sem_segredo("isto não é uma url") == "<url de banco ilegível>"


class TestBoot:
    def test_o_boot_registra_ambiente_banco_e_origens(self, monkeypatch, caplog):
        """As três linhas que respondem "por que não funciona?" sem abrir a AWS.

        `criar_tabelas` é neutralizado e o engine trocado porque o que está sob
        teste é o log do boot, não a migração — e disparar o lifespan de verdade
        criaria o `app.db` de desenvolvimento no meio da suíte.
        """
        monkeypatch.setattr(main, "criar_tabelas", lambda: None)
        monkeypatch.setattr(database, "engine", create_engine("sqlite://"))
        monkeypatch.setattr(
            main.settings, "origens_permitidas", "https://mapface.exemplo.br"
        )
        monkeypatch.setattr(
            main.settings, "database_url", "postgresql://mapface:segredo@db.interna/mapface"
        )

        with caplog.at_level(logging.INFO):
            with TestClient(main.app):
                pass

        inicio = [linha for linha in _linhas(caplog) if linha["mensagem"] == "aplicação iniciada"]
        assert len(inicio) == 1
        assert inicio[0]["ambiente"] == main.settings.ambiente
        assert inicio[0]["origens_de_cors"] == ["https://mapface.exemplo.br"]
        assert inicio[0]["banco"] == "postgresql://mapface:***@db.interna/mapface"

    def test_a_senha_do_banco_nao_aparece_em_lugar_nenhum_do_boot(
        self, monkeypatch, caplog
    ):
        monkeypatch.setattr(main, "criar_tabelas", lambda: None)
        monkeypatch.setattr(database, "engine", create_engine("sqlite://"))
        monkeypatch.setattr(
            main.settings,
            "database_url",
            "postgresql://mapface:s3nh4-do-rds@db.interna/mapface",
        )

        with caplog.at_level(logging.INFO):
            with TestClient(main.app):
                pass

        assert "s3nh4-do-rds" not in json.dumps(_linhas(caplog), ensure_ascii=False)


class TestEncerramentoAutomatico:
    """A varredura deixa rastro — e o rastro não leva nada escrito pelo aluno."""

    @pytest.fixture(name="sessao_abandonada")
    def sessao_abandonada_fixture(self, session: Session) -> SessaoEstudo:
        aluno = Aluno(nome="Ana Souza", email=EMAIL_DO_ALUNO, senha_hash="irrelevante")
        session.add(aluno)
        session.commit()
        session.refresh(aluno)

        sessao = SessaoEstudo(id_aluno=aluno.id, assunto=ASSUNTO_DO_ALUNO)
        session.add(sessao)
        session.commit()
        session.refresh(sessao)
        return sessao

    def _varrer(self, session, sessao):
        limite = sessoes.limite_de_ausencia_da(sessao)
        return sessoes.encerrar_inativas(
            session, agora=como_utc(sessao.inicio) + limite + timedelta(minutes=1)
        )

    def test_registra_uma_linha_por_sessao_encerrada(
        self, session, sessao_abandonada, caplog
    ):
        """Sem esta linha, "o aluno fechou a aba" e "a conexão caiu" são
        indistinguíveis depois do fato — e só a segunda é defeito."""
        with caplog.at_level(logging.INFO):
            encerradas = self._varrer(session, sessao_abandonada)

        assert len(encerradas) == 1
        linhas = [
            linha
            for linha in _linhas(caplog)
            if linha["mensagem"] == "sessão encerrada por ausência"
        ]
        assert len(linhas) == 1
        assert linhas[0]["id_sessao"] == sessao_abandonada.id
        assert linhas[0]["id_aluno"] == sessao_abandonada.id_aluno

    def test_o_assunto_escrito_pelo_aluno_nao_entra_no_log(
        self, session, sessao_abandonada, caplog
    ):
        """`assunto` é texto autoral. Um log de encerramento com ele dentro
        seria confortável de ler e transformaria o agregador num arquivo do que
        cada pessoa estuda."""
        with caplog.at_level(logging.INFO):
            self._varrer(session, sessao_abandonada)

        saida = json.dumps(_linhas(caplog), ensure_ascii=False)
        assert ASSUNTO_DO_ALUNO not in saida
        assert "assunto" not in saida

    def test_o_email_nao_entra_no_log(self, session, sessao_abandonada, caplog):
        """O sistema identifica por id numérico em quase tudo; o log segue a
        mesma moeda. Id basta para investigar e não vaza por leitura casual."""
        with caplog.at_level(logging.INFO):
            self._varrer(session, sessao_abandonada)

        assert EMAIL_DO_ALUNO not in json.dumps(_linhas(caplog), ensure_ascii=False)


class TestFalhaNaoTratada:
    """§2.4 — o cliente recebe uma frase; o log recebe o traceback."""

    @pytest.fixture(name="cliente_com_rota_que_estoura")
    def cliente_fixture(self):
        aplicacao = main.criar_app()

        @aplicacao.get("/estoura")
        def estoura():
            raise RuntimeError("detalhe interno que não pode sair daqui")

        # `raise_server_exceptions=False` é obrigatório: por padrão o TestClient
        # relança a exceção para o teste em vez de entregar a resposta, e o que
        # está sob teste é justamente o que chega ao cliente.
        return TestClient(aplicacao, raise_server_exceptions=False)

    def test_o_cliente_recebe_500_com_corpo_generico(self, cliente_com_rota_que_estoura):
        resposta = cliente_com_rota_que_estoura.get("/estoura")

        assert resposta.status_code == 500
        assert resposta.json() == {"detail": main.FALHA_GENERICA}

    def test_nada_do_traceback_chega_ao_navegador(self, cliente_com_rota_que_estoura):
        """O que vazava sem handler: nome de arquivo, trecho de código e a
        estrutura do projeto, projetados na parede numa defesa de TCC."""
        corpo = cliente_com_rota_que_estoura.get("/estoura").text

        assert "detalhe interno que não pode sair daqui" not in corpo
        assert "RuntimeError" not in corpo
        assert "Traceback" not in corpo

    def test_a_falha_vira_linha_de_log_com_metodo_e_caminho(
        self, cliente_com_rota_que_estoura, caplog
    ):
        with caplog.at_level(logging.ERROR):
            cliente_com_rota_que_estoura.get("/estoura")

        linha = [
            linha for linha in _linhas(caplog) if linha["mensagem"] == "falha não tratada"
        ][0]
        assert linha["metodo"] == "GET"
        assert linha["caminho"] == "/estoura"
        assert "RuntimeError" in linha["excecao"]

    def test_a_query_string_nao_entra_no_log(self, cliente_com_rota_que_estoura, caplog):
        """É por ali que um dado de aluno entraria numa linha de log sem ninguém
        decidir que entraria."""
        with caplog.at_level(logging.ERROR):
            cliente_com_rota_que_estoura.get("/estoura?assunto=" + ASSUNTO_DO_ALUNO)

        assert ASSUNTO_DO_ALUNO not in json.dumps(_linhas(caplog), ensure_ascii=False)


def test_o_relogio_da_linha_e_utc(caplog):
    """Um log sem fuso é um log que não casa com o de mais ninguém.

    O resto do sistema já grava tudo em UTC (`app.tempo`); a linha segue a mesma
    regra, e a margem generosa abaixo é só para não depender do tempo que o
    teste leva.
    """
    logger = obter_logger("exemplo")

    with caplog.at_level(logging.INFO):
        registrar(logger, logging.INFO, "agora")

    from datetime import datetime

    instante = datetime.fromisoformat(_linhas(caplog)[0]["instante"])
    assert abs((instante - agora_utc()).total_seconds()) < 60
