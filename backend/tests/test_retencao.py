"""Testes da sumarização e retenção dos logs (ticket 13).

A sumarização **colapsa**: as linhas de uma janela viram uma só, com as médias
dela, e as originais somem. É o que o spec pede ao dizer que os logs granulares
são resumidos em médias depois do fim da sessão — copiar para outra tabela e
manter as granulares não reduziria nada.

O que estes testes protegem, além da aritmética, é a propriedade que faz o
colapso ser seguro: **o relatório tem que dizer a mesma coisa antes e depois**.
Se resumir mudasse os indicadores, o aluno veria sua sessão mudar de nota
sozinha algum tempo depois de encerrá-la.
"""
from datetime import datetime, timedelta, timezone
from itertools import count

import pytest

from app import relatorio, retencao
from app.models import LogEngajamento, SessaoEstudo

T0 = datetime(2026, 8, 28, 15, 0, 0, tzinfo=timezone.utc)


_contador = count(1)


def _sessao(session, encerrada=True, minutos=5):
    from app.models import Aluno

    # Cada sessão ganha o próprio aluno, e o e-mail é único por construção: um
    # teste que cria duas sessões esbarraria na constraint com um sufixo fixo.
    aluno = Aluno(nome="Ana", email=f"ana{next(_contador)}@exemplo.com", senha_hash="x")
    session.add(aluno)
    session.commit()
    session.refresh(aluno)

    sessao = SessaoEstudo(
        id_aluno=aluno.id,
        inicio=T0,
        fim=(T0 + timedelta(minutes=minutos)) if encerrada else None,
    )
    session.add(sessao)
    session.commit()
    session.refresh(sessao)
    return sessao


def _plantar(session, sessao, quantos, score=lambda i: 80.0, **kwargs):
    for i in range(quantos):
        session.add(
            LogEngajamento(
                id_sessao=sessao.id,
                horario_registro=T0 + timedelta(seconds=i),
                score=score(i),
                direcao_olhar=kwargs.get("olhar", 0.0),
                fator_fadiga=kwargs.get("fadiga", 0.0),
                flag_fadiga=kwargs.get("fadiga", 0.0) > 0,
                alerta_gerado=kwargs.get("alerta"),
                ear=kwargs.get("ear", 0.25),
                mar=kwargs.get("mar", 0.01),
            )
        )
    session.commit()


def _logs(session, sessao):
    from app import telemetria

    return telemetria.buscar_logs(session, id_sessao=sessao.id)


# --- Colapso ---------------------------------------------------------------


def test_uma_janela_de_60s_vira_uma_linha(session):
    sessao = _sessao(session)
    _plantar(session, sessao, 60)

    assert retencao.sumarizar_sessao(session, sessao) == 1

    logs = _logs(session, sessao)
    assert len(logs) == 1
    assert logs[0].n_leituras == 60


def test_tres_minutos_viram_tres_linhas(session):
    sessao = _sessao(session)
    _plantar(session, sessao, 180)

    retencao.sumarizar_sessao(session, sessao)

    logs = _logs(session, sessao)
    assert len(logs) == 3
    assert [log.n_leituras for log in logs] == [60, 60, 60]


def test_janela_incompleta_no_fim_nao_e_descartada(session):
    # 90 segundos: um minuto cheio e meio minuto. Descartar a sobra perderia o
    # final da sessão, que é justamente onde o cansaço costuma aparecer.
    sessao = _sessao(session)
    _plantar(session, sessao, 90)

    retencao.sumarizar_sessao(session, sessao)

    logs = _logs(session, sessao)
    assert [log.n_leituras for log in logs] == [60, 30]


def test_o_horario_do_resumo_e_o_inicio_da_janela(session):
    sessao = _sessao(session)
    _plantar(session, sessao, 120)

    retencao.sumarizar_sessao(session, sessao)

    logs = _logs(session, sessao)
    from app.tempo import como_utc

    assert como_utc(logs[0].horario_registro) == T0
    assert como_utc(logs[1].horario_registro) == T0 + timedelta(seconds=60)


# --- Médias ----------------------------------------------------------------


def test_o_score_do_resumo_e_a_media_da_janela(session):
    sessao = _sessao(session)
    # Primeiro minuto a 100, segundo a 40.
    _plantar(session, sessao, 120, score=lambda i: 100.0 if i < 60 else 40.0)

    retencao.sumarizar_sessao(session, sessao)

    logs = _logs(session, sessao)
    assert logs[0].score == pytest.approx(100.0)
    assert logs[1].score == pytest.approx(40.0)


def test_alertas_da_janela_sao_unidos_sem_repetir(session):
    sessao = _sessao(session)
    _plantar(session, sessao, 30, alerta="bocejos")
    for i in range(30, 60):
        session.add(
            LogEngajamento(
                id_sessao=sessao.id,
                horario_registro=T0 + timedelta(seconds=i),
                score=50.0,
                alerta_gerado="bocejos,palpebras-pesadas",
                direcao_olhar=0.0,
            )
        )
    session.commit()

    retencao.sumarizar_sessao(session, sessao)

    (log,) = _logs(session, sessao)
    assert log.alerta_gerado == "bocejos,palpebras-pesadas"


