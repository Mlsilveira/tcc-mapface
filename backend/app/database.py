from contextlib import contextmanager
from typing import Callable, ContextManager, Iterator, Optional

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


#: Quantas conexões deste processo podem estar em uso ao mesmo tempo.
#:
#: **De onde sai o 45, e por que ele não é um chute de capacidade.** Este
#: processo é um só (o `CMD` do Dockerfile sobe sem `--workers`, porque a
#: baseline calibrada vive em memória de processo), e dentro dele só existem
#: **dois** lugares de onde pode partir uma chamada bloqueante ao banco:
#:
#: 1. o *threadpool* do AnyIO, onde o FastAPI executa toda rota declarada com
#:    `def` — login, heartbeat, telas, `/pronto`. O limite dele é 40 threads
#:    (`anyio.to_thread.current_default_thread_limiter().total_tokens`), e 40
#:    threads não conseguem segurar 41 conexões;
#: 2. o próprio laço de eventos, onde as rotas `async` — hoje, só o WebSocket —
#:    executam SQLAlchemy síncrono em linha. O laço é de uma thread só, então
#:    **todos** os canais abertos somados produzem no máximo **uma** chamada ao
#:    banco em voo, por mais alunos que estejam com a webcam ligada.
#:
#: 40 + 1 = 41 é o teto verdadeiro do processo. 45 deixa quatro de folga para o
#: que roda fora dos dois caminhos (o `criar_tabelas` do lifespan, um script de
#: manutenção apontado para o mesmo banco) e garante a propriedade que
#: interessa: **nada neste processo fica esperando no pool**, então o
#: `pool_timeout` de 30 s nunca dispara e `/pronto` não pode ser esganado por
#: telemetria. Era exatamente o desfecho do teto anterior de 15 — do 16º aluno
#: em diante, `/pronto` falhava e o orquestrador tirava da rotação a única task
#: que existe.
#:
#: **E o outro lado da conta, o banco.** O `max_connections` padrão do RDS
#: PostgreSQL é `LEAST(DBInstanceClassMemory/9531392, 5000)`: ≈112 numa
#: `db.t4g.micro` (1 GiB) e ≈225 numa `db.t4g.small`. Tirando as 3 reservadas
#: para superusuário e as que o próprio RDS mantém, sobram ~100 na menor
#: instância plausível. Uma aplicação com teto 45 usa menos da metade disso —
#: sobra banco para um `psql` durante o teste com a turma, que é justamente a
#: hora em que alguém vai querer olhar uma tabela.
TETO_DE_CONEXOES = 45

#: Quantas conexões continuam **abertas** depois que o pico passa.
#:
#: Não é quanto o pool pré-abre (o SQLAlchemy abre sob demanda): é quanto ele
#: retém. As 25 acima destas são o `max_overflow` — nascem no pico e são
#: fechadas ao voltar.
#:
#: 20 é generoso de propósito para o regime normal do experimento, que é
#: pequeno: 40 alunos a 1 Hz produzem 40 gravações por segundo, mas serializadas
#: no laço de eventos (item 2 acima) elas ocupam **uma** conexão; o heartbeat do
#: navegador bate uma vez por minuto por aluno, ou ~0,7 requisição por segundo
#: numa turma de 40; as telas são esporádicas. Um punhado de conexões daria
#: conta. O que 20 compra é não pagar aperto de mão com o RDS no primeiro pico
#: depois de cada vale — e não manter 45 conexões ociosas estacionadas no banco
#: a tarde inteira, que é o que `pool_size=45` faria.
CONEXOES_AQUECIDAS = 20


def _argumentos_de_pool(url: str) -> dict:
    """Como o pool é dimensionado — e por que o SQLite fica de fora.

    `pool_size` e `max_overflow` só existem no `QueuePool`. O SQLite em memória
    da suíte usa `SingletonThreadPool`, que **recusa** esses argumentos com um
    `TypeError` no `create_engine` — ou seja, passá-los sem distinção derrubaria
    todo teste da suíte antes da primeira asserção.

    `pool_pre_ping` vale para os dois, e é o único ajuste que vale a pena
    manter ligado também em SQLite: assim o caminho que roda em produção é o
    mesmo que a suíte exercita.

    **O que `pool_pre_ping` resolve.** Uma conexão parada é derrubada do outro
    lado sem aviso — pelo `idle_session_timeout` do RDS, por um NAT no meio —, e
    o pool só descobre no `SELECT` seguinte, que volta como 500 para o aluno. O
    intervalo que produz isso não é hipotético neste projeto: é o que separa o
    teste com a turma da defesa. Com o *pre-ping*, o pool gasta um `SELECT 1` no
    empréstimo, vê a conexão morta, descarta e abre outra — e ninguém percebe.

    *A alternativa descartada* foi `pool_recycle`, que fecha a conexão por
    idade. Ela resolveria o mesmo caso e exigiria manter um número deste lado
    sempre menor que o tempo ocioso tolerado do outro — um acoplamento a um
    valor que mora no console da AWS e que ninguém revisaria ao mudar de
    instância. O *pre-ping* pergunta em vez de supor.

    O custo do *pre-ping* é um `SELECT 1` por empréstimo, e ele é real: com a
    sessão curta por payload (`sessao_curta`), uma turma de 40 alunos a 1 Hz
    empresta algumas dezenas de vezes por segundo. É um ida-e-volta trivial numa
    rede local de VPC, e o que ele evita é um 500 numa demonstração.
    """
    if url.startswith("sqlite"):
        return {"pool_pre_ping": True}
    return {
        "pool_size": CONEXOES_AQUECIDAS,
        "max_overflow": TETO_DE_CONEXOES - CONEXOES_AQUECIDAS,
        "pool_pre_ping": True,
    }


