"""Testes do histórico de sessões (ticket 12).

A ticket é curta — listar sessões e dar acesso ao relatório de cada uma — mas
tem duas armadilhas que estes testes existem para travar.

A primeira é **privacidade**: o histórico é a tela que mais convida a vazar dado
de um aluno para outro, porque o identificador da sessão está na URL. O spec é
explícito em que os dados de um estudante são visíveis apenas para ele.

A segunda é o **N+1**: montar o relatório completo de cada linha da lista
custaria uma consulta por sessão. `agregar_por_sessao` resolve as três colunas
de resumo numa consulta só, e há um teste que falha se ela deixar de fazer isso.
"""
from datetime import datetime, timedelta, timezone
from itertools import count

import pytest

from app import relatorio, sessoes, telemetria
from app.models import Aluno, LogEngajamento, SessaoEstudo

T0 = datetime(2026, 8, 28, 15, 0, 0, tzinfo=timezone.utc)

_contador = count(1)


def _aluno(session) -> Aluno:
    aluno = Aluno(nome="Ana", email=f"ana{next(_contador)}@exemplo.com", senha_hash="x")
    session.add(aluno)
    session.commit()
    session.refresh(aluno)
    return aluno


def _sessao(session, aluno, inicio_em=0, duracao=None) -> SessaoEstudo:
    sessao = SessaoEstudo(
        id_aluno=aluno.id,
        inicio=T0 + timedelta(minutes=inicio_em),
        fim=(T0 + timedelta(minutes=inicio_em, seconds=duracao)) if duracao else None,
    )
    session.add(sessao)
    session.commit()
    session.refresh(sessao)
    return sessao


def _logs(session, sessao, quantos, score=80.0, peso=1, fadiga=0.0):
    for i in range(quantos):
        session.add(
            LogEngajamento(
                id_sessao=sessao.id,
                horario_registro=T0 + timedelta(seconds=i),
                score=score,
                n_leituras=peso,
                fator_fadiga=fadiga,
                flag_fadiga=fadiga > 0,
                direcao_olhar=0.0,
            )
        )
    session.commit()


# --- Listagem --------------------------------------------------------------


def test_lista_da_mais_recente_para_a_mais_antiga(session):
    """A sessão de hoje é a que o aluno quer ver primeiro."""
    aluno = _aluno(session)
    antiga = _sessao(session, aluno, inicio_em=0, duracao=60)
    recente = _sessao(session, aluno, inicio_em=120, duracao=60)
    meio = _sessao(session, aluno, inicio_em=60, duracao=60)

    assert [s.id for s in sessoes.listar(session, aluno.id)] == [
        recente.id,
        meio.id,
        antiga.id,
    ]


def test_um_aluno_nao_ve_a_sessao_do_outro(session):
    ana = _aluno(session)
    bruno = _aluno(session)
    _sessao(session, ana, duracao=60)
    do_bruno = _sessao(session, bruno, duracao=60)

    assert [s.id for s in sessoes.listar(session, bruno.id)] == [do_bruno.id]


def test_a_sessao_em_andamento_aparece_na_lista(session):
    # Esconder a atual criaria um buraco esquisito: o aluno encerraria a sessão
    # e ela apareceria, como se tivesse nascido naquele instante.
    aluno = _aluno(session)
    aberta = _sessao(session, aluno, duracao=None)

    (item,) = sessoes.listar(session, aluno.id)
    assert item.id == aberta.id
    assert item.fim is None


def test_a_lista_tem_teto(session):
    # Um semestre de estudo diário são centenas de sessões; devolver tudo faria
    # a tela de histórico virar uma resposta que ninguém rola até o fim.
    aluno = _aluno(session)
    for i in range(5):
        _sessao(session, aluno, inicio_em=i, duracao=30)

    assert len(sessoes.listar(session, aluno.id, limite=3)) == 3


def test_aluno_sem_sessao_recebe_lista_vazia(session):
    assert sessoes.listar(session, _aluno(session).id) == []


# --- Agregação sem N+1 -----------------------------------------------------


def test_agrega_varias_sessoes_de_uma_vez(session):
    aluno = _aluno(session)
    primeira = _sessao(session, aluno, duracao=60)
    segunda = _sessao(session, aluno, inicio_em=60, duracao=60)
    _logs(session, primeira, 10, score=90.0)
    _logs(session, segunda, 10, score=40.0)

    agregados = telemetria.agregar_por_sessao(session, [primeira.id, segunda.id])

    assert agregados[primeira.id].score_medio == pytest.approx(90.0)
    assert agregados[segunda.id].score_medio == pytest.approx(40.0)
    assert agregados[primeira.id].n_leituras == 10


