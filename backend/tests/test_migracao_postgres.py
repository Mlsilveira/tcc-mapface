"""A migração caseira contra um PostgreSQL de verdade.

**Por que um arquivo separado de `test_migracao.py`.** Aquele arquivo fala com o
banco pelo módulo `sqlite3` da biblioteca padrão — `PRAGMA table_info`, `sqlite_master`,
arquivo em `tmp_path`. Nada disso existe no PostgreSQL, e parametrizar aqueles
testes para os dois bancos significaria reescrever cada asserção em duas
versões dentro do mesmo teste, que é a duplicação que se queria evitar, só que
pior — escondida dentro de `if`. O que é comum aos dois bancos já roda nos dois:
é a suíte inteira, que o `conftest.py` aponta para onde `DATABASE_URL_DE_TESTE`
mandar. O que sobra para cá é o que **só existe** no PostgreSQL.

**E o que só existe aqui é o caminho que nunca tinha rodado.** O SQLite não tem
`ALTER COLUMN`, então `_relaxar_obrigatoriedade` reconstrói a tabela inteira lá;
o ramo `ALTER TABLE ... ALTER COLUMN ... DROP NOT NULL` estava escrito no código
desde a ticket 10, apontado pelo comentário "o PostgreSQL da ticket 14 tem", e
não havia uma única execução dele em lugar nenhum. Estes testes são a primeira.

O cenário é o mesmo que produziu a falha original: um banco anterior à ticket
10, em que `log_engajamento.score` ainda é `NOT NULL`. Naquele banco tudo
funciona até o aluno apagar a luz — e aí o primeiro ponto de incerteza estoura
como `IntegrityError` no meio da sessão dele.
"""
import pytest
from sqlalchemy import text
from sqlmodel import SQLModel, create_engine

from app.database import criar_tabelas
from tests.conftest import RODANDO_EM_POSTGRES, URL_DE_TESTE

pytestmark = pytest.mark.skipif(
    not RODANDO_EM_POSTGRES,
    reason="exige DATABASE_URL_DE_TESTE apontando para um PostgreSQL",
)

#: Schema próprio, e não o `public` que o resto da suíte usa.
#:
#: Estes testes derrubam e recriam tabelas com dados dentro; rodar isso no mesmo
#: lugar em que as outras fixtures gravam faria a ordem de execução da suíte
#: decidir o resultado. Um schema é o isolamento mais barato que o PostgreSQL
#: oferece — separar por banco exigiria `CREATE DATABASE`, que é privilégio que
#: nem todo ambiente de CI concede, e criaria um banco fora do que o
#: desenvolvedor autorizou.
ESQUEMA = "migracao_postgres"

#: O schema anterior à ticket 10, escrito à mão. `score` é `NOT NULL`, que é a
#: restrição inteira em jogo, e os índices são os de então.
DDL_ANTIGO = f"""
CREATE TABLE {ESQUEMA}.aluno (
    id SERIAL PRIMARY KEY,
    nome VARCHAR,
    email VARCHAR,
    senha_hash VARCHAR
);
CREATE TABLE {ESQUEMA}.sessao_estudo (
    id SERIAL PRIMARY KEY,
    id_aluno INTEGER,
    inicio TIMESTAMP,
    fim TIMESTAMP,
    ultima_atividade TIMESTAMP
);
CREATE TABLE {ESQUEMA}.log_engajamento (
    id SERIAL PRIMARY KEY,
    id_sessao INTEGER NOT NULL,
    horario_registro TIMESTAMP NOT NULL,
    score FLOAT NOT NULL
);
CREATE INDEX ix_log_engajamento_antigo
    ON {ESQUEMA}.log_engajamento (id_sessao);
INSERT INTO {ESQUEMA}.aluno (id, nome, email, senha_hash)
    VALUES (1, 'Ana Souza', 'ana@exemplo.com', 'nao-importa-aqui');
INSERT INTO {ESQUEMA}.sessao_estudo (id, id_aluno, inicio, ultima_atividade)
    VALUES (1, 1, '2026-08-20 10:00:00', '2026-08-20 10:00:00');
INSERT INTO {ESQUEMA}.log_engajamento (id_sessao, horario_registro, score)
    VALUES (1, '2026-08-20 10:00:01', 72.5), (1, '2026-08-20 10:00:02', 68.0);
"""


