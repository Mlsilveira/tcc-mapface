"""Testes das recomendações de autorregulação (ticket 11, AC-11-3).

O que estes testes protegem não é o texto — texto muda —, é a **regra de
disparo** e o compromisso de tom: o relatório descreve o que foi observado e
sugere o que fazer, e nunca afirma estado interno do aluno.

`test_nenhum_texto_afirma_estado_interno` é o guardião dessa régua, e é de
propósito que ele varre todas as recomendações possíveis em vez de conferir uma.
"""
import re
from datetime import datetime, timedelta, timezone

import pytest

from app import blocos, criterios, recomendacoes
from app.models import LogEngajamento
from app.relatorio import ResumoDaSessao

T0 = datetime(2026, 9, 21, 9, 0, 0, tzinfo=timezone.utc)


def _blocos(declaracoes) -> list:
    """`(indice, tipo, inicio_s, fim_s)` vira blocos, como em `test_criterios.py`."""
    return [
        blocos.Bloco(
            indice=indice,
            tipo=tipo,
            inicio=T0 + timedelta(seconds=inicio),
            fim=T0 + timedelta(seconds=fim),
        )
        for indice, tipo, inicio, fim in declaracoes
    ]


def _serie(declaracoes) -> list:
    """Um ponto por segundo cobrindo tudo o que foi declarado.

    Score 70 no foco e 0 na pausa: é o que de fato acontece quando o aluno sai
    da frente da webcam e `calcular_iee` devolve zero por `P(t) = 0`.
    """
    pontos = []
    for _, tipo, inicio, fim in declaracoes:
        for segundo in range(inicio, fim):
            pontos.append(
                LogEngajamento(
                    id_sessao=1,
                    score=70.0 if tipo == blocos.TIPO_FOCO else 0.0,
                    fadiga=0.0,
                    alerta=None,
                    horario_registro=T0 + timedelta(seconds=segundo),
                )
            )
    return pontos


def resumo(**campos) -> ResumoDaSessao:
    padrao = dict(
        media=70.0,
        pico=90.0,
        vale=50.0,
        pontos_medidos=100,
        pontos_incertos=0,
        pontos_zerados=0,
        alertas_de_fadiga={},
        motivos_de_incerteza={},
        duracao_total=timedelta(minutes=10),
        duracao_presente=timedelta(minutes=10),
    )
    padrao.update(campos)
    return ResumoDaSessao(**padrao)


def codigos(resultado) -> list:
    return [r.codigo for r in resultado]


class TestFadiga:
    def test_microssono_pede_descanso_e_nao_so_pausa(self):
        """Fechamento prolongado é o sinal mais forte; não pode virar "pausa curta"."""
        sugestoes = recomendacoes.recomendar(
            resumo(alertas_de_fadiga={"olhos-fechados-prolongados": 3})
        )

        assert codigos(sugestoes)[0] == "descanso"

    def test_palpebras_pesadas_pedem_pausa_curta(self):
        sugestoes = recomendacoes.recomendar(resumo(alertas_de_fadiga={"palpebras-pesadas": 12}))

        assert codigos(sugestoes)[0] == "pausa"

    def test_microssono_e_palpebras_juntos_nao_geram_duas_sugestoes_de_parar(self):
        """Dois avisos para a mesma ação é ruído; vale o mais urgente."""
        sugestoes = recomendacoes.recomendar(
            resumo(alertas_de_fadiga={"olhos-fechados-prolongados": 1, "palpebras-pesadas": 9})
        )

        assert codigos(sugestoes).count("descanso") == 1
        assert "pausa" not in codigos(sugestoes)

    def test_motivo_traz_a_evidencia_junto(self):
        """Sugestão sem o dado que a originou é conselho genérico."""
        sugestoes = recomendacoes.recomendar(resumo(alertas_de_fadiga={"bocejos": 4}))

        assert "Bocejos: 4 registros" in sugestoes[0].motivo


