"""Testes da sumarização e da retenção da série (ticket 13).

O que está em jogo aqui não é economia de disco — é não perder, na faxina, as
distinções que as tickets 10 e 11 custaram a construir. Um colapso descuidado
transformaria "não deu para medir" em zero e apagaria a quebra da curva, sem
que nenhum teste das tickets anteriores percebesse.
"""
from datetime import timedelta

import pytest
from sqlmodel import Session, select

from app import relatorio, sumarizacao, telemetria
from app.models import ENCERRAMENTO_MANUAL, LogEngajamento, ResumoSessao, SessaoEstudo
from app.tempo import agora_utc


@pytest.fixture(name="sessao")
def sessao_fixture(session: Session) -> SessaoEstudo:
    # Alinhado ao minuto de propósito: o colapso agrupa por minuto de relógio,
    # e um início em 13:00:25 espalharia "os 60 primeiros segundos" por dois
    # baldes — o que é o comportamento correto, mas torna ilegível um teste que
    # quer falar sobre "o primeiro minuto".
    inicio = (agora_utc() - timedelta(days=3)).replace(second=0, microsecond=0)
    sessao = SessaoEstudo(
        id_aluno=1,
        inicio=inicio,
        fim=inicio + timedelta(minutes=3),
        ultima_atividade=inicio + timedelta(minutes=3),
        encerramento=ENCERRAMENTO_MANUAL,
    )
    session.add(sessao)
    session.commit()
    session.refresh(sessao)
    return sessao


def gravar(session: Session, sessao: SessaoEstudo, pontos):
    """`pontos` é uma lista de `(segundo, score, alerta)` a partir do início."""
    for segundo, score, alerta in pontos:
        telemetria.registrar_log(
            session,
            id_sessao=sessao.id,
            score=score,
            fadiga=0.0,
            alerta=alerta,
            agora=sessao.inicio + timedelta(seconds=segundo),
        )


class TestResumoCongelado:
    def test_grava_os_indicadores_da_serie_completa(self, session, sessao):
        gravar(session, sessao, [(0, 90.0, None), (1, 60.0, None), (2, 30.0, "bocejos")])

        registro = sumarizacao.registrar_resumo(session, sessao)

        # média de 90, 60 e 30 = 60, calculada à mão.
        assert registro.media == pytest.approx(60.0)
        assert registro.pico == pytest.approx(90.0)
        assert registro.vale == pytest.approx(30.0)
        assert registro.pontos_medidos == 3
        assert registro.alertas_de_fadiga == {"bocejos": 1}

    def test_e_idempotente(self, session, sessao):
        """O encerramento tem dois caminhos, e nada impede que os dois rodem."""
        gravar(session, sessao, [(0, 90.0, None)])
        primeiro = sumarizacao.registrar_resumo(session, sessao)

        gravar(session, sessao, [(1, 10.0, None)])
        segundo = sumarizacao.registrar_resumo(session, sessao)

        assert segundo.media == primeiro.media == pytest.approx(90.0)
        assert len(session.exec(select(ResumoSessao)).all()) == 1

    def test_sessao_sem_medida_congela_none_e_nao_zero(self, session, sessao):
        gravar(session, sessao, [(0, None, "baixa-luz"), (1, None, "baixa-luz")])

        registro = sumarizacao.registrar_resumo(session, sessao)

        assert registro.media is None
        assert registro.pontos_incertos == 2
        assert registro.motivos_de_incerteza == {"baixa-luz": 2}


