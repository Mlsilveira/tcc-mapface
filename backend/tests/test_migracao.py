"""Testes da migração leve de schema (`app.database.criar_tabelas`).

`SQLModel.metadata.create_all` só cria tabela nova. Numa tabela que já existe
ele não faz nada e não avisa, então uma coluna acrescentada a um modelo passa o
boot inteiro em silêncio e só se manifesta no primeiro INSERT — como
`OperationalError` no meio da sessão de estudo de alguém.

Foi exatamente o que a ticket 10 quase causou: ela acrescentou `fadiga` e
`alerta` a `log_engajamento`, e todo banco anterior a ela quebraria no primeiro
payload de telemetria. Os testes de suíte não pegavam porque cada um cria um
banco em memória do zero, que nunca é o caso do banco de alguém.
"""
import pathlib
import sqlite3

import pytest
from sqlmodel import create_engine, text

from app.database import criar_tabelas


def _colunas(caminho, tabela):
    with sqlite3.connect(caminho) as conexao:
        return {linha[1] for linha in conexao.execute(f"PRAGMA table_info({tabela})")}


@pytest.fixture(name="banco_antigo")
def banco_antigo_fixture(tmp_path):
    """Um banco no schema anterior à ticket 10, com uma linha já gravada."""
    caminho = tmp_path / "antigo.db"

    with sqlite3.connect(caminho) as conexao:
        conexao.executescript(
            """
            CREATE TABLE aluno (
                id INTEGER PRIMARY KEY, nome VARCHAR, email VARCHAR, senha_hash VARCHAR
            );
            CREATE TABLE sessao_estudo (
                id INTEGER PRIMARY KEY, id_aluno INTEGER, inicio DATETIME,
                fim DATETIME, ultima_atividade DATETIME
            );
            CREATE TABLE log_engajamento (
                id INTEGER PRIMARY KEY, id_sessao INTEGER,
                horario_registro DATETIME, score FLOAT
            );
            INSERT INTO sessao_estudo (id, id_aluno, inicio, ultima_atividade)
                VALUES (1, 1, '2026-08-20 10:00:00', '2026-08-20 10:00:00');
            INSERT INTO log_engajamento (id_sessao, horario_registro, score)
                VALUES (1, '2026-08-20 10:00:01', 72.5);
            """
        )

    return caminho


def test_acrescenta_as_colunas_que_faltam(banco_antigo):
    assert _colunas(banco_antigo, "log_engajamento") == {
        "id",
        "id_sessao",
        "horario_registro",
        "score",
    }

    criar_tabelas(create_engine(f"sqlite:///{banco_antigo}"))

    assert {"fadiga", "alerta"} <= _colunas(banco_antigo, "log_engajamento")


def test_preserva_os_dados_ja_gravados(banco_antigo):
    """Migrar não pode custar a série de quem já usou o sistema.

    A alternativa que quase entrou — apagar o banco e deixar recriar — resolveria
    o erro e levaria junto o histórico de todas as sessões anteriores.

    **`fadiga` chega em 0,0, e não em `NULL`.** Até a ticket 11 esta asserção
    esperava `NULL`, porque `_acrescentar_colunas_faltantes` acrescenta a coluna
    vazia e nada a preenchia depois. O modelo, porém, declara `fadiga` como
    `float` obrigatório com default 0,0, e o `NULL` que sobrava só se
    manifestava longe daqui — como `TypeError` na primeira média que somasse a
    coluna. Quem preenche agora é `_preencher_obrigatorias`, e o valor vem do
    default do próprio modelo, não de um palpite da migração.

    O que **não** mudou é o que o teste protege: o score gravado continua
    exatamente onde estava.
    """
    criar_tabelas(create_engine(f"sqlite:///{banco_antigo}"))

    with sqlite3.connect(banco_antigo) as conexao:
        linhas = conexao.execute("SELECT score, fadiga, alerta FROM log_engajamento").fetchall()

    assert linhas == [(72.5, 0.0, None)]


