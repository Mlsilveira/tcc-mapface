"""Testes da duração por presença real (AC-11-5, ticket 11).

O teste que dá nome ao arquivo é `test_aba_aberta_sem_captura_nao_conta`: ele
descreve exatamente o bug que a AC existe para corrigir — vinte minutos de aba
aberta, cinco minutos de captura, e um relatório que dizia vinte.

Como em `test_analista.py`, as durações esperadas são contadas à mão a partir da
definição, nunca lidas da implementação.
"""
from datetime import datetime, timedelta, timezone

from app import presenca
from app.config import settings

T0 = datetime(2026, 9, 21, 9, 0, 0, tzinfo=timezone.utc)


def em(segundos: float) -> datetime:
    return T0 + timedelta(seconds=segundos)


def instantes(inicio: int, fim: int, passo: int = 1):
    """A série como a captura a grava: um ponto por segundo."""
    return [em(s) for s in range(inicio, fim + 1, passo)]


class TestDuracaoPresente:
    def test_aba_aberta_sem_captura_nao_conta(self):
        """O bug da AC-11-5, no menor caso que o reproduz.

        Cinco minutos de captura, e depois quinze de nada — o heartbeat do
        navegador segue batendo, a sessão segue "viva", e nenhum ponto é
        gravado. A duração presente tem que dizer cinco.
        """
        serie = instantes(0, 300)

        presente = presenca.duracao_presente(em(0), em(1200), serie)

        assert presente == timedelta(minutes=5)
        assert presenca.duracao_total(em(0), em(1200)) == timedelta(minutes=20)

    def test_pausa_curta_continua_sendo_tempo_de_estudo(self):
        """Abaixo do limite de inatividade, silêncio é pausa, não ausência.

        Dois blocos de 60 s separados por 120 s sem sinal. O vão é menor que o
        limite, então conta: 60 + 120 + 60 = 240 s.
        """
        serie = instantes(0, 60) + instantes(180, 240)

        assert presenca.duracao_presente(em(0), em(240), serie) == timedelta(seconds=240)

    def test_vao_maior_que_o_limite_sai_inteiro(self):
        """Um silêncio longo não conta nem pela metade.

        O limite aqui é o vão máximo da série — o maior silêncio ainda
        atribuível a perda de captura. Um segundo acima dele já é buraco.
        Sobram os dois blocos de 60 s: 120 s.
        """
        limite = int(settings.vao_maximo_da_serie_minutos * 60)
        volta = 60 + limite + 1
        serie = instantes(0, 60) + instantes(volta, volta + 60)

        assert presenca.duracao_presente(em(0), em(volta + 60), serie) == timedelta(
            seconds=120
        )

    def test_serie_vazia_nao_tem_duracao(self):
        """Sem um único ponto, nada prova que alguém esteve na frente da webcam."""
        assert presenca.duracao_presente(em(0), em(3600), []) == timedelta(0)

    def test_conta_da_abertura_ate_o_primeiro_ponto(self):
        """O tempo entre abrir a sessão e o primeiro ponto é tempo de estudo.

        A captura leva alguns segundos para subir o modelo. Descartar esse
        pedaço faria a duração encolher por um detalhe de inicialização.
        """
        serie = instantes(5, 10)

        assert presenca.duracao_presente(em(0), em(10), serie) == timedelta(seconds=10)

    def test_ordem_da_serie_nao_altera_o_resultado(self):
        """A soma é sobre a linha do tempo, não sobre a ordem de chegada."""
        serie = instantes(0, 60)

        assert presenca.duracao_presente(
            em(0), em(60), reversed(serie)
        ) == presenca.duracao_presente(em(0), em(60), serie)

    def test_sessao_em_andamento_nao_estima_o_fim(self):
        """Sem `fim`, a conta vai só até o último ponto gravado.

        Inventar "até agora" aqui faria a duração crescer sozinha enquanto
        ninguém está sendo medido — que é o mesmo erro, de outro ângulo.
        """
        serie = instantes(0, 60)

        assert presenca.duracao_presente(em(0), None, serie) == timedelta(seconds=60)
        assert presenca.duracao_total(em(0), None) == timedelta(0)

    def test_instantes_sem_fuso_sao_lidos_como_utc(self):
        """O SQLite devolve datetime sem `tzinfo`; comparar com UTC estouraria.

        `como_utc` já resolve isso no resto do sistema, e a duração precisa do
        mesmo cuidado — senão a conta quebra só em produção, só no SQLite.
        """
        ingenuos = [em(s).replace(tzinfo=None) for s in range(0, 61)]

        assert presenca.duracao_presente(
            em(0).replace(tzinfo=None), em(60).replace(tzinfo=None), ingenuos
        ) == timedelta(seconds=60)
