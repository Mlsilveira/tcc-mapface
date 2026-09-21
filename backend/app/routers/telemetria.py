"""Canal de telemetria por WebSocket (ticket 6).

Autenticação pela **primeira mensagem**, e não por query param: token em URL
vaza para log de servidor, proxy e histórico do navegador — inaceitável num
projeto cujo eixo é privacidade. E o WebSocket do navegador não permite mandar
header `Authorization`, então a primeira mensagem é o único lugar limpo.

O que trafega aqui são métricas numéricas já calculadas no navegador (EAR, yaw,
presença facial). Nenhum frame, nenhuma imagem, nenhum landmark bruto.

**A credencial é reavaliada durante a conexão, e isso não é zelo excessivo.**
Autenticar só na primeira mensagem bastava enquanto nenhuma sessão passava de
30 minutos: o heartbeat tomava 401, o cliente desmontava tudo e o canal caía
junto. Com a renovação de credencial (`app.security`) as sessões passam a durar
horas, e um WebSocket que autentica uma vez vira **canal autenticado de vida
ilimitada** — imune à expiração do token e imune ao logout. O buraco não é
criado pela renovação; ele já existia e era escondido pelo teto de 30 minutos.
"""
from datetime import datetime, timedelta
from typing import NamedTuple, Optional, Tuple

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlmodel import Session, select

from app import analista, sessoes, telemetria
from app.database import get_session
from app.models import Aluno
from app.security import decodificar_token, expiracao_do_token
from app.tempo import agora_utc

router = APIRouter(tags=["telemetria"])

#: De quanto em quanto tempo a validade do token é reconferida no canal aberto.
#:
#: Não a cada payload: o loop roda a 1 Hz por aluno, e custo por payload é uma
#: preocupação declarada deste projeto — cada mensagem já paga um `INSERT` com
#: `commit`, e somar a isso a verificação de um instante seria barato, mas somar
#: o hábito de "só mais uma coisinha por payload" não é.
#:
#: Um minuto é a granularidade certa porque o que se quer limitar é a **janela
#: de sobrevida** de um canal cuja credencial venceu, e um minuto de sobrevida
#: é da mesma ordem do heartbeat que já governa o resto do ciclo de vida. Mais
#: fino não compra segurança perceptível; mais grosso começa a ser sobrevida
#: relevante.
INTERVALO_DE_REAVALIACAO = timedelta(minutes=1)


class Credencial(NamedTuple):
    """Quem é o aluno e até quando o token dele vale.

    Os dois andam juntos porque separá-los foi justamente o defeito: o handler
    guardava o aluno e jogava fora o `exp`, e com isso perdia a única informação
    que permitiria reavaliar a credencial depois.
    """

    aluno: Aluno
    expira_em: Optional[datetime]


def _autenticar(db: Session, mensagem: dict) -> Optional[Credencial]:
    """Resolve o aluno e a expiração a partir do token da primeira mensagem."""
    token = mensagem.get("token") if isinstance(mensagem, dict) else None
    if not isinstance(token, str) or not token:
        return None

    email = decodificar_token(token)
    if email is None:
        return None

    aluno = db.exec(select(Aluno).where(Aluno.email == email)).first()
    if aluno is None:
        return None

    return Credencial(aluno=aluno, expira_em=expiracao_do_token(token))


