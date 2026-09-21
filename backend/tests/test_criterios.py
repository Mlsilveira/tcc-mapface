"""Testes dos critérios do método de estudo (ticket 17, E02-S02).

Seam do mesmo tipo que `test_relatorio.py` e `test_presenca.py`: função pura de
blocos + série para critérios e frases, sem banco, HTTP nem UI por perto.

Como em `test_analista.py`, **os valores esperados são calculados à mão a partir
da definição**, nunca extraídos da implementação. Um teste que copia o resultado
do código não pega regressão — só congela o que houver lá.

Duas travas moram aqui e valem mais que os casos:

1. **A estrutural** (`TestNadaDeRazaoNormalizada`). Nenhum campo do contrato de
   critério pode ser um quociente entre o declarado e o executado. A razão é que
   `"aderência: 62%"` **passaria** em silêncio pelo teste parametrizado de tom —
   não afirma estado interno nenhum, é aritmética sobre carimbos de tempo. Teste
   de string é conselho; teste de tipo é regra.
2. **A da média** (`TestPausasForaDaConta`). É a correção que a ticket 17 inteira
   existe para fazer, e ela precisa de um teste que a nomeie.
"""
from dataclasses import fields, is_dataclass
from datetime import datetime, timedelta, timezone
from typing import Union, get_args, get_origin, get_type_hints

import pytest

from app import blocos, criterios, metodos, relatorio, schemas
from app.models import LogEngajamento, SessaoEstudo

T0 = datetime(2026, 9, 21, 9, 0, 0, tzinfo=timezone.utc)

MINUTO = 60


def em(segundos: float) -> datetime:
    return T0 + timedelta(seconds=segundos)


def ponto(score, segundo: int, alerta=None) -> LogEngajamento:
    return LogEngajamento(
        id_sessao=1, score=score, fadiga=0.0, alerta=alerta, horario_registro=em(segundo)
    )


def trecho(score, de: int, ate: int, alerta=None, passo: int = 1):
    """Um ponto por segundo no intervalo semiaberto `[de, ate)`.

    Semiaberto para casar com `blocos.recortar`: o ponto da borda pertence ao
    bloco que começa, e gerar a série do outro jeito faria os testes mentirem
    sobre a partição sem que o código estivesse errado.
    """
    return [ponto(score, segundo, alerta) for segundo in range(de, ate, passo)]


def bloco(indice: int, tipo: str, inicio_s: float, fim_s) -> blocos.Bloco:
    return blocos.Bloco(
        indice=indice,
        tipo=tipo,
        inicio=em(inicio_s),
        fim=em(fim_s) if fim_s is not None else None,
    )


def _blocos_de_teste(declaracoes) -> list:
    """`(indice, tipo, offset_inicio_s, offset_fim_s)` vira lista de blocos."""
    return [bloco(indice, tipo, inicio, fim) for indice, tipo, inicio, fim in declaracoes]


#: Um ciclo Pomodoro executado: quatro blocos de foco (24, 27, 31 e 12 min) e
#: três pausas de 5 min entre eles. As durações são as da fixture do contrato de
#: teste, e são propositalmente irregulares — um ciclo perfeito não distinguiria
#: uma contagem certa de uma contagem que sempre devolve o total.
SESSAO_POMODORO = _blocos_de_teste(
    [
        (1, blocos.TIPO_FOCO, 0, 24 * MINUTO),
        (2, blocos.TIPO_PAUSA, 24 * MINUTO, 29 * MINUTO),
        (3, blocos.TIPO_FOCO, 29 * MINUTO, 56 * MINUTO),
        (4, blocos.TIPO_PAUSA, 56 * MINUTO, 61 * MINUTO),
        (5, blocos.TIPO_FOCO, 61 * MINUTO, 92 * MINUTO),
        (6, blocos.TIPO_PAUSA, 92 * MINUTO, 97 * MINUTO),
        (7, blocos.TIPO_FOCO, 97 * MINUTO, 109 * MINUTO),
    ]
)


def codigos(avaliacao) -> list:
    return [criterio.codigo for criterio in avaliacao.criterios]


def por_indice(avaliacao, indice: int) -> criterios.BlocoAvaliado:
    return next(b for b in avaliacao.blocos if b.indice == indice)


