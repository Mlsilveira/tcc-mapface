"""Testes do canal de telemetria por WebSocket (ticket 6, seam B).

O JWT chega na **primeira mensagem** depois do connect, não na URL: token em
query string vaza para log de servidor, proxy e histórico do navegador, o que
seria incoerente num projeto cujo eixo é privacidade. O navegador tampouco
permite mandar header `Authorization` num WebSocket, então a primeira
mensagem é o único lugar limpo que sobra.
"""
import pytest

from app import sessoes

PAYLOAD_ALUNO = {"nome": "Ana Souza", "email": "ana@exemplo.com", "senha": "senhaSegura123"}


def _registrar_e_logar(client, payload=PAYLOAD_ALUNO):
    client.post("/auth/registro", json=payload)
    resposta = client.post(
        "/auth/login", json={"email": payload["email"], "senha": payload["senha"]}
    )
    return resposta.json()["access_token"]


@pytest.fixture(name="token")
def token_fixture(client):
    return _registrar_e_logar(client)


@pytest.fixture(name="com_sessao_ativa")
def com_sessao_ativa_fixture(client, token):
    client.post("/sessoes", headers={"Authorization": f"Bearer {token}"})
    return token


def test_autentica_pela_primeira_mensagem(client, com_sessao_ativa):
    with client.websocket_connect("/telemetria") as ws:
        ws.send_json({"token": com_sessao_ativa})
        assert ws.receive_json() == {"tipo": "autenticado"}


def test_recusa_token_invalido(client, com_sessao_ativa):
    with client.websocket_connect("/telemetria") as ws:
        ws.send_json({"token": "token-que-nao-vale-nada"})
        resposta = ws.receive_json()

    assert resposta["tipo"] == "erro"
    assert resposta["motivo"] == "nao-autenticado"


def _id_da_sessao_ativa(client, token):
    return client.get("/sessoes/ativa", headers={"Authorization": f"Bearer {token}"}).json()["id"]


def test_payload_de_metricas_devolve_score_e_persiste_log(client, com_sessao_ativa, session):
    from app import telemetria

    id_sessao = _id_da_sessao_ativa(client, com_sessao_ativa)

    with client.websocket_connect("/telemetria") as ws:
        ws.send_json({"token": com_sessao_ativa})
        ws.receive_json()

        # Olhos plenamente abertos e cabeça de frente: score máximo pela fórmula
        # provisória acordada.
        ws.send_json({"ear": 0.30, "yaw": 0.0, "rosto_detectado": True})
        resposta = ws.receive_json()

    assert resposta["tipo"] == "score"
    assert resposta["score"] == pytest.approx(100.0)

    logs = telemetria.buscar_logs(session, id_sessao=id_sessao)
    assert len(logs) == 1
    assert logs[0].score == pytest.approx(100.0)


def test_cada_payload_vira_um_ponto_da_serie(client, com_sessao_ativa, session):
    from app import telemetria

    id_sessao = _id_da_sessao_ativa(client, com_sessao_ativa)

    with client.websocket_connect("/telemetria") as ws:
        ws.send_json({"token": com_sessao_ativa})
        ws.receive_json()

        for ear in (0.30, 0.15, 0.0):
            ws.send_json({"ear": ear, "yaw": 0.0, "rosto_detectado": True})
            ws.receive_json()

    # 100, 70 e 40 pela fórmula: a série tem que preservar a queda, senão o
    # gráfico da ticket 9 e o relatório da 11 mostrariam uma linha achatada.
    assert [log.score for log in telemetria.buscar_logs(session, id_sessao=id_sessao)] == [
        pytest.approx(100.0),
        pytest.approx(70.0),
        pytest.approx(40.0),
    ]


def test_recusa_conexao_sem_sessao_de_estudo_em_andamento(client, token):
    # Sem sessão não há onde gravar. Aceitar em silêncio faria o aluno acreditar
    # que está sendo medido.
    with client.websocket_connect("/telemetria") as ws:
        ws.send_json({"token": token})
        resposta = ws.receive_json()

    assert resposta == {"tipo": "erro", "motivo": "sem-sessao-ativa"}


def test_nao_aceita_metricas_antes_de_autenticar(client, com_sessao_ativa):
    with client.websocket_connect("/telemetria") as ws:
        ws.send_json({"ear": 0.3, "yaw": 0.0})
        resposta = ws.receive_json()

    assert resposta["motivo"] == "nao-autenticado"


