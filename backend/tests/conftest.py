import os
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from app.database import criar_motor, get_session, obter_fabrica_de_sessoes
from app.main import app

#: Banco contra o qual a suíte roda. Vazio (o padrão) significa SQLite em
#: memória.
#:
#: **Por que variável de ambiente e não um segundo conjunto de testes.** O que
#: precisa ser verificado no PostgreSQL não é um comportamento extra: é *o
#: mesmo* comportamento, contra outro banco. Duplicar as 383 asserções em
#: arquivos paralelos garantiria que as duas cópias divergissem — a primeira
#: correção feita com pressa entraria só na cópia que o desenvolvedor estava
#: olhando, e a outra continuaria verde afirmando o contrário. Uma variável de
#: ambiente troca o banco embaixo da suíte inteira, e o que ela prova é que
#: **aquelas** asserções valem nos dois lugares.
#:
#: SQLite continua sendo o padrão porque é o único que roda sem depender de um
#: serviço no ar: `python -m pytest` numa máquina recém-clonada precisa
#: funcionar, ou a suíte deixa de ser executada.
#:
#:     DATABASE_URL_DE_TESTE=postgresql+psycopg://usuario@127.0.0.1:5432/mapface_teste \
#:         .venv/bin/python -m pytest
URL_DE_TESTE = os.getenv("DATABASE_URL_DE_TESTE", "").strip()

#: Verdadeiro quando a suíte está apontada para um banco de verdade.
#:
#: Exposto para os poucos testes que só fazem sentido num banco fora do SQLite —
#: hoje, o caminho `ALTER COLUMN ... DROP NOT NULL` da migração, que o SQLite
#: nem tem.
RODANDO_EM_POSTGRES = URL_DE_TESTE.startswith("postgresql")


@pytest.fixture(autouse=True)
def registro_de_analistas_limpo():
    """Dá a cada teste um registro de analistas vazio.

    O registro é estado de processo, e cada teste começa com um banco limpo —
    então a sessão de estudo criada por todos eles recebe o mesmo `id`. Sem
    isto, a calibração acumulada num teste seria reencontrada pelo teste
    seguinte, que passaria (ou falharia) por causa do anterior.
    """
    from app import analista

    analista.registro = analista.RegistroDeAnalistas()
    yield


@pytest.fixture(autouse=True)
def limites_de_autenticacao_zerados():
    """Dá a cada teste a porta da frente descontada.

    Mesmo motivo do registro de analistas acima: as tentativas de login e as
    vagas em voo são **estado de processo**, e a suíte registra e faz login com
    os mesmos poucos e-mails dezenas de vezes seguidas. Sem zerar, o teste que
    passasse do limite falharia por causa dos anteriores — e o de número onze
    falharia hoje, passaria amanhã ao mudar a ordem, e acusaria a rota errada.
    """
    from app import contencao

    contencao.esquecer_tudo()
    yield
    contencao.esquecer_tudo()


@pytest.fixture(name="motor_de_teste", scope="session")
def motor_de_teste_fixture():
    """O engine do banco externo, criado **uma vez** para a suíte inteira.

    Escopo de sessão porque abrir conexão e recriar o schema custa caro contra
    um servidor de verdade: multiplicado pelos 383 testes, o `create_all` sozinho
    passaria a dominar o tempo da suíte, e uma suíte lenta é uma suíte que
    ninguém roda antes de commitar.

    O schema nasce derrubado e recriado, e não só criado: uma coluna removida de
    um modelo sobreviveria no banco entre execuções, e a suíte passaria a rodar
    contra um schema que nenhum `create_all` de produção produziria. É o oposto
    do que esta fixture existe para provar.

    Em SQLite a fixture não é usada — lá cada teste ganha um banco em memória
    novo, que é isolamento de graça.
    """
    if not URL_DE_TESTE:
        pytest.skip("suíte em SQLite: não há banco externo a preparar")

    motor = criar_motor(URL_DE_TESTE)
    SQLModel.metadata.drop_all(motor)
    SQLModel.metadata.create_all(motor)
    yield motor
    motor.dispose()


