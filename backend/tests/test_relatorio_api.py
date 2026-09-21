"""Testes do relatório de autopercepção pela borda HTTP (ticket 11).

Os indicadores em si são testados em `test_relatorio.py`, sobre a função pura.
O que estes testes cobrem é o que só existe na borda: a autorização, o formato
que chega ao navegador e a regra de quando o relatório fica disponível.
"""
from datetime import timedelta

import pytest
from sqlmodel import Session, select

from app import blocos, sessoes, sumarizacao, telemetria
from app.models import (
    ENCERRAMENTO_MANUAL,
    ENCERRAMENTO_POR_INATIVIDADE,
    Aluno,
    BlocoEstudo,
    SessaoEstudo,
)
from app.tempo import agora_utc

PAYLOAD_ALUNO = {"nome": "Ana Souza", "email": "ana@exemplo.com", "senha": "senhaSegura123"}
PAYLOAD_OUTRO_ALUNO = {"nome": "Rui Lima", "email": "rui@exemplo.com", "senha": "senhaSegura456"}


def _registrar_e_logar(client, payload):
    client.post("/auth/registro", json=payload)
    resposta = client.post(
        "/auth/login", json={"email": payload["email"], "senha": payload["senha"]}
    )
    return {"Authorization": f"Bearer {resposta.json()['access_token']}"}


@pytest.fixture(name="cabecalhos")
def cabecalhos_fixture(client):
    return _registrar_e_logar(client, PAYLOAD_ALUNO)


@pytest.fixture(name="cabecalhos_outro_aluno")
def cabecalhos_outro_aluno_fixture(client):
    return _registrar_e_logar(client, PAYLOAD_OUTRO_ALUNO)


@pytest.fixture(name="aluno")
def aluno_fixture(client, cabecalhos, session: Session) -> Aluno:
    return session.exec(select(Aluno).where(Aluno.email == PAYLOAD_ALUNO["email"])).one()


def _serie_de_teste(session: Session, id_sessao: int, pontos, inicio=None):
    """Grava a série como `telemetria.registrar_log` a gravaria.

    `pontos` é uma lista de `(segundo, score, alerta)` — a mesma forma que os
    testes da função pura usam, para que os dois lados sejam comparáveis.
    """
    inicio = inicio or agora_utc()
    for segundo, score, alerta in pontos:
        telemetria.registrar_log(
            session,
            id_sessao=id_sessao,
            score=score,
            fadiga=0.0,
            alerta=alerta,
            agora=inicio + timedelta(seconds=segundo),
        )