def test_payload_invalido_nao_derruba_a_conexao(client, com_sessao_ativa, session):
    from app import telemetria

    id_sessao = _id_da_sessao_ativa(client, com_sessao_ativa)

    with client.websocket_connect("/telemetria") as ws:
        ws.send_json({"token": com_sessao_ativa})
        ws.receive_json()

        ws.send_json({"ear": "abacaxi", "yaw": None})
        erro = ws.receive_json()

        # A conexão precisa sobreviver: um payload estranho no meio de uma
        # sessão de uma hora não pode custar a sessão inteira.
        ws.send_json({"ear": 0.30, "yaw": 0.0, "rosto_detectado": True})
        depois = ws.receive_json()

    assert erro == {"tipo": "erro", "motivo": "payload-invalido"}
    assert depois["tipo"] == "score"

    # E o payload inválido não pode ter virado um ponto na série.
    assert len(telemetria.buscar_logs(session, id_sessao=id_sessao)) == 1


def test_score_do_primeiro_minuto_vem_marcado_como_calibrando(client, com_sessao_ativa):
    """A calibração da ticket 7 é silenciosa, mas não é invisível.

    O canal continua devolvendo um score por segundo desde o primeiro payload —
    só que medido contra a referência genérica. Quem consome precisa conseguir
    distinguir esse score do que vem depois da baseline fechar.
    """
    with client.websocket_connect("/telemetria") as ws:
        ws.send_json({"token": com_sessao_ativa})
        ws.receive_json()

        ws.send_json({"ear": 0.30, "yaw": 0.0, "rosto_detectado": True})
        resposta = ws.receive_json()

    assert resposta["calibrando"] is True


def test_reconexao_reencontra_a_baseline_ja_calibrada(client, com_sessao_ativa):
    """Ticket 7 sobre a reconexão automática da ticket 6.

    Uma queda de rede não pode custar a calibração: sem o registro por sessão, o
    aluno voltaria a ser medido contra o rosto médio a cada oscilação — e em rede
    ruim isso é a sessão inteira.
    """
    from datetime import datetime, timedelta, timezone

    from app import analista

    id_sessao = _id_da_sessao_ativa(client, com_sessao_ativa)

    # Um minuto de aluno de EAR neutro 0,18 (o caso dos óculos), como se a
    # conexão anterior já tivesse calibrado.
    t0 = datetime(2026, 8, 18, 12, 0, 0, tzinfo=timezone.utc)
    engajamento = analista.registro.obter(id_sessao)
    for segundo in range(61):
        engajamento.observar(ear=0.18, yaw=0.0, agora=t0 + timedelta(seconds=segundo))
    assert engajamento.calibrando is False

    with client.websocket_connect("/telemetria") as ws:
        ws.send_json({"token": com_sessao_ativa})
        ws.receive_json()

        ws.send_json({"ear": 0.18, "yaw": 0.0, "rosto_detectado": True})
        resposta = ws.receive_json()

    # Contra a baseline dele, 0,18 é o olho plenamente aberto: 100. Contra a
    # referência genérica de 0,30 seriam 76 — a calibração teria sido perdida.
    assert resposta["calibrando"] is False
    assert resposta["score"] == pytest.approx(100.0)


def test_score_vem_acompanhado_do_fator_de_fadiga(client, com_sessao_ativa):
    """Ticket 8: o `F` e seus motivos sobem junto com o score.

    O relatório da ticket 11 precisa dizer *por que* houve penalidade — "seu
    score caiu 20 pontos" sem "você passou 30% do último minuto de olhos
    fechados" é um número que o aluno não tem como usar.
    """
    with client.websocket_connect("/telemetria") as ws:
        ws.send_json({"token": com_sessao_ativa})
        ws.receive_json()

        ws.send_json({"ear": 0.30, "yaw": 0.0, "mar": 0.02, "rosto_detectado": True})
        resposta = ws.receive_json()

    assert resposta["fadiga"] == pytest.approx(0.0)
    assert resposta["motivos_fadiga"] == []


def test_payload_sem_mar_continua_aceito(client, com_sessao_ativa, session):
    """Cliente anterior à ticket 8 não pode ter a sessão derrubada.

    Sem `mar` a detecção de bocejo fica inativa, mas os outros dois sinais de
    fadiga — PERCLOS e fechamento prolongado — continuam valendo.
    """
    from app import telemetria

    id_sessao = _id_da_sessao_ativa(client, com_sessao_ativa)

    with client.websocket_connect("/telemetria") as ws:
        ws.send_json({"token": com_sessao_ativa})
        ws.receive_json()

        ws.send_json({"ear": 0.30, "yaw": 0.0, "rosto_detectado": True})
        resposta = ws.receive_json()

    assert resposta["tipo"] == "score"
    assert resposta["score"] == pytest.approx(100.0)
    assert len(telemetria.buscar_logs(session, id_sessao=id_sessao)) == 1