class TestEstrategiaEDuracao:
    def test_sessao_longa_sugere_fracionar(self):
        sugestoes = recomendacoes.recomendar(
            resumo(duracao_presente=recomendacoes.DURACAO_SEM_FRACIONAR)
        )

        assert "fracionar" in codigos(sugestoes)

    def test_sessao_curta_nao_sugere_fracionar(self):
        sugestoes = recomendacoes.recomendar(
            resumo(duracao_presente=recomendacoes.DURACAO_SEM_FRACIONAR - timedelta(seconds=1))
        )

        assert "fracionar" not in codigos(sugestoes)

    def test_media_baixa_sem_fadiga_sugere_mudar_a_estrategia(self):
        """Índice baixo sem sinal físico aponta para o material, não para o corpo."""
        sugestoes = recomendacoes.recomendar(resumo(media=recomendacoes.MEDIA_BAIXA - 1))

        assert "estrategia" in codigos(sugestoes)

    def test_media_baixa_com_fadiga_nao_culpa_a_estrategia(self):
        """Havendo sinal de cansaço, ele já explica o índice — trocar o material não."""
        sugestoes = recomendacoes.recomendar(
            resumo(media=10.0, alertas_de_fadiga={"palpebras-pesadas": 20})
        )

        assert "estrategia" not in codigos(sugestoes)

    def test_sem_media_nao_ha_sugestao_sobre_estrategia(self):
        """Sessão inteira incerta não tem média — e `None` não é "média baixa"."""
        sugestoes = recomendacoes.recomendar(
            resumo(media=None, pico=None, vale=None, pontos_medidos=0, pontos_incertos=50)
        )

        assert "estrategia" not in codigos(sugestoes)


class TestIncerteza:
    def test_incerteza_relevante_sugere_ajustar_o_ambiente(self):
        sugestoes = recomendacoes.recomendar(
            resumo(pontos_medidos=60, pontos_incertos=40, motivos_de_incerteza={"baixa-luz": 40})
        )

        ambiente = [r for r in sugestoes if r.codigo == "ambiente"]
        assert ambiente and "Pouca luz no ambiente" in ambiente[0].motivo

    def test_incerteza_pontual_nao_vira_aviso(self):
        """Avisar a cada tropeço de captura treina o aluno a ignorar o aviso."""
        sugestoes = recomendacoes.recomendar(
            resumo(pontos_medidos=99, pontos_incertos=1, motivos_de_incerteza={"oclusao": 1})
        )

        assert "ambiente" not in codigos(sugestoes)

    def test_empate_entre_motivos_e_deterministico(self):
        """O mesmo relatório precisa gerar sempre o mesmo texto."""
        empatados = resumo(
            pontos_medidos=0,
            pontos_incertos=20,
            media=None,
            pico=None,
            vale=None,
            motivos_de_incerteza={"oclusao": 10, "baixa-luz": 10},
        )

        primeiro = recomendacoes.recomendar(empatados)
        segundo = recomendacoes.recomendar(empatados)

        assert [r.motivo for r in primeiro] == [r.motivo for r in segundo]


class TestCasosDegenerados:
    def test_sessao_sem_nenhum_ponto_fala_da_captura_e_nao_do_estudo(self):
        sugestoes = recomendacoes.recomendar(
            resumo(media=None, pico=None, vale=None, pontos_medidos=0, pontos_incertos=0)
        )

        assert codigos(sugestoes) == ["sem-dados"]

    def test_sessao_limpa_ainda_recebe_uma_recomendacao(self):
        """Relatório que volta vazio ensina o aluno a só abri-lo quando algo deu errado."""
        sugestoes = recomendacoes.recomendar(resumo())

        assert codigos(sugestoes) == ["manter"]


class TestVocabulario:
    def test_todo_rotulo_gravavel_tem_nome_legivel(self):
        """Se o backend pode gravar o rótulo, o relatório precisa saber dizê-lo.

        As duas fontes são `DetectorDeFadiga` e `MOTIVOS_DE_INCERTEZA`; este
        teste é o que trava a tradução quando um motivo novo for criado lá.
        """
        from app.analista import INCERTEZA_DESCONHECIDA, MOTIVOS_DE_INCERTEZA

        gravaveis = {
            "palpebras-pesadas",
            "olhos-fechados-prolongados",
            "bocejos",
            INCERTEZA_DESCONHECIDA,
            *MOTIVOS_DE_INCERTEZA,
        }

        assert gravaveis <= set(recomendacoes.NOMES_DE_ALERTA)

    def test_rotulo_desconhecido_aparece_cru_em_vez_de_sumir(self):
        """Alerta sem tradução é bug visível; alerta omitido é bug invisível."""
        assert recomendacoes.nome_do_alerta("motivo-novo") == "motivo-novo"

    @pytest.mark.parametrize(
        "caso",
        [
            {"alertas_de_fadiga": {"olhos-fechados-prolongados": 2}},
            {"alertas_de_fadiga": {"palpebras-pesadas": 5}},
            {"alertas_de_fadiga": {"bocejos": 2}},
            {"duracao_presente": timedelta(hours=2)},
            {"media": 12.0},
            {"pontos_medidos": 10, "pontos_incertos": 90, "motivos_de_incerteza": {"oclusao": 90}},
            {"pontos_medidos": 0, "pontos_incertos": 0},
            {},
        ],
    )
    def test_nenhum_texto_afirma_estado_interno(self, caso):
        """A régua da história 22 do spec, aplicada a cada frase que o aluno lê.

        O sistema mede abertura ocular, orientação da cabeça e abertura da boca.
        "Você estava cansado", "você se distraiu" ou "você estava desmotivado"
        são afirmações sobre estado interno que esses três números não sustentam
        — e o relatório é justamente o lugar onde seria mais fácil escorregar.
        """
        proibidas = (
            "você estava cansado",
            "você está cansado",
            "você se distraiu",
            "você estava distraído",
            "você estava desatento",
            "você estava desmotivado",
            "falta de interesse",
            "você não prestou atenção",
        )

        for sugestao in recomendacoes.recomendar(resumo(**caso)):
            texto = f"{sugestao.titulo} {sugestao.texto} {sugestao.motivo}".lower()
            for frase in proibidas:
                assert frase not in texto