def test_um_instante_de_fadiga_marca_a_janela_inteira(session):
    """Diluir o flag esconderia o episódio.

    A média já diz *o quanto* houve; zerar o flag porque 59 dos 60 segundos
    estavam limpos apagaria do relatório que houve um episódio.
    """
    sessao = _sessao(session)
    _plantar(session, sessao, 59)
    session.add(
        LogEngajamento(
            id_sessao=sessao.id,
            horario_registro=T0 + timedelta(seconds=59),
            score=40.0,
            fator_fadiga=15.0,
            flag_fadiga=True,
            alerta_gerado="olhos-fechados-prolongados",
            direcao_olhar=0.0,
        )
    )
    session.commit()

    retencao.sumarizar_sessao(session, sessao)

    (log,) = _logs(session, sessao)
    assert log.flag_fadiga is True
    assert log.fator_fadiga == pytest.approx(15.0 / 60)


def test_janela_toda_sem_rosto_mantem_direcao_nula(session):
    # `None` é "não observado". Virar zero na média diria "olhando de frente".
    sessao = _sessao(session)
    for i in range(60):
        session.add(
            LogEngajamento(
                id_sessao=sessao.id,
                horario_registro=T0 + timedelta(seconds=i),
                score=0.0,
                direcao_olhar=None,
                ear=None,
                mar=None,
            )
        )
    session.commit()

    retencao.sumarizar_sessao(session, sessao)

    (log,) = _logs(session, sessao)
    assert log.direcao_olhar is None
    assert log.ear is None


# --- Idempotência e escopo -------------------------------------------------


def test_sessao_aberta_nao_e_sumarizada(session):
    """Resumir no meio da medição jogaria fora a resolução que o dashboard ao
    vivo está usando naquele instante."""
    sessao = _sessao(session, encerrada=False)
    _plantar(session, sessao, 120)

    assert retencao.sumarizar_sessao(session, sessao) == 0
    assert len(_logs(session, sessao)) == 120


def test_sumarizar_duas_vezes_nao_muda_nada(session):
    sessao = _sessao(session)
    _plantar(session, sessao, 120)

    retencao.sumarizar_sessao(session, sessao)
    antes = [(log.score, log.n_leituras) for log in _logs(session, sessao)]

    retencao.sumarizar_sessao(session, sessao)
    assert [(log.score, log.n_leituras) for log in _logs(session, sessao)] == antes


def test_sessao_sem_leitura_alguma_e_marcada_como_resumida(session):
    # Senão a varredura a reexaminaria para sempre, sobre nada.
    sessao = _sessao(session)

    retencao.sumarizar_sessao(session, sessao)

    session.refresh(sessao)
    assert sessao.resumida is True


def test_varredura_pega_encerradas_e_ignora_abertas(session):
    aberta = _sessao(session, encerrada=False)
    fechada = _sessao(session, encerrada=True)
    _plantar(session, aberta, 120)
    _plantar(session, fechada, 120)

    resumidas = retencao.sumarizar_encerradas(session)

    assert resumidas == [fechada.id]
    assert len(_logs(session, aberta)) == 120
    assert len(_logs(session, fechada)) == 2


# --- A propriedade que torna o colapso seguro ------------------------------


def test_o_relatorio_diz_a_mesma_coisa_antes_e_depois(session):
    """Se resumir mudasse os indicadores, o aluno veria sua sessão mudar de
    nota sozinha algum tempo depois de encerrá-la."""
    sessao = _sessao(session)
    _plantar(session, sessao, 180, score=lambda i: 90.0 if i < 90 else 50.0)

    antes = relatorio.montar(sessao, _logs(session, sessao))
    retencao.sumarizar_sessao(session, sessao)
    depois = relatorio.montar(sessao, _logs(session, sessao))

    assert depois.indicadores.n_leituras == antes.indicadores.n_leituras == 180
    assert depois.indicadores.score_medio == pytest.approx(antes.indicadores.score_medio)
    assert depois.indicadores.prop_com_rosto == pytest.approx(antes.indicadores.prop_com_rosto)
    assert depois.indicadores.duracao_s == pytest.approx(antes.indicadores.duracao_s, abs=60)


def test_a_serie_do_grafico_encolhe_mas_continua_descrevendo_a_sessao(session):
    sessao = _sessao(session)
    _plantar(session, sessao, 600, score=lambda i: 100.0 if i < 300 else 40.0)

    retencao.sumarizar_sessao(session, sessao)

    serie = relatorio.montar(sessao, _logs(session, sessao)).serie
    assert len(serie) == 10                       # 600 pontos viraram 10
    assert serie[0].score == pytest.approx(100.0)  # a queda continua visível
    assert serie[-1].score == pytest.approx(40.0)
