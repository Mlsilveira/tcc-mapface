"""Testes da senha do banco lida a cada conexão nova.

O defeito que eles travam aconteceu no ambiente publicado: a AWS troca sozinha
a senha do RDS a cada 7 dias, a task só lia a senha ao nascer, e a partir da
rotação toda conexão **nova** falhava com `password authentication failed` —
enquanto as que já estavam no pool seguiam funcionando e escondiam o problema.
"""
import json

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from app import senha_do_banco

ARN = "arn:aws:secretsmanager:us-east-1:481503226251:secret:rds!db-abc123-XyZ"


class SecretsManagerFalso:
    """Devolve, a cada leitura, a próxima senha da fila — como uma rotação."""

    def __init__(self, *senhas):
        self.senhas = list(senhas)
        self.lidos = []

    def get_secret_value(self, SecretId):
        self.lidos.append(SecretId)
        senha = self.senhas.pop(0)
        return {"SecretString": json.dumps({"username": "mapface", "password": senha})}


# --- A leitura do segredo ----------------------------------------------------


def test_le_so_a_senha_do_documento_que_o_rds_guarda():
    """O RDS guarda um JSON com usuário e senha; a conexão quer só a senha."""
    cliente = SecretsManagerFalso("s3nh@:com/simbolos#")

    assert senha_do_banco.ler_senha(ARN, cliente=cliente) == "s3nh@:com/simbolos#"
    assert cliente.lidos == [ARN]


def test_a_regiao_vem_do_proprio_arn():
    """Sem depender de `AWS_REGION` estar definida no contêiner."""
    assert senha_do_banco.regiao_do_arn(ARN) == "us-east-1"


@pytest.mark.parametrize("ruim", ["", "nao-e-arn", "arn:aws:s3:::um-bucket"])
def test_arn_que_nao_e_de_segredo_falha_no_boot(ruim):
    """Melhor errar ao subir do que na primeira conexão, com mensagem de senha."""
    with pytest.raises(ValueError):
        senha_do_banco.regiao_do_arn(ruim)


# --- A senha a cada conexão --------------------------------------------------


def _motor_que_registra_a_senha(buscar):
    """Um motor real cuja conexão é interceptada para expor a senha usada.

    O gancho de produção roda primeiro e põe a senha em `cparams`; o segundo
    ouvinte só a anota e devolve uma conexão SQLite, já que não há PostgreSQL
    na suíte. Os dois são ouvintes do mesmo evento `do_connect`, na ordem em que
    foram registrados.
    """
    from sqlalchemy import event
    import sqlite3

    motor = create_engine("sqlite://", poolclass=NullPool)
    senha_do_banco.senha_a_cada_conexao(motor, buscar)
    usadas = []

    @event.listens_for(motor, "do_connect")
    def _anotar(dialect, conn_rec, cargs, cparams):
        usadas.append(cparams.get("password"))
        return sqlite3.connect(":memory:")

    return motor, usadas


def test_cada_conexao_nova_nasce_com_a_senha_de_agora():
    """A rotação entre a primeira e a segunda conexão não quebra a segunda."""
    cliente = SecretsManagerFalso("senha-antiga", "senha-depois-da-rotacao")
    motor, usadas = _motor_que_registra_a_senha(lambda: senha_do_banco.ler_senha(ARN, cliente=cliente))

    for _ in range(2):
        with motor.connect() as conexao:
            conexao.execute(text("SELECT 1"))

    assert usadas == ["senha-antiga", "senha-depois-da-rotacao"]


def test_conexao_reaproveitada_do_pool_nao_relê_o_segredo():
    """O custo é uma leitura por conexão aberta, e não por requisição."""
    leituras = []

    def buscar():
        leituras.append(1)
        return "x"

    motor = create_engine("sqlite://")
    senha_do_banco.senha_a_cada_conexao(motor, buscar)
    from sqlalchemy import event
    import sqlite3

    @event.listens_for(motor, "do_connect")
    def _sqlite(dialect, conn_rec, cargs, cparams):
        return sqlite3.connect(":memory:", check_same_thread=False)

    for _ in range(5):
        with motor.connect() as conexao:
            conexao.execute(text("SELECT 1"))

    assert len(leituras) == 1


# --- A configuração ----------------------------------------------------------


def test_sem_arn_nada_muda():
    """Desenvolvimento local e a suíte continuam sem tocar na AWS."""
    from app.config import Settings

    assert Settings(_env_file=None).database_password_secret_arn is None