def test_o_ponto_novo_grava_no_banco_migrado(banco_antigo):
    """O teste que de fato reproduz a falha: gravar com as colunas novas."""
    motor = create_engine(f"sqlite:///{banco_antigo}")
    criar_tabelas(motor)

    with motor.begin() as conexao:
        conexao.execute(
            text(
                "INSERT INTO log_engajamento (id_sessao, horario_registro, score, fadiga, alerta)"
                " VALUES (1, '2026-08-20 10:00:02', NULL, 0.0, 'baixa-luz')"
            )
        )

    with sqlite3.connect(banco_antigo) as conexao:
        assert conexao.execute(
            "SELECT count(*) FROM log_engajamento WHERE alerta = 'baixa-luz'"
        ).fetchone() == (1,)


def test_e_idempotente(banco_antigo):
    # Roda a cada boot: a segunda passada não pode tentar acrescentar de novo o
    # que a primeira já acrescentou.
    motor = create_engine(f"sqlite:///{banco_antigo}")

    criar_tabelas(motor)
    antes = _colunas(banco_antigo, "log_engajamento")
    criar_tabelas(motor)

    assert _colunas(banco_antigo, "log_engajamento") == antes


def test_migra_sem_depender_de_quem_importou_os_modelos(banco_antigo, tmp_path):
    """Num processo que só importa `app.database`, a migração ainda acontece.

    Uma tabela só entra em `SQLModel.metadata` quando o módulo que a define é
    carregado. Enquanto `criar_tabelas` dependia de alguém já ter importado
    `app.models`, ela percorria um metadata vazio e não fazia nada — sem erro,
    porque não há o que reclamar quando não há tabela a considerar. Funcionava no
    boot só porque os routers importam os modelos antes do lifespan rodar.

    O subprocesso é o ponto do teste: dentro da suíte o `conftest` já importou
    meio mundo, e a falha seria invisível.
    """
    import subprocess
    import sys

    script = (
        "from sqlmodel import create_engine\n"
        "from app.database import criar_tabelas\n"
        f"criar_tabelas(create_engine('sqlite:///{banco_antigo}'))\n"
    )

    resultado = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(pathlib.Path(__file__).resolve().parent.parent),
        capture_output=True,
        text=True,
    )

    assert resultado.returncode == 0, resultado.stderr
    assert {"fadiga", "alerta"} <= _colunas(banco_antigo, "log_engajamento")


def test_cria_do_zero_um_banco_vazio(tmp_path):
    caminho = tmp_path / "novo.db"

    criar_tabelas(create_engine(f"sqlite:///{caminho}"))

    assert {"fadiga", "alerta", "score"} <= _colunas(caminho, "log_engajamento")


def _tabelas(caminho):
    with sqlite3.connect(caminho) as conexao:
        return {
            linha[0]
            for linha in conexao.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }


def test_acrescenta_o_encerramento_da_ticket_11(banco_antigo):
    """A coluna que distingue sessão encerrada pelo aluno de sessão derrubada.

    Mesmo risco da ticket 10, um ticket depois: sem este ALTER, o primeiro
    `POST /sessoes/{id}/encerrar` num banco antigo quebraria.
    """
    assert "encerramento" not in _colunas(banco_antigo, "sessao_estudo")

    criar_tabelas(create_engine(f"sqlite:///{banco_antigo}"))

    assert "encerramento" in _colunas(banco_antigo, "sessao_estudo")


def test_sessao_antiga_fica_sem_encerramento_em_vez_de_receber_um_inventado(banco_antigo):
    """A migração acrescenta coluna; nunca preenche linha antiga.

    Uma sessão gravada antes da ticket 11 não tem como dizer se terminou por
    clique ou por abandono. `NULL` é a resposta verdadeira, e o relatório a
    trata como "não dá para saber" — marcar todas como parciais inventaria uma
    informação que o banco não tem.
    """
    criar_tabelas(create_engine(f"sqlite:///{banco_antigo}"))

    with sqlite3.connect(banco_antigo) as conexao:
        assert [linha[0] for linha in conexao.execute("SELECT encerramento FROM sessao_estudo")] == [
            None
        ]


