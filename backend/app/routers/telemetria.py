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

from app import analista, sessoes, telemetria
from app.database import get_session
from app.models import Aluno
from app.security import decodificar_token

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


def _ler_metricas(payload: object) -> Optional[Tuple[float, float, bool]]:
    """Extrai (ear, yaw, rosto_detectado) do payload, ou `None` se estiver torto.

    Booleano não é aceito como número apesar de `bool` ser subclasse de `int`
    em Python: `{"ear": true}` é payload quebrado, não um EAR de 1,0.
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

    rosto_detectado = payload.get("rosto_detectado", True)
    if not isinstance(rosto_detectado, bool):
        return None

    return ear, yaw, rosto_detectado


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

    # Vem do registro, e não é criado aqui, porque a reconexão automática da
    # ticket 6 abre uma conexão nova para a mesma sessão: um analista por
    # conexão faria o aluno recalibrar a cada oscilação de rede.
    engajamento = analista.registro.obter(sessao.id)

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

        ear, yaw, rosto_detectado = metricas
        resultado = engajamento.observar(ear=ear, yaw=yaw, rosto_detectado=rosto_detectado)

        telemetria.registrar_log(db, id_sessao=sessao.id, score=resultado.score)

        # Quem manda telemetria está estudando. Sem isto, uma sessão silenciosa
        # seria encerrada por "inatividade" justamente enquanto era medida.
        sessoes.registrar_atividade(db, id_sessao=sessao.id, id_aluno=aluno.id)

        # `calibrando` acompanha o score porque o primeiro minuto é medido
        # contra uma referência genérica: o dashboard da ticket 9 precisa poder
        # dizer isso em vez de apresentar os dois como equivalentes.
        await websocket.send_json(
            {"tipo": "score", "score": resultado.score, "calibrando": resultado.calibrando}
        )