@pytest.fixture(name="session")
def session_fixture(request):
    """Uma sessão de banco limpa por teste, no banco que a suíte escolheu.

    **Os dois bancos precisam do mesmo isolamento por motivos opostos.** O
    SQLite em memória com `StaticPool` isola sozinho: o banco vive na conexão, e
    a conexão morre com o teste. Um PostgreSQL é um servidor — o que um teste
    gravou continua lá para o próximo, e a suíte passaria a depender da ordem
    de execução, que é a falha mais cara de diagnosticar que existe numa suíte.

    **`TRUNCATE ... RESTART IDENTITY`, e não uma transação revertida.** A receita
    usual (abrir uma transação externa e dar rollback no fim) é mais rápida, e
    foi descartada por duas razões. A primeira é que o código da aplicação faz
    `commit` o tempo todo, e emulá-lo com savepoints muda o que está sendo
    testado — o teste passaria a exercitar um aninhamento que produção não tem.
    A segunda é decisiva: sequências no PostgreSQL **não** voltam atrás num
    rollback. Os `id` iriam subindo de teste para teste, enquanto no SQLite eles
    recomeçam do 1 — e vários testes daqui afirmam coisas sobre a sessão `1`.
    A mesma suíte precisa ver o mesmo banco nos dois lugares, e `RESTART
    IDENTITY` é o que devolve essa igualdade.

    `CASCADE` é obrigatório: `bloco_estudo`, `log_engajamento` e `resumo_sessao`
    referenciam `sessao_estudo`, e o PostgreSQL recusa truncar uma tabela
    referenciada sem ele.
    """
    if not URL_DE_TESTE:
        motor = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(motor)
        with Session(motor) as session:
            yield session
        return

    motor = request.getfixturevalue("motor_de_teste")
    _limpar(motor)
    with Session(motor) as session:
        yield session


def _limpar(motor) -> None:
    """Esvazia todas as tabelas do metadata e zera as sequências."""
    nomes = ", ".join(f'"{tabela.name}"' for tabela in SQLModel.metadata.sorted_tables)
    with motor.begin() as conexao:
        conexao.execute(text(f"TRUNCATE TABLE {nomes} RESTART IDENTITY CASCADE"))


@pytest.fixture(name="client")
def client_fixture(session: Session):
    """O cliente HTTP/WebSocket apontado para o banco descartável do teste.

    **Duas substituições, porque há dois jeitos de pedir banco.** As rotas HTTP
    pedem uma sessão pronta (`get_session`); o canal de telemetria pede a
    *fábrica* (`obter_fabrica_de_sessoes`), para poder abrir e fechar uma sessão
    curta por payload em vez de segurar uma conexão o canal inteiro. Sem a
    segunda linha o WebSocket falaria com o `app.db` do disco, e os testes dele
    passariam a afirmar coisas sobre o banco de desenvolvimento de quem rodou a
    suíte.

    A fábrica de teste devolve **sempre a mesma** sessão e não a fecha: o teste
    precisa poder inspecionar depois o que o canal gravou, e fechar a sessão
    compartilhada no fim do primeiro payload derrubaria o próprio teste. O que
    está sob teste aqui é o ciclo de vida do empréstimo (quantas vezes se pede e
    se devolve), não a identidade do objeto emprestado.
    """

    def get_session_override():
        return session

    @contextmanager
    def sessao_compartilhada():
        yield session

    app.dependency_overrides[get_session] = get_session_override
    app.dependency_overrides[obter_fabrica_de_sessoes] = lambda: sessao_compartilhada
    # Não usamos "with TestClient(app)" de propósito: isso dispararia o
    # lifespan (criar_tabelas) contra o banco real de app.database.engine,
    # criando um app.db espúrio no disco durante os testes. As tabelas de
    # teste já são criadas no engine em memória pela fixture "session".
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()