class TestEstruturaExecutada:
    """AC-17-9: o relatório mostra a estrutura que o aluno de fato executou."""

    def test_separa_blocos_de_foco_de_pausas_e_soma_as_duracoes(self):
        # Calculado à mão a partir da fixture: foco 24 + 27 + 31 + 12 = 94 min;
        # pausa 5 + 5 + 5 = 15 min.
        avaliacao = criterios.avaliar("pomodoro", SESSAO_POMODORO, [])

        assert avaliacao.blocos_de_foco == 4
        assert avaliacao.blocos_de_pausa == 3
        assert avaliacao.duracao_de_foco_s == 94 * MINUTO
        assert avaliacao.duracao_de_pausa_s == 15 * MINUTO

    def test_cada_bloco_sai_com_a_duracao_que_foi_declarada(self):
        avaliacao = criterios.avaliar("pomodoro", SESSAO_POMODORO, [])

        duracoes = [b.duracao_s for b in avaliacao.blocos]
        assert duracoes == [
            24 * MINUTO,
            5 * MINUTO,
            27 * MINUTO,
            5 * MINUTO,
            31 * MINUTO,
            5 * MINUTO,
            12 * MINUTO,
        ]

    def test_a_media_de_um_bloco_sai_so_dos_pontos_daquele_bloco(self):
        """Dois blocos consecutivos, médias diferentes, conferidas à mão."""
        declarados = _blocos_de_teste(
            [(1, blocos.TIPO_FOCO, 0, 120), (2, blocos.TIPO_FOCO, 120, 240)]
        )
        # Bloco 1: 120 pontos de 80. Bloco 2: 120 pontos de 40.
        serie = trecho(80.0, 0, 120) + trecho(40.0, 120, 240)

        avaliacao = criterios.avaliar("pomodoro", declarados, serie)

        assert por_indice(avaliacao, 1).media == pytest.approx(80.0)
        assert por_indice(avaliacao, 2).media == pytest.approx(40.0)
        assert por_indice(avaliacao, 1).pontos_medidos == 120


class TestPausasForaDaConta:
    """A correção que a ticket 17 inteira existe para fazer.

    Antes disto, uma pausa corretamente executada derrubava a média de quem
    seguiu o método à risca: o aluno sai da frente da webcam, `calcular_iee`
    devolve 0,0 por `P(t) = 0`, e esses zeros entravam na média da sessão. O
    sistema penalizava exatamente o comportamento que o Pomodoro prescreve.
    """

    def test_os_pontos_das_pausas_nao_entram_na_media_dos_blocos_de_foco(self):
        declarados = _blocos_de_teste(
            [
                (1, blocos.TIPO_FOCO, 0, 120),
                (2, blocos.TIPO_PAUSA, 120, 240),
                (3, blocos.TIPO_FOCO, 240, 360),
            ]
        )
        # Foco: 240 pontos de 80. Pausa: 120 pontos de 0 (cadeira vazia).
        # Média só do foco = 80. Média da sessão inteira = (240*80)/360 ≈ 53,3.
        serie = trecho(80.0, 0, 120) + trecho(0.0, 120, 240) + trecho(80.0, 240, 360)

        avaliacao = criterios.avaliar("pomodoro", declarados, serie)

        assert avaliacao.media_de_foco == pytest.approx(80.0)
        assert relatorio.resumir_serie(serie).media == pytest.approx(160.0 / 3)

    def test_a_media_de_foco_e_dos_pontos_crus_e_nao_media_das_medias(self):
        """Um bloco longo pesa mais que um curto, porque tem mais medida dentro.

        Média de médias não é média: com ela, um bloco de 2 minutos valeria o
        mesmo que um de 10 e a conta mudaria de valor só por o aluno ter
        apertado o botão mais vezes. É a mesma recusa que fez a ticket 13
        congelar os indicadores em vez de recalculá-los sobre a série colapsada.
        """
        declarados = _blocos_de_teste(
            [(1, blocos.TIPO_FOCO, 0, 600), (2, blocos.TIPO_FOCO, 600, 720)]
        )
        # 600 pontos de 90 e 120 pontos de 40.
        # Crua: (600*90 + 120*40) / 720 = 58800/720 = 81,666…
        # Média das médias seria (90 + 40) / 2 = 65 — o número errado.
        serie = trecho(90.0, 0, 600) + trecho(40.0, 600, 720)

        avaliacao = criterios.avaliar("pomodoro", declarados, serie)

        assert avaliacao.media_de_foco == pytest.approx(58800 / 720)

    def test_a_frase_das_pausas_conta_quantas_foram_e_quanto_duraram(self):
        avaliacao = criterios.avaliar("pomodoro", SESSAO_POMODORO, [])

        pausas = next(c for c in avaliacao.criterios if c.codigo == "pausas")
        assert "três pausas" in pausas.texto
        assert "15 min" in pausas.texto