def _ler_metricas(
    payload: object,
) -> Optional[Tuple[float, float, bool, Optional[float], Optional[str]]]:
    """Extrai (ear, yaw, rosto_detectado, mar, incerteza) do payload, ou `None`.

    Booleano não é aceito como número apesar de `bool` ser subclasse de `int`
    em Python: `{"ear": true}` é payload quebrado, não um EAR de 1,0.

    `mar` entrou na ticket 8, para a detecção de bocejo, e é **opcional**: um
    cliente anterior a ela continua sendo aceito, só sem o sinal de bocejo. Vale
    a leniência porque a alternativa é derrubar a sessão de quem está com a aba
    aberta desde antes do deploy — e a fadiga tem outros dois sinais.
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

    # A incerteza da ticket 10 vem como rótulo curto, e o `AnalistaEngajamento`
    # a reduz a um motivo conhecido antes de qualquer coisa chegar ao banco.
    # Rótulo não-string é ignorado em vez de invalidar o payload: no pior caso
    # o ponto é medido quando não deveria, o que é menos destrutivo que perder
    # a série inteira de um cliente com um campo torto.
    incerteza = payload.get("incerteza")
    if not isinstance(incerteza, str):
        incerteza = None

    # `mar` malformado é tratado como ausente, e não como payload inválido: a
    # medição de bocejo se degrada sozinha sem custar a leitura de EAR e yaw,
    # que são o que sustenta o score.
    return ear, yaw, rosto_detectado, numero("mar"), incerteza


def _alerta_do(resultado: analista.ResultadoIEE) -> Optional[str]:
    """O rótulo que vai para a coluna `alerta` do log (ticket 10).

    Um rótulo só: sob incerteza, o motivo dela — não há score para a fadiga
    descontar, e um motivo de fadiga apurado sobre leituras em que não se confia
    seria ruído com cara de evidência. Havendo score, o motivo dominante da
    fadiga, que é o que o relatório da ticket 11 mostra ao aluno.
    """
    if resultado.incerteza is not None:
        return resultado.incerteza
    return resultado.fadiga.motivos[0] if resultado.fadiga.motivos else None


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

    credencial = _autenticar(db, primeira)
    if credencial is None:
        await websocket.send_json({"tipo": "erro", "motivo": "nao-autenticado"})
        await websocket.close()
        return

    sessao = sessoes.buscar_ativa(db, credencial.aluno.id)
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

    # A primeira conferência fica para daqui a um minuto: o token acabou de ser
    # validado por `decodificar_token`, que já recusa expirado.
    proxima_conferencia = agora_utc() + INTERVALO_DE_REAVALIACAO

    while True:
        try:
            payload = await websocket.receive_json()
        except (WebSocketDisconnect, ValueError):
            return

        agora = agora_utc()
        if agora >= proxima_conferencia:
            proxima_conferencia = agora + INTERVALO_DE_REAVALIACAO
            # `expira_em is None` é token sem `exp` legível, e fecha junto: um
            # canal cuja validade não dá para afirmar não é um canal válido. É
            # a mesma escolha que o resto do projeto faz com medida ausente —
            # abster-se, em vez de assumir o caso favorável.
            if credencial.expira_em is None or agora >= credencial.expira_em:
                await websocket.send_json(
                    {"tipo": "erro", "motivo": "nao-autenticado"}
                )
                await websocket.close()
                return

        metricas = _ler_metricas(payload)
        if metricas is None:
            # Um payload estranho no meio de uma sessão de uma hora não pode
            # custar a sessão inteira: avisa e segue ouvindo.
            await websocket.send_json({"tipo": "erro", "motivo": "payload-invalido"})
            continue

        ear, yaw, rosto_detectado, mar, incerteza = metricas
        resultado = engajamento.observar(
            ear=ear, yaw=yaw, rosto_detectado=rosto_detectado, mar=mar, incerteza=incerteza
        )

        telemetria.registrar_log(
            db,
            id_sessao=sessao.id,
            score=resultado.score,
            fadiga=resultado.fadiga.fator,
            alerta=_alerta_do(resultado),
        )

        # Presença é **rosto na câmera**, não payload recebido — e esta linha é a
        # correção inteira do ciclo de vida da sessão.
        #
        # O comentário que estava aqui dizia "quem manda telemetria está
        # estudando", e a premissa era falsa: `agregacao.ts` devolve um payload
        # válido, com `rosto_detectado: false`, sempre que há quadro de vídeo sem
        # rosto. Só devolve `null` quando não há quadro nenhum. Logo, cadeira
        # vazia com a aba em primeiro plano renovava a atividade uma vez por
        # segundo, indefinidamente — a sessão nunca morria, e o relatório contava
        # a tarde inteira como estudo.
        #
        # **A incerteza de captura não desqualifica a presença.** Ela é sobre o
        # score: "não dá para afirmar quanto engajamento houve neste segundo".
        # Achar o rosto é uma afirmação mais fraca e independente — luz baixa,
        # reflexo no óculos e oclusão parcial estragam a medida do EAR sem tirar
        # ninguém da frente da webcam. Tratar incerteza como ausência
        # encerraria a sessão de quem está estudando num quarto mal iluminado, e
        # seria a mesma confusão entre "não medi" e "não estava lá" que a
        # ticket 10 existe para recusar.
        if rosto_detectado:
            sessoes.registrar_presenca(db, sessao)

        # `calibrando` acompanha o score porque o primeiro minuto é medido
        # contra uma referência genérica: o dashboard da ticket 9 precisa poder
        # dizer isso em vez de apresentar os dois como equivalentes.
        #
        # Os motivos da fadiga vão junto pela mesma razão: "seu score caiu 20
        # pontos" sem "você passou 30% do último minuto de olhos fechados" é um
        # número que o aluno não tem como usar. O relatório da ticket 11 e o
        # dashboard da 9 consomem daqui.
        # `incerteza` acompanha o score pela mesma lógica de `calibrando`: o
        # aluno precisa ver "não deu para medir agora" na tela, e não um gráfico
        # que simplesmente para de subir sem explicação (ticket 10).
        await websocket.send_json(
            {
                "tipo": "score",
                "score": resultado.score,
                "calibrando": resultado.calibrando,
                "fadiga": resultado.fadiga.fator,
                "motivos_fadiga": list(resultado.fadiga.motivos),
                "incerteza": resultado.incerteza,
            }
        )
