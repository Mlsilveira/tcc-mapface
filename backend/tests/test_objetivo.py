"""Objetivo de estudo (RF04) e a recomendação que ele dispara (RF17).

O que se protege aqui: o objetivo é gravado no cadastro e pode ser corrigido
depois; só os três valores do catálogo são aceitos; conta antiga, sem objetivo,
continua funcionando e não recebe recomendação inventada; e a recomendação por
objetivo entra no fim da lista, sem empurrar para baixo o que a sessão mostrou.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app import recomendacoes, telemetria
from tests.apoio import ACEITE_DO_TERMO
from tests.test_recomendacoes import (
    FAMILIA_DE_JULGAMENTO,
    _sem_julgamento,
    codigos,
    resumo,
)

ANA = {"nome": "Ana Souza", "email": "ana@exemplo.com", "senha": "senhaSegura123", **ACEITE_DO_TERMO}
T0 = datetime(2026, 11, 8, 15, 0, 0, tzinfo=timezone.utc)


def _cabecalhos(client, dados):
    resposta = client.post("/auth/login", json={"email": dados["email"], "senha": dados["senha"]})
    return {"Authorization": f"Bearer {resposta.json()['access_token']}"}


class TestCadastro:
    @pytest.mark.parametrize("objetivo", ["prova", "vestibular", "pessoal"])
    def test_objetivo_do_cadastro_volta_no_perfil(self, client, objetivo):
        criado = client.post("/auth/registro", json={**ANA, "objetivo": objetivo})

        assert criado.status_code == 201
        assert criado.json()["objetivo"] == objetivo
        perfil = client.get("/auth/me", headers=_cabecalhos(client, ANA)).json()
        assert perfil["objetivo"] == objetivo

    def test_objetivo_fora_do_catalogo_e_recusado(self, client):
        resposta = client.post("/auth/registro", json={**ANA, "objetivo": "concurso"})

        assert resposta.status_code == 422

    def test_cadastro_sem_objetivo_continua_valido(self, client):
        """Clientes antigos não mandam o campo; a conta nasce sem objetivo."""
        resposta = client.post("/auth/registro", json=ANA)

        assert resposta.status_code == 201
        assert resposta.json()["objetivo"] is None


class TestCorrecao:
    def test_objetivo_pode_ser_alterado_depois(self, client):
        client.post("/auth/registro", json={**ANA, "objetivo": "prova"})
        cabecalhos = _cabecalhos(client, ANA)

        resposta = client.patch("/auth/me", headers=cabecalhos, json={"objetivo": "pessoal"})

        assert resposta.status_code == 200
        assert resposta.json()["objetivo"] == "pessoal"
        assert client.get("/auth/me", headers=cabecalhos).json()["objetivo"] == "pessoal"

    def test_corrigir_o_nome_nao_apaga_o_objetivo(self, client):
        client.post("/auth/registro", json={**ANA, "objetivo": "vestibular"})
        cabecalhos = _cabecalhos(client, ANA)

        client.patch("/auth/me", headers=cabecalhos, json={"nome": "Ana S."})

        assert client.get("/auth/me", headers=cabecalhos).json()["objetivo"] == "vestibular"

    def test_correcao_com_objetivo_invalido_e_recusada(self, client):
        client.post("/auth/registro", json={**ANA, "objetivo": "prova"})

        resposta = client.patch(
            "/auth/me", headers=_cabecalhos(client, ANA), json={"objetivo": "qualquer"}
        )

        assert resposta.status_code == 422


class TestRegra:
    @pytest.mark.parametrize(
        "objetivo, codigo",
        [("prova", "objetivo-prova"), ("vestibular", "objetivo-prova"), ("pessoal", "objetivo-pessoal")],
    )
    def test_cada_objetivo_dispara_a_sua_linha_da_tabela_6(self, objetivo, codigo):
        assert codigos(recomendacoes.recomendar(resumo(), objetivo))[-1] == codigo

    def test_sem_objetivo_nao_ha_recomendacao_de_metodo(self):
        resultado = codigos(recomendacoes.recomendar(resumo(), None))

        assert not any(c.startswith("objetivo-") for c in resultado)

    def test_recomendacao_por_objetivo_vem_depois_das_da_sessao(self):
        """Fadiga é mais urgente que conselho de método."""
        caso = resumo(alertas_de_fadiga={"olhos-fechados-prolongados": 2})

        resultado = codigos(recomendacoes.recomendar(caso, "prova"))

        assert resultado[0] == "descanso"
        assert resultado[-1] == "objetivo-prova"

    def test_sessao_sem_nenhum_ponto_nao_recebe_conselho_de_metodo(self):
        caso = resumo(pontos_medidos=0, pontos_incertos=0)

        assert codigos(recomendacoes.recomendar(caso, "pessoal")) == ["sem-dados"]

    def test_motivo_diz_qual_objetivo_foi_declarado(self):
        vestibular = recomendacoes.recomendar(resumo(), "vestibular")[-1]
        prova = recomendacoes.recomendar(resumo(), "prova")[-1]

        assert "vestibular" in vestibular.motivo
        assert "prova específica" in prova.motivo

    @pytest.mark.parametrize("objetivo", ["prova", "vestibular", "pessoal"])
    def test_texto_por_objetivo_nao_emite_veredito(self, objetivo):
        assert FAMILIA_DE_JULGAMENTO  # a mesma trava das outras recomendações
        _sem_julgamento([(s.titulo, s.texto, s.motivo) for s in recomendacoes.recomendar(resumo(), objetivo)])


class TestNoRelatorio:
    def test_relatorio_traz_a_recomendacao_do_objetivo_do_aluno(self, client, session):
        client.post("/auth/registro", json={**ANA, "objetivo": "pessoal"})
        cabecalhos = _cabecalhos(client, ANA)
        id_sessao = client.post("/sessoes", headers=cabecalhos, json={"metodo": "pomodoro"}).json()["id"]
        for segundo in range(3):
            telemetria.registrar_log(
                session, id_sessao=id_sessao, score=80.0, agora=T0 + timedelta(seconds=segundo)
            )
        client.post(f"/sessoes/{id_sessao}/encerrar", headers=cabecalhos)

        corpo = client.get(f"/sessoes/{id_sessao}/relatorio", headers=cabecalhos).json()

        assert corpo["recomendacoes"][-1]["codigo"] == "objetivo-pessoal"