class TestCadenciaEmContagem:
    """AC-17-10: o declarado ao lado do executado, em contagem.

    A faixa é `|duração − alvo| ≤ 0,2 × alvo`. Com o alvo do Pomodoro (25 min),
    isso dá **de 20 a 30 minutos**, com os dois limites conferidos à mão:
    0,2 × 25 = 5, então 25 − 5 = 20 e 25 + 5 = 30.
    """

    def test_conta_quantos_blocos_de_foco_ficaram_na_faixa(self):
        # Blocos de foco da fixture: 24, 27, 31 e 12 minutos.
        # 24 ∈ [20, 30] ✓ · 27 ∈ [20, 30] ✓ · 31 ∉ [20, 30] ✗ · 12 ∉ [20, 30] ✗
        # Dois dos quatro. (O contrato de teste dizia três; a conta à mão diz
        # dois, e o teste segue a definição — ver o relatório da story.)
        avaliacao = criterios.avaliar("pomodoro", SESSAO_POMODORO, [])

        assert avaliacao.cadencia.blocos_na_faixa == 2
        assert avaliacao.cadencia.blocos_de_foco == 4
        assert avaliacao.cadencia.duracao_alvo_s == 25 * MINUTO

    def test_o_bloco_de_exatamente_trinta_minutos_esta_dentro_da_faixa(self):
        """O limite é fechado: 30 min é `25 + 0,2 × 25` na bala, e conta."""
        na_borda = _blocos_de_teste(
            [
                (1, blocos.TIPO_FOCO, 0, 30 * MINUTO),
                (2, blocos.TIPO_FOCO, 30 * MINUTO, 60 * MINUTO + 1),
            ]
        )

        avaliacao = criterios.avaliar("pomodoro", na_borda, [])

        # 30 min entra; 30 min e 1 s não.
        assert avaliacao.cadencia.blocos_na_faixa == 1

    def test_a_frase_da_cadencia_diz_a_contagem_e_nunca_um_percentual(self):
        avaliacao = criterios.avaliar("pomodoro", SESSAO_POMODORO, [])

        cadencia = next(c for c in avaliacao.criterios if c.codigo == "cadencia")
        assert "dois dos quatro blocos de foco" in cadencia.texto.lower()
        assert "entre 20 e 30 minutos" in cadencia.texto
        assert "%" not in f"{cadencia.texto} {cadencia.detalhe}"

    def test_acima_de_doze_blocos_a_frase_cai_no_algarismo(self):
        """Feio e honesto é melhor que inventar "quatorze".

        A tabela por extenso para em doze porque `schemas.META_MAXIMA_DE_BLOCOS`
        é doze. Uma sessão com treze blocos de foco só existe se alguém abrir o
        teto — e nesse dia a frase precisa sair inteira, e não faltando o número.
        """
        treze = _blocos_de_teste(
            [
                (i + 1, blocos.TIPO_FOCO, i * 25 * MINUTO, (i + 1) * 25 * MINUTO)
                for i in range(13)
            ]
        )

        avaliacao = criterios.avaliar("pomodoro", treze, [])

        cadencia = next(c for c in avaliacao.criterios if c.codigo == "cadencia")
        assert "13" in cadencia.texto

    def test_a_meta_declarada_e_comparada_em_contagem(self):
        avaliacao = criterios.avaliar(
            "pomodoro", SESSAO_POMODORO, [], meta_de_blocos=4
        )

        meta = next(c for c in avaliacao.criterios if c.codigo == "meta")
        assert "quatro" in meta.texto
        assert avaliacao.cadencia.meta_de_blocos == 4
        assert "%" not in meta.texto