def test_cria_a_tabela_de_resumo_da_ticket_13(banco_antigo):
    assert "resumo_sessao" not in _tabelas(banco_antigo)

    criar_tabelas(create_engine(f"sqlite:///{banco_antigo}"))

    assert "resumo_sessao" in _tabelas(banco_antigo)
    assert {"media", "duracao_presente_s", "granular_descartado"} <= _colunas(
        banco_antigo, "resumo_sessao"
    )


def test_acrescenta_o_contexto_e_a_presenca_da_sessao(banco_antigo):
    """As colunas de método de estudo, na mesma disciplina das anteriores.

    `ultima_presenca` é a mais crítica das cinco: é ela que passa a decidir o
    encerramento automático. Sem este ALTER, o primeiro payload de telemetria
    num banco antigo quebraria no meio da sessão de estudo de alguém.
    """
    assert "metodo" not in _colunas(banco_antigo, "sessao_estudo")

    criar_tabelas(create_engine(f"sqlite:///{banco_antigo}"))

    assert {
        "metodo",
        "assunto",
        "meta_de_blocos",
        "pausa_maxima_s",
        "ultima_presenca",
    } <= _colunas(banco_antigo, "sessao_estudo")


def test_sessao_antiga_fica_sem_metodo_em_vez_de_virar_sem_metodo(banco_antigo):
    """`NULL` e `"livre"` dizem coisas diferentes, e a migração não as colapsa.

    `NULL` é "esta sessão é anterior ao recurso"; `"livre"` é "o aluno escolheu
    estudar sem método". Preencher as antigas com `"livre"` inventaria uma
    escolha que ninguém fez — o mesmo erro que `encerramento` evita ao deixar
    sessão antiga sem valor em vez de chutar "manual".
    """
    criar_tabelas(create_engine(f"sqlite:///{banco_antigo}"))

    with sqlite3.connect(banco_antigo) as conexao:
        linhas = list(
            conexao.execute(
                "SELECT metodo, pausa_maxima_s, ultima_presenca FROM sessao_estudo"
            )
        )

    assert linhas == [(None, None, None)]


def test_sessao_aberta_no_deploy_nao_morre_por_falta_de_presenca(banco_antigo):
    """O risco agudo desta migração, travado num teste.

    Toda sessão já aberta ganha `ultima_presenca = NULL`. Se a varredura
    tratasse nulo como ausência infinita, ela mataria **todas** as sessões vivas
    no primeiro boot, antes de o primeiro payload chegar. A regra é cair em
    `inicio`, e uma sessão recém-aberta continua viva.
    """
    from app.models import SessaoEstudo
    from app.tempo import agora_utc
    from sqlmodel import Session

    motor = create_engine(f"sqlite:///{banco_antigo}")
    agora = agora_utc()

    with sqlite3.connect(banco_antigo) as conexao:
        conexao.execute(
            "INSERT INTO sessao_estudo (id, id_aluno, inicio, ultima_atividade)"
            " VALUES (2, 1, ?, ?)",
            (agora.replace(tzinfo=None).isoformat(sep=" "),) * 2,
        )

    criar_tabelas(motor)

    from app import sessoes

    with Session(motor) as db:
        # A sessão 1 da fixture é de agosto e morre com razão; a recém-aberta
        # é a que este teste protege.
        encerradas = sessoes.encerrar_inativas(db, agora=agora)
        assert 2 not in [s.id for s in encerradas]
        assert db.get(SessaoEstudo, 2).fim is None


def test_cria_a_tabela_de_blocos_do_metodo_de_estudo(banco_antigo):
    """Espelha `test_cria_a_tabela_de_resumo_da_ticket_13`, uma tabela depois.

    `create_all` cria tabela nova sozinho, então o risco aqui não é a criação —
    é a **chave estrangeira**. `bloco_estudo` referencia `sessao_estudo`, e uma
    FK entra em `SQLModel.metadata.sorted_tables`: se ela invertesse a ordem,
    a varredura de `_relaxar_obrigatoriedade` passaria por `sessao_estudo`
    antes das suas dependências e a reconstrução (que derruba e recria a tabela)
    aconteceria no lugar errado.
    """
    assert "bloco_estudo" not in _tabelas(banco_antigo)

    criar_tabelas(create_engine(f"sqlite:///{banco_antigo}"))

    assert "bloco_estudo" in _tabelas(banco_antigo)
    assert {"id_sessao", "indice", "tipo", "inicio", "fim", "origem"} <= _colunas(
        banco_antigo, "bloco_estudo"
    )


