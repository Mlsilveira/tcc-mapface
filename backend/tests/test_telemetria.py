"""Testes da persistência da série de engajamento (ticket 6, seam C).

Os testes de **cálculo** do score saíram daqui na ticket 7, junto com a fórmula:
ela virou `app/analista.py` e é testada em `test_analista.py`, agora contra a
baseline individual do aluno. O que ficou é o que este módulo sempre fez, que é
gravar e ler pontos da série.
"""
import pytest

from app import telemetria

# --- Persistência do log de engajamento ------------------------------------


def _sessao_de_teste(session):
    from app.models import Aluno, SessaoEstudo

    aluno = Aluno(nome="Ana Souza", email="ana@exemplo.com", senha_hash="x")
    session.add(aluno)
    session.commit()
    session.refresh(aluno)

    sessao = SessaoEstudo(id_aluno=aluno.id)
    session.add(sessao)
    session.commit()
    session.refresh(sessao)
    return sessao


def test_log_de_engajamento_e_persistido_e_recuperavel(session):
    sessao = _sessao_de_teste(session)

    telemetria.registrar_log(session, id_sessao=sessao.id, score=72.5)

    logs = telemetria.buscar_logs(session, id_sessao=sessao.id)
    assert len(logs) == 1
    assert logs[0].score == pytest.approx(72.5)
    assert logs[0].id_sessao == sessao.id
    assert logs[0].horario_registro is not None


def test_logs_ficam_separados_por_sessao(session):
    # Os dados de uma sessão não podem aparecer no relatório de outra.
    primeira = _sessao_de_teste(session)

    from app.models import SessaoEstudo

    segunda = SessaoEstudo(id_aluno=primeira.id_aluno)
    session.add(segunda)
    session.commit()
    session.refresh(segunda)

    telemetria.registrar_log(session, id_sessao=primeira.id, score=10.0)
    telemetria.registrar_log(session, id_sessao=segunda.id, score=90.0)

    assert [log.score for log in telemetria.buscar_logs(session, id_sessao=primeira.id)] == [10.0]
    assert [log.score for log in telemetria.buscar_logs(session, id_sessao=segunda.id)] == [90.0]


# --- Persistência da fadiga ------------------------------------------------


def test_log_sem_fadiga_grava_os_defaults(session):
    sessao = _sessao_de_teste(session)

    log = telemetria.registrar_log(session, id_sessao=sessao.id, score=100.0)

    assert log.flag_fadiga is False
    assert log.fator_fadiga == pytest.approx(0.0)
    assert log.alerta_gerado is None


def test_fator_de_fadiga_e_persistido(session):
    sessao = _sessao_de_teste(session)

    telemetria.registrar_log(
        session,
        id_sessao=sessao.id,
        score=80.0,
        fator_fadiga=15.0,
        alertas=("olhos-fechados-prolongados",),
    )

    (log,) = telemetria.buscar_logs(session, id_sessao=sessao.id)
    assert log.fator_fadiga == pytest.approx(15.0)
    assert log.alerta_gerado == "olhos-fechados-prolongados"


def test_flag_de_fadiga_e_derivado_do_fator(session):
    """O flag nunca pode discordar do fator.

    Os dois convivem porque respondem perguntas diferentes — "houve fadiga?" e
    "quanta?" — mas derivar o flag num lugar só é o que impede uma linha em que
    `flag_fadiga` seja falso com 20 pontos de penalidade gravados ao lado.
    """
    sessao = _sessao_de_teste(session)

    telemetria.registrar_log(session, id_sessao=sessao.id, score=90.0, fator_fadiga=0.0)
    telemetria.registrar_log(session, id_sessao=sessao.id, score=70.0, fator_fadiga=8.0)

    primeiro, segundo = telemetria.buscar_logs(session, id_sessao=sessao.id)
    assert primeiro.flag_fadiga is False
    assert segundo.flag_fadiga is True


def test_varios_alertas_viram_uma_lista_separada_por_virgula(session):
    sessao = _sessao_de_teste(session)

    telemetria.registrar_log(
        session,
        id_sessao=sessao.id,
        score=60.0,
        fator_fadiga=33.0,
        alertas=("palpebras-pesadas", "bocejos"),
    )

    (log,) = telemetria.buscar_logs(session, id_sessao=sessao.id)
    assert log.alerta_gerado == "palpebras-pesadas,bocejos"


def test_sem_alerta_o_campo_fica_nulo_e_nao_string_vazia(session):
    # String vazia e ausência de alerta seriam indistinguíveis numa consulta
    # `WHERE alerta_gerado IS NOT NULL`, que é como o relatório vai contá-los.
    sessao = _sessao_de_teste(session)

    telemetria.registrar_log(session, id_sessao=sessao.id, score=100.0, alertas=())

    (log,) = telemetria.buscar_logs(session, id_sessao=sessao.id)
    assert log.alerta_gerado is None


def test_direcao_do_olhar_e_persistida_com_sinal(session):
    # O sinal distingue "olhou para a esquerda" de "olhou para a direita", e o
    # relatório precisa disso para dizer para onde o aluno desviava.
    sessao = _sessao_de_teste(session)

    telemetria.registrar_log(session, id_sessao=sessao.id, score=90.0, direcao_olhar=-12.5)

    (log,) = telemetria.buscar_logs(session, id_sessao=sessao.id)
    assert log.direcao_olhar == pytest.approx(-12.5)


def test_direcao_do_olhar_nula_quando_nao_houve_rosto(session):
    # `None` é "não observado", que não é o mesmo que "olhando para a frente".
    sessao = _sessao_de_teste(session)

    telemetria.registrar_log(session, id_sessao=sessao.id, score=0.0, direcao_olhar=None)

    (log,) = telemetria.buscar_logs(session, id_sessao=sessao.id)
    assert log.direcao_olhar is None


def test_schema_do_log_nao_tem_campo_de_imagem_ou_video():
    """Critério 5 da ticket 6, no nível do schema.

    A lista é fechada de propósito: qualquer coluna nova precisa passar por
    aqui, e é nesse momento que alguém tem que perguntar se ela carrega dado
    bruto de imagem. Uma asserção genérica de "não contém 'foto'" deixaria
    passar um `frame_base64` da vida.
    """
    from app.models import LogEngajamento

    assert set(LogEngajamento.__table__.columns.keys()) == {
        "id",
        "id_sessao",
        "horario_registro",
        "score",
        # Entraram com a persistência da fadiga. Nenhuma carrega dado de imagem:
        # duas são números derivados do score, uma é rótulo de texto e a última
        # é um ângulo em graus.
        "flag_fadiga",
        "fator_fadiga",
        "alerta_gerado",
        "direcao_olhar",
    }
