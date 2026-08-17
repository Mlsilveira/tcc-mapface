"""Canal de telemetria por WebSocket (ticket 6).

Autenticação pela **primeira mensagem**, e não por query param: token em URL
vaza para log de servidor, proxy e histórico do navegador — inaceitável num
projeto cujo eixo é privacidade. E o WebSocket do navegador não permite mandar
header `Authorization`, então a primeira mensagem é o único lugar limpo.

O que trafega aqui são métricas numéricas já calculadas no navegador (EAR, yaw,
presença facial). Nenhum frame, nenhuma imagem, nenhum landmark bruto.
"""
from typing import Optional, Tuple

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlmodel import Session, select

from app import analista, calibracao, sessoes, telemetria
from app.analista import AnalistaEngajamento
from app.database import get_session
from app.models import Aluno
from app.security import decodificar_token
from app.tempo import agora_utc

router = APIRouter(tags=["telemetria"])


def _autenticar(db: Session, mensagem: dict) -> Optional[Aluno]:
    """Resolve o aluno a partir do token da primeira mensagem."""
    token = mensagem.get("token") if isinstance(mensagem, dict) else None
    if not isinstance(token, str) or not token:
        return None

    email = decodificar_token(token)
    if email is None:
        return None

    return db.exec(select(Aluno).where(Aluno.email == email)).first()


def _ler_metricas(payload: object) -> Optional[Tuple[float, float, float, bool]]:
    """Extrai (ear, yaw, pitch, rosto_detectado) do payload, ou `None` se torto.

    Booleano não é aceito como número apesar de `bool` ser subclasse de `int`
    em Python: `{"ear": true}` é payload quebrado, não um EAR de 1,0.

    `pitch` tem default 0,0 em vez de ser obrigatório: um cliente da ticket 6,
    ainda sem a atualização que passou a enviá-lo, continua sendo medido em vez
    de ver todos os seus payloads recusados. Cabeça neutra no eixo vertical é a
    suposição menos danosa — e, se o aluno de fato mantiver a cabeça reta, é
    também a correta.
    """
    if not isinstance(payload, dict):
        return None

    def numero(chave: str) -> Optional[float]:
        valor = payload.get(chave)
        if isinstance(valor, bool) or not isinstance(valor, (int, float)):
            return None
        return float(valor)

    ear = numero("ear")
    yaw = numero("yaw")
    if ear is None or yaw is None:
        return None

    pitch = 0.0 if "pitch" not in payload else numero("pitch")
    if pitch is None:
        return None

    rosto_detectado = payload.get("rosto_detectado", True)
    if not isinstance(rosto_detectado, bool):
        return None

    return ear, yaw, pitch, rosto_detectado


@router.websocket("/telemetria")
async def telemetria_ws(
    websocket: WebSocket,
    db: Session = Depends(get_session),
) -> None:
    """Recebe métricas faciais e devolve o score de engajamento a cada payload.

    A sessão de estudo não vem do cliente: é resolvida no servidor a partir do
    aluno autenticado. Aceitar um `id_sessao` do cliente abriria espaço para
    alguém gravar log na sessão de outra pessoa.
    """
    await websocket.accept()

    try:
        primeira = await websocket.receive_json()
    except (WebSocketDisconnect, ValueError):
        return

    aluno = _autenticar(db, primeira)
    if aluno is None:
        await websocket.send_json({"tipo": "erro", "motivo": "nao-autenticado"})
        await websocket.close()
        return

    sessao = sessoes.buscar_ativa(db, aluno.id)
    if sessao is None:
        # Telemetria sem sessão em andamento não teria onde ser gravada, e
        # aceitar o payload em silêncio faria o aluno crer que está sendo medido.
        await websocket.send_json({"tipo": "erro", "motivo": "sem-sessao-ativa"})
        await websocket.close()
        return

    await websocket.send_json({"tipo": "autenticado"})

    while True:
        try:
            payload = await websocket.receive_json()
        except (WebSocketDisconnect, ValueError):
            return

        metricas = _ler_metricas(payload)
        if metricas is None:
            # Um payload estranho no meio de uma sessão de uma hora não pode
            # custar a sessão inteira: avisa e segue ouvindo.
            await websocket.send_json({"tipo": "erro", "motivo": "payload-invalido"})
            continue

        ear, yaw, pitch, rosto_detectado = metricas
        resultado = _analisar(
            db,
            id_sessao=sessao.id,
            ear=ear,
            yaw=yaw,
            pitch=pitch,
            rosto_detectado=rosto_detectado,
        )

        telemetria.registrar_log(db, id_sessao=sessao.id, score=resultado.score)

        # Quem manda telemetria está estudando. Sem isto, uma sessão silenciosa
        # seria encerrada por "inatividade" justamente enquanto era medida.
        sessoes.registrar_atividade(db, id_sessao=sessao.id, id_aluno=aluno.id)

        await websocket.send_json(
            {
                "tipo": "score",
                "score": resultado.score,
                "calibrando": resultado.calibrando,
            }
        )


def _analisar(
    db: Session,
    id_sessao: int,
    ear: float,
    yaw: float,
    pitch: float,
    rosto_detectado: bool,
) -> analista.Resultado:
    """Roda o analista sobre um payload e persiste o que ele decidiu.

    O analista é reconstruído a cada mensagem a partir do banco, e não mantido
    vivo na conexão: é isso que faz a calibração de 60 segundos sobreviver à
    reconexão automática da ticket 6 — e ao roteamento para outra instância no
    deploy da ticket 15, onde memória de processo não vale nada.

    A tradução do `Resultado` para o banco é toda aqui, e são quatro casos:
    a janela acabou de fechar (baseline nova), a calibração avançou (acumulador),
    o aluno sumiu durante a calibração (descarta e recomeça), ou já havia
    baseline (nada a gravar — o analista devolve a mesma ecoada).
    """
    leitura = calibracao.carregar(db, id_sessao)

    resultado = AnalistaEngajamento(
        baseline=leitura.baseline, estado=leitura.estado
    ).processar(
        ear=ear,
        yaw=yaw,
        pitch=pitch,
        rosto_detectado=rosto_detectado,
        agora=agora_utc(),
    )

    if resultado.baseline is not None and leitura.baseline is None:
        calibracao.salvar_baseline(db, id_sessao, resultado.baseline)
    elif resultado.estado is not None:
        try:
            calibracao.salvar_estado(db, id_sessao, resultado.estado)
        except calibracao.CalibracaoJaConcluida:
            # Outra conexão da mesma sessão fechou a janela entre o `carregar`
            # acima e esta gravação — duas abas abertas, ou a sobreposição do
            # socket antigo com o novo durante a reconexão da ticket 6. A
            # calibração alheia vale: não há o que acumular, e este payload
            # perde só a chance de contribuir para uma baseline que já existe.
            # Deixar a exceção subir mataria a conexão no meio da sessão.
            pass
    elif resultado.calibrando:
        # Sem estado e ainda calibrando: o aluno saiu de quadro antes de a
        # janela fechar. O acumulado mistura presença com ausência, e uma média
        # assim é pior que média nenhuma (história 14 do spec).
        calibracao.descartar(db, id_sessao)

    return resultado
