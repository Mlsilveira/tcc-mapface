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
import logging
import math
import time
from datetime import datetime, timedelta
from typing import List, NamedTuple, Optional

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlmodel import Session, select

from app import analista, sessoes, telemetria
from app.database import get_session
from app.models import Aluno
from app.security import decodificar_token, expiracao_do_token
from app.tempo import agora_utc

router = APIRouter(tags=["telemetria"])

logger = logging.getLogger(__name__)

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


def _ler_t0(payload: object) -> Optional[float]:
    """O carimbo de envio do cliente, se ele mandou um, para ser devolvido intacto.

    **Por que existe (parecer do TC2, F01).** A meta de latência do WebSocket
    precisa de um número medido no ambiente publicado, e medir ida e volta exige
    saber a qual envio cada resposta corresponde. O servidor não interpreta este
    valor — não sabe nem em que relógio ele está —, só o devolve. Quem enviou é
    quem subtrai.

    Opcional e ignorado se malformado: um cliente que não manda carimbo é o
    navegador de todo dia, e um carimbo torto não pode custar a leitura de EAR
    do segundo. Booleano não conta como número, pela mesma razão de
    `_ler_metricas`.
    """
    if not isinstance(payload, dict):
        return None
    valor = payload.get("t0")
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        return None
    return float(valor) if math.isfinite(valor) else None


def percentil(valores: List[float], p: float) -> Optional[float]:
    """Percentil por posição mais próxima (*nearest-rank*), sem interpolar.

    Sem interpolação de propósito: o p95 de 60 medições tem de ser **uma das
    medições**, para que quem lê o relatório possa apontar o segundo em que ela
    aconteceu. Uma interpolação devolveria um número que nenhum pacote teve.
    """
    if not valores:
        return None
    ordenados = sorted(valores)
    posicao = max(1, math.ceil(p / 100 * len(ordenados)))
    return ordenados[posicao - 1]


def _registrar_latencia(id_sessao: int, tempos_ms: List[float]) -> None:
    """Uma linha de log por conexão com o tempo de processamento do servidor.

    Por conexão, e não por mensagem: a 1 Hz por aluno, uma linha por payload
    afogaria o log em ruído, e o que a medição precisa é a distribuição — que
    cabe numa linha só. Os valores individuais continuam disponíveis para quem
    precisar deles, em cada resposta (`processamento_ms`).
    """
    if not tempos_ms:
        return
    logger.info(
        "latencia do canal: sessao=%s n=%d p50=%.2fms p95=%.2fms max=%.2fms",
        id_sessao,
        len(tempos_ms),
        percentil(tempos_ms, 50),
        percentil(tempos_ms, 95),
        max(tempos_ms),
    )


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


class MetricasDaLeitura(NamedTuple):
    """O que um payload de telemetria carrega, já validado.

    Virou um tipo nomeado quando os campos passaram de cinco para nove: uma
    tupla de nove posições desempacotada na chamada é um erro esperando a
    próxima adição, e trocar `pitch` por `roll` sem querer não produziria erro
    nenhum — só uma feature com o valor da outra.

    Os quatro últimos campos entraram junto com o classificador de sonolência,
    que precisa dos olhos separados e da pose completa. São opcionais pela mesma
    razão que `mar` foi opcional na ticket 8: um cliente anterior ao deploy
    continua sendo aceito, só sem o sinal novo.
    """

    ear: float
    yaw: float
    rosto_detectado: bool
    mar: Optional[float]
    incerteza: Optional[str]
    ear_esq: Optional[float] = None
    ear_dir: Optional[float] = None
    pitch: Optional[float] = None
    roll: Optional[float] = None