@pytest.fixture(name="motor_pre_ticket_10")
def motor_pre_ticket_10_fixture():
    """Um PostgreSQL no schema anterior à ticket 10, isolado num schema próprio.

    O engine é montado aqui em vez de vir de `database.criar_motor` porque
    precisa de um `search_path` além do fuso — e o `search_path` é justamente o
    que dá o isolamento. O `-c timezone=UTC` é repetido **de propósito**: é o
    mesmo ajuste que a aplicação faz, e omiti-lo aqui faria estes testes rodarem
    contra uma conexão diferente da de produção, que é o contrário do que eles
    existem para provar.
    """
    opcoes = f"-c timezone=UTC -c search_path={ESQUEMA}"
    motor = create_engine(URL_DE_TESTE, connect_args={"options": opcoes})

    with motor.begin() as conexao:
        conexao.execute(text(f"DROP SCHEMA IF EXISTS {ESQUEMA} CASCADE"))
        conexao.execute(text(f"CREATE SCHEMA {ESQUEMA}"))
        for comando in filter(str.strip, DDL_ANTIGO.split(";")):
            conexao.execute(text(comando))

    yield motor

    with motor.begin() as conexao:
        conexao.execute(text(f"DROP SCHEMA IF EXISTS {ESQUEMA} CASCADE"))
    motor.dispose()


def _obrigatoria(motor, tabela, coluna) -> bool:
    """`True` se o banco recusa `NULL` naquela coluna, lido do catálogo."""
    with motor.begin() as conexao:
        return (
            conexao.execute(
                text(
                    "SELECT is_nullable FROM information_schema.columns"
                    " WHERE table_schema = :esquema"
                    " AND table_name = :tabela AND column_name = :coluna"
                ),
                {"esquema": ESQUEMA, "tabela": tabela, "coluna": coluna},
            ).scalar()
            == "NO"
        )


def _colunas(motor, tabela) -> set:
    with motor.begin() as conexao:
        return {
            linha[0]
            for linha in conexao.execute(
                text(
                    "SELECT column_name FROM information_schema.columns"
                    " WHERE table_schema = :esquema AND table_name = :tabela"
                ),
                {"esquema": ESQUEMA, "tabela": tabela},
            )
        }


def _tabelas(motor) -> set:
    with motor.begin() as conexao:
        return {
            linha[0]
            for linha in conexao.execute(
                text(
                    "SELECT table_name FROM information_schema.tables"
                    " WHERE table_schema = :esquema"
                ),
                {"esquema": ESQUEMA},
            )
        }


def _identidade_da_tabela(motor, tabela) -> int:
    """O OID da tabela — a prova de que ela é a **mesma**, e não uma recriada."""
    with motor.begin() as conexao:
        return conexao.execute(
            text("SELECT to_regclass(:nome)::oid"), {"nome": f"{ESQUEMA}.{tabela}"}
        ).scalar()


def test_score_deixa_de_ser_obrigatorio(motor_pre_ticket_10):
    """A falha original, reproduzida no banco que vai para produção.

    A ticket 10 tornou `score` opcional — `NULL` passou a significar "não deu
    para medir este segundo" — e `create_all` não muda tabela que já existe.
    """
    assert _obrigatoria(motor_pre_ticket_10, "log_engajamento", "score")

    criar_tabelas(motor_pre_ticket_10)

    assert not _obrigatoria(motor_pre_ticket_10, "log_engajamento", "score")


def test_grava_o_ponto_de_incerteza_depois_de_migrar(motor_pre_ticket_10):
    """O que de fato importa: o `INSERT` que antes estourava agora passa.

    A asserção acima lê o catálogo; esta exercita o caminho do aluno que apagou
    a luz no meio da sessão, que é por onde a falha apareceu.
    """
    criar_tabelas(motor_pre_ticket_10)

    with motor_pre_ticket_10.begin() as conexao:
        conexao.execute(
            text(
                "INSERT INTO log_engajamento"
                " (id_sessao, horario_registro, score, fadiga, alerta)"
                " VALUES (1, '2026-08-20 10:00:03', NULL, 0.0, 'baixa-luz')"
            )
        )
        assert conexao.execute(
            text("SELECT count(*) FROM log_engajamento WHERE score IS NULL")
        ).scalar() == 1