class TestRelatorioAoEncerrar:
    def test_encerrar_e_buscar_devolve_a_serie_gravada(self, client, cabecalhos, session):
        """AC-11-1: o relatório existe assim que a sessão é encerrada."""
        id_sessao = client.post("/sessoes", headers=cabecalhos).json()["id"]
        _serie_de_teste(session, id_sessao, [(0, 80.0, None), (1, 60.0, None), (2, 40.0, None)])

        client.post(f"/sessoes/{id_sessao}/encerrar", headers=cabecalhos)
        resposta = client.get(f"/sessoes/{id_sessao}/relatorio", headers=cabecalhos)

        assert resposta.status_code == 200
        corpo = resposta.json()
        assert [ponto["score"] for ponto in corpo["serie"]] == [80.0, 60.0, 40.0]
        # média de 80, 60 e 40 = 60, calculada à mão.
        assert corpo["media"] == pytest.approx(60.0)
        assert corpo["pico"] == pytest.approx(80.0)
        assert corpo["vale"] == pytest.approx(40.0)
        assert corpo["parcial"] is False

    def test_incerteza_atravessa_como_nulo(self, client, cabecalhos, session):
        """O nulo é o que faz a curva quebrar; virar zero desfaria a ticket 10."""
        id_sessao = client.post("/sessoes", headers=cabecalhos).json()["id"]
        _serie_de_teste(
            session, id_sessao, [(0, 70.0, None), (1, None, "baixa-luz"), (2, 90.0, None)]
        )
        client.post(f"/sessoes/{id_sessao}/encerrar", headers=cabecalhos)

        corpo = client.get(f"/sessoes/{id_sessao}/relatorio", headers=cabecalhos).json()

        assert [ponto["score"] for ponto in corpo["serie"]] == [70.0, None, 90.0]
        assert corpo["media"] == pytest.approx(80.0)
        assert corpo["pontos_incertos"] == 1

    def test_traz_os_alertas_com_nome_legivel(self, client, cabecalhos, session):
        id_sessao = client.post("/sessoes", headers=cabecalhos).json()["id"]
        _serie_de_teste(
            session,
            id_sessao,
            [(0, 50.0, "bocejos"), (1, 40.0, "bocejos"), (2, None, "baixa-luz")],
        )
        client.post(f"/sessoes/{id_sessao}/encerrar", headers=cabecalhos)

        corpo = client.get(f"/sessoes/{id_sessao}/relatorio", headers=cabecalhos).json()

        assert corpo["alertas_de_fadiga"] == [
            {"codigo": "bocejos", "nome": "Bocejos", "ocorrencias": 2}
        ]
        assert corpo["motivos_de_incerteza"][0]["nome"] == "Pouca luz no ambiente"

    def test_traz_recomendacoes(self, client, cabecalhos, session):
        """AC-11-3: o relatório não pára no diagnóstico."""
        id_sessao = client.post("/sessoes", headers=cabecalhos).json()["id"]
        _serie_de_teste(session, id_sessao, [(0, 20.0, "olhos-fechados-prolongados")])
        client.post(f"/sessoes/{id_sessao}/encerrar", headers=cabecalhos)

        corpo = client.get(f"/sessoes/{id_sessao}/relatorio", headers=cabecalhos).json()

        assert corpo["recomendacoes"][0]["codigo"] == "descanso"
        assert corpo["recomendacoes"][0]["motivo"]

    def test_sessao_sem_pontos_e_um_estado_e_nao_um_erro(self, client, cabecalhos):
        id_sessao = client.post("/sessoes", headers=cabecalhos).json()["id"]
        client.post(f"/sessoes/{id_sessao}/encerrar", headers=cabecalhos)

        resposta = client.get(f"/sessoes/{id_sessao}/relatorio", headers=cabecalhos)

        assert resposta.status_code == 200
        corpo = resposta.json()
        assert corpo["serie"] == []
        assert corpo["media"] is None
        assert corpo["recomendacoes"][0]["codigo"] == "sem-dados"


class TestDuracaoPresenteNaBorda:
    def test_pausa_declarada_nao_infla_a_duracao(self, client, cabecalhos, session, aluno):
        """AC-11-5, ponta a ponta, com um método de estudo declarado.

        Quarenta minutos de sessão aberta: dez de captura, dezessete de pausa —
        a que o 52/17 prescreve, com a aba em segundo plano e a captura parada —
        e treze de captura de novo. O relatório informa os dois números sem
        confundi-los: 40 min de sessão, 23 de captura.

        A pausa cai **entre** os dois limites, e é essa janela que só existe
        depois de eles terem sido desacoplados: ela é mais longa que o vão
        máximo da série (10 min), então sai da duração presente; e mais curta
        que o limite de ausência do método (17 + 3 = 20 min), então a sessão
        sobrevive a ela. Com um limite só, ou a pausa contava como estudo ou
        custava a sessão — e as duas respostas estavam erradas.
        """
        inicio = agora_utc() - timedelta(minutes=40)
        sessao = SessaoEstudo(
            id_aluno=aluno.id,
            inicio=inicio,
            metodo="52-17",
            pausa_maxima_s=17 * 60,
            ultima_atividade=agora_utc(),
            ultima_presenca=agora_utc(),
        )
        session.add(sessao)
        session.commit()
        session.refresh(sessao)

        captura = [(s, 70.0, None) for s in range(0, 601, 10)]
        captura += [(s, 70.0, None) for s in range(1620, 2401, 10)]
        _serie_de_teste(session, sessao.id, captura, inicio=inicio)
        client.post(f"/sessoes/{sessao.id}/encerrar", headers=cabecalhos)

        corpo = client.get(f"/sessoes/{sessao.id}/relatorio", headers=cabecalhos).json()

        assert corpo["duracao_presente_s"] == pytest.approx(600.0 + 780.0, abs=5.0)
        assert corpo["duracao_total_s"] == pytest.approx(2400.0, abs=5.0)


