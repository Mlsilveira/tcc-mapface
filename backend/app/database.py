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

def _argumentos_de_conexao(url: str) -> dict:
    """O que cada banco precisa receber na conexão para se comportar igual.

    **SQLite: `check_same_thread`.** O driver recusa, por padrão, uma conexão
    usada por thread diferente da que a abriu, e o uvicorn atende requisições em
    threads de um pool.

    **PostgreSQL: `timezone=UTC`, e esta é a linha que impede uma falha inteira
    de horário.** Toda coluna de instante deste projeto é `TIMESTAMP WITHOUT
    TIME ZONE` (é o que o `datetime` do SQLModel gera), e tudo que o código
    grava é UTC com fuso explícito (`tempo.agora_utc`). Ao inserir um valor com
    fuso numa coluna sem fuso, o PostgreSQL **converte para o fuso da sessão** e
    só então descarta a informação. Numa máquina em `America/Sao_Paulo` o
    instante gravado sai três horas no passado, e volta da leitura como se fosse
    UTC — a sessão de estudo recém-aberta nasce com `inicio` de três horas atrás
    e a varredura de ausência a encerra no primeiro `GET /sessoes/ativa`. Foi
    exatamente o que aconteceu na primeira execução da suíte contra o Postgres:
    44 testes vermelhos, quase todos por esse desvio.

    Fixar o fuso da **sessão de conexão** em UTC torna essa conversão a
    identidade, e o valor gravado volta a ser o mesmo que o SQLite guardaria.

    *A alternativa descartada* foi declarar as colunas como `TIMESTAMP WITH TIME
    ZONE` (`DateTime(timezone=True)` nos modelos), que é o tipo mais correto em
    absoluto. Ela foi recusada porque muda o **tipo** das colunas existentes, e a
    migração caseira deste projeto acrescenta coluna e afrouxa obrigatoriedade —
    não converte tipo (ver `_acrescentar_colunas_faltantes`). Adotá-la exigiria a
    ferramenta de migração que o plano decidiu não trazer agora. Esta linha
    resolve o mesmo problema sem tocar no schema, e resolve também para quem
    subir a aplicação num servidor cujo `TimeZone` ninguém conferiu.
    """
    if url.startswith("sqlite"):
        return {"check_same_thread": False}
    if url.startswith("postgresql"):
        return {"options": "-c timezone=UTC"}
    return {}


def criar_motor(url: str) -> Engine:
    """Um engine com os ajustes que o banco daquela URL exige.

    Existe para que o engine da suíte de testes e o da aplicação nasçam da mesma
    função. Enquanto os argumentos de conexão ficavam soltos aqui, o
    `conftest.py` montava o seu próprio engine — e um teste que passasse ali não
    diria nada sobre o engine que sobe em produção, que é justamente o que a
    suíte contra PostgreSQL existe para verificar.
    """
    return create_engine(url, connect_args=_argumentos_de_conexao(url))


engine = criar_motor(settings.database_url)


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
    _preencher_obrigatorias(motor)
    _relaxar_obrigatoriedade(motor)


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

    Não cobre mudança de **restrição** numa coluna que já existe — isso é
    `_relaxar_obrigatoriedade`, que nasceu de um caso real e está logo abaixo.

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


def _preencher_obrigatorias(motor: Engine) -> None:
    """Dá valor às linhas antigas nas colunas que o modelo exige preenchidas.

    Contrapartida de `_acrescentar_colunas_faltantes`: ele acrescenta a coluna
    vazia, porque a linha antiga não tem valor a oferecer para um campo que não
    existia quando foi gravada. Só que o modelo pode exigir valor ali — `fadiga`
    é `float` com default 0,0 —, e o `NULL` que ficou vira um `TypeError` na
    primeira conta que some a coluna, longe daqui e sem pista de origem.

    Só preenche onde o **próprio modelo** já diz qual é o valor ausente, via
    default escalar. Coluna obrigatória sem default fica como está: inventar
    número para ela seria o sistema decidir sozinho o que aconteceu num dia em
    que ninguém estava medindo.
    """
    inspetor = inspect(motor)
    existentes = set(inspetor.get_table_names())

    with motor.begin() as conexao:
        for tabela in SQLModel.metadata.sorted_tables:
            if tabela.name not in existentes:
                continue

            no_banco = {coluna["name"] for coluna in inspetor.get_columns(tabela.name)}

            for coluna in tabela.columns:
                padrao = coluna.default
                if (
                    coluna.nullable
                    or coluna.name not in no_banco
                    or padrao is None
                    or padrao.is_callable
                ):
                    continue

                conexao.execute(
                    text(
                        f'UPDATE "{tabela.name}" SET "{coluna.name}" = :valor '
                        f'WHERE "{coluna.name}" IS NULL'
                    ),
                    {"valor": padrao.arg},
                )