class TestNadaDeRazaoNormalizada:
    """A trava estrutural — vale por todas as outras.

    `"aderência: 62%"` não afirma estado interno nenhum: é aritmética sobre
    carimbos de tempo, e o teste parametrizado de tom a aprovaria em silêncio. A
    régua que ela atravessa é a outra, a que a ticket 12 enunciou — *oferecer a
    linha do tempo é útil; desenhar uma seta para cima em cima dela seria
    afirmar mais do que o dado sustenta*. Por isso a trava é de **tipo**.
    """

    #: Os únicos nomes que o contrato de cadência carrega. Campo novo aqui faz o
    #: teste falhar de propósito: quem quiser o percentual precisa acrescentá-lo
    #: e justificar no PR, que é exatamente a conversa que esta lista força.
    CAMPOS_DA_CADENCIA = {
        "duracao_alvo_s",
        "duracoes_observadas_s",
        "blocos_na_faixa",
        "meta_de_blocos",
        "blocos_de_foco",
    }

    #: Vocabulário de quociente. Um campo com qualquer um destes no nome é uma
    #: razão normalizada tentando entrar pela porta da frente.
    PALAVRAS_DE_RAZAO = (
        "aderencia",
        "aderência",
        "percentual",
        "porcentagem",
        "porcento",
        "taxa",
        "razao",
        "razão",
        "fracao",
        "fração",
        "proporcao",
        "proporção",
        "nota",
        "desempenho",
    )

    #: Os únicos `float` autorizados a atravessar sem sufixo de duração: são
    #: médias do IEE, que já é uma escala de 0 a 100 do próprio aluno e não um
    #: quociente entre declarado e executado.
    FLOATS_QUE_NAO_SAO_DURACAO = {"media", "media_de_foco", "pico", "vale"}

    def _contratos(self):
        """Todo dataclass de `criterios` e o DTO de cadência que vai para a rede.

        Os dois lados, porque a trava não serve de nada se o campo proibido for
        acrescentado só no Pydantic, a um passo do navegador.
        """
        do_modulo = [
            valor
            for valor in vars(criterios).values()
            if is_dataclass(valor) and getattr(valor, "__module__", "") == criterios.__name__
        ]
        return do_modulo, [schemas.CadenciaPublica, schemas.BlocoAvaliadoPublico]

    def test_a_cadencia_carrega_exatamente_os_campos_do_contrato(self):
        nomes = {campo.name for campo in fields(criterios.Cadencia)}

        assert nomes == self.CAMPOS_DA_CADENCIA

    def test_o_dto_de_cadencia_na_rede_carrega_os_mesmos_campos(self):
        assert set(schemas.CadenciaPublica.model_fields) == self.CAMPOS_DA_CADENCIA

    def test_nenhum_campo_tem_nome_de_quociente(self):
        do_modulo, dtos = self._contratos()
        nomes = [campo.name for tipo in do_modulo for campo in fields(tipo)]
        nomes += [nome for dto in dtos for nome in dto.model_fields]

        for nome in nomes:
            for palavra in self.PALAVRAS_DE_RAZAO:
                assert palavra not in nome, f"{nome} parece uma razão normalizada"

    def test_todo_float_do_contrato_e_duracao_ou_media(self):
        """O teste de tipo propriamente dito.

        Um quociente entre observado e declarado é um `float` — e, para caber
        no contrato, ele precisaria ou terminar em `_s` (mentindo que é uma
        duração em segundos) ou entrar na lista fechada de médias acima. As duas
        portas são visíveis no diff, que é tudo que esta trava precisa garantir.
        """
        do_modulo, dtos = self._contratos()

        anotados = []
        for tipo in do_modulo:
            dicas = get_type_hints(tipo)
            anotados += [(campo.name, dicas[campo.name]) for campo in fields(tipo)]
        for dto in dtos:
            anotados += [(nome, campo.annotation) for nome, campo in dto.model_fields.items()]

        for nome, anotacao in anotados:
            if not self._e_float(anotacao):
                continue
            assert (
                nome.endswith("_s") or nome in self.FLOATS_QUE_NAO_SAO_DURACAO
            ), f"{nome} é um float que não é duração nem média"

    @staticmethod
    def _e_float(anotacao) -> bool:
        """`float`, `Optional[float]`, `List[float]` e `Tuple[float, ...]`."""
        if anotacao is float:
            return True
        origem = get_origin(anotacao)
        if origem in (Union, list, tuple):
            return any(
                TestNadaDeRazaoNormalizada._e_float(arg)
                for arg in get_args(anotacao)
                if arg is not type(None) and arg is not Ellipsis
            )
        return False