class TestSessaoInterrompida:
    def test_sessao_derrubada_vira_relatorio_parcial(self, client, cabecalhos, session, aluno):
        """AC-11-4: queda de conexão não custa o relatório da sessão.

        Ninguém clica em "Encerrar" quando o navegador fecha sozinho. Quem
        fecha a sessão é a varredura de inatividade, e o relatório sai — com a
        marca de que o fim foi inferido, não observado.
        """
        inicio = agora_utc() - timedelta(hours=2)
        sessao = SessaoEstudo(
            id_aluno=aluno.id,
            inicio=inicio,
            ultima_atividade=inicio + timedelta(minutes=10),
        )
        session.add(sessao)
        session.commit()
        session.refresh(sessao)
        _serie_de_teste(session, sessao.id, [(0, 65.0, None), (60, 55.0, None)], inicio=inicio)

        resposta = client.get(f"/sessoes/{sessao.id}/relatorio", headers=cabecalhos)

        assert resposta.status_code == 200
        corpo = resposta.json()
        assert corpo["parcial"] is True
        assert corpo["media"] == pytest.approx(60.0)

        session.refresh(sessao)
        assert sessao.encerramento == ENCERRAMENTO_POR_INATIVIDADE

    def test_sessao_encerrada_pelo_aluno_nao_e_parcial(self, client, cabecalhos, session):
        id_sessao = client.post("/sessoes", headers=cabecalhos).json()["id"]
        client.post(f"/sessoes/{id_sessao}/encerrar", headers=cabecalhos)

        sessao = session.get(SessaoEstudo, id_sessao)
        assert sessao.encerramento == ENCERRAMENTO_MANUAL
        assert client.get(f"/sessoes/{id_sessao}/relatorio", headers=cabecalhos).json()[
            "parcial"
        ] is False


class TestAutorizacaoEDisponibilidade:
    def test_sessao_de_outro_aluno_responde_404(self, client, cabecalhos, cabecalhos_outro_aluno):
        """404, não 403: 403 confirmaria que aquela sessão existe."""
        id_sessao = client.post("/sessoes", headers=cabecalhos).json()["id"]
        client.post(f"/sessoes/{id_sessao}/encerrar", headers=cabecalhos)

        resposta = client.get(f"/sessoes/{id_sessao}/relatorio", headers=cabecalhos_outro_aluno)

        assert resposta.status_code == 404

    def test_sessao_inexistente_responde_o_mesmo_que_a_de_outro_aluno(
        self, client, cabecalhos, cabecalhos_outro_aluno
    ):
        """Se as duas divergissem, a diferença viraria um oráculo de existência."""
        id_sessao = client.post("/sessoes", headers=cabecalhos).json()["id"]
        client.post(f"/sessoes/{id_sessao}/encerrar", headers=cabecalhos)

        de_outro = client.get(f"/sessoes/{id_sessao}/relatorio", headers=cabecalhos_outro_aluno)
        inexistente = client.get("/sessoes/9999/relatorio", headers=cabecalhos_outro_aluno)

        assert de_outro.status_code == inexistente.status_code == 404
        assert de_outro.json() == inexistente.json()

    def test_sem_token_responde_401(self, client):
        assert client.get("/sessoes/1/relatorio").status_code == 401

    def test_sessao_em_andamento_nao_entrega_relatorio(self, client, cabecalhos):
        """A decisão da ticket 9, defendida na borda.

        A série existe e os indicadores sairiam. Servi-los enquanto a sessão
        roda devolveria o dashboard ao vivo por uma porta lateral — bastava
        deixar a segunda aba aberta no relatório.
        """
        id_sessao = client.post("/sessoes", headers=cabecalhos).json()["id"]

        resposta = client.get(f"/sessoes/{id_sessao}/relatorio", headers=cabecalhos)

        assert resposta.status_code == 409


class TestFormato:
    def test_datetimes_chegam_com_fuso_explicito(self, client, cabecalhos, session):
        """Sem fuso, o navegador lê o instante como hora local e desloca a curva."""
        id_sessao = client.post("/sessoes", headers=cabecalhos).json()["id"]
        _serie_de_teste(session, id_sessao, [(0, 70.0, None)])
        client.post(f"/sessoes/{id_sessao}/encerrar", headers=cabecalhos)

        corpo = client.get(f"/sessoes/{id_sessao}/relatorio", headers=cabecalhos).json()

        for instante in (corpo["inicio"], corpo["fim"], corpo["serie"][0]["instante"]):
            assert instante.endswith("Z") or "+00:00" in instante