def test_mar_malformado_nao_invalida_a_leitura(client, com_sessao_ativa):
    # O bocejo se degrada sozinho; EAR e yaw, que sustentam o score, continuam
    # sendo lidos. Derrubar o payload inteiro por causa do campo mais periférico
    # seria trocar um sinal ausente por um ponto perdido na série.
    with client.websocket_connect("/telemetria") as ws:
        ws.send_json({"token": com_sessao_ativa})
        ws.receive_json()

        ws.send_json({"ear": 0.30, "yaw": 0.0, "mar": "abacaxi", "rosto_detectado": True})
        resposta = ws.receive_json()

    assert resposta["tipo"] == "score"
    assert resposta["score"] == pytest.approx(100.0)


def test_captura_incerta_devolve_o_motivo_e_nao_grava_score(
    client, com_sessao_ativa, session
):
    """Ticket 10, ponta a ponta.

    O navegador é quem tem a imagem, então é ele quem julga se dá para confiar
    nela. O backend não discute o julgamento: ele se abstém de medir e registra
    o motivo, para que a ausência de score no gráfico e no relatório tenha uma
    explicação em vez de virar um buraco.
    """
    from app import telemetria

    id_sessao = _id_da_sessao_ativa(client, com_sessao_ativa)

    with client.websocket_connect("/telemetria") as ws:
        ws.send_json({"token": com_sessao_ativa})
        ws.receive_json()

        ws.send_json(
            {"ear": 0.30, "yaw": 0.0, "rosto_detectado": True, "incerteza": "baixa-luz"}
        )
        resposta = ws.receive_json()

    assert resposta["score"] is None
    assert resposta["incerteza"] == "baixa-luz"

    logs = telemetria.buscar_logs(session, id_sessao=id_sessao)
    assert len(logs) == 1
    assert logs[0].score is None
    assert logs[0].alerta == "baixa-luz"


def test_motivo_de_incerteza_arbitrario_nao_chega_ao_banco(client, com_sessao_ativa, session):
    """O rótulo é do cliente, mas a coluna é nossa.

    Gravar a string crua deixaria o navegador escrever texto livre dentro de
    `log_engajamento` — e um relatório que agrupa alertas por rótulo passaria a
    exibir o que quer que tivesse sido mandado.
    """
    from app import telemetria

    id_sessao = _id_da_sessao_ativa(client, com_sessao_ativa)

    with client.websocket_connect("/telemetria") as ws:
        ws.send_json({"token": com_sessao_ativa})
        ws.receive_json()

        ws.send_json(
            {
                "ear": 0.30,
                "yaw": 0.0,
                "rosto_detectado": True,
                "incerteza": "<script>alert(1)</script>",
            }
        )
        resposta = ws.receive_json()

    assert resposta["score"] is None
    assert telemetria.buscar_logs(session, id_sessao=id_sessao)[0].alerta == "desconhecida"


def test_cliente_sem_o_campo_de_incerteza_continua_medido(client, com_sessao_ativa):
    # Mesma leniência que valeu para `mar` na ticket 8: um cliente com a aba
    # aberta desde antes do deploy não perde a sessão por um campo novo.
    with client.websocket_connect("/telemetria") as ws:
        ws.send_json({"token": com_sessao_ativa})
        ws.receive_json()

        ws.send_json({"ear": 0.30, "yaw": 0.0, "rosto_detectado": True})
        resposta = ws.receive_json()

    assert resposta["score"] == pytest.approx(100.0)
    assert resposta["incerteza"] is None


def _ultima_presenca(session, id_sessao):
    from app.models import SessaoEstudo

    session.expire_all()
    return session.get(SessaoEstudo, id_sessao).ultima_presenca


def test_payload_com_rosto_registra_presenca(client, com_sessao_ativa, session):
    """Rosto na câmera é o que mantém a sessão viva."""
    id_sessao = _id_da_sessao_ativa(client, com_sessao_ativa)
    assert _ultima_presenca(session, id_sessao) is None

    with client.websocket_connect("/telemetria") as ws:
        ws.send_json({"token": com_sessao_ativa})
        ws.receive_json()
        ws.send_json({"ear": 0.30, "yaw": 0.0, "rosto_detectado": True})
        ws.receive_json()

    assert _ultima_presenca(session, id_sessao) is not None