#: A família de julgamento, que a E02-S02 acrescentou à trava de tom.
#:
#: A anterior proíbe afirmar **estado interno** ("você estava cansado"). Esta
#: proíbe emitir **veredito**: nota, percentual, aderência, obediência. As duas
#: pegam coisas diferentes, e a segunda existe porque a primeira não pegava o
#: risco desta story — `"aderência: 62%"` não afirma estado interno nenhum, é
#: aritmética sobre carimbos de tempo, e passaria em silêncio pela lista acima.
#:
#: Em expressão regular, e não em substring, porque "nota" mora dentro de
#: "anotar" e uma trava que dispara em falso é uma trava que alguém desliga.
FAMILIA_DE_JULGAMENTO = (
    r"você não seguiu",
    r"você cumpriu",
    r"aderência de",
    r"\bnota\b",
    r"\bdesempenho\b",
    r"falhou",
    r"%",
)


def _sem_julgamento(frases) -> None:
    for titulo, texto, detalhe in frases:
        inteiro = f"{titulo} {texto} {detalhe}".lower()
        for padrao in FAMILIA_DE_JULGAMENTO:
            assert re.search(padrao, inteiro) is None, f"{padrao!r} em {inteiro!r}"


class TestJulgamentoNasRecomendacoes:
    @pytest.mark.parametrize(
        "caso",
        [
            {"alertas_de_fadiga": {"olhos-fechados-prolongados": 2}},
            {"alertas_de_fadiga": {"palpebras-pesadas": 5}},
            {"duracao_presente": timedelta(hours=2)},
            {"media": 12.0},
            {"pontos_medidos": 0, "pontos_incertos": 0},
            {},
        ],
    )
    def test_nenhuma_recomendacao_emite_veredito(self, caso):
        _sem_julgamento(
            [(s.titulo, s.texto, s.motivo) for s in recomendacoes.recomendar(resumo(**caso))]
        )


class TestJulgamentoNosCriterios:
    """A mesma régua aplicada às frases de `app/criterios.py`.

    Elas moram lá e são testadas **aqui** de propósito: a trava de tom deste
    projeto vale porque é um lugar só onde alguém vai olhar quando escrever a
    próxima frase que o aluno lê sobre si. Espalhá-la por arquivo de origem
    devolveria a cada autor a chance de não saber que ela existe.
    """

    @pytest.mark.parametrize(
        "caso",
        [
            # Ciclo bem executado, ciclo torto, bloco não executado, sem bloco
            # nenhum, e um método sem duração prescrita.
            ("pomodoro", [(1, "foco", 0, 1500), (2, "pausa", 1500, 1800), (3, "foco", 1800, 3300)]),
            ("pomodoro", [(1, "foco", 0, 720), (2, "pausa", 720, 1020), (3, "foco", 1020, 3600)]),
            ("pomodoro", [(1, "foco", 0, 1500), (2, "foco", 1500, 1500)]),
            ("pomodoro", []),
            ("flow", [(1, "foco", 0, 3600), (2, "foco", 3600, 7200)]),
            ("livre", [(1, "foco", 0, 1500)]),
        ],
    )
    def test_nenhum_criterio_emite_veredito(self, caso):
        codigo, declaracoes = caso
        avaliacao = criterios.avaliar(
            codigo, _blocos(declaracoes), _serie(declaracoes), meta_de_blocos=4
        )

        _sem_julgamento([(c.titulo, c.texto, c.detalhe) for c in avaliacao.criterios])

    @pytest.mark.parametrize("motivo", sorted(criterios.FRASES_SEM_MEDIA))
    def test_nenhuma_frase_de_abstencao_emite_veredito(self, motivo):
        """O traço explica a si mesmo sem virar reprovação do bloco."""
        _sem_julgamento([("", criterios.FRASES_SEM_MEDIA[motivo], "")])