def test_a_media_do_historico_e_ponderada_por_n_leituras(session):
    """Uma linha resumida vale um minuto; tratá-la como uma leitura faria o
    histórico mudar de número conforme as sessões fossem sendo sumarizadas."""
    aluno = _aluno(session)
    sessao = _sessao(session, aluno, duracao=120)
    # Um minuto a 100 (resumido em 1 linha de peso 60) e um a 40 (60 linhas).
    _logs(session, sessao, 1, score=100.0, peso=60)
    _logs(session, sessao, 60, score=40.0, peso=1)

    (agregado,) = telemetria.agregar_por_sessao(session, [sessao.id]).values()

    assert agregado.n_leituras == 120
    assert agregado.score_medio == pytest.approx(70.0)


def test_marca_a_sessao_que_teve_fadiga(session):
    aluno = _aluno(session)
    limpa = _sessao(session, aluno, duracao=60)
    cansada = _sessao(session, aluno, inicio_em=60, duracao=60)
    _logs(session, limpa, 5)
    _logs(session, cansada, 4)
    _logs(session, cansada, 1, fadiga=15.0)

    agregados = telemetria.agregar_por_sessao(session, [limpa.id, cansada.id])

    assert agregados[limpa.id].teve_fadiga is False
    assert agregados[cansada.id].teve_fadiga is True


def test_agregar_sem_ids_nao_consulta_o_banco(session):
    assert telemetria.agregar_por_sessao(session, []) == {}


def test_uma_unica_consulta_para_qualquer_numero_de_sessoes(session):
    """O ponto da agregação em lote. Se alguém trocar isto por um laço que
    consulta sessão a sessão, o teste falha em vez de a tela ficar lenta."""
    from sqlalchemy import event

    aluno = _aluno(session)
    ids = []
    for i in range(6):
        s = _sessao(session, aluno, inicio_em=i, duracao=30)
        _logs(session, s, 3)
        ids.append(s.id)

    consultas = []
    motor = session.get_bind()
    ouvir = lambda *args: consultas.append(args[2])  # noqa: E731
    event.listen(motor, "before_cursor_execute", ouvir)
    try:
        telemetria.agregar_por_sessao(session, ids)
    finally:
        event.remove(motor, "before_cursor_execute", ouvir)

    assert len(consultas) == 1, f"esperava 1 consulta, houve {len(consultas)}"


# --- Montagem do histórico (pura) ------------------------------------------


def test_historico_combina_sessao_e_agregado(session):
    aluno = _aluno(session)
    sessao = _sessao(session, aluno, duracao=300)
    _logs(session, sessao, 10, score=75.0)

    itens = relatorio.historico(
        sessoes.listar(session, aluno.id),
        telemetria.agregar_por_sessao(session, [sessao.id]),
    )

    (item,) = itens
    assert item.id_sessao == sessao.id
    assert item.duracao_s == pytest.approx(300.0)
    assert item.score_medio == pytest.approx(75.0)
    assert item.parcial is False


def test_sessao_sem_leitura_alguma_aparece_com_zeros(session):
    """Webcam negada: a sessão existiu, durou, e não mediu nada.

    Sumir com ela da lista esconderia do aluno que a tentativa aconteceu.
    """
    aluno = _aluno(session)
    sessao = _sessao(session, aluno, duracao=45)

    (item,) = relatorio.historico(sessoes.listar(session, aluno.id), {})

    assert item.n_leituras == 0
    assert item.score_medio == 0.0
    assert item.teve_fadiga is False
    # A duração é real: o aluno passou 45 s na tela, e mostrar zero mentiria.
    assert item.duracao_s == pytest.approx(45.0)


def test_sessao_em_andamento_vem_marcada_como_parcial(session):
    aluno = _aluno(session)
    _sessao(session, aluno, duracao=None)

    (item,) = relatorio.historico(sessoes.listar(session, aluno.id), {})

    assert item.parcial is True
    assert item.fim is None
    # Sem `fim` não há duração fechada para mostrar; quem consome usa o
    # cronômetro da tela de sessão para isso.
    assert item.duracao_s == 0.0
