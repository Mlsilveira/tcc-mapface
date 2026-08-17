"""Testes da persistência da série de engajamento (tickets 6 e 7).

Os testes do `calcular_score` provisório saíram junto com a função: a ticket 7
substituiu aquela fórmula pelo `AnalistaEngajamento`, e a regra do IEE agora é
exercitada em `test_analista.py`, contra a baseline individual do aluno. Mantê-los
aqui seria manter verde uma fórmula que não roda mais em lugar nenhum.

O que sobrou é o seam de persistência, que a ticket 7 não mudou.
"""
import pytest

from app import telemetria



# --- Persistência do log de engajamento (seam C) ---------------------------


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
    }