def _relaxar_obrigatoriedade(motor: Engine) -> None:
    """Deixa aceitar nulo a coluna que o modelo tornou opcional.

    **Por que existe.** A ticket 10 mudou `LogEngajamento.score` de obrigatório
    para opcional: `NULL` passou a significar "não deu para medir este segundo",
    que é a distinção inteira daquela ticket. Só que num banco criado antes dela
    a coluna continua `NOT NULL`, e `create_all` não muda tabela existente.

    O resultado é o pior tipo de falha: tudo funciona até o aluno apagar a luz,
    e aí o primeiro ponto de incerteza estoura como `IntegrityError` no meio da
    sessão dele. Nenhum teste de suíte pegava, porque cada um cria um banco em
    memória a partir dos modelos de hoje — onde a coluna já nasce opcional.
    Apareceu ao abrir a aplicação contra o `app.db` de desenvolvimento, que é
    anterior à ticket 10.

    **Só afrouxa, nunca aperta.** Tornar uma coluna obrigatória exige decidir o
    que fazer com as linhas que já estão lá com `NULL` — inventar valor, apagar
    linha, recusar o boot —, e essa é uma decisão de produto que uma migração
    automática não tem como tomar sozinha.
    """
    inspetor = inspect(motor)
    existentes = set(inspetor.get_table_names())

    for tabela in SQLModel.metadata.sorted_tables:
        if tabela.name not in existentes:
            continue

        no_banco = {coluna["name"]: coluna for coluna in inspetor.get_columns(tabela.name)}
        a_relaxar = [
            coluna.name
            for coluna in tabela.columns
            if coluna.nullable
            and not coluna.primary_key
            and coluna.name in no_banco
            and not no_banco[coluna.name]["nullable"]
        ]
        if not a_relaxar:
            continue

        if motor.dialect.name == "sqlite":
            # O SQLite não tem ALTER COLUMN: a receita oficial é reconstruir a
            # tabela. O PostgreSQL da ticket 14 tem, e é o caminho de baixo.
            _reconstruir_tabela(motor, tabela, set(no_banco))
        else:
            with motor.begin() as conexao:
                for nome in a_relaxar:
                    conexao.execute(
                        text(
                            f'ALTER TABLE "{tabela.name}" '
                            f'ALTER COLUMN "{nome}" DROP NOT NULL'
                        )
                    )


def _reconstruir_tabela(motor: Engine, tabela, colunas_no_banco: set) -> None:
    """Recria a tabela no schema atual e traz os dados junto (só SQLite).

    O SQLite não tem `ALTER COLUMN`; a receita oficial é reconstruir a tabela. A
    ordem abaixo é o que importa, e cada passo protege o seguinte:

    1. A tabela antiga é **renomeada**, em vez de a nova nascer com nome
       provisório. Parece equivalente e não é: criar a nova pelo modelo exige
       que as tabelas referenciadas por chave estrangeira estejam no mesmo
       metadata, e só o metadata real do SQLModel tem todas elas.
    2. Os índices antigos são derrubados antes de a tabela nova nascer. No
       SQLite eles acompanham a tabela renomeada com os nomes originais, e
       colidiriam com os que o modelo vai criar.
    3. A cópia leva só as colunas presentes **nos dois** lados. Coluna que só
       existe no modelo entra com o default; coluna que só existe no banco fica
       para trás de propósito — se ninguém mais a declara, carregá-la adiante só
       adiaria a conversa.
    """
    comuns = [coluna.name for coluna in tabela.columns if coluna.name in colunas_no_banco]
    lista = ", ".join(f'"{nome}"' for nome in comuns)
    antiga = f"_migracao_{tabela.name}"

    indices = [indice["name"] for indice in inspect(motor).get_indexes(tabela.name)]

    with motor.begin() as conexao:
        conexao.execute(text(f'ALTER TABLE "{tabela.name}" RENAME TO "{antiga}"'))
        for nome in indices:
            if nome:
                conexao.execute(text(f'DROP INDEX IF EXISTS "{nome}"'))

    tabela.create(motor)

    with motor.begin() as conexao:
        conexao.execute(
            text(f'INSERT INTO "{tabela.name}" ({lista}) SELECT {lista} FROM "{antiga}"')
        )
        conexao.execute(text(f'DROP TABLE "{antiga}"'))


def get_session():
    with Session(engine) as session:
        yield session