def test_a_tabela_e_alterada_no_lugar_e_nao_reconstruida(motor_pre_ticket_10):
    """A diferença entre os dois bancos, afirmada onde ela é observável.

    No SQLite a única saída é reconstruir a tabela — renomear, recriar, copiar,
    apagar —, e é a operação mais perigosa desta migração inteira: ela passa por
    um instante em que os dados existem só na cópia. O PostgreSQL tem `ALTER
    COLUMN ... DROP NOT NULL`, que não move linha nenhuma.

    O OID é o que separa os dois casos: ele identifica a tabela física, e uma
    tabela recriada recebe outro. Comparar contagem de linhas ou nomes de coluna
    não distinguiria nada — a reconstrução preserva as duas.

    Ficar sem nenhuma `_migracao_*` para trás é a outra metade: é o nome
    provisório que só o caminho do SQLite usa.
    """
    antes = _identidade_da_tabela(motor_pre_ticket_10, "log_engajamento")

    criar_tabelas(motor_pre_ticket_10)

    assert _identidade_da_tabela(motor_pre_ticket_10, "log_engajamento") == antes
    assert not [nome for nome in _tabelas(motor_pre_ticket_10) if nome.startswith("_migracao_")]


def test_a_serie_ja_gravada_sobrevive(motor_pre_ticket_10):
    """Migrar não pode custar o histórico de quem já usou o sistema."""
    criar_tabelas(motor_pre_ticket_10)

    with motor_pre_ticket_10.begin() as conexao:
        scores = conexao.execute(
            text("SELECT score FROM log_engajamento ORDER BY horario_registro")
        ).all()

    assert scores == [(72.5,), (68.0,)]


def test_acrescenta_as_colunas_que_faltam_e_preenche_a_obrigatoria(motor_pre_ticket_10):
    """`_acrescentar_colunas_faltantes` e `_preencher_obrigatorias` no PostgreSQL.

    Os dois também nunca tinham rodado fora do SQLite, e o segundo é o que
    impede o `NULL` que entra por `ALTER TABLE ADD COLUMN` de virar um
    `TypeError` longe daqui, na primeira média que somar a coluna. `fadiga` é
    `float` obrigatório com default 0,0 no modelo — o valor vem dali, não de um
    palpite da migração.
    """
    assert {"fadiga", "alerta"} & _colunas(motor_pre_ticket_10, "log_engajamento") == set()

    criar_tabelas(motor_pre_ticket_10)

    assert {"fadiga", "alerta"} <= _colunas(motor_pre_ticket_10, "log_engajamento")
    with motor_pre_ticket_10.begin() as conexao:
        assert conexao.execute(
            text("SELECT DISTINCT fadiga FROM log_engajamento")
        ).all() == [(0.0,)]
        assert conexao.execute(
            text("SELECT count(*) FROM log_engajamento WHERE alerta IS NOT NULL")
        ).scalar() == 0


def test_cria_as_tabelas_que_ainda_nao_existiam(motor_pre_ticket_10):
    """As tabelas das tickets 13 e do método de estudo nascem no mesmo boot.

    Vale a mesma armadilha do SQLite: `bloco_estudo` e `resumo_sessao`
    referenciam `sessao_estudo`, e nascer na ordem errada seria erro de chave
    estrangeira — que aqui, ao contrário do SQLite, o banco de fato verifica.
    """
    assert {"bloco_estudo", "resumo_sessao"} & _tabelas(motor_pre_ticket_10) == set()

    criar_tabelas(motor_pre_ticket_10)

    assert {"bloco_estudo", "resumo_sessao"} <= _tabelas(motor_pre_ticket_10)