class TestHistorico:
    def test_lista_apenas_as_sessoes_encerradas_do_proprio_aluno(
        self, client, cabecalhos, cabecalhos_outro_aluno, session
    ):
        primeira = client.post("/sessoes", headers=cabecalhos).json()["id"]
        _serie_de_teste(session, primeira, [(0, 70.0, None)])
        client.post(f"/sessoes/{primeira}/encerrar", headers=cabecalhos)

        client.post("/sessoes", headers=cabecalhos_outro_aluno)
        em_andamento = client.post("/sessoes", headers=cabecalhos).json()["id"]

        corpo = client.get("/sessoes/historico", headers=cabecalhos).json()

        assert [linha["id"] for linha in corpo] == [primeira]
        assert em_andamento not in [linha["id"] for linha in corpo]

    def test_ordena_da_mais_recente_para_a_mais_antiga(self, client, cabecalhos, session, aluno):
        agora = agora_utc()
        ids = []
        for minutos in (30, 10, 20):
            sessao = SessaoEstudo(
                id_aluno=aluno.id,
                inicio=agora - timedelta(minutes=minutos),
                fim=agora - timedelta(minutes=minutos - 5),
                ultima_atividade=agora - timedelta(minutes=minutos - 5),
                encerramento=ENCERRAMENTO_MANUAL,
            )
            session.add(sessao)
            session.commit()
            session.refresh(sessao)
            ids.append((minutos, sessao.id))

        corpo = client.get("/sessoes/historico", headers=cabecalhos).json()

        esperado = [id_sessao for _, id_sessao in sorted(ids, key=lambda par: par[0])]
        assert [linha["id"] for linha in corpo] == esperado

    def test_linha_resume_sem_carregar_a_serie(self, client, cabecalhos, session):
        """A lista inteira não pode virar o download de todo o histórico."""
        id_sessao = client.post("/sessoes", headers=cabecalhos).json()["id"]
        _serie_de_teste(session, id_sessao, [(0, 80.0, "bocejos"), (1, 40.0, None)])
        client.post(f"/sessoes/{id_sessao}/encerrar", headers=cabecalhos)

        linha = client.get("/sessoes/historico", headers=cabecalhos).json()[0]

        assert "serie" not in linha
        assert linha["media"] == pytest.approx(60.0)
        assert linha["alertas"] == 1

    def test_sem_token_responde_401(self, client):
        assert client.get("/sessoes/historico").status_code == 401

    def test_historico_nao_e_confundido_com_id_de_sessao(self, client, cabecalhos):
        """A rota estática precisa vencer a dinâmica; senão "historico" vira id."""
        assert client.get("/sessoes/historico", headers=cabecalhos).status_code == 200


MINUTO = 60


def _sessao_com_contexto(session: Session, aluno, inicio, **contexto) -> SessaoEstudo:
    """Uma sessão encerrada com método, assunto e meta declarados.

    Montada à mão, e não por `POST /sessoes`, porque os blocos precisam de
    carimbos de tempo no passado: uma sessão aberta agora teria todos os blocos
    empilhados no mesmo segundo e a cadência não teria o que comparar.
    """
    sessao = SessaoEstudo(
        id_aluno=aluno.id,
        inicio=inicio,
        ultima_atividade=agora_utc(),
        ultima_presenca=agora_utc(),
        **contexto,
    )
    session.add(sessao)
    session.commit()
    session.refresh(sessao)
    return sessao


def _blocos_de_teste(session: Session, id_sessao: int, declaracoes, inicio):
    """`(indice, tipo, offset_inicio_s, offset_fim_s)` vira linhas de `bloco_estudo`."""
    for indice, tipo, de, ate in declaracoes:
        session.add(
            BlocoEstudo(
                id_sessao=id_sessao,
                indice=indice,
                tipo=tipo,
                inicio=inicio + timedelta(seconds=de),
                fim=inicio + timedelta(seconds=ate),
            )
        )
    session.commit()


#: Um ciclo Pomodoro: foco de 24 min, pausa de 5, foco de 27, pausa de 5.
CICLO_POMODORO = [
    (1, blocos.TIPO_FOCO, 0, 24 * MINUTO),
    (2, blocos.TIPO_PAUSA, 24 * MINUTO, 29 * MINUTO),
    (3, blocos.TIPO_FOCO, 29 * MINUTO, 56 * MINUTO),
    (4, blocos.TIPO_PAUSA, 56 * MINUTO, 61 * MINUTO),
]


def _captura_do_ciclo():
    """Dois minutos de captura no começo de cada bloco de foco, e a pausa inteira.

    Dois minutos porque o bloco precisa de pelo menos um de medida para receber
    média, e mais que isso só deixaria o teste lento — cada ponto custa um
    commit. A pausa entra com score zero, que é o que a webcam vê quando o aluno
    sai da frente dela, e é justamente o que não pode entrar na média do foco.
    """
    pontos = [(s, 80.0, None) for s in range(0, 120)]
    pontos += [(24 * MINUTO + s, 0.0, None) for s in range(0, 120)]
    pontos += [(29 * MINUTO + s, 40.0, None) for s in range(0, 120)]
    return pontos


