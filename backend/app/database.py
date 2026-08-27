from typing import Optional

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from app.config import settings

# Importado pelo efeito colateral: uma tabela só entra em `SQLModel.metadata`
# quando o módulo que a define é carregado. Sem isto, `criar_tabelas` percorre um
# metadata vazio e não cria nem migra nada — em silêncio, porque não há erro a
# dar quando não há tabela a considerar. Hoje funciona por acidente, já que os
# routers importam os modelos antes do lifespan rodar; qualquer entrada que não
# passe pelo `app.main` (um script de manutenção, um shell) não teria essa sorte.
from app import models  # noqa: F401

_connect_args = (
    {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
)
engine = create_engine(settings.database_url, connect_args=_connect_args)


def criar_tabelas(motor: Optional[Engine] = None) -> None:
    """Deixa o banco em dia com os modelos, criando o que falta.

    `create_all` só cria tabelas novas: numa tabela que já existe ele não faz
    nada, nem sequer avisa. Uma coluna acrescentada a um modelo — como `fadiga`
    e `alerta` na ticket 10 — passaria o boot inteiro em silêncio e só apareceria
    no primeiro INSERT, como `OperationalError` no meio da sessão de estudo de
    alguém. `_acrescentar_colunas_faltantes` fecha essa lacuna.

    `motor` existe para o teste apontar para um banco descartável; em produção o
    engine do módulo é o único que interessa.
    """
    motor = motor or engine
    SQLModel.metadata.create_all(motor)
    _acrescentar_colunas_faltantes(motor)


def _acrescentar_colunas_faltantes(motor: Engine) -> None:
    """Roda `ALTER TABLE ADD COLUMN` para o que os modelos têm e o banco não.

    Migração de PoC, deliberadamente estreita: acrescenta coluna, e só. Não
    remove, não renomeia, não muda tipo nem preenche valor — as três operações
    que precisariam saber o que fazer com os dados que já estão lá, e onde uma
    ferramenta de migração de verdade passa a valer o próprio peso.

    É idempotente porque compara com o schema real a cada boot, então rodar duas
    vezes não faz nada na segunda. Toda coluna acrescentada precisa aceitar nulo
    ou ter default — o que já é verdade para as linhas antigas, que não têm valor
    nenhum a oferecer para um campo que não existia quando foram gravadas.

    A ticket 15 (deploy) é onde isto provavelmente vira Alembic: com mais de uma
    réplica subindo ao mesmo tempo contra o RDS, duas podem tentar o mesmo ALTER,
    e aí faz falta o controle de versão que uma migração de verdade tem.
    """
    inspetor = inspect(motor)
    existentes = set(inspetor.get_table_names())

    with motor.begin() as conexao:
        for tabela in SQLModel.metadata.sorted_tables:
            if tabela.name not in existentes:
                continue

            no_banco = {coluna["name"] for coluna in inspetor.get_columns(tabela.name)}

            for coluna in tabela.columns:
                if coluna.name in no_banco or coluna.primary_key:
                    continue

                tipo = coluna.type.compile(motor.dialect)
                conexao.execute(
                    text(f'ALTER TABLE "{tabela.name}" ADD COLUMN "{coluna.name}" {tipo}')
                )


def get_session():
    with Session(engine) as session:
        yield session
