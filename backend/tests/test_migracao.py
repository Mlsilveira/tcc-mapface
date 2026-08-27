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
    """
    criar_tabelas(create_engine(f"sqlite:///{banco_antigo}"))

    with sqlite3.connect(banco_antigo) as conexao:
        linhas = conexao.execute("SELECT score, fadiga, alerta FROM log_engajamento").fetchall()

    assert linhas == [(72.5, None, None)]


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