def test_a_sessao_referenciada_vem_antes_do_bloco_na_ordem_da_migracao(banco_antigo):
    """A ordem topológica que a FK impõe, fixada explicitamente.

    É a asserção que o teste acima não consegue fazer olhando só o resultado:
    aqui se afirma que `sessao_estudo` é percorrida **antes** de `bloco_estudo`,
    que é o que garante que a tabela referenciada já esteja no schema atual
    quando a que a referencia nascer.
    """
    from sqlmodel import SQLModel

    from app import models  # noqa: F401 — garante o metadata carregado

    ordem = [tabela.name for tabela in SQLModel.metadata.sorted_tables]

    assert ordem.index("sessao_estudo") < ordem.index("bloco_estudo")


def test_sessao_antiga_nao_ganha_bloco_inventado(banco_antigo):
    """A tabela nasce **vazia**, e é isso que o relatório precisa encontrar.

    Uma sessão anterior ao recurso não tem blocos, e não os tem porque ninguém
    os declarou — não porque se perderam. Semear um bloco de foco cobrindo a
    sessão inteira faria o relatório de janeiro afirmar uma estrutura de estudo
    que o aluno nunca escolheu, que é o mesmo erro de preencher `metodo` com
    `"livre"`.
    """
    criar_tabelas(create_engine(f"sqlite:///{banco_antigo}"))

    with sqlite3.connect(banco_antigo) as conexao:
        assert conexao.execute("SELECT count(*) FROM bloco_estudo").fetchone() == (0,)


def test_o_bloco_grava_no_banco_migrado(banco_antigo):
    """O teste que de fato reproduz a falha: declarar uma transição."""
    motor = create_engine(f"sqlite:///{banco_antigo}")
    criar_tabelas(motor)

    with motor.begin() as conexao:
        conexao.execute(
            text(
                "INSERT INTO bloco_estudo (id_sessao, indice, tipo, inicio, fim, origem)"
                " VALUES (1, 1, 'foco', '2026-08-20 10:00:00', NULL, 'metodo')"
            )
        )

    with sqlite3.connect(banco_antigo) as conexao:
        assert conexao.execute(
            "SELECT indice, tipo, fim, origem FROM bloco_estudo"
        ).fetchall() == [(1, "foco", None, "metodo")]


def test_o_indice_por_sessao_do_bloco_existe(banco_antigo):
    """Todo leitor quer "os blocos desta sessão"; nenhum quer "todos os blocos".

    Mesmo argumento que levou `log_engajamento.id_sessao` a ser indexado na
    ticket 13 — em escala menor, mas de graça.
    """
    criar_tabelas(create_engine(f"sqlite:///{banco_antigo}"))

    with sqlite3.connect(banco_antigo) as conexao:
        indices = {
            linha[0]
            for linha in conexao.execute(
                "SELECT name FROM sqlite_master"
                " WHERE type='index' AND tbl_name='bloco_estudo'"
            )
        }

    assert "ix_bloco_estudo_id_sessao" in indices


