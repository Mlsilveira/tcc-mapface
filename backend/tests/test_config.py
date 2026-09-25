"""Testes da composição da URL do banco.

Existe por causa de uma restrição do ECS: ele injeta um segredo em **uma
variável de ambiente**, não no meio de uma URL. Montar a `DATABASE_URL` completa
exigiria alguém concatenar a senha com o resto — e esse alguém passaria a ter a
senha em texto claro, no estado do Terraform ou no log do contêiner.

Com as peças separadas, a senha viaja sozinha do Secrets Manager para a variável
de ambiente, e a URL é montada em memória. O que estes testes travam é que essa
composição não mude o comportamento de quem já funcionava.
"""
from app.config import Settings


def settings(**valores) -> Settings:
    """Uma configuração isolada do `.env` do desenvolvedor que rodar a suíte."""
    return Settings(_env_file=None, **valores)


# --- Precedência -----------------------------------------------------------


def test_sem_host_a_url_e_a_de_sempre():
    """O caminho de todo mundo: desenvolvimento local e a suíte inteira."""
    assert settings().url_do_banco == "sqlite:///./app.db"


def test_database_url_explicita_continua_valendo():
    url = "postgresql+psycopg://alguem:x@outro-host:5432/outro"

    assert settings(database_url=url).url_do_banco == url


def test_o_host_e_o_que_liga_a_composicao():
    """`DATABASE_HOST` é o interruptor — sem ele, nada é composto.

    É deliberado que a chave seja o host, e não a senha: um ambiente com senha
    definida e sem host é configuração pela metade, e cair no SQLite ali é
    menos destrutivo que montar uma URL apontando para lugar nenhum.
    """
    sem_host = settings(database_password="segredo")

    assert sem_host.url_do_banco == "sqlite:///./app.db"


# --- Composição ------------------------------------------------------------


def test_compoe_a_url_das_pecas():
    montada = settings(
        database_host="banco.rds.amazonaws.com",
        database_password="senha-simples",
    ).url_do_banco

    assert montada == (
        "postgresql+psycopg://mapface:senha-simples@banco.rds.amazonaws.com:5432/mapface"
    )


def test_usa_o_driver_psycopg_e_nao_o_antigo():
    """O `requirements.txt` traz `psycopg` 3; `psycopg2` não está instalado."""
    montada = settings(database_host="x", database_password="y").url_do_banco

    assert montada.startswith("postgresql+psycopg://")
    assert "psycopg2" not in montada


def test_host_sem_senha_ainda_monta():
    """IAM database authentication, ou um Postgres local sem senha."""
    montada = settings(database_host="localhost").url_do_banco

    assert montada == "postgresql+psycopg://mapface@localhost:5432/mapface"


def test_porta_usuario_e_banco_sao_ajustaveis():
    montada = settings(
        database_host="h",
        database_port=6543,
        database_user="outro",
        database_name="outro_banco",
        database_password="s",
    ).url_do_banco

    assert montada == "postgresql+psycopg://outro:s@h:6543/outro_banco"


# --- O caractere que quebra tudo -------------------------------------------


def test_a_senha_e_escapada():
    """Senha gerada pela AWS contém `@`, `/`, `:` e `#` — todos com significado
    dentro de uma URL.

    Sem escapar, uma senha com `@` parte a URL no lugar errado, e o erro que
    aparece é "host desconhecido" — que não se parece nem um pouco com a causa.
    """
    montada = settings(database_host="h", database_password="a@b/c:d#e").url_do_banco

    assert "a%40b%2Fc%3Ad%23e" in montada
    # O `@` que separa credencial de host continua sendo exatamente um.
    assert montada.count("@") == 1


def test_o_usuario_tambem_e_escapado():
    montada = settings(database_host="h", database_user="user@dominio").url_do_banco

    assert "user%40dominio@h" in montada