class TestRelatorioPorBlocos:
    """AC-17-9 e AC-17-10 na borda: a estrutura executada chega ao navegador."""

    def test_traz_os_blocos_em_ordem_de_indice_com_as_duas_duracoes(
        self, client, cabecalhos, session, aluno
    ):
        inicio = agora_utc() - timedelta(minutes=61)
        sessao = _sessao_com_contexto(
            session,
            aluno,
            inicio,
            metodo="pomodoro",
            assunto="Cálculo II",
            meta_de_blocos=4,
            pausa_maxima_s=5 * MINUTO,
        )
        _blocos_de_teste(session, sessao.id, CICLO_POMODORO, inicio)
        _serie_de_teste(session, sessao.id, _captura_do_ciclo(), inicio=inicio)
        client.post(f"/sessoes/{sessao.id}/encerrar", headers=cabecalhos)

        corpo = client.get(f"/sessoes/{sessao.id}/relatorio", headers=cabecalhos).json()

        assert [b["indice"] for b in corpo["blocos"]] == [1, 2, 3, 4]
        assert [b["tipo"] for b in corpo["blocos"]] == ["foco", "pausa", "foco", "pausa"]
        # 24 min declarados, 2 min com captura — a discrepância é informação.
        assert corpo["blocos"][0]["duracao_s"] == pytest.approx(24 * MINUTO)
        assert corpo["blocos"][0]["duracao_com_captura_s"] == pytest.approx(119.0, abs=2.0)
        assert corpo["metodo"] == "pomodoro"
        assert corpo["metodo_nome"] == "Pomodoro"
        assert corpo["assunto"] == "Cálculo II"

    def test_a_pausa_sai_da_media_dos_blocos_de_foco(
        self, client, cabecalhos, session, aluno
    ):
        """A correção da ticket 17, conferida na borda.

        Foco: 120 pontos de 80 e 120 de 40 — média 60, calculada à mão. A pausa
        tem 120 pontos de zero, e eles derrubariam a média da sessão inteira
        para 40 se entrassem na conta do método.
        """
        inicio = agora_utc() - timedelta(minutes=61)
        sessao = _sessao_com_contexto(
            session, aluno, inicio, metodo="pomodoro", pausa_maxima_s=5 * MINUTO
        )
        _blocos_de_teste(session, sessao.id, CICLO_POMODORO, inicio)
        _serie_de_teste(session, sessao.id, _captura_do_ciclo(), inicio=inicio)
        client.post(f"/sessoes/{sessao.id}/encerrar", headers=cabecalhos)

        corpo = client.get(f"/sessoes/{sessao.id}/relatorio", headers=cabecalhos).json()

        assert corpo["media_de_foco"] == pytest.approx(60.0)
        assert corpo["media"] == pytest.approx(40.0)
        # E a cadência chega em contagem: 24 e 27 min estão na faixa de 20 a 30.
        assert corpo["cadencia"]["blocos_na_faixa"] == 2
        assert corpo["cadencia"]["blocos_de_foco"] == 2
        assert corpo["cadencia"]["duracao_alvo_s"] == 25 * MINUTO

    def test_nenhum_campo_do_payload_de_cadencia_e_percentual(
        self, client, cabecalhos, session, aluno
    ):
        """A trava estrutural, conferida no JSON que sai pela rede.

        `"aderência: 62%"` passaria por todo teste de texto deste projeto. O que
        a barra é o contrato: quem quiser o percentual precisa acrescentar campo
        e justificar no PR.
        """
        inicio = agora_utc() - timedelta(minutes=61)
        sessao = _sessao_com_contexto(
            session, aluno, inicio, metodo="pomodoro", pausa_maxima_s=5 * MINUTO
        )
        _blocos_de_teste(session, sessao.id, CICLO_POMODORO, inicio)
        client.post(f"/sessoes/{sessao.id}/encerrar", headers=cabecalhos)

        corpo = client.get(f"/sessoes/{sessao.id}/relatorio", headers=cabecalhos).json()

        assert set(corpo["cadencia"]) == {
            "duracao_alvo_s",
            "duracoes_observadas_s",
            "blocos_na_faixa",
            "blocos_de_foco",
            "meta_de_blocos",
        }
        assert "%" not in " ".join(
            f"{c['titulo']} {c['texto']} {c['detalhe']}" for c in corpo["criterios"]
        )


