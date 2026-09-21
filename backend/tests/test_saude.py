"""As duas sondas de saúde, e o que cada uma responde com o banco fora (§2.2).

O defeito que estes testes travam é o `{"status": "ok"}` incondicional que havia
antes: uma sonda que responde sem tocar em nada afirma apenas que o processo
está de pé, e o orquestrador a lê como "pode mandar aluno para cá". Com o banco
fora, a task entrava na rotação e servia erro 500 num painel todo verde.
"""
import pytest
from sqlalchemy.exc import OperationalError
from sqlmodel import create_engine

from app import database


class _BancoForaDoAr:
    """Um engine de mentira que recusa conexão, como um RDS inacessível.

    Prefere-se isto a apontar para um endereço que não existe: um host errado
    faria o teste esperar o tempo de conexão (segundos, por teste) e depender da
    rede da máquina que roda a suíte. A sonda não distingue os dois casos — para
    ela, conexão que estoura é banco fora —, então a imitação é fiel no que
    importa.
    """

    def connect(self):
        raise OperationalError("SELECT 1", {}, Exception("conexão recusada"))


@pytest.fixture(name="banco_no_ar")
def banco_no_ar_fixture(monkeypatch):
    """Troca o engine do módulo por um SQLite em memória.

    Sem isto a sonda consultaria `sqlite:///./app.db`, o banco de
    desenvolvimento — e numa máquina limpa o arquivo seria **criado** pela
    consulta, que é exatamente o lixo que a `conftest` evita ao não disparar o
    lifespan.
    """
    monkeypatch.setattr(database, "engine", create_engine("sqlite://"))


@pytest.fixture(name="banco_fora")
def banco_fora_fixture(monkeypatch):
    monkeypatch.setattr(database, "engine", _BancoForaDoAr())


class TestSondaDeVida:
    def test_responde_com_o_banco_no_ar(self, client, banco_no_ar):
        resposta = client.get("/vivo")

        assert resposta.status_code == 200
        assert resposta.json() == {"status": "vivo"}

    def test_continua_respondendo_com_o_banco_fora(self, client, banco_fora):
        """É o ponto inteiro de haver duas rotas.

        Se a sonda de vida caísse junto com o banco, o orquestrador reiniciaria
        a aplicação em laço durante uma indisponibilidade do banco — matando
        repetidamente um processo que não tinha defeito nenhum, e enterrando a
        causa real sob um incidente de contêineres morrendo.
        """
        resposta = client.get("/vivo")

        assert resposta.status_code == 200
        assert resposta.json() == {"status": "vivo"}


class TestSondaDeProntidao:
    def test_diz_pronto_com_o_banco_acessivel(self, client, banco_no_ar):
        resposta = client.get("/pronto")

        assert resposta.status_code == 200
        assert resposta.json() == {"status": "pronto", "banco": "ok"}

    def test_devolve_503_com_o_banco_inacessivel(self, client, banco_fora):
        """503, e não 500: a diferença muda o que o balanceador faz.

        503 tira a task da rotação e continua tentando; 500 é um erro da
        requisição, que uma sonda pode muito bem contar como resposta válida.
        """
        resposta = client.get("/pronto")

        assert resposta.status_code == 503
        assert resposta.json() == {"status": "indisponivel", "banco": "inacessivel"}


class TestApelidoHistorico:
    def test_health_mantem_o_corpo_que_sempre_devolveu(self, client, banco_no_ar):
        """`{"status": "ok"}`, letra por letra.

        A rota é anterior a este plano e pode haver sonda apontada para ela.
        Mudar o caminho seria quebrar em silêncio; mudar o corpo, também.
        """
        resposta = client.get("/health")

        assert resposta.status_code == 200
        assert resposta.json() == {"status": "ok"}

    def test_health_passa_a_falhar_com_o_banco_inacessivel(self, client, banco_fora):
        """A correção de §2.2, vista de onde ela importa.

        Antes esta chamada devolvia 200 com o banco no chão. Quem aponta uma
        sonda para `/health` está perguntando "posso mandar tráfego?", e a
        resposta verdadeira, nesse estado, é não.
        """
        resposta = client.get("/health")

        assert resposta.status_code == 503
        assert resposta.json() == {"status": "indisponivel", "banco": "inacessivel"}
