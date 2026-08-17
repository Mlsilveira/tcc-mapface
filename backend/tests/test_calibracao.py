"""Testes da persistência da calibração de baseline (ticket 7).

A calibração dura 60 segundos e o WebSocket da ticket 6 reconecta sozinho. Um
acumulador que vivesse só na memória da conexão recomeçaria do zero a cada
queda — numa rede ruim, a calibração nunca terminaria. Estes testes fixam o
comportamento que torna isso impossível: o estado atravessa o banco, e é de lá
que o analista é reconstruído a cada payload.

Os testes batem na interface pública de `app.calibracao`, nunca em SQL cru nem
em atributos privados: o schema pode mudar sem reescrever esta suíte.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from sqlmodel import select

from app import calibracao
from app.models import Aluno, Calibracao, SessaoEstudo


#: Instante fixo e com fuso explícito: as asserções de round-trip precisam de um
#: valor que não dependa do relógio de quem roda a suíte.
INICIO = datetime(2026, 8, 17, 12, 30, 5, tzinfo=timezone.utc)


def _sessao_de_teste(session: Session, email: str = "ana@exemplo.com") -> SessaoEstudo:
    aluno = Aluno(nome="Ana Souza", email=email, senha_hash="x")
    session.add(aluno)
    session.commit()
    session.refresh(aluno)

    sessao = SessaoEstudo(id_aluno=aluno.id)
    session.add(sessao)
    session.commit()
    session.refresh(sessao)
    return sessao


def _acumular(session: Session, id_sessao: int, amostras: int, ear: float = 0.29) -> None:
    """Simula `amostras` payloads já somados na janela de calibração."""
    calibracao.salvar_estado(
        session,
        id_sessao,
        calibracao.EstadoCalibracao(
            inicio=INICIO,
            soma_ear=ear * amostras,
            soma_yaw=0.0,
            soma_pitch=0.0,
            amostras=amostras,
        ),
    )


def _quantas_linhas(session: Session, id_sessao: int) -> int:
    """Quantas calibrações existem para a sessão — o invariante é "no máximo 1"."""
    return len(session.exec(select(Calibracao).where(Calibracao.id_sessao == id_sessao)).all())


class TestPrimeiraMensagem:
    def test_sessao_sem_calibracao_nao_tem_baseline_nem_estado(self, session):
        # É a primeira mensagem da sessão: o chamador precisa distinguir isso de
        # "calibração em andamento" para saber que tem que começar uma nova.
        sessao = _sessao_de_teste(session)

        leitura = calibracao.carregar(session, sessao.id)

        assert leitura.baseline is None
        assert leitura.estado is None
        assert leitura.nao_iniciada is True
        assert leitura.em_andamento is False
        assert leitura.concluida is False


class TestAcumulador:
    def test_estado_salvo_volta_identico_da_leitura(self, session):
        # Round-trip fiel: o que entra é o que sai. Um deslize aqui envenena a
        # média da baseline sem levantar erro nenhum.
        sessao = _sessao_de_teste(session)
        estado = calibracao.EstadoCalibracao(
            inicio=INICIO, soma_ear=0.87, soma_yaw=-3.5, soma_pitch=1.25, amostras=3
        )

        calibracao.salvar_estado(session, sessao.id, estado)

        assert calibracao.carregar(session, sessao.id).estado == estado

    def test_inicio_volta_em_utc_e_nao_ingenuo(self, session):
        # O SQLite devolve datetime sem fuso. Sem normalizar, a conta que decide
        # se os 60 segundos passaram estouraria com "can't subtract offset-naive
        # from offset-aware" — ou pior, silenciosamente compararia errado.
        sessao = _sessao_de_teste(session)
        calibracao.salvar_estado(
            session,
            sessao.id,
            calibracao.EstadoCalibracao(
                inicio=INICIO, soma_ear=0.3, soma_yaw=0.0, soma_pitch=0.0, amostras=1
            ),
        )

        lido = calibracao.carregar(session, sessao.id).estado

        assert lido.inicio.tzinfo is not None
        assert lido.inicio == INICIO

    def test_sessao_com_acumulador_esta_em_andamento_e_sem_baseline(self, session):
        sessao = _sessao_de_teste(session)
        calibracao.salvar_estado(
            session,
            sessao.id,
            calibracao.EstadoCalibracao(
                inicio=INICIO, soma_ear=0.3, soma_yaw=0.0, soma_pitch=0.0, amostras=1
            ),
        )

        leitura = calibracao.carregar(session, sessao.id)

        assert leitura.em_andamento is True
        assert leitura.concluida is False
        assert leitura.nao_iniciada is False
        assert leitura.baseline is None

    def test_salvar_duas_vezes_atualiza_a_mesma_linha(self, session):
        # Um payload por segundo durante 60 segundos são 60 chamadas. Se cada
        # uma criasse linha, a leitura viraria loteria e a unicidade por sessão
        # seria uma promessa vazia.
        sessao = _sessao_de_teste(session)
        primeiro = calibracao.EstadoCalibracao(
            inicio=INICIO, soma_ear=0.30, soma_yaw=1.0, soma_pitch=0.5, amostras=1
        )
        segundo = calibracao.EstadoCalibracao(
            inicio=INICIO, soma_ear=0.61, soma_yaw=1.5, soma_pitch=0.9, amostras=2
        )

        calibracao.salvar_estado(session, sessao.id, primeiro)
        calibracao.salvar_estado(session, sessao.id, segundo)

        assert calibracao.carregar(session, sessao.id).estado == segundo
        assert _quantas_linhas(session, sessao.id) == 1

    def test_o_inicio_da_janela_nao_e_reescrito_pela_acumulacao(self, session):
        # O `inicio` é o que define quando os 60 segundos acabam. Se cada payload
        # o empurrasse para frente, a janela nunca fecharia.
        sessao = _sessao_de_teste(session)
        calibracao.salvar_estado(
            session,
            sessao.id,
            calibracao.EstadoCalibracao(
                inicio=INICIO, soma_ear=0.30, soma_yaw=0.0, soma_pitch=0.0, amostras=1
            ),
        )

        calibracao.salvar_estado(
            session,
            sessao.id,
            calibracao.EstadoCalibracao(
                inicio=INICIO, soma_ear=0.61, soma_yaw=0.0, soma_pitch=0.0, amostras=2
            ),
        )

        assert calibracao.carregar(session, sessao.id).estado.inicio == INICIO

    def test_calibracoes_de_sessoes_diferentes_nao_se_misturam(self, session):
        primeira = _sessao_de_teste(session)
        segunda = SessaoEstudo(id_aluno=primeira.id_aluno)
        session.add(segunda)
        session.commit()
        session.refresh(segunda)

        calibracao.salvar_estado(
            session,
            primeira.id,
            calibracao.EstadoCalibracao(
                inicio=INICIO, soma_ear=0.30, soma_yaw=0.0, soma_pitch=0.0, amostras=1
            ),
        )

        assert calibracao.carregar(session, segunda.id).nao_iniciada is True
        assert calibracao.carregar(session, primeira.id).estado.amostras == 1


class TestUmaCalibracaoPorSessao:
    def test_o_schema_recusa_duas_calibracoes_para_a_mesma_sessao(self, session):
        # A regra está no banco, não só no código: em ECS Fargate (ticket 15) há
        # mais de uma instância, e "o código sempre checa antes" não garante nada
        # quando dois processos checam ao mesmo tempo.
        sessao = _sessao_de_teste(session)
        session.add(Calibracao(id_sessao=sessao.id))
        session.commit()

        session.add(Calibracao(id_sessao=sessao.id))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

    def test_payload_que_perdeu_a_corrida_atualiza_em_vez_de_estourar(self, session):
        # A corrida real: dois payloads quase simultâneos da mesma sessão, ambos
        # lendo "ainda não existe" antes de qualquer um commitar. O segundo
        # INSERT bate na unicidade — e tem que virar UPDATE, não erro na cara do
        # aluno. A cegueira é injetada porque é a única forma determinística de
        # reproduzir a janela; o que se afirma abaixo é só comportamento público.
        sessao = _sessao_de_teste(session)
        _acumular(session, sessao.id, amostras=1)

        leituras = []
        original = calibracao._buscar

        def cego_na_primeira(db, id_sessao):
            leituras.append(id_sessao)
            if len(leituras) == 1:
                return None
            return original(db, id_sessao)

        calibracao._buscar = cego_na_primeira
        try:
            vencedor = calibracao.EstadoCalibracao(
                inicio=INICIO, soma_ear=0.61, soma_yaw=1.0, soma_pitch=0.5, amostras=2
            )
            calibracao.salvar_estado(session, sessao.id, vencedor)
        finally:
            calibracao._buscar = original

        assert _quantas_linhas(session, sessao.id) == 1
        assert calibracao.carregar(session, sessao.id).estado == vencedor


class TestDescartar:
    def test_descartar_apaga_o_acumulado_e_a_sessao_volta_a_estaca_zero(self, session):
        # É a recalibração: o aluno se ausentou no meio dos 60 segundos, e o que
        # foi medido até ali mistura rosto presente com rosto ausente. Média de
        # dados assim é pior que média nenhuma.
        sessao = _sessao_de_teste(session)
        calibracao.salvar_estado(
            session,
            sessao.id,
            calibracao.EstadoCalibracao(
                inicio=INICIO, soma_ear=0.90, soma_yaw=2.0, soma_pitch=1.0, amostras=3
            ),
        )

        calibracao.descartar(session, sessao.id)

        assert calibracao.carregar(session, sessao.id).nao_iniciada is True
        assert _quantas_linhas(session, sessao.id) == 0

    def test_apos_descartar_a_janela_recomeca_do_novo_inicio(self, session):
        sessao = _sessao_de_teste(session)
        calibracao.salvar_estado(
            session,
            sessao.id,
            calibracao.EstadoCalibracao(
                inicio=INICIO, soma_ear=0.90, soma_yaw=2.0, soma_pitch=1.0, amostras=3
            ),
        )
        calibracao.descartar(session, sessao.id)

        recomeco = INICIO + timedelta(seconds=40)
        calibracao.salvar_estado(
            session,
            sessao.id,
            calibracao.EstadoCalibracao(
                inicio=recomeco, soma_ear=0.31, soma_yaw=0.0, soma_pitch=0.0, amostras=1
            ),
        )

        estado = calibracao.carregar(session, sessao.id).estado
        assert estado.inicio == recomeco
        assert estado.amostras == 1
        assert estado.soma_ear == pytest.approx(0.31)
        assert _quantas_linhas(session, sessao.id) == 1

    def test_descartar_sessao_sem_calibracao_e_inofensivo(self, session):
        # Chamado a cada ausência de rosto, `descartar` roda muitas vezes sem ter
        # o que descartar. Isso não pode ser um erro.
        sessao = _sessao_de_teste(session)

        assert calibracao.descartar(session, sessao.id) is False

    def test_descartar_avisa_que_havia_algo_a_descartar(self, session):
        sessao = _sessao_de_teste(session)
        calibracao.salvar_estado(
            session,
            sessao.id,
            calibracao.EstadoCalibracao(
                inicio=INICIO, soma_ear=0.30, soma_yaw=0.0, soma_pitch=0.0, amostras=1
            ),
        )

        assert calibracao.descartar(session, sessao.id) is True

    def test_descartar_nao_atinge_outras_sessoes(self, session):
        primeira = _sessao_de_teste(session)
        segunda = SessaoEstudo(id_aluno=primeira.id_aluno)
        session.add(segunda)
        session.commit()
        session.refresh(segunda)
        for id_sessao in (primeira.id, segunda.id):
            calibracao.salvar_estado(
                session,
                id_sessao,
                calibracao.EstadoCalibracao(
                    inicio=INICIO, soma_ear=0.30, soma_yaw=0.0, soma_pitch=0.0, amostras=1
                ),
            )

        calibracao.descartar(session, primeira.id)

        assert calibracao.carregar(session, segunda.id).em_andamento is True


class TestConclusaoDaBaseline:
    def test_baseline_salva_volta_identica_da_leitura(self, session):
        sessao = _sessao_de_teste(session)
        baseline = calibracao.Baseline(
            ear_neutro=0.284, yaw_neutro=-1.75, pitch_neutro=3.5, amostras=57
        )

        calibracao.salvar_baseline(session, sessao.id, baseline)

        assert calibracao.carregar(session, sessao.id).baseline == baseline

    def test_sessao_com_baseline_esta_concluida_e_nao_em_andamento(self, session):
        # O chamador usa isso para decidir entre "continua calibrando" e "calcula
        # o IEE de verdade". Os dois estados não podem ser verdadeiros juntos.
        sessao = _sessao_de_teste(session)
        _acumular(session, sessao.id, amostras=59)

        calibracao.salvar_baseline(
            session,
            sessao.id,
            calibracao.Baseline(
                ear_neutro=0.29, yaw_neutro=0.0, pitch_neutro=0.0, amostras=59
            ),
        )

        leitura = calibracao.carregar(session, sessao.id)
        assert leitura.concluida is True
        assert leitura.em_andamento is False
        assert leitura.nao_iniciada is False

    def test_concluir_nao_duplica_a_linha_da_sessao(self, session):
        sessao = _sessao_de_teste(session)
        _acumular(session, sessao.id, amostras=59)

        calibracao.salvar_baseline(
            session,
            sessao.id,
            calibracao.Baseline(
                ear_neutro=0.29, yaw_neutro=0.0, pitch_neutro=0.0, amostras=59
            ),
        )

        assert _quantas_linhas(session, sessao.id) == 1

    def test_conclusao_preserva_o_acumulador_que_gerou_a_baseline(self, session):
        # As somas ficam ao lado da baseline como a evidência de onde ela saiu: o
        # relatório da ticket 11 precisa poder explicar o score, e "a média de 59
        # amostras" é uma explicação melhor com as 59 amostras à vista.
        sessao = _sessao_de_teste(session)
        _acumular(session, sessao.id, amostras=59)

        calibracao.salvar_baseline(
            session,
            sessao.id,
            calibracao.Baseline(
                ear_neutro=0.29, yaw_neutro=0.0, pitch_neutro=0.0, amostras=59
            ),
        )

        estado = calibracao.carregar(session, sessao.id).estado
        assert estado.inicio == INICIO
        assert estado.amostras == 59
        assert estado.soma_ear == pytest.approx(0.29 * 59)

    def test_baseline_atipica_de_quem_usa_oculos_nao_e_ajustada(self, session):
        # Uma armação pode deprimir o EAR neutro para perto de 0,18. É o valor
        # certo para essa pessoa: se a persistência o "corrigisse" para uma faixa
        # esperada, o aluno começaria a sessão com o score errado de fábrica.
        sessao = _sessao_de_teste(session)
        atipica = calibracao.Baseline(
            ear_neutro=0.178, yaw_neutro=-12.4, pitch_neutro=8.9, amostras=60
        )

        calibracao.salvar_baseline(session, sessao.id, atipica)

        assert calibracao.carregar(session, sessao.id).baseline == atipica

    def test_sessao_recem_concluida_nao_afeta_a_leitura_de_outra(self, session):
        primeira = _sessao_de_teste(session)
        segunda = SessaoEstudo(id_aluno=primeira.id_aluno)
        session.add(segunda)
        session.commit()
        session.refresh(segunda)

        calibracao.salvar_baseline(
            session,
            primeira.id,
            calibracao.Baseline(
                ear_neutro=0.29, yaw_neutro=0.0, pitch_neutro=0.0, amostras=60
            ),
        )

        assert calibracao.carregar(session, segunda.id).nao_iniciada is True


class TestReconexao:
    """O motivo de tudo isto estar no banco, e não na memória da conexão."""

    def test_o_acumulado_sobrevive_a_uma_queda_no_meio_da_janela(self, session):
        # Queda no segundo 30 de 60. O cliente reconecta, o processo do outro
        # lado pode nem ser o mesmo (ECS Fargate, ticket 15), e o analista é
        # reconstruído só a partir do banco. Se isto falhar, numa rede ruim a
        # calibração recomeça para sempre e nunca termina.
        sessao = _sessao_de_teste(session)
        _acumular(session, sessao.id, amostras=30)

        # Reconectou: nada em memória, tudo relido.
        retomado = calibracao.carregar(session, sessao.id).estado
        assert retomado.amostras == 30
        assert retomado.inicio == INICIO

        calibracao.salvar_estado(
            session,
            sessao.id,
            calibracao.EstadoCalibracao(
                inicio=retomado.inicio,
                soma_ear=retomado.soma_ear + 0.29,
                soma_yaw=retomado.soma_yaw,
                soma_pitch=retomado.soma_pitch,
                amostras=retomado.amostras + 1,
            ),
        )

        assert calibracao.carregar(session, sessao.id).estado.amostras == 31

    def test_apos_a_queda_a_baseline_pronta_e_reencontrada(self, session):
        # Reconexão depois dos 60 segundos: não se recalibra nada, a baseline já
        # vale e o IEE é calculado desde o primeiro payload da nova conexão.
        sessao = _sessao_de_teste(session)
        baseline = calibracao.Baseline(
            ear_neutro=0.283, yaw_neutro=-2.1, pitch_neutro=4.4, amostras=58
        )
        _acumular(session, sessao.id, amostras=58)
        calibracao.salvar_baseline(session, sessao.id, baseline)

        leitura = calibracao.carregar(session, sessao.id)

        assert leitura.concluida is True
        assert leitura.baseline == baseline


class TestCalibracaoConcluidaEFinal:
    def test_acumular_sobre_calibracao_concluida_e_recusado(self, session):
        # `amostras` é uma coluna só, compartilhada entre o acumulador e a
        # baseline. Deixar um payload atrasado escrever ali depois da conclusão
        # corromperia em silêncio a contagem por trás da baseline — e o relatório
        # da ticket 11 exibiria um número que nunca existiu.
        sessao = _sessao_de_teste(session)
        _acumular(session, sessao.id, amostras=60)
        calibracao.salvar_baseline(
            session,
            sessao.id,
            calibracao.Baseline(
                ear_neutro=0.29, yaw_neutro=0.0, pitch_neutro=0.0, amostras=60
            ),
        )

        with pytest.raises(calibracao.CalibracaoJaConcluida):
            calibracao.salvar_estado(
                session,
                sessao.id,
                calibracao.EstadoCalibracao(
                    inicio=INICIO, soma_ear=0.1, soma_yaw=0.0, soma_pitch=0.0, amostras=1
                ),
            )

        assert calibracao.carregar(session, sessao.id).baseline.amostras == 60

    def test_descartar_reabre_a_sessao_para_uma_nova_calibracao(self, session):
        # A única porta de volta: quem quiser recalibrar uma sessão já calibrada
        # tem que dizer isso em voz alta.
        sessao = _sessao_de_teste(session)
        calibracao.salvar_baseline(
            session,
            sessao.id,
            calibracao.Baseline(
                ear_neutro=0.29, yaw_neutro=0.0, pitch_neutro=0.0, amostras=60
            ),
        )

        calibracao.descartar(session, sessao.id)
        recomeco = INICIO + timedelta(minutes=5)
        calibracao.salvar_estado(
            session,
            sessao.id,
            calibracao.EstadoCalibracao(
                inicio=recomeco, soma_ear=0.30, soma_yaw=0.0, soma_pitch=0.0, amostras=1
            ),
        )

        leitura = calibracao.carregar(session, sessao.id)
        assert leitura.em_andamento is True
        assert leitura.estado.inicio == recomeco
        assert _quantas_linhas(session, sessao.id) == 1