class TestAbstencaoDeMedia:
    """E1 e E7: os dois jeitos de um bloco não ter média, e por que não são um.

    O projeto já tem a disciplina do `media = None`, mas ela nunca foi
    exercitada com n pequeno. Num bloco de 12 minutos um ponto espúrio é 1 em
    720 e vira o carimbo daquele bloco; numa sessão de 2 h ele sumia em 7.200.
    """

    def test_bloco_com_menos_de_um_minuto_de_medida_nao_recebe_media(self):
        # 59 pontos medidos: um a menos que o mínimo, conferido à mão.
        curto = _blocos_de_teste([(1, blocos.TIPO_FOCO, 0, 59)])

        avaliacao = criterios.avaliar("pomodoro", curto, trecho(80.0, 0, 59))

        avaliado = por_indice(avaliacao, 1)
        assert avaliado.media is None
        assert avaliado.motivo_sem_media == criterios.MOTIVO_CURTO_DEMAIS
        assert avaliado.observacao == "Curto demais para uma média."

    def test_um_ponto_a_mais_ja_sustenta_a_media(self):
        """O limite existe e é exatamente 60 pontos, não "cerca de um minuto"."""
        no_limite = _blocos_de_teste([(1, blocos.TIPO_FOCO, 0, 60)])

        avaliacao = criterios.avaliar("pomodoro", no_limite, trecho(80.0, 0, 60))

        assert por_indice(avaliacao, 1).media == pytest.approx(80.0)

    def test_bloco_inteiramente_incerto_diz_que_nao_deu_para_medir(self):
        """E7: `media = None` por incerteza, não por n pequeno.

        Os dois diagnósticos mandam o aluno mexer em coisas diferentes — a luz
        do quarto, ou a duração do bloco — e uma frase só para os dois desfaria
        na tela a distinção que a ticket 10 comprou no banco.
        """
        longo = _blocos_de_teste([(1, blocos.TIPO_FOCO, 0, 600)])
        serie = trecho(None, 0, 600, alerta="baixa-luz")

        avaliacao = criterios.avaliar("pomodoro", longo, serie)

        avaliado = por_indice(avaliacao, 1)
        assert avaliado.media is None
        assert avaliado.motivo_sem_media == criterios.MOTIVO_SEM_MEDIDA
        assert avaliado.observacao != criterios.FRASES_SEM_MEDIA[criterios.MOTIVO_CURTO_DEMAIS]
        assert avaliado.pontos_incertos == 600

    def test_o_criterio_de_medida_separa_os_dois_diagnosticos(self):
        declarados = _blocos_de_teste(
            [(1, blocos.TIPO_FOCO, 0, 600), (2, blocos.TIPO_FOCO, 600, 630)]
        )
        serie = trecho(None, 0, 600, alerta="oclusao") + trecho(70.0, 600, 630)

        avaliacao = criterios.avaliar("pomodoro", declarados, serie)

        medida = next(c for c in avaliacao.criterios if c.codigo == "medida")
        assert "não deu para medir" in medida.detalhe.lower()
        assert "curto demais" in medida.detalhe.lower()

    def test_bloco_sem_media_nao_reporta_zero_em_lugar_nenhum(self):
        """Traço, nunca zero — a régua que atravessa o relatório inteiro."""
        vazio = _blocos_de_teste([(1, blocos.TIPO_FOCO, 0, 600)])

        avaliacao = criterios.avaliar("pomodoro", vazio, [])

        assert por_indice(avaliacao, 1).media is None
        assert avaliacao.media_de_foco is None