class TestRetencao:
    def test_nao_colapsa_antes_da_janela(self, session, sessao):
        """A sessão recém-encerrada é justamente a que o aluno vai abrir."""
        gravar(session, sessao, [(s, 70.0, None) for s in range(0, 120)])
        sessao.fim = agora_utc() - timedelta(hours=1)
        session.add(sessao)
        session.commit()

        assert sumarizacao.aplicar_retencao(session, id_aluno=1) == []
        assert len(telemetria.buscar_logs(session, sessao.id)) == 120

    def test_colapsa_em_medias_por_minuto_depois_da_janela(self, session, sessao):
        """120 pontos em dois minutos viram dois pontos."""
        gravar(session, sessao, [(s, 40.0, None) for s in range(0, 60)])
        gravar(session, sessao, [(s, 80.0, None) for s in range(60, 120)])

        assert sumarizacao.aplicar_retencao(session, id_aluno=1) == [sessao.id]

        serie = telemetria.buscar_logs(session, sessao.id)
        assert [ponto.score for ponto in serie] == [pytest.approx(40.0), pytest.approx(80.0)]

    def test_minuto_misto_usa_so_as_medidas(self, session, sessao):
        """Incerto não entra como zero — é o score enganoso que a ticket 10 recusa.

        Média de 60 e 80, com dois pontos incertos ignorados, é 70.
        """
        gravar(
            session,
            sessao,
            [(0, 60.0, None), (1, None, "baixa-luz"), (2, 80.0, None), (3, None, "oclusao")],
        )

        sumarizacao.aplicar_retencao(session, id_aluno=1)

        serie = telemetria.buscar_logs(session, sessao.id)
        assert len(serie) == 1
        assert serie[0].score == pytest.approx(70.0)

    def test_minuto_inteiramente_incerto_sobrevive_como_nulo(self, session, sessao):
        """Sem esse ponto, a curva ligaria os dois lados do buraco."""
        gravar(session, sessao, [(0, 70.0, None), (1, 70.0, None)])
        gravar(session, sessao, [(60 + s, None, "baixa-luz") for s in range(0, 10)])
        gravar(session, sessao, [(120, 90.0, None)])

        sumarizacao.aplicar_retencao(session, id_aluno=1)

        serie = telemetria.buscar_logs(session, sessao.id)
        assert [ponto.score for ponto in serie] == [
            pytest.approx(70.0),
            None,
            pytest.approx(90.0),
        ]
        assert serie[1].alerta == "baixa-luz"

    def test_rotulo_de_fadiga_e_de_incerteza_nao_se_misturam(self, session, sessao):
        """Linha com score e motivo de incerteza ninguém sabe interpretar."""
        gravar(
            session,
            sessao,
            [(0, 50.0, "bocejos"), (1, 50.0, "bocejos"), (2, None, "baixa-luz")],
        )

        sumarizacao.aplicar_retencao(session, id_aluno=1)

        serie = telemetria.buscar_logs(session, sessao.id)
        assert serie[0].alerta == "bocejos"

    def test_nao_colapsa_duas_vezes(self, session, sessao):
        gravar(session, sessao, [(s, 40.0, None) for s in range(0, 60)])

        assert sumarizacao.aplicar_retencao(session, id_aluno=1) == [sessao.id]
        assert sumarizacao.aplicar_retencao(session, id_aluno=1) == []
        assert len(telemetria.buscar_logs(session, sessao.id)) == 1

    def test_nao_toca_na_sessao_de_outro_aluno(self, session, sessao):
        gravar(session, sessao, [(s, 40.0, None) for s in range(0, 60)])

        assert sumarizacao.aplicar_retencao(session, id_aluno=2) == []
        assert len(telemetria.buscar_logs(session, sessao.id)) == 60

    def test_nao_toca_em_sessao_em_andamento(self, session, sessao):
        gravar(session, sessao, [(s, 40.0, None) for s in range(0, 60)])
        sessao.fim = None
        session.add(sessao)
        session.commit()

        assert sumarizacao.aplicar_retencao(session, id_aluno=1) == []
        assert len(telemetria.buscar_logs(session, sessao.id)) == 60


class TestIndicadoresSobrevivemAoColapso:
    def test_media_congelada_nao_vira_media_de_medias(self, session, sessao):
        """O motivo de existir de `resumo_sessao`, num caso em que dá diferença.

        Primeiro minuto: 59 pontos de 100 e 1 de 0 — média 98,33. Segundo
        minuto: 1 ponto de 0. A média verdadeira sobre os 61 pontos é
        5900/61 = 96,72. A média das duas médias por minuto seria 49,17.
        """
        gravar(session, sessao, [(s, 100.0, None) for s in range(0, 59)])
        gravar(session, sessao, [(59, 0.0, None), (60, 0.0, None)])

        sumarizacao.aplicar_retencao(session, id_aluno=1)

        congelado = sumarizacao.buscar_resumo(session, sessao.id)
        assert congelado.media == pytest.approx(5900 / 61)

        serie_colapsada = telemetria.buscar_logs(session, sessao.id)
        recalculado = relatorio.resumir(sessao, serie_colapsada)
        assert recalculado.media == pytest.approx(49.166, abs=0.01)

    def test_relatorio_prefere_o_congelado_depois_do_colapso(
        self, client, session, sessao, monkeypatch
    ):
        """A borda HTTP tem que ler o congelado, não recalcular sobre o colapso."""
        from app.routers import sessoes as router_sessoes

        gravar(session, sessao, [(s, 100.0, None) for s in range(0, 59)])
        gravar(session, sessao, [(59, 0.0, None), (60, 0.0, None)])
        sumarizacao.aplicar_retencao(session, id_aluno=1)

        resumo = router_sessoes._resumo_de(session, sessao)

        assert resumo.media == pytest.approx(5900 / 61)
        assert resumo.pontos_medidos == 61


class TestIndices:
    def test_a_coluna_mais_consultada_da_serie_e_indexada(self):
        """Exigência explícita da ticket 13.

        `log_engajamento` é a tabela que cresce — um ponto por segundo, por
        aluno. Sem índice, cada relatório custa uma varredura completa dela.
        """
        indexadas = {
            coluna.name
            for indice in LogEngajamento.__table__.indexes
            for coluna in indice.columns
        }

        assert {"horario_registro", "id_sessao"} <= indexadas
