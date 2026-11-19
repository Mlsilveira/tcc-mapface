"""A senha do banco, lida do Secrets Manager no instante de cada conexão nova.

**Por que a variável de ambiente não basta.** A senha do RDS é gerenciada pela
própria AWS (`manage_master_user_password`, em `infra/modules/banco`), que a
**troca sozinha a cada 7 dias**. O ECS injeta um segredo numa variável de
ambiente uma única vez, quando a task nasce; depois da primeira rotação, a
variável guarda uma senha morta.

O defeito é traiçoeiro porque não aparece logo. O PostgreSQL não derruba as
sessões já autenticadas quando a senha muda, então as conexões que estavam no
pool continuam funcionando — até a aplicação precisar de uma conexão **nova**.
No ambiente publicado, com a task de pé desde 10/11/2026 e a rotação de 18/11,
7 de 10 cadastros simultâneos voltaram 500 com `password authentication
failed`: passaram só os que pegaram uma conexão antiga.

Ler a senha no momento em que o SQLAlchemy abre a conexão torna a rotação
invisível: cada conexão nasce com a senha que vale agora. O custo é uma chamada
ao Secrets Manager **por conexão aberta**, e não por requisição — o pool
reaproveita as conexões, e uma task ociosa não chama nada.
"""
import json
from functools import lru_cache
from typing import Callable

from sqlalchemy import event
from sqlalchemy.engine import Engine

BuscarSenha = Callable[[], str]


def regiao_do_arn(arn: str) -> str:
    """A região sai do próprio ARN, sem depender de `AWS_REGION` no contêiner.

    Um ARN que não é de segredo falha aqui, no boot, e não na primeira conexão —
    onde o erro chegaria disfarçado de senha errada.
    """
    partes = arn.split(":")
    if len(partes) < 7 or partes[0] != "arn" or partes[2] != "secretsmanager":
        raise ValueError(f"Não é o ARN de um segredo do Secrets Manager: {arn!r}")
    return partes[3]


@lru_cache(maxsize=None)
def _cliente(regiao: str):
    # Importado aqui, e não no topo: o boto3 só existe para quem roda na AWS, e
    # o desenvolvimento local e a suíte não deveriam pagar o import.
    import boto3

    return boto3.client("secretsmanager", region_name=regiao)


def ler_senha(arn: str, cliente=None) -> str:
    """A senha atual, extraída do JSON `{"username": ..., "password": ...}` do RDS."""
    cliente = cliente or _cliente(regiao_do_arn(arn))
    documento = cliente.get_secret_value(SecretId=arn)["SecretString"]
    return json.loads(documento)["password"]


def senha_a_cada_conexao(motor: Engine, buscar: BuscarSenha) -> None:
    """Faz toda conexão nova do `motor` nascer com a senha que `buscar` devolver.

    A senha entra em `cparams`, que é o que o driver recebe — e por isso nunca
    passa por uma URL, por um log ou pelo `repr` do motor.
    """

    @event.listens_for(motor, "do_connect")
    def _com_a_senha_de_agora(dialect, conn_rec, cargs, cparams):
        cparams["password"] = buscar()