class TestBordasDaSessao:
    """E2, E3, E4 e E8 — os estados em que o critério precisa se abster."""

    def test_sessao_com_um_bloco_so_nao_compara_o_bloco_consigo_mesmo(self):
        """E2: sem dois blocos de foco não há primeiro nem último."""
        unico = _blocos_de_teste([(1, blocos.TIPO_FOCO, 0, 600)])

        avaliacao = criterios.avaliar("pomodoro", unico, trecho(70.0, 0, 600))

        assert "continuidade" not in codigos(avaliacao)

    def test_dois_blocos_de_foco_ja_rendem_a_comparacao(self):
        dois = _blocos_de_teste(
            [(1, blocos.TIPO_FOCO, 0, 600), (2, blocos.TIPO_FOCO, 600, 1200)]
        )
        serie = trecho(70.0, 0, 600) + trecho(50.0, 600, 1200)

        avaliacao = criterios.avaliar("pomodoro", dois, serie)

        continuidade = next(c for c in avaliacao.criterios if c.codigo == "continuidade")
        assert "70" in continuidade.detalhe and "50" in continuidade.detalhe

    def test_bloco_declarado_e_nao_executado_nao_conta_na_faixa(self):
        """E3: `fim == inicio` é duração zero, e duração zero não é um bloco feito.

        O caso é real e já está travado em `test_sessoes.py`: o aluno aperta
        "pausa" e não volta mais, e a varredura fecha o bloco com o `fim` da
        sessão, que é anterior ao início dele.
        """
        declarados = _blocos_de_teste(
            [
                (1, blocos.TIPO_FOCO, 0, 25 * MINUTO),
                (2, blocos.TIPO_FOCO, 25 * MINUTO, 25 * MINUTO),
            ]
        )

        avaliacao = criterios.avaliar("pomodoro", declarados, [])

        assert avaliacao.cadencia.blocos_na_faixa == 1
        assert por_indice(avaliacao, 2).duracao_s == 0
        assert por_indice(avaliacao, 2).motivo_sem_media == criterios.MOTIVO_SEM_CAPTURA

    def test_sessao_sem_metodo_nao_tem_avaliacao_nenhuma(self):
        """E4, primeira metade: `metodo IS NULL` é "anterior ao recurso"."""
        assert criterios.avaliar(None, SESSAO_POMODORO, []) is None

    def test_metodo_declarado_sem_bloco_nenhum_nao_e_sessao_sem_metodo(self):
        """E4, segunda metade: aqui houve escolha, e ela precisa aparecer."""
        avaliacao = criterios.avaliar("pomodoro", [], [])

        assert avaliacao is not None
        assert avaliacao.blocos == ()
        assert codigos(avaliacao) == ["sem-blocos"]
        assert "Pomodoro" in avaliacao.criterios[0].detalhe

    def test_metodo_sem_duracao_prescrita_nao_gera_cadencia(self):
        """E8: Flow não prescreve duração de bloco, então não há o que comparar.

        Inventar um alvo — "vamos supor 25 minutos" — faria o relatório cobrar
        do aluno um plano que ele não declarou. O critério de continuidade, que
        não depende de alvo nenhum, continua valendo.
        """
        dois = _blocos_de_teste(
            [(1, blocos.TIPO_FOCO, 0, 600), (2, blocos.TIPO_FOCO, 600, 1200)]
        )
        serie = trecho(70.0, 0, 600) + trecho(50.0, 600, 1200)

        avaliacao = criterios.avaliar("flow", dois, serie)

        assert metodos.buscar("flow").foco_s is None
        assert avaliacao.cadencia is None
        assert "cadencia" not in codigos(avaliacao)
        assert "continuidade" in codigos(avaliacao)


