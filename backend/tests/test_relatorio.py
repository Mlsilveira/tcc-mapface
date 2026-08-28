"""Testes do relatório de autopercepção (ticket 11).

`app/relatorio.py` é função pura sobre a série gravada: não consulta banco, não
sabe de HTTP. Isso permite montar aqui sessões improváveis — vazia, interrompida,
inteira sem rosto — sem subir aplicação nenhuma, que é o que torna os casos de
borda baratos de cobrir.

As sessões abaixo são construídas à mão, a 1 Hz, com os indicadores esperados
calculados a partir dos valores plantados.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app import relatorio
from app.models import LogEngajamento, SessaoEstudo

T0 = datetime(2026, 8, 28, 14, 0, 0, tzinfo=timezone.utc)


def sessao(fim_em: float = None) -> SessaoEstudo:
    return SessaoEstudo(
        id=1,
        id_aluno=1,
        inicio=T0,
        fim=(T0 + timedelta(seconds=fim_em)) if fim_em is not None else None,
    )


def log(segundo, score, fadiga=0.0, alerta=None, olhar=0.0):
    return LogEngajamento(
        id_sessao=1,
        horario_registro=T0 + timedelta(seconds=segundo),
        score=score,
        fator_fadiga=fadiga,
        flag_fadiga=fadiga > 0,
        alerta_gerado=alerta,
        direcao_olhar=olhar,
    )


def serie(scores, **kwargs):
    return [log(i, s, **kwargs) for i, s in enumerate(scores)]


# --- Indicadores -----------------------------------------------------------


def test_indicadores_basicos_de_uma_sessao_estavel():
    r = relatorio.montar(sessao(fim_em=60), serie([80.0] * 61))

    assert r.indicadores.n_leituras == 61
    assert r.indicadores.duracao_s == pytest.approx(60.0)
    assert r.indicadores.score_medio == pytest.approx(80.0)
    assert r.indicadores.score_minimo == pytest.approx(80.0)
    assert r.indicadores.score_maximo == pytest.approx(80.0)
    assert r.indicadores.prop_com_rosto == pytest.approx(1.0)
    assert r.indicadores.prop_com_fadiga == pytest.approx(0.0)


def test_tendencia_compara_tercos_e_nao_pontos_isolados():
    """Um ponto é ruído; a pergunta é se o engajamento caiu ao longo da sessão."""
    # 30 leituras a 90, depois 30 a 40, com um pico isolado no fim.
    scores = [90.0] * 30 + [40.0] * 29 + [100.0]
    r = relatorio.montar(sessao(fim_em=59), serie(scores))

    assert r.indicadores.score_inicio == pytest.approx(90.0)
    # O 100 isolado no último ponto não desfaz a queda do terço.
    assert r.indicadores.score_fim < 50.0


def test_desvio_do_olhar_ignora_leituras_sem_rosto():
    """Contar ausência como zero puxaria a média para "olhando de frente"
    justamente nos instantes em que não havia para onde olhar."""
    logs = serie([80.0] * 10, olhar=30.0)
    for l in serie([0.0] * 10):
        l.direcao_olhar = None
        logs.append(l)

    r = relatorio.montar(sessao(fim_em=20), logs)
    assert r.indicadores.desvio_olhar_medio == pytest.approx(30.0)
    assert r.indicadores.prop_com_rosto == pytest.approx(0.5)


def test_serie_sai_em_ordem_cronologica():
    # O gráfico da ticket 9 desenharia uma linha embaralhada se dependesse da
    # ordem de inserção.
    logs = [log(5, 50.0), log(1, 90.0), log(3, 70.0)]
    r = relatorio.montar(sessao(fim_em=10), logs)

    assert [p.score for p in r.serie] == [90.0, 70.0, 50.0]


# --- Alertas ---------------------------------------------------------------


def test_alertas_sao_contados_por_tipo():
    logs = (
        serie([70.0] * 5, fadiga=15.0, alerta="olhos-fechados-prolongados")
        + [log(10 + i, 60.0, 20.0, "palpebras-pesadas,bocejos") for i in range(3)]
    )
    r = relatorio.montar(sessao(fim_em=20), logs)

    assert r.alertas == {
        "olhos-fechados-prolongados": 5,
        "palpebras-pesadas": 3,
        "bocejos": 3,
    }


def test_sessao_sem_alertas_nao_inventa_chaves():
    r = relatorio.montar(sessao(fim_em=60), serie([95.0] * 61))
    assert r.alertas == {}


# --- Relatório parcial (critério 4) ----------------------------------------


def test_sessao_sem_fim_gera_relatorio_parcial():
    """O critério de relatório parcial da ticket 11.

    Não há caminho especial: o relatório não exige `fim`. Se o navegador caiu
    antes do encerramento formal, o aluno não perde o que já foi medido.
    """
    r = relatorio.montar(sessao(fim_em=None), serie([75.0] * 30))

    assert r.parcial is True
    assert r.fim is None
    assert r.indicadores.n_leituras == 30
    assert r.indicadores.score_medio == pytest.approx(75.0)


def test_sessao_encerrada_nao_e_parcial():
    r = relatorio.montar(sessao(fim_em=60), serie([75.0] * 61))
    assert r.parcial is False
    assert r.fim is not None


def test_sessao_sem_nenhuma_leitura_nao_quebra():
    # Webcam negada, ou sessão iniciada e encerrada na hora.
    r = relatorio.montar(sessao(fim_em=5), [])

    assert r.indicadores.n_leituras == 0
    assert r.indicadores.score_medio == 0.0
    assert r.serie == []
    assert "Não houve medição" in r.recomendacoes[0]


# --- Recomendações ---------------------------------------------------------


def test_sessao_estavel_recebe_recomendacao_neutra():
    r = relatorio.montar(sessao(fim_em=60), serie([85.0] * 61))

    assert len(r.recomendacoes) == 1
    assert "estável" in r.recomendacoes[0]


def test_olhos_fechados_prolongados_sugerem_pausa():
    logs = serie([60.0] * 30, fadiga=15.0, alerta="olhos-fechados-prolongados")
    r = relatorio.montar(sessao(fim_em=30), logs)

    assert any("pausa" in frase for frase in r.recomendacoes)


def test_queda_ao_longo_da_sessao_sugere_trocar_de_estrategia():
    scores = [90.0] * 20 + [70.0] * 20 + [50.0] * 20
    r = relatorio.montar(sessao(fim_em=60), serie(scores))

    assert any("Trocar de assunto" in frase for frase in r.recomendacoes)


def test_pouca_presenca_vira_ressalva_e_nao_diagnostico():
    """Indicadores sobre 40% da sessão não podem ser apresentados como se
    descrevessem a sessão inteira."""
    logs = serie([80.0] * 4)
    for i in range(6):
        l = log(10 + i, 0.0)
        l.direcao_olhar = None
        logs.append(l)

    r = relatorio.montar(sessao(fim_em=20), logs)
    assert any("40%" in frase for frase in r.recomendacoes)


def test_recomendacoes_nao_afirmam_estado_mental():
    """O sistema mede proxies comportamentais visuais, e o texto não pode
    prometer mais que isso — é restrição de produto, não de implementação."""
    logs = serie([40.0] * 30, fadiga=25.0, alerta="palpebras-pesadas,bocejos", olhar=35.0)
    r = relatorio.montar(sessao(fim_em=30), logs)

    proibidas = ("desatento", "desinteressado", "preguiç", "cansado você está", "sonolento")
    texto = " ".join(r.recomendacoes).lower()
    for palavra in proibidas:
        assert palavra not in texto, f"o relatório afirmou estado mental: {palavra!r}"