def test_payload_sem_rosto_nao_registra_presenca(client, com_sessao_ativa, session):
    """A correção inteira do ciclo de vida da sessão está aqui.

    `agregacao.ts` devolve um payload **válido** com `rosto_detectado: false`
    sempre que há quadro de vídeo sem rosto — só devolve `null` quando não há
    quadro nenhum. Enquanto quem renovava a sessão era "chegou payload", cadeira
    vazia com a aba em primeiro plano mantinha a sessão viva a 1 Hz, para
    sempre, e o relatório contava a tarde inteira como estudo.

    O ponto ainda é gravado na série: ele é a evidência de que a captura estava
    rodando, e o score zero dele é uma medida legítima. O que ele não é, e nunca
    foi, é prova de que alguém estava ali.
    """
    id_sessao = _id_da_sessao_ativa(client, com_sessao_ativa)

    with client.websocket_connect("/telemetria") as ws:
        ws.send_json({"token": com_sessao_ativa})
        ws.receive_json()
        ws.send_json({"ear": 0.0, "yaw": 0.0, "rosto_detectado": False})
        ws.receive_json()

    assert _ultima_presenca(session, id_sessao) is None


def test_incerteza_de_captura_nao_desqualifica_a_presenca(client, com_sessao_ativa, session):
    """Incerteza é sobre o score, não sobre estar lá.

    Luz baixa, reflexo no óculos e oclusão parcial estragam a medida do EAR sem
    tirar ninguém da frente da webcam. Tratar incerteza como ausência encerraria
    a sessão de quem estuda num quarto mal iluminado — a mesma confusão entre
    "não medi" e "não estava lá" que a ticket 10 existe para recusar.
    """
    id_sessao = _id_da_sessao_ativa(client, com_sessao_ativa)

    with client.websocket_connect("/telemetria") as ws:
        ws.send_json({"token": com_sessao_ativa})
        ws.receive_json()
        ws.send_json(
            {"ear": 0.30, "yaw": 0.0, "rosto_detectado": True, "incerteza": "baixa-luz"}
        )
        resposta = ws.receive_json()

    assert resposta["score"] is None
    assert _ultima_presenca(session, id_sessao) is not None


def _token_que_vence_em(segundos: int, emitido_em=None):
    """Um token legítimo, com validade curta, para exercitar a reavaliação."""
    from datetime import datetime, timedelta, timezone

    from jose import jwt

    from app.config import settings

    emissao = emitido_em or datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": PAYLOAD_ALUNO["email"],
            "iat": emissao,
            "exp": emissao + timedelta(seconds=segundos),
        },
        settings.secret_key,
        algorithm=settings.algorithm,
    )


def _relogio_do_canal(monkeypatch, instante_inicial):
    """Substitui o relógio do handler para poder avançar o tempo no teste.

    O relógio que valida assinatura e `exp` dentro do `jwt.decode` continua
    sendo o real — é ele que prova que o token estava vivo na conexão.
    """
    from app.routers import telemetria as router_telemetria

    relogio = {"agora": instante_inicial}
    monkeypatch.setattr(router_telemetria, "agora_utc", lambda: relogio["agora"])
    return relogio


def test_websocket_com_token_expirado_e_fechado_no_minuto_seguinte(
    client, com_sessao_ativa, monkeypatch
):
    """O buraco que a renovação de credencial torna explorável.

    O canal autentica na **primeira mensagem** e, até aqui, nunca reavaliava. Isso
    era invisível enquanto nenhuma sessão passava de 30 minutos: o heartbeat
    tomava 401, o cliente desmontava tudo e o WebSocket caía junto. Com sessões
    de horas, um WebSocket aberto seria um canal autenticado de vida ilimitada —
    imune à expiração do token e imune ao logout.

    A reavaliação é **uma vez por minuto**, e não a cada payload: o loop roda a
    1 Hz por aluno e custo por payload é preocupação declarada deste projeto. Daí
    o que o teste afirma ser "fechado no minuto seguinte", e não "fechado no
    primeiro payload depois de vencer".
    """
    from datetime import datetime, timedelta, timezone

    t0 = datetime.now(timezone.utc)
    token = _token_que_vence_em(30)
    relogio = _relogio_do_canal(monkeypatch, t0)

    with client.websocket_connect("/telemetria") as ws:
        ws.send_json({"token": token})
        assert ws.receive_json() == {"tipo": "autenticado"}

        # Dentro do primeiro minuto: nada é reconferido, e o canal responde.
        ws.send_json({"ear": 0.30, "yaw": 0.0, "rosto_detectado": True})
        assert ws.receive_json()["tipo"] == "score"

        # O token venceu aos 30 s; a conferência acontece aos 60 s.
        relogio["agora"] = t0 + timedelta(seconds=90)
        ws.send_json({"ear": 0.30, "yaw": 0.0, "rosto_detectado": True})

        assert ws.receive_json() == {"tipo": "erro", "motivo": "nao-autenticado"}


