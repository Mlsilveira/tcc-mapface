"""Como o processo empresta conexões do banco, e por que os números são esses.

Este arquivo não testa consulta nenhuma: testa o **dimensionamento**. O defeito
que ele tranca não aparece em teste funcional e não aparece com duas abas
abertas — aparece na 16ª pessoa da sala com a webcam ligada, quando o pool
esgota e para tudo, inclusive `/pronto`, que é o que mantém a única task do
serviço na rotação.

A conta que sustenta os números está no docstring de
`app.database.TETO_DE_CONEXOES`. Aqui ela é refeita à mão, para que mudá-la em
silêncio custe um teste vermelho.
"""
import anyio
import pytest
from sqlalchemy.pool import QueuePool
from sqlmodel import SQLModel, select

from app import database
from app.database import (
    CONEXOES_AQUECIDAS,
    TETO_DE_CONEXOES,
    criar_motor,
    obter_fabrica_de_sessoes,
    sessao_curta,
)
from app.models import Aluno

#: URL de PostgreSQL usada só para montar o engine. `create_engine` não conecta,
#: então não há servidor envolvido — o que se inspeciona é a configuração.
URL_DE_PRODUCAO = "postgresql+psycopg://mapface:irrelevante@db.interna:5432/mapface"


def _limite_do_threadpool() -> int:
    """Quantas rotas `def` o FastAPI consegue executar ao mesmo tempo.

    É o limitador do AnyIO, que o Starlette usa para tirar o código síncrono do
    laço de eventos. Ele é lido de dentro de um contexto assíncrono porque o
    limitador padrão é por *event loop*.
    """

    async def ler() -> int:
        return anyio.to_thread.current_default_thread_limiter().total_tokens

    return anyio.run(ler)


class TestDimensionamentoDoPool:
    def test_o_teto_e_a_soma_do_aquecido_com_o_transbordo(self):
        motor = criar_motor(URL_DE_PRODUCAO)

        assert isinstance(motor.pool, QueuePool)
        # Esperado à mão: 20 retidas + 25 de transbordo = 45.
        assert motor.pool.size() == 20
        assert motor.pool._max_overflow == 25
        assert CONEXOES_AQUECIDAS + motor.pool._max_overflow == TETO_DE_CONEXOES
        assert TETO_DE_CONEXOES == 45

    def test_o_teto_cobre_toda_concorrencia_que_este_processo_consegue_produzir(self):
        """A conta inteira, refeita aqui.

        Só existem dois lugares de onde sai uma chamada bloqueante ao banco
        neste processo:

        1. o threadpool do AnyIO, onde rodam as rotas `def` (login, heartbeat,
           telas, `/pronto`). N threads seguram no máximo N conexões;
        2. o laço de eventos, onde as rotas `async` — o WebSocket — executam
           SQLAlchemy síncrono em linha. O laço é de uma thread só, então todos
           os canais abertos somados produzem **uma** chamada em voo.

        Se o teto ficar abaixo dessa soma, existe uma combinação de requisições
        legítimas que faz alguém esperar no pool — e quem esperar pode ser a
        sonda de prontidão.
        """
        laco_de_eventos = 1
        maximo_simultaneo = _limite_do_threadpool() + laco_de_eventos

        # Escrito à mão: o padrão do AnyIO é 40, então 40 + 1 = 41.
        assert maximo_simultaneo == 41
        assert TETO_DE_CONEXOES >= maximo_simultaneo

    def test_o_teto_antigo_nao_cobria_uma_turma(self):
        """O bloqueador, dito como número.

        O padrão do SQLAlchemy é `pool_size=5` com `max_overflow=10`: 15
        conexões. Enquanto cada WebSocket segurava uma pela sessão inteira, 15
        era o número de alunos que cabiam na sala — e o 16º derrubava o serviço
        para os 15 primeiros também.
        """
        padrao_do_sqlalchemy = 5 + 10

        assert padrao_do_sqlalchemy == 15
        assert TETO_DE_CONEXOES > padrao_do_sqlalchemy

    def test_o_teto_cabe_na_menor_instancia_de_rds_plausivel(self):
        """O outro lado da conta: o banco também tem limite.

        `max_connections` no RDS PostgreSQL é
        `LEAST(DBInstanceClassMemory/9531392, 5000)` — ≈112 numa `db.t4g.micro`
        de 1 GiB. Tirando as reservadas para superusuário e as que o próprio RDS
        mantém, sobra por volta de 100.

        A aplicação é uma instância só (requisito de correção: a baseline
        calibrada vive em memória de processo), então o teto dela é o consumo
        total. Ele precisa deixar banco de sobra para um `psql` no meio do teste
        com a turma, que é justamente quando alguém vai querer olhar uma tabela.
        """
        # Esperado à mão: 1 GiB = 1073741824 bytes; 1073741824 / 9531392 = 112,6.
        max_connections_na_micro = int(1073741824 / 9531392)
        assert max_connections_na_micro == 112

        reservadas_para_superusuario = 3
        utilizaveis = max_connections_na_micro - reservadas_para_superusuario

        assert TETO_DE_CONEXOES < utilizaveis / 2


