"""Testes da regra de telemetria (ticket 6).

O score desta ticket é deliberadamente provisório: serve para provar o pipeline
ponta a ponta antes da fórmula real do IEE entrar na ticket 7. A estrutura de
pesos, porém, já é a definitiva — 0,6 para abertura ocular e 0,4 para orientação
da cabeça — trocando apenas a baseline individual do aluno por constantes fixas.

Os valores esperados abaixo foram calculados à mão a partir da fórmula acordada,
não extraídos do código:

    score = 100 × (0,6 × min(EAR/0,3, 1) + 0,4 × max(0, 1 − |yaw|/45))
"""
import pytest

from app import telemetria


def test_score_maximo_com_olhos_abertos_e_cabeca_de_frente():
    # 100 × (0,6 × 1 + 0,4 × 1) = 100
    assert telemetria.calcular_score(ear=0.30, yaw=0.0) == pytest.approx(100.0)


def test_olhos_semicerrados_derrubam_a_parcela_ocular():
    # EAR 0,15 → 0,15/0,3 = 0,5 → 100 × (0,6 × 0,5 + 0,4 × 1) = 70
    assert telemetria.calcular_score(ear=0.15, yaw=0.0) == pytest.approx(70.0)


def test_cabeca_totalmente_virada_zera_a_parcela_de_orientacao():
    # yaw 45° → 1 − 45/45 = 0 → 100 × (0,6 × 1 + 0,4 × 0) = 60
    assert telemetria.calcular_score(ear=0.30, yaw=45.0) == pytest.approx(60.0)


def test_olhos_fechados_e_cabeca_virada_zeram_o_score():
    assert telemetria.calcular_score(ear=0.0, yaw=45.0) == pytest.approx(0.0)


def test_score_nao_passa_de_100_com_olhos_muito_abertos():
    # Arregalar os olhos não é "mais engajado" que o teto: sem o limite, um EAR
    # atípico geraria score acima de 100 e quebraria a escala de 0 a 100.
    assert telemetria.calcular_score(ear=0.90, yaw=0.0) == pytest.approx(100.0)


def test_score_nao_fica_negativo_com_cabeca_alem_do_limite():
    # yaw 90° passaria de 1 na normalização; sem o piso, a parcela viraria
    # negativa e roubaria pontos da parcela ocular.
    assert telemetria.calcular_score(ear=0.30, yaw=90.0) == pytest.approx(60.0)


def test_yaw_e_simetrico_entre_esquerda_e_direita():
    # Virar para um lado ou para o outro dispersa igual.
    assert telemetria.calcular_score(ear=0.30, yaw=-30.0) == pytest.approx(
        telemetria.calcular_score(ear=0.30, yaw=30.0)
    )


def test_sem_rosto_o_score_e_zero():
    # É o P(t) = 0 do spec, antecipado: sem rosto não há comportamento
    # observável, e qualquer score seria invenção.
    assert telemetria.calcular_score(ear=0.30, yaw=0.0, rosto_detectado=False) == 0.0


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