def test_websocket_com_token_valido_sobrevive_a_reavaliacao(
    client, com_sessao_ativa, monkeypatch
):
    """O par do teste acima, e não é redundante com ele.

    Sem este, fechar o canal incondicionalmente na primeira conferência passaria
    — e derrubaria exatamente a sessão longa que a renovação de credencial foi
    construída para permitir.
    """
    from datetime import datetime, timedelta, timezone

    t0 = datetime.now(timezone.utc)
    token = _token_que_vence_em(30 * 60)
    relogio = _relogio_do_canal(monkeypatch, t0)

    with client.websocket_connect("/telemetria") as ws:
        ws.send_json({"token": token})
        ws.receive_json()

        relogio["agora"] = t0 + timedelta(seconds=90)
        ws.send_json({"ear": 0.30, "yaw": 0.0, "rosto_detectado": True})

        assert ws.receive_json()["tipo"] == "score"


def test_expiracao_e_conferida_uma_vez_por_minuto_e_nao_a_cada_payload(
    client, com_sessao_ativa, monkeypatch
):
    """A cadência da conferência é parte do contrato, não detalhe interno.

    O canal recebe um payload por segundo por aluno, e cada um já paga um
    `INSERT` com `commit`. Conferir a validade a cada payload seria barato em
    isolamento e caro como hábito — o princípio de custo por payload deste
    projeto existe para não acumular "só mais uma coisinha".
    """
    from datetime import datetime, timezone

    from app.security import expiracao_do_token

    chamadas = {"total": 0}
    t0 = datetime.now(timezone.utc)
    _relogio_do_canal(monkeypatch, t0)

    from app.routers import telemetria as router_telemetria

    def contando(token):
        chamadas["total"] += 1
        return expiracao_do_token(token)

    monkeypatch.setattr(router_telemetria, "expiracao_do_token", contando)

    with client.websocket_connect("/telemetria") as ws:
        ws.send_json({"token": _token_que_vence_em(30 * 60)})
        ws.receive_json()

        for _ in range(5):
            ws.send_json({"ear": 0.30, "yaw": 0.0, "rosto_detectado": True})
            ws.receive_json()

    # Uma leitura do token, na entrada. Os cinco payloads seguintes, com o
    # relógio parado, não produzem nenhuma outra.
    assert chamadas["total"] == 1


def test_recusa_token_de_aluno_removido(client, com_sessao_ativa, session):
    # Assinatura válida e prazo em dia, mas a conta não existe mais: o canal não
    # pode ser aceito só por o token ser bem formado.
    from sqlmodel import select

    from app.models import Aluno

    token = _token_que_vence_em(30 * 60)
    session.delete(session.exec(select(Aluno).where(Aluno.email == PAYLOAD_ALUNO["email"])).first())
    session.commit()

    with client.websocket_connect("/telemetria") as ws:
        ws.send_json({"token": token})
        resposta = ws.receive_json()

    assert resposta == {"tipo": "erro", "motivo": "nao-autenticado"}


def test_canal_sem_validade_conhecida_e_fechado_na_conferencia(
    client, com_sessao_ativa, monkeypatch
):
    """Token sem `exp` legível fecha junto com o expirado.

    Um canal cuja validade não dá para afirmar não é um canal válido. A
    alternativa — deixá-lo aberto por não saber — daria vida ilimitada
    justamente a quem apresentou a credencial menos verificável.
    """
    from datetime import datetime, timedelta, timezone

    from jose import jwt

    from app.config import settings

    token_sem_prazo = jwt.encode(
        {"sub": PAYLOAD_ALUNO["email"]}, settings.secret_key, algorithm=settings.algorithm
    )
    t0 = datetime.now(timezone.utc)
    relogio = _relogio_do_canal(monkeypatch, t0)

    with client.websocket_connect("/telemetria") as ws:
        ws.send_json({"token": token_sem_prazo})
        assert ws.receive_json() == {"tipo": "autenticado"}

        relogio["agora"] = t0 + timedelta(seconds=90)
        ws.send_json({"ear": 0.30, "yaw": 0.0, "rosto_detectado": True})

        assert ws.receive_json() == {"tipo": "erro", "motivo": "nao-autenticado"}