class TestAjustesDoEngine:
    def test_o_pre_ping_esta_ligado(self):
        """O que salva a primeira requisição depois de um intervalo parado.

        Conexão ociosa derrubada do outro lado (o `idle_session_timeout` do RDS,
        um NAT no meio) só é descoberta no `SELECT` seguinte, que volta como 500
        para o aluno. O intervalo que produz isso não é hipotético aqui: é o que
        separa o teste com a turma da defesa.
        """
        assert criar_motor(URL_DE_PRODUCAO).pool._pre_ping is True

    def test_os_parametros_da_consulta_nao_entram_na_mensagem_de_erro(self):
        """A metade de configuração do vazamento de §2.3.

        O que acontece com uma exceção de verdade está em
        `test_observabilidade.py::TestParametrosDaConsultaNoLog`; aqui só se
        afirma que o engine nasce com a trava ligada, inclusive em SQLite — o
        banco contra o qual a suíte roda por padrão.
        """
        assert criar_motor(URL_DE_PRODUCAO).hide_parameters is True
        assert criar_motor("sqlite://").hide_parameters is True

    def test_o_sqlite_nasce_sem_os_argumentos_de_pool(self):
        """Regressão de um jeito fácil de quebrar a suíte inteira.

        O SQLite em memória usa `SingletonThreadPool`, que **recusa**
        `pool_size` e `max_overflow` com um `TypeError` dentro do
        `create_engine`. Passá-los sem distinguir a URL derrubaria todo teste
        antes da primeira asserção — e o erro apareceria como falha de coleta,
        longe da linha que o causou.
        """
        motor = criar_motor("sqlite://")

        assert not isinstance(motor.pool, QueuePool)
        assert motor.pool._pre_ping is True

    def test_o_sqlite_em_arquivo_tambem_sobe(self, tmp_path):
        """O outro SQLite: em arquivo o SQLAlchemy usa `QueuePool`.

        É o banco de `app.db` e o dos testes de migração, e ele passa pelo mesmo
        `criar_motor` — então a distinção acima precisa valer para os dois.
        """
        motor = criar_motor("sqlite:///{}".format(tmp_path / "app.db"))

        assert motor.hide_parameters is True
        motor.dispose()


class TestSessaoCurta:
    """A correção que realmente resolve o bloqueador, medida no pool.

    Aumentar o teto move o limite de 15 alunos para 45 e mantém a forma da
    falha: conexão retida por tempo de **conexão**, e não por tempo de
    **trabalho**. O que muda a forma é a sessão curta — e a diferença entre as
    duas é exatamente o número que `checkedout()` devolve.
    """

    @pytest.fixture(name="motor_no_lugar_do_engine")
    def motor_no_lugar_do_engine_fixture(self, monkeypatch, tmp_path):
        """Um banco descartável no lugar do `engine` do módulo.

        `sessao_curta` lê `database.engine` na hora da chamada, que é o que
        permite trocá-lo aqui sem tocar na aplicação. Banco em arquivo porque o
        SQLite em arquivo usa `QueuePool`, e é o `QueuePool` que sabe contar
        conexões emprestadas — o de memória não.
        """
        motor = criar_motor("sqlite:///{}".format(tmp_path / "curta.db"))
        SQLModel.metadata.create_all(motor)
        monkeypatch.setattr(database, "engine", motor)
        yield motor
        motor.dispose()

    def test_a_conexao_volta_para_o_pool_ao_fim_do_bloco(self, motor_no_lugar_do_engine):
        """Esperado à mão: 0 emprestadas antes, 1 durante a consulta, 0 depois.

        O "1 durante" não é detalhe: sem ele o teste passaria mesmo se a sessão
        nunca tivesse encostado no banco, e não diria nada sobre a devolução.
        """
        motor = motor_no_lugar_do_engine
        assert motor.pool.checkedout() == 0

        with sessao_curta() as db:
            db.exec(select(Aluno)).all()
            assert motor.pool.checkedout() == 1

        assert motor.pool.checkedout() == 0

    def test_a_fabrica_entrega_a_sessao_curta(self):
        """A dependência devolve a fábrica, não uma sessão aberta.

        É o que faz a diferença num WebSocket: uma dependência com `yield`
        ficaria pendurada no ciclo de vida do canal, e uma comum é chamada e
        devolve na hora.
        """
        assert obter_fabrica_de_sessoes() is sessao_curta


@pytest.mark.parametrize("url", ["sqlite://", URL_DE_PRODUCAO])
def test_o_fuso_e_o_check_same_thread_continuam_de_pe(url):
    """Os ajustes anteriores não podem ter sido atropelados pelos novos.

    `connect_args` e os argumentos de pool entram na mesma chamada de
    `create_engine`, e é fácil um `**` novo apagar o que já estava lá — a falha
    apareceria como sessão de estudo nascendo três horas no passado (o fuso) ou
    como o uvicorn recusando a segunda requisição (o `check_same_thread`).
    """
    from app.database import _argumentos_de_conexao

    if url.startswith("sqlite"):
        assert _argumentos_de_conexao(url) == {"check_same_thread": False}
    else:
        assert _argumentos_de_conexao(url) == {"options": "-c timezone=UTC"}