def criar_motor(url: str) -> Engine:
    """Um engine com os ajustes que o banco daquela URL exige.

    Existe para que o engine da suíte de testes e o da aplicação nasçam da mesma
    função. Enquanto os argumentos de conexão ficavam soltos aqui, o
    `conftest.py` montava o seu próprio engine — e um teste que passasse ali não
    diria nada sobre o engine que sobe em produção, que é justamente o que a
    suíte contra PostgreSQL existe para verificar.

    **`hide_parameters=True` é uma decisão de privacidade, não de verbosidade.**
    Sem ele, toda exceção do SQLAlchemy carrega `[parameters: (...)]` com os
    valores ligados à consulta que falhou — e o handler global de `app/main.py`
    registra a falha com `exc_info=True`, o que faz o `FormatadorJson` serializar
    o traceback inteiro no campo `excecao`. Dois `POST /auth/registro`
    simultâneos com o mesmo e-mail bastam, **sem autenticação nenhuma**, para
    pôr o e-mail e o hash bcrypt de alguém no CloudWatch; um `INSERT` que falhe
    em `sessao_estudo` põe o `assunto`, que é texto escrito pelo aluno. O
    docstring de `app/observabilidade.py` promete que nada disso aparece no log,
    e esta linha é o que torna a promessa verdadeira — a disciplina de não
    escrever dado pessoal em `contexto={...}` não alcança o que o driver anexa
    sozinho à mensagem de erro.

    O que se perde é a depuração por leitura do log: saber *qual* linha colidiu
    exige ir ao banco. É o preço certo — o tipo da exceção, a consulta e a
    origem continuam na linha, e são eles que dizem o que quebrou. *A
    alternativa descartada* foi filtrar os parâmetros no `FormatadorJson`, por
    expressão regular sobre o traceback já formatado: ela deixaria o dado
    circular dentro do processo e dependeria de a regex acompanhar o formato de
    mensagem de cada driver, que é a categoria de defeito que só aparece em
    produção. Aqui o valor simplesmente nunca é escrito.
    """
    return create_engine(
        url,
        connect_args=_argumentos_de_conexao(url),
        hide_parameters=True,
        **_argumentos_de_pool(url),
    )


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


@contextmanager
def sessao_curta() -> Iterator[Session]:
    """Uma sessão de banco que vive o tempo de **uma** unidade de trabalho.

    Existe para o WebSocket, e a diferença para `get_session` é o tempo de vida,
    não o conteúdo. Uma dependência com `yield` numa rota HTTP dura o que dura a
    requisição — milissegundos. A mesma dependência num WebSocket dura o que
    dura o **canal**, que neste projeto são horas: era `db: Session =
    Depends(get_session)` na assinatura de `telemetria_ws`, e cada aluno com a
    webcam ligada segurava uma conexão do pool a sessão de estudo inteira.

    Com 15 conexões no pool, o 16º aluno travava — e não travava só a telemetria
    dele: travava login, heartbeat e `/pronto` para todo mundo, porque o pool é
    do processo. `/pronto` falhando faz o orquestrador tirar a task da rotação, e
    a topologia desta versão tem **uma** task. O gatilho não era um atacante: era
    a turma do teste, com a carga para a qual o sistema foi feito.

    Aumentar o pool sozinho não resolveria: moveria o teto de 15 para 45 alunos
    e manteria intacta a forma da falha — conexão retida por tempo de conexão, e
    não por tempo de trabalho. Aqui a conexão é emprestada para o `INSERT` do
    payload e devolvida em seguida, então o número de canais abertos deixa de
    ser o número de conexões ocupadas. O canal a 1 Hz usa alguns milissegundos
    de conexão por segundo, em vez de mil.

    *A alternativa descartada* foi manter a dependência e chamar `db.close()` ao
    fim de cada payload, reabrindo sob demanda. Funciona — uma `Session` reabre
    sozinha na consulta seguinte —, e foi recusada porque o tempo de vida do
    recurso ficaria implícito numa chamada solta no meio do laço, que é
    exatamente o tipo de coisa que a próxima edição do handler apaga sem notar.
    Um `with` diz onde a sessão começa e onde termina.
    """
    with Session(engine) as sessao:
        yield sessao


def obter_fabrica_de_sessoes() -> Callable[[], ContextManager[Session]]:
    """Dependência que entrega **a fábrica**, e não uma sessão já aberta.

    É o que permite ao WebSocket abrir e fechar uma sessão por payload sem
    perder a substituição por `app.dependency_overrides`: uma dependência comum
    (sem `yield`) é chamada e devolve na hora, então nada fica pendurado no
    ciclo de vida do canal.

    Poderia não existir — o handler importaria `sessao_curta` direto —, e aí a
    suíte perderia o único ponto em que trocar o banco do canal é possível.
    Todos os testes de WebSocket passariam a falar com o `app.db` do disco em
    vez do banco descartável da fixture.
    """
    return sessao_curta
