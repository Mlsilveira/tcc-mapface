"""Testes do catálogo de métodos de estudo (`app.metodos`).

Os números esperados aqui são calculados **à mão a partir da definição**, nunca
lidos da implementação — é a regra que `test_analista.py` estabeleceu e o que
torna estes testes capazes de pegar regressão em vez de fotografar o código.
"""
from datetime import timedelta

import pytest

from app import metodos


class TestCatalogo:
    @pytest.mark.parametrize("codigo", sorted(metodos.METODOS))
    def test_todo_metodo_tem_nome_legivel(self, codigo):
        """Mesma trava que `recomendacoes.NOMES_DE_ALERTA` carrega.

        Um código gravável sem nome legível é um método que chega ao relatório
        como string de banco de dados — e o aluno lê "52-17" em vez de "52/17".
        """
        nome = metodos.METODOS[codigo].nome

        assert nome and nome != codigo

    @pytest.mark.parametrize("codigo", sorted(metodos.METODOS))
    def test_o_codigo_bate_com_a_chave(self, codigo):
        """A chave do dicionário é o que vai para o banco; divergir cria fantasma."""
        assert metodos.METODOS[codigo].codigo == codigo

    def test_existe_um_metodo_para_quem_nao_quer_metodo(self):
        """`"livre"` precisa ser escolha gravável, e não ausência de valor.

        Sem ele, "não quero método" e "sessão anterior ao recurso" cairiam os
        dois em `NULL`, e o relatório perderia para sempre a distinção.
        """
        assert metodos.METODO_LIVRE in metodos.METODOS

    def test_nenhum_metodo_declara_pausa_zero(self):
        """Pausa zero faria ir ao banheiro custar a sessão.

        Flow e Timeboxing não prescrevem pausa, e a tentação é gravar 0. A regra
        viraria "fique imóvel na frente da webcam", que não é o que método
        nenhum pede nem o que o sistema quer incentivar.
        """
        assert all(metodo.pausa_s > 0 for metodo in metodos.METODOS.values())


class TestResolucaoNoServidor:
    def test_sem_metodo_nao_ha_pausa_a_resolver(self):
        assert metodos.resolver_pausa_maxima(None) is None

    def test_resolve_a_pausa_curta_do_pomodoro(self):
        """Cinco minutos, e não quinze.

        A pausa longa do Pomodoro encerra a sessão — uma sessão aqui é **um
        ciclo**. Só a pausa curta acontece dentro dela.
        """
        assert metodos.resolver_pausa_maxima("pomodoro") == 5 * 60

    def test_metodo_desconhecido_e_recusado(self):
        """Entrada do aluno se valida contra o catálogo, não se aceita e conserta."""
        with pytest.raises(metodos.MetodoDesconhecido):
            metodos.resolver_pausa_maxima("feynman")


class TestLimiteDeAusencia:
    def test_sem_metodo_vale_a_regra_anterior(self):
        """Sessão aberta antes do recurso não recebe limite inventado."""
        legado = timedelta(minutes=10)

        assert metodos.limite_de_ausencia(None, legado) == legado

    def test_pomodoro_tolera_a_pausa_curta_mais_o_atraso(self):
        """5 min de pausa + 3 de tolerância = 8."""
        assert metodos.limite_de_ausencia(5 * 60, timedelta(minutes=10)) == timedelta(
            minutes=8
        )

    def test_o_52_17_bate_no_teto(self):
        """17 + 3 = 20, que é exatamente o teto. É honesto que bata."""
        assert metodos.limite_de_ausencia(17 * 60, timedelta(minutes=10)) == timedelta(
            minutes=20
        )

    def test_pausa_absurda_nao_passa_do_teto(self):
        """A razão de segurança do teto: método mal parametrizado não cria sessão eterna."""
        assert metodos.limite_de_ausencia(24 * 3600, timedelta(minutes=10)) == (
            metodos.TETO_DE_AUSENCIA
        )

    def test_legado_torto_tambem_passa_pelo_teto(self):
        """Um `.env` com o vão da série em 12 h não pode virar sessão imortal."""
        assert metodos.limite_de_ausencia(None, timedelta(hours=12)) == (
            metodos.TETO_DE_AUSENCIA
        )

    @pytest.mark.parametrize("codigo", sorted(metodos.METODOS))
    def test_nenhum_metodo_do_catalogo_passa_do_teto(self, codigo):
        """A trava que vale por todas: o teto é absoluto, não uma sugestão."""
        pausa = metodos.METODOS[codigo].pausa_s

        limite = metodos.limite_de_ausencia(pausa, timedelta(minutes=10))

        assert limite <= metodos.TETO_DE_AUSENCIA