class TestSessaoSemMetodo:
    """AC-17-11 e o edge case E4: dois estados diferentes, duas respostas."""

    def test_sessao_com_metodo_nulo_nao_ganha_secao_de_metodo_nenhuma(
        self, client, cabecalhos, session
    ):
        """`metodo IS NULL` é "anterior ao recurso" — não há o que descrever."""
        id_sessao = client.post("/sessoes", headers=cabecalhos).json()["id"]
        _serie_de_teste(session, id_sessao, [(0, 70.0, None), (1, 50.0, None)])
        client.post(f"/sessoes/{id_sessao}/encerrar", headers=cabecalhos)

        resposta = client.get(f"/sessoes/{id_sessao}/relatorio", headers=cabecalhos)

        assert resposta.status_code == 200
        corpo = resposta.json()
        assert corpo["metodo"] is None
        assert corpo["metodo_nome"] is None
        assert corpo["blocos"] == []
        assert corpo["criterios"] == []
        assert corpo["cadencia"] is None
        assert corpo["media_de_foco"] is None

    def test_metodo_declarado_sem_bloco_nenhum_nao_e_sessao_sem_metodo(
        self, client, cabecalhos, session, aluno
    ):
        """E4: aqui houve escolha, e ela não pode ser renderizada como ausência.

        Colapsar os dois faria o relatório esconder do aluno que ele abriu a
        sessão com um método e não conduziu nenhuma transição — que é
        exatamente o que ele foi lá saber.
        """
        inicio = agora_utc() - timedelta(minutes=10)
        sessao = _sessao_com_contexto(
            session, aluno, inicio, metodo="livre", pausa_maxima_s=5 * MINUTO
        )
        client.post(f"/sessoes/{sessao.id}/encerrar", headers=cabecalhos)

        corpo = client.get(f"/sessoes/{sessao.id}/relatorio", headers=cabecalhos).json()

        assert corpo["metodo"] == "livre"
        assert corpo["metodo_nome"] == "Sem método"
        assert corpo["blocos"] == []
        assert [c["codigo"] for c in corpo["criterios"]] == ["sem-blocos"]


class TestRelatorioDepoisDaRetencao:
    """E5: passadas 24 h a série é colapsada, e o relatório não muda de valor."""

    def test_os_numeros_da_sessao_e_os_blocos_sobrevivem_ao_colapso(
        self, client, cabecalhos, session, aluno
    ):
        """Se o relatório mudasse de valor no dia seguinte, a ticket 13 foi desfeita.

        Os indicadores da sessão vêm do `resumo_sessao` congelado; os blocos são
        recalculados sobre a série colapsada, e continuam recebendo média porque
        o relatório sabe que cada ponto passou a valer um minuto.
        """
        inicio = agora_utc() - timedelta(days=2)
        sessao = _sessao_com_contexto(
            session, aluno, inicio, metodo="pomodoro", pausa_maxima_s=5 * MINUTO
        )
        sessao.fim = inicio + timedelta(minutes=61)
        sessao.encerramento = ENCERRAMENTO_MANUAL
        session.add(sessao)
        session.commit()

        _blocos_de_teste(session, sessao.id, CICLO_POMODORO, inicio)
        # 40 minutos de captura contínua a 1 Hz custariam 2400 commits; um ponto
        # a cada 10 s descreve a mesma sessão e o colapso os agrupa igual.
        _serie_de_teste(
            session,
            sessao.id,
            [(s, 80.0, None) for s in range(0, 24 * MINUTO, 10)]
            + [(29 * MINUTO + s, 40.0, None) for s in range(0, 27 * MINUTO, 10)],
            inicio=inicio,
        )

        antes = client.get(f"/sessoes/{sessao.id}/relatorio", headers=cabecalhos).json()
        # O histórico é onde a faxina roda (ticket 13).
        client.get("/sessoes/historico", headers=cabecalhos)
        depois = client.get(f"/sessoes/{sessao.id}/relatorio", headers=cabecalhos).json()

        assert len(depois["serie"]) < len(antes["serie"])
        for indicador in ("media", "pico", "vale", "pontos_medidos"):
            assert depois[indicador] == antes[indicador]
        assert [b["indice"] for b in depois["blocos"]] == [1, 2, 3, 4]
        assert depois["blocos"][0]["media"] == pytest.approx(80.0)
        assert depois["blocos"][0]["observacao"] is None
