"""Testes da regra de blocos declarados (`app.blocos`).

O módulo não conhece HTTP nem banco, então estes testes não sobem nenhum dos
dois: é o seam. Tudo que se verifica aqui sai da definição escrita no docstring
do módulo — o intervalo semiaberto, a numeração a partir de 1, a absorção da
declaração repetida —, e não de uma leitura da implementação.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app import blocos


def _instante(hora: int, minuto: int, segundo: int = 0) -> datetime:
    return datetime(2026, 9, 21, hora, minuto, segundo, tzinfo=timezone.utc)


class TestVocabulario:
    def test_os_tipos_sao_so_foco_e_pausa(self):
        """Vocabulário fechado, no molde de `recomendacoes.NOMES_DE_ALERTA`.

        Um terceiro tipo não seria "um tipo novo": seria um trecho da sessão que
        nenhum critério do relatório pergunta, e que por isso sumiria da tela em
        silêncio.
        """
        assert blocos.TIPOS == {"foco", "pausa"}

    def test_as_origens_sao_so_metodo_e_aluno(self):
        assert blocos.ORIGENS == {"metodo", "aluno"}

    @pytest.mark.parametrize("tipo", ["foco", "pausa"])
    def test_aceita_os_tipos_do_vocabulario(self, tipo):
        blocos.validar_declaracao(tipo, blocos.ORIGEM_METODO)

    def test_recusa_tipo_fora_do_vocabulario(self):
        with pytest.raises(blocos.TipoDeBlocoDesconhecido):
            blocos.validar_declaracao("descanso", blocos.ORIGEM_METODO)

    def test_recusa_origem_fora_do_vocabulario(self):
        with pytest.raises(blocos.OrigemDeBlocoDesconhecida):
            blocos.validar_declaracao(blocos.TIPO_FOCO, "servidor")

    def test_o_tipo_e_conferido_antes_da_origem(self):
        """Com os dois errados, o erro reclama do tipo.

        Ordem fixada porque a mensagem vai para a tela do aluno: reclamar do
        campo que ele preenche primeiro é o que faz a correção ser uma só.
        """
        with pytest.raises(blocos.TipoDeBlocoDesconhecido):
            blocos.validar_declaracao("descanso", "servidor")


class TestDeclaracaoRedundante:
    def test_declarar_de_novo_o_que_ja_esta_aberto_e_redundante(self):
        assert blocos.e_redundante(blocos.TIPO_PAUSA, blocos.TIPO_PAUSA) is True

    def test_declarar_o_outro_tipo_e_transicao_de_verdade(self):
        assert blocos.e_redundante(blocos.TIPO_FOCO, blocos.TIPO_PAUSA) is False

    def test_sem_bloco_aberto_nada_e_redundante(self):
        """A primeira declaração da sessão nunca pode ser absorvida.

        É o caso do começo do estudo, e se ele fosse tratado como eco a sessão
        inteira ficaria sem bloco nenhum.
        """
        assert blocos.e_redundante(blocos.TIPO_FOCO, None) is False


class TestNumeracao:
    def test_o_primeiro_bloco_e_o_numero_um(self):
        # Numeração para pessoa ("bloco 1"), não deslocamento em vetor.
        assert blocos.proximo_indice([]) == 1

    def test_segue_a_partir_do_maior_indice_usado(self):
        assert blocos.proximo_indice([1, 2, 3]) == 4

    def test_um_buraco_na_sequencia_nao_faz_dois_blocos_com_o_mesmo_numero(self):
        """Com [1, 3], o próximo é 4 — e não 3, que a contagem daria.

        Dois "bloco 3" na mesma sessão é pior que um buraco: o aluno lê o
        número, e dois trechos diferentes com o mesmo nome no relatório são
        irrecuperáveis para quem olha.
        """
        assert blocos.proximo_indice([1, 3]) == 4


class TestDuracao:
    def test_bloco_fechado_dura_do_inicio_ao_fim(self):
        # 10h00 → 10h25 são 25 minutos, ou 1500 segundos.
        bloco = blocos.Bloco(
            indice=1,
            tipo=blocos.TIPO_FOCO,
            inicio=_instante(10, 0),
            fim=_instante(10, 25),
        )

        assert blocos.duracao(bloco) == timedelta(seconds=1500)

    def test_bloco_aberto_dura_ate_o_instante_pedido(self):
        bloco = blocos.Bloco(indice=1, tipo=blocos.TIPO_FOCO, inicio=_instante(10, 0))

        assert blocos.duracao(bloco, ate=_instante(10, 7)) == timedelta(minutes=7)

    def test_bloco_aberto_sem_referencia_nao_inventa_duracao(self):
        """Sem `fim` e sem `ate` não há duração — e zero é o que se afirma.

        A alternativa seria o módulo puro olhar o relógio do processo, e aí a
        mesma chamada devolveria números diferentes a cada execução.
        """
        bloco = blocos.Bloco(indice=1, tipo=blocos.TIPO_FOCO, inicio=_instante(10, 0))

        assert blocos.duracao(bloco) == timedelta(0)

    def test_bloco_que_termina_antes_de_comecar_dura_zero(self):
        """O caso real: pausa declarada depois da última presença observada.

        A varredura encerra a sessão com `fim = ultima_presenca`, um instante do
        passado. O bloco declarado depois dela foi declarado e não foi
        executado, e zero é exatamente isso — nunca um número negativo.
        """
        bloco = blocos.Bloco(
            indice=2,
            tipo=blocos.TIPO_PAUSA,
            inicio=_instante(10, 30),
            fim=_instante(10, 25),
        )

        assert blocos.duracao(bloco) == timedelta(0)

    def test_instante_sem_fuso_conta_como_utc(self):
        """O SQLite devolve datetime sem `tzinfo`, e a conta não pode quebrar."""
        bloco = blocos.Bloco(
            indice=1,
            tipo=blocos.TIPO_FOCO,
            inicio=datetime(2026, 9, 21, 10, 0),
            fim=_instante(10, 25),
        )

        assert blocos.duracao(bloco) == timedelta(minutes=25)


class TestRecorte:
    def test_o_ponto_da_borda_de_inicio_entra(self):
        bloco = blocos.Bloco(
            indice=1, tipo=blocos.TIPO_FOCO, inicio=_instante(10, 0), fim=_instante(10, 1)
        )
        serie = [_instante(9, 59, 59), _instante(10, 0, 0), _instante(10, 0, 30)]

        assert blocos.recortar(bloco, serie, lambda p: p) == [
            _instante(10, 0, 0),
            _instante(10, 0, 30),
        ]

    def test_o_ponto_da_borda_de_fim_nao_entra(self):
        """Semiaberto: o instante da transição é do bloco que começa.

        Contá-lo dos dois lados faria uma sessão de N blocos reportar N−1
        pontos a mais do que gravou — um erro que cresce com o número de blocos,
        que é justamente o que este recurso existe para aumentar.
        """
        bloco = blocos.Bloco(
            indice=1, tipo=blocos.TIPO_FOCO, inicio=_instante(10, 0), fim=_instante(10, 1)
        )
        serie = [_instante(10, 0, 59), _instante(10, 1, 0)]

        assert blocos.recortar(bloco, serie, lambda p: p) == [_instante(10, 0, 59)]

    def test_dois_blocos_consecutivos_particionam_a_serie(self):
        """Nenhum ponto some, nenhum é contado duas vezes.

        A série tem cinco pontos; a soma dos recortes tem que ter cinco, e a
        união tem que ser a série.
        """
        primeiro = blocos.Bloco(
            indice=1, tipo=blocos.TIPO_FOCO, inicio=_instante(10, 0), fim=_instante(10, 2)
        )
        segundo = blocos.Bloco(
            indice=2, tipo=blocos.TIPO_PAUSA, inicio=_instante(10, 2), fim=_instante(10, 4)
        )
        serie = [
            _instante(10, 0, 0),
            _instante(10, 1, 0),
            _instante(10, 2, 0),
            _instante(10, 3, 0),
            _instante(10, 3, 59),
        ]

        de_foco = blocos.recortar(primeiro, serie, lambda p: p)
        de_pausa = blocos.recortar(segundo, serie, lambda p: p)

        assert len(de_foco) + len(de_pausa) == len(serie)
        assert de_foco + de_pausa == serie

    def test_bloco_aberto_leva_tudo_que_veio_depois_do_inicio(self):
        bloco = blocos.Bloco(indice=3, tipo=blocos.TIPO_FOCO, inicio=_instante(10, 2))
        serie = [_instante(10, 1), _instante(10, 2), _instante(10, 9)]

        assert blocos.recortar(bloco, serie, lambda p: p) == [
            _instante(10, 2),
            _instante(10, 9),
        ]

    def test_o_instante_sai_da_funcao_recebida_e_nao_de_um_atributo(self):
        """É `instante_de` que mantém o módulo sem conhecer `LogEngajamento`.

        Aqui a série é de tuplas; no relatório será de linhas do SQLModel. O
        módulo não precisa saber a diferença, e é isso que o teste fixa.
        """
        bloco = blocos.Bloco(
            indice=1, tipo=blocos.TIPO_FOCO, inicio=_instante(10, 0), fim=_instante(10, 1)
        )
        serie = [("a", _instante(10, 0, 10)), ("b", _instante(10, 5))]

        assert blocos.recortar(bloco, serie, lambda par: par[1]) == [("a", _instante(10, 0, 10))]

    def test_serie_vazia_devolve_lista_vazia(self):
        bloco = blocos.Bloco(indice=1, tipo=blocos.TIPO_FOCO, inicio=_instante(10, 0))

        assert blocos.recortar(bloco, [], lambda p: p) == []