@pytest.fixture(name="banco_pre_ticket_10")
def banco_pre_ticket_10_fixture(tmp_path):
    """Um banco em que `score` ainda é obrigatório, como antes da ticket 10.

    É o `app.db` de quem usou o sistema antes daquela ticket — e foi nele que a
    falha apareceu, ao abrir a aplicação de verdade. A suíte inteira passava
    porque cada teste cria um banco em memória a partir dos modelos de hoje,
    onde a coluna já nasce opcional.
    """
    caminho = tmp_path / "pre10.db"

    with sqlite3.connect(caminho) as conexao:
        conexao.executescript(
            """
            CREATE TABLE aluno (
                id INTEGER PRIMARY KEY, nome VARCHAR, email VARCHAR, senha_hash VARCHAR
            );
            CREATE TABLE sessao_estudo (
                id INTEGER PRIMARY KEY, id_aluno INTEGER, inicio DATETIME,
                fim DATETIME, ultima_atividade DATETIME
            );
            CREATE TABLE log_engajamento (
                id INTEGER PRIMARY KEY,
                id_sessao INTEGER NOT NULL,
                horario_registro DATETIME NOT NULL,
                score FLOAT NOT NULL
            );
            CREATE INDEX ix_log_engajamento_antigo ON log_engajamento (id_sessao);
            INSERT INTO sessao_estudo (id, id_aluno, inicio, ultima_atividade)
                VALUES (1, 1, '2026-08-20 10:00:00', '2026-08-20 10:00:00');
            INSERT INTO log_engajamento (id_sessao, horario_registro, score)
                VALUES (1, '2026-08-20 10:00:01', 72.5), (1, '2026-08-20 10:00:02', 68.0);
            """
        )

    return caminho


def _obrigatorias(caminho, tabela):
    with sqlite3.connect(caminho) as conexao:
        return {
            linha[1] for linha in conexao.execute(f"PRAGMA table_info({tabela})") if linha[3]
        }


def test_score_deixa_de_ser_obrigatorio_num_banco_anterior_a_ticket_10(banco_pre_ticket_10):
    """A falha real: a ticket 10 tornou `score` opcional e o banco não soube.

    Sem isto, tudo funciona até o aluno apagar a luz — e aí o primeiro ponto de
    incerteza estoura como `IntegrityError` no meio da sessão dele.
    """
    assert "score" in _obrigatorias(banco_pre_ticket_10, "log_engajamento")

    criar_tabelas(create_engine(f"sqlite:///{banco_pre_ticket_10}"))

    assert "score" not in _obrigatorias(banco_pre_ticket_10, "log_engajamento")


def test_grava_incerteza_depois_de_migrar(banco_pre_ticket_10):
    """O teste que de fato reproduz a falha: gravar o ponto de incerteza."""
    criar_tabelas(create_engine(f"sqlite:///{banco_pre_ticket_10}"))

    with sqlite3.connect(banco_pre_ticket_10) as conexao:
        conexao.execute(
            "INSERT INTO log_engajamento (id_sessao, horario_registro, score, fadiga, alerta)"
            " VALUES (1, '2026-08-20 10:00:03', NULL, 0.0, 'baixa-luz')"
        )
        assert conexao.execute(
            "SELECT count(*) FROM log_engajamento WHERE score IS NULL"
        ).fetchone()[0] == 1


def test_reconstruir_a_tabela_nao_custa_os_dados(banco_pre_ticket_10):
    """A reconstrução é a parte perigosa: ela derruba e recria a tabela."""
    criar_tabelas(create_engine(f"sqlite:///{banco_pre_ticket_10}"))

    with sqlite3.connect(banco_pre_ticket_10) as conexao:
        assert conexao.execute(
            "SELECT score FROM log_engajamento ORDER BY horario_registro"
        ).fetchall() == [(72.5,), (68.0,)]


def test_preenche_a_coluna_obrigatoria_que_veio_vazia(banco_pre_ticket_10):
    """`fadiga` entra por ALTER, nasce nula, e o modelo a exige preenchida.

    O `NULL` que ficava ali só se manifestava longe daqui, como `TypeError` na
    primeira média que somasse a coluna.
    """
    criar_tabelas(create_engine(f"sqlite:///{banco_pre_ticket_10}"))

    with sqlite3.connect(banco_pre_ticket_10) as conexao:
        assert conexao.execute(
            "SELECT count(*) FROM log_engajamento WHERE fadiga IS NULL"
        ).fetchone()[0] == 0
        assert conexao.execute(
            "SELECT DISTINCT fadiga FROM log_engajamento"
        ).fetchall() == [(0.0,)]