def test_e_idempotente(motor_pre_ticket_10):
    """Roda a cada boot: a segunda passada não pode desfazer a primeira.

    O `ALTER COLUMN` não é condicional — quem decide se ele acontece é a
    comparação entre o modelo e o catálogo. Se essa comparação errasse na
    segunda passada, o `ALTER` seria emitido de novo (inofensivo) ou, pior, a
    varredura cairia no ramo do SQLite e reconstruiria a tabela num banco que
    não precisa disso.
    """
    criar_tabelas(motor_pre_ticket_10)
    colunas = _colunas(motor_pre_ticket_10, "log_engajamento")
    identidade = _identidade_da_tabela(motor_pre_ticket_10, "log_engajamento")

    criar_tabelas(motor_pre_ticket_10)

    assert _colunas(motor_pre_ticket_10, "log_engajamento") == colunas
    assert _identidade_da_tabela(motor_pre_ticket_10, "log_engajamento") == identidade
    with motor_pre_ticket_10.begin() as conexao:
        assert conexao.execute(text("SELECT count(*) FROM log_engajamento")).scalar() == 2


def test_o_indice_antigo_continua_no_lugar(motor_pre_ticket_10):
    """`ALTER COLUMN` não mexe em índice, e isso é uma diferença real.

    No SQLite a reconstrução derruba os índices antigos de propósito: eles
    acompanham a tabela renomeada com os nomes originais e colidiriam com os que
    o modelo vai criar. Aqui nada é reconstruído, então o índice de antes
    permanece — e os do modelo **não** são criados, porque `create_all` não toca
    em tabela existente.

    O teste registra o estado real em vez de fingir que os dois bancos terminam
    iguais. Não é risco em produção: um PostgreSQL novo nasce pelo `create_all`
    com todos os índices do modelo. Só um banco PostgreSQL anterior à ticket 10
    — que não existe — ficaria sem eles.
    """
    criar_tabelas(motor_pre_ticket_10)

    with motor_pre_ticket_10.begin() as conexao:
        indices = {
            linha[0]
            for linha in conexao.execute(
                text(
                    "SELECT indexname FROM pg_indexes"
                    " WHERE schemaname = :esquema AND tablename = 'log_engajamento'"
                ),
                {"esquema": ESQUEMA},
            )
        }

    assert "ix_log_engajamento_antigo" in indices


def test_a_sessao_de_estudo_continua_utilizavel_depois_da_migracao(motor_pre_ticket_10):
    """O teste de ponta: gravar pelos modelos, e não por SQL cru.

    Os anteriores falam com o catálogo e com `text()`. Este passa pelo SQLModel,
    que é o caminho que a aplicação usa — inclusive pelo `Dict[str, int]` com
    `Column(JSON)` de `ResumoSessao`, que é tipo que o SQLite guarda como texto
    e o PostgreSQL guarda como `json`.
    """
    from sqlmodel import Session, select

    from app.models import ResumoSessao

    criar_tabelas(motor_pre_ticket_10)

    with Session(motor_pre_ticket_10) as db:
        db.add(
            ResumoSessao(
                id_sessao=1,
                media=70.25,
                pontos_medidos=2,
                motivos_de_incerteza={"baixa-luz": 3},
                granular_descartado=True,
            )
        )
        db.commit()

    with Session(motor_pre_ticket_10) as db:
        gravado = db.exec(select(ResumoSessao)).one()

    assert gravado.motivos_de_incerteza == {"baixa-luz": 3}
    assert gravado.granular_descartado is True
    assert gravado.media == pytest.approx(70.25)


def test_o_metadata_nao_fica_preso_ao_schema_de_teste():
    """Um cuidado sobre estes testes, não sobre a migração.

    `SQLModel.metadata` é global ao processo. Se alguma coisa aqui carimbasse o
    schema `migracao_postgres` nas tabelas do metadata, todo teste posterior da
    suíte passaria a falar com o schema errado — e o sintoma apareceria longe,
    em arquivos que não mencionam PostgreSQL em lugar nenhum.

    O isolamento vem do `search_path` da conexão justamente para isto: o
    metadata continua sem schema, e quem resolve o nome é o banco.
    """
    assert {tabela.schema for tabela in SQLModel.metadata.sorted_tables} == {None}
