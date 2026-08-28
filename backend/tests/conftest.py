import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from app.database import get_session
from app.main import app


@pytest.fixture(autouse=True)
def registro_de_analistas_limpo():
    """Dá a cada teste um registro de analistas vazio.

    O registro é estado de processo, e cada teste começa com um banco em memória
    novo — então a sessão de estudo criada por todos eles recebe o mesmo `id`. Sem
    isto, a calibração acumulada num teste seria reencontrada pelo teste seguinte,
    que passaria (ou falharia) por causa do anterior.
    """
    from app import analista

    analista.registro = analista.RegistroDeAnalistas()
    yield


@pytest.fixture(name="session")
def session_fixture():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture(name="client")
def client_fixture(session: Session):
    def get_session_override():
        return session

    app.dependency_overrides[get_session] = get_session_override
    # Não usamos "with TestClient(app)" de propósito: isso dispararia o
    # lifespan (criar_tabelas) contra o banco real de app.database.engine,
    # criando um app.db espúrio no disco durante os testes. As tabelas de
    # teste já são criadas no engine em memória pela fixture "session".
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()