class TestLacunaDeCaptura:
    """E6: a fadiga que a lacuna fabrica não pode virar o rótulo do bloco.

    `DetectorDeFadiga._intervalos` atribui a duração entre duas amostras ao
    estado da **primeira**. Uma parada de captura de 30 a 59 s logo depois de
    uma piscada computa o intervalo inteiro como pálpebra fechada (acima de 60 s
    a janela descarta). Diluído em 2 h isso some; dentro de um bloco de 12 min
    viraria o nome daquele bloco no relatório.
    """

    def test_a_lacuna_vira_contagem_de_registro_e_nao_rotulo_do_bloco(self):
        de_doze_minutos = _blocos_de_teste([(1, blocos.TIPO_FOCO, 0, 12 * MINUTO)])
        # Captura normal, uma piscada, 45 s de silêncio, e o ponto que volta
        # trazendo o intervalo inteiro rotulado como pálpebra fechada.
        serie = trecho(75.0, 0, 300)
        serie += [ponto(20.0, 345, alerta="olhos-fechados-prolongados")]
        serie += trecho(75.0, 346, 12 * MINUTO)

        avaliacao = criterios.avaliar("pomodoro", de_doze_minutos, serie)
        avaliado = por_indice(avaliacao, 1)

        # O alerta aparece pelo que é: **um** registro, entre 720 pontos.
        assert avaliado.alertas_de_fadiga == {"olhos-fechados-prolongados": 1}
        # E não existe campo de rótulo dominante que pudesse virar o nome do
        # bloco — a ausência é a trava, e é ela que este teste congela.
        nomes = {campo.name for campo in fields(criterios.BlocoAvaliado)}
        assert not {"alerta", "alerta_dominante", "rotulo", "classificacao"} & nomes

    def test_a_lacuna_nao_puxa_a_media_do_bloco_para_baixo(self):
        """Um ponto em 720 continua sendo um ponto em 720.

        Calculado à mão: 719 pontos de 75 e um de 20 dão
        (719 × 75 + 20) / 720 = 53 945 / 720 ≈ 74,92.
        """
        de_doze_minutos = _blocos_de_teste([(1, blocos.TIPO_FOCO, 0, 12 * MINUTO)])
        serie = trecho(75.0, 0, 345)
        serie += [ponto(20.0, 345, alerta="olhos-fechados-prolongados")]
        serie += trecho(75.0, 346, 12 * MINUTO)

        avaliacao = criterios.avaliar("pomodoro", de_doze_minutos, serie)

        assert por_indice(avaliacao, 1).media == pytest.approx(53945 / 720)


class TestSerieColapsada:
    """E5: passadas 24 h a série vira médias por minuto e o relatório não muda de assunto."""

    def test_bloco_de_serie_colapsada_continua_recebendo_media(self):
        """Sem a resolução, um bloco de meia hora diria "curto demais".

        A frase seria falsa e teria sido produzida por uma faxina de banco —
        exatamente a espécie de defeito que a ticket 13 foi construída para
        impedir.
        """
        de_trinta_minutos = _blocos_de_teste([(1, blocos.TIPO_FOCO, 0, 30 * MINUTO)])
        # Um ponto por minuto, como `sumarizacao._medias_por_minuto` os grava.
        colapsada = trecho(80.0, 0, 30 * MINUTO, passo=MINUTO)

        assert len(colapsada) == 30

        avaliacao = criterios.avaliar(
            "pomodoro", de_trinta_minutos, colapsada, resolucao_da_serie_s=MINUTO
        )

        assert por_indice(avaliacao, 1).media == pytest.approx(80.0)


class TestDecomposicaoDoResumo:
    """`resumir_serie` é decomposição de `resumir`, e não redesenho.

    Mora aqui, e não em `test_relatorio.py`, porque aquele arquivo é a linha de
    base que a story protege: ele precisa continuar passando **sem nenhuma
    edição**, e a prova disso é mais forte se ninguém encostar nele.
    """

    def test_resumir_serie_e_resumir_concordam_nos_indicadores(self):
        serie = [
            ponto(80.0, 0),
            ponto(0.0, 1),
            ponto(None, 2, alerta="baixa-luz"),
            ponto(40.0, 3, alerta="bocejos"),
        ]
        sessao = SessaoEstudo(id=1, id_aluno=1, inicio=em(0), fim=em(3), ultima_atividade=em(3))

        do_trecho = relatorio.resumir_serie(serie)
        da_sessao = relatorio.resumir(sessao, serie)

        for campo in (
            "media",
            "pico",
            "vale",
            "pontos_medidos",
            "pontos_incertos",
            "pontos_zerados",
            "alertas_de_fadiga",
            "motivos_de_incerteza",
        ):
            assert getattr(do_trecho, campo) == getattr(da_sessao, campo)

    def test_resumir_serie_nao_conhece_duracao_nenhuma(self):
        """As durações são o que **não** cabe num trecho: elas são da sessão."""
        nomes = {campo.name for campo in fields(relatorio.IndicadoresDaSerie)}

        assert not any(nome.startswith("duracao") for nome in nomes)