def _ler_metricas(payload: object) -> Optional[MetricasDaLeitura]:
    """Valida o payload e devolve as métricas dele, ou `None` se estiver quebrado.

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
    # que são o que sustenta o score. O mesmo vale para os quatro campos do
    # classificador de sonolência — ausentes, as features correspondentes saem
    # `nan`, que é o que o imputador do pipeline sabe tratar.
    return MetricasDaLeitura(
        ear=ear,
        yaw=yaw,
        rosto_detectado=rosto_detectado,
        mar=numero("mar"),
        incerteza=incerteza,
        ear_esq=numero("ear_esq"),
        ear_dir=numero("ear_dir"),
        pitch=numero("pitch"),
        roll=numero("roll"),
    )


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
    if sessao is None or not credencial.aluno.consentimento_vigente:
        # Telemetria sem sessão em andamento não teria onde ser gravada, e
        # aceitar o payload em silêncio faria o aluno crer que está sendo medido.
        await websocket.send_json({"tipo": "erro", "motivo": "sem-sessao-ativa"})
        await websocket.close()
        return

    await websocket.send_json({"tipo": "autenticado"})

    # Guardado como número enquanto a linha existe. Depois de um commit o ORM
    # relê os atributos da entidade, e numa sessão recém-excluída pelo titular
    # até ler `sessao.id` levanta `ObjectDeletedError`.
    id_sessao = sessao.id

    # Vem do registro, e não é criado aqui, porque a reconexão automática da
    # ticket 6 abre uma conexão nova para a mesma sessão: um analista por
    # conexão faria o aluno recalibrar a cada oscilação de rede.
    engajamento = analista.registro.obter(id_sessao)

    # A primeira conferência fica para daqui a um minuto: o token acabou de ser
    # validado por `decodificar_token`, que já recusa expirado.
    proxima_conferencia = agora_utc() + INTERVALO_DE_REAVALIACAO

    # Tempo de processamento de cada payload neste canal, em ms. Vira uma linha
    # de log quando a conexão termina — por qualquer um dos caminhos de saída,
    # daí o `finally`.
    tempos_ms: List[float] = []
    try:
        await _laco_do_canal(
            websocket, db, credencial, sessao, id_sessao, engajamento, proxima_conferencia, tempos_ms
        )
    finally:
        _registrar_latencia(id_sessao, tempos_ms)


async def _laco_do_canal(
    websocket: WebSocket,
    db: Session,
    credencial: "Credencial",
    sessao,
    id_sessao: int,
    engajamento,
    proxima_conferencia: datetime,
    tempos_ms: List[float],
) -> None:
    """O laço de um canal autenticado: payload entra, score sai.

    Separado de `telemetria_ws` só para o `finally` de lá registrar a latência
    em todos os caminhos de saída — queda, credencial vencida, cliente que fecha.
    O comportamento é o mesmo de antes.
    """
    while True:
        try:
            payload = await websocket.receive_json()
        except (WebSocketDisconnect, ValueError):
            return

        # O relógio começa quando o payload já está em memória e para logo antes
        # da resposta sair. Ficam dentro: a reconferência da credencial, a
        # fórmula, a janela do classificador e — o que mais pesa — o `INSERT`
        # com `commit`. Ficam fora: rede e o tempo que o payload esperou na fila
        # do socket, que já estão no RTT que o cliente mede.
        inicio = time.perf_counter()
        t0 = _ler_t0(payload)

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

        # A revogação e a exclusão chegam por outra requisição, com este canal
        # aberto. Sem conferir aqui, o segundo seguinte gravaria um ponto numa
        # sessão que o titular acabou de mandar parar.
        if not sessoes.em_andamento(db, id_sessao):
            await websocket.send_json({"tipo": "erro", "motivo": "sem-sessao-ativa"})
            await websocket.close()
            return

        resultado = engajamento.observar(
            ear=metricas.ear,
            yaw=metricas.yaw,
            rosto_detectado=metricas.rosto_detectado,
            mar=metricas.mar,
            incerteza=metricas.incerteza,
            ear_esq=metricas.ear_esq,
            ear_dir=metricas.ear_dir,
            pitch=metricas.pitch,
            roll=metricas.roll,
        )
        rosto_detectado = metricas.rosto_detectado

        telemetria.registrar_log(
            db,
            id_sessao=id_sessao,
            score=resultado.score,
            fadiga=resultado.fadiga.fator,
            alerta=_alerta_do(resultado),
            sonolencia=resultado.sonolencia,
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
                # Vai junto, mas não é o mesmo tipo de coisa que os campos
                # acima: `fadiga` explica o desconto que o score sofreu, e isto
                # é uma leitura paralela que não entrou na conta. `None`
                # enquanto a primeira janela de 10s não fecha depois da
                # calibração — e `None` continua sendo "não dá para afirmar",
                # nunca zero.
                "sonolencia": resultado.sonolencia,
                # Para a medição de latência (parecer do TC2, F01): o cliente
                # subtrai `processamento_ms` do RTT que ele mediu e obtém o
                # tempo de rede, sem somar duas vezes o que já está dentro.
                "processamento_ms": _registrar_tempo(inicio, tempos_ms),
                "t0": t0,
            }
        )


def _registrar_tempo(inicio: float, tempos_ms: List[float]) -> float:
    """Fecha o cronômetro deste payload e guarda o valor para o resumo da conexão."""
    decorrido = round((time.perf_counter() - inicio) * 1000, 3)
    tempos_ms.append(decorrido)
    return decorrido