def test_deixa_os_indices_do_modelo_no_lugar_e_leva_os_antigos_embora(banco_pre_ticket_10):
    """No SQLite os índices seguem a tabela renomeada e colidiriam de nome."""
    criar_tabelas(create_engine(f"sqlite:///{banco_pre_ticket_10}"))

    with sqlite3.connect(banco_pre_ticket_10) as conexao:
        indices = {
            linha[0]
            for linha in conexao.execute(
                "SELECT name FROM sqlite_master"
                " WHERE type='index' AND tbl_name='log_engajamento'"
            )
        }

    assert {"ix_log_engajamento_horario_registro", "ix_log_engajamento_id_sessao"} <= indices
    assert "ix_log_engajamento_antigo" not in indices


def test_e_idempotente(banco_pre_ticket_10):
    """Rodar duas vezes não pode reconstruir a tabela de novo."""
    motor = create_engine(f"sqlite:///{banco_pre_ticket_10}")
    criar_tabelas(motor)
    antes = _colunas(banco_pre_ticket_10, "log_engajamento")

    criar_tabelas(motor)

    assert _colunas(banco_pre_ticket_10, "log_engajamento") == antes
    with sqlite3.connect(banco_pre_ticket_10) as conexao:
        assert conexao.execute("SELECT count(*) FROM log_engajamento").fetchone()[0] == 2
        assert conexao.execute(
            "SELECT count(*) FROM sqlite_master WHERE name LIKE '_migracao_%'"
        ).fetchone()[0] == 0


def test_a_tabela_de_blocos_nasce_no_banco_que_exige_reconstrucao(banco_pre_ticket_10):
    """A combinação perigosa: tabela nova com FK **e** reconstrução no mesmo boot.

    `banco_pre_ticket_10` é a fixture em que `_reconstruir_tabela` de fato roda
    (`log_engajamento.score` precisa deixar de ser obrigatório). Acrescentar uma
    tabela que referencia `sessao_estudo` no mesmo metadata podia mudar a ordem
    de varredura e fazer a reconstrução cair sobre a tabela errada, levando a
    sessão junto. Este teste afirma que os três acontecem e nenhum atropela o
    outro.
    """
    criar_tabelas(create_engine(f"sqlite:///{banco_pre_ticket_10}"))

    assert "bloco_estudo" in _tabelas(banco_pre_ticket_10)

    with sqlite3.connect(banco_pre_ticket_10) as conexao:
        # A sessão que já estava lá continua lá, com o início original.
        assert conexao.execute("SELECT id, inicio FROM sessao_estudo").fetchall() == [
            (1, "2026-08-20 10:00:00")
        ]
        # E a série dela também — a reconstrução de `log_engajamento` aconteceu.
        assert conexao.execute(
            "SELECT score FROM log_engajamento ORDER BY horario_registro"
        ).fetchall() == [(72.5,), (68.0,)]
        # Nenhuma tabela provisória ficou para trás.
        assert conexao.execute(
            "SELECT count(*) FROM sqlite_master WHERE name LIKE '_migracao_%'"
        ).fetchone() == (0,)


def test_o_bloco_gravado_sobrevive_ao_boot_seguinte(banco_pre_ticket_10):
    """Idempotência com dado dentro: a segunda passada não recria a tabela.

    Uma tabela nova recriada por engano no boot seguinte apagaria os blocos de
    todas as sessões — silenciosamente, porque o relatório de uma sessão sem
    blocos é uma tela válida.
    """
    motor = create_engine(f"sqlite:///{banco_pre_ticket_10}")
    criar_tabelas(motor)

    with motor.begin() as conexao:
        conexao.execute(
            text(
                "INSERT INTO bloco_estudo (id_sessao, indice, tipo, inicio, fim, origem)"
                " VALUES (1, 1, 'pausa', '2026-08-20 10:25:00',"
                " '2026-08-20 10:30:00', 'aluno')"
            )
        )

    criar_tabelas(motor)

    with sqlite3.connect(banco_pre_ticket_10) as conexao:
        assert conexao.execute("SELECT indice, tipo FROM bloco_estudo").fetchall() == [
            (1, "pausa")
        ]
