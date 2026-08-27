"""Testes da incerteza de captura (ticket 10).

O que a ticket protege não é um cálculo, é uma **abstenção**: quando as
condições de captura são ruins — pouca luz, reflexo no óculos, rosto
parcialmente ocluso — o sistema precisa dizer "não sei" em vez de emitir um
número que parece medição e não é.

Daí os três eixos testados aqui: a leitura incerta não vira score, não vira
baseline, e não vira ponto corrompido no banco.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app import analista, telemetria
from app.analista import AnalistaEngajamento

T0 = datetime(2026, 8, 27, 9, 0, 0, tzinfo=timezone.utc)


def _em(segundo: float) -> datetime:
    return T0 + timedelta(seconds=segundo)


# --- O score se abstém -----------------------------------------------------


def test_leitura_incerta_nao_produz_score():
    resultado = AnalistaEngajamento().observar(
        ear=0.30, yaw=0.0, agora=T0, incerteza="baixa-luz"
    )

    # `None`, e não zero: zero é uma afirmação sobre o aluno ("não estava lá"),
    # e aqui não há afirmação nenhuma a fazer.
    assert resultado.score is None
    assert resultado.incerteza == "baixa-luz"


def test_leitura_confiavel_continua_produzindo_score():
    resultado = AnalistaEngajamento().observar(ear=0.30, yaw=0.0, agora=T0)

    assert resultado.score == pytest.approx(100.0)
    assert resultado.incerteza is None


def test_motivo_desconhecido_ainda_suspende_a_medicao():
    """O rótulo do cliente não entra no banco, mas a abstenção dele vale.

    Um cliente mais novo que este backend pode reportar um motivo que ainda não
    existe aqui. Ignorar a marca por não reconhecer o texto seria voltar a medir
    exatamente a leitura que o navegador acabou de dizer que não presta.
    """
    resultado = AnalistaEngajamento().observar(
        ear=0.30, yaw=0.0, agora=T0, incerteza="sol-na-lente-esquerda"
    )

    assert resultado.score is None
    assert resultado.incerteza == analista.INCERTEZA_DESCONHECIDA


def test_rosto_ausente_zera_o_score_em_vez_de_suspende_lo():
    """Ausência é medição; incerteza não é. A ticket 10 depende dessa distinção.

    Sem rosto o `P(t) = 0` do spec afirma algo verdadeiro sobre o aluno — ele
    não estava na frente da webcam. Confundir os dois casos faria "saí da mesa"
    e "a lâmpada queimou" virarem o mesmo ponto no gráfico.
    """
    analista_ = AnalistaEngajamento()

    ausente = analista_.observar(ear=0.0, yaw=0.0, rosto_detectado=False, agora=T0)
    incerto = analista_.observar(ear=0.30, yaw=0.0, agora=_em(1), incerteza="oclusao")

    assert ausente.score == pytest.approx(0.0)
    assert incerto.score is None


def test_score_segue_zerado_durante_ausencia_prolongada():
    analista_ = AnalistaEngajamento()

    scores = [
        analista_.observar(
            ear=0.0, yaw=0.0, rosto_detectado=False, agora=_em(segundo)
        ).score
        for segundo in range(0, 120, 5)
    ]

    # Nenhum ponto do meio pode "lembrar" a última leitura boa: um aluno que saiu
    # da mesa não pode aparecer como presente no gráfico da ticket 9.
    assert scores == [pytest.approx(0.0)] * len(scores)


# --- A baseline se abstém --------------------------------------------------


def test_calibracao_ignora_leituras_incertas():
    """Um minuto inteiro de captura ruim não fecha baseline nenhuma.

    Calibrar aqui seria gravar a má iluminação como se fosse o rosto neutro do
    aluno, e medi-lo contra ela pelo resto da sessão — o oposto exato do que a
    calibração individual da ticket 7 existe para fazer.
    """
    analista_ = AnalistaEngajamento()

    for segundo in range(61):
        analista_.observar(ear=0.30, yaw=0.0, agora=_em(segundo), incerteza="baixa-luz")

    assert analista_.calibrando is True
    assert analista_.baseline is None


def test_calibracao_recomeca_depois_de_incerteza_prolongada():
    """Incerteza longa no meio do minuto inicial descarta o que foi acumulado.

    É a mesma regra da ausência prolongada da ticket 7: uma baseline feita de
    dez segundos de dados bons costurados com cinquenta de dados descartados
    descreveria aqueles dez segundos, não o padrão neutro do aluno.
    """
    analista_ = AnalistaEngajamento()

    for segundo in range(10):
        analista_.observar(ear=0.18, yaw=0.0, agora=_em(segundo))

    for segundo in range(10, 40):
        analista_.observar(ear=0.30, yaw=0.0, agora=_em(segundo), incerteza="reflexo-ocular")

    # Luz de volta: a contagem do minuto recomeça daqui, não continua de onde parou.
    for segundo in range(40, 71):
        analista_.observar(ear=0.18, yaw=0.0, agora=_em(segundo))

    assert analista_.calibrando is True

    for segundo in range(71, 105):
        analista_.observar(ear=0.18, yaw=0.0, agora=_em(segundo))

    assert analista_.calibrando is False
    assert analista_.baseline.ear_neutro == pytest.approx(0.18)


def test_incerteza_nao_conta_como_palpebra_fechada():
    """PERCLOS não pode subir por falta de informação (ticket 8 × ticket 10).

    Contar leitura descartada como olho fechado transformaria "a luz apagou" em
    "o aluno cochilou", que é uma acusação sobre o comportamento dele tirada de
    um problema do ambiente.
    """
    analista_ = AnalistaEngajamento()

    for segundo in range(0, 60):
        analista_.observar(ear=0.05, yaw=0.0, agora=_em(segundo), incerteza="baixa-luz")

    resultado = analista_.observar(ear=0.30, yaw=0.0, agora=_em(60))

    assert resultado.fadiga.fator == pytest.approx(0.0)
    assert resultado.fadiga.perclos == pytest.approx(0.0)


# --- O banco se abstém -----------------------------------------------------


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


def test_ponto_incerto_e_gravado_sem_score(session):
    """Critério 2 da ticket 10, no nível da persistência.

    O ponto **existe** — o relatório da ticket 11 precisa saber que aquele
    segundo passou e não foi medido — mas não carrega número nenhum.
    """
    sessao = _sessao_de_teste(session)

    telemetria.registrar_log(session, id_sessao=sessao.id, score=None, alerta="baixa-luz")

    logs = telemetria.buscar_logs(session, id_sessao=sessao.id)
    assert len(logs) == 1
    assert logs[0].score is None
    assert logs[0].alerta == "baixa-luz"
