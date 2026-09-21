"""Núcleo de inferência do IEE: baseline individual e fórmula real (ticket 7).

Como `app/sessoes.py` e `app/telemetria.py`, este módulo não conhece HTTP,
WebSocket nem banco. É o `AnalistaEngajamento` que o spec nomeia como seam
principal de teste, e é onde a ticket 8 vai plugar o fator de fadiga `F`.

A fórmula é a do spec::

    IEE(t) = P(t) × [(0,6 × EAR_norm) + (0,4 × HP_norm)] − F

O que a ticket 7 muda em relação ao score provisório da ticket 6 não é a
estrutura de pesos — essa já era a definitiva — mas a **origem das referências**.
Na ticket 6, `EAR_norm` era medido contra a constante 0,30, igual para todo
mundo. Aqui ele passa a ser medido contra o EAR neutro do próprio aluno, apurado
nos primeiros 60 segundos da sessão.

Isso não é refinamento cosmético: é o que impede que um aluno de olhos
naturalmente mais fechados, que use óculos ou que sente levemente de lado seja
lido como permanentemente disperso. A referência fixa media todo mundo contra um
rosto médio que não existe.

**Enquanto a calibração não termina, a baseline provisória é a da ticket 6.** O
canal continua devolvendo um score por segundo desde o primeiro payload — o
spec pede calibração *silenciosa*, e ficar um minuto sem devolver nada seria
tudo menos silencioso. O que vai junto é a marca `calibrando`, para que o
dashboard da ticket 9 possa dizer que aquele primeiro minuto ainda é aproximado.
"""
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import median
from typing import Deque, Dict, List, Optional, Tuple

from app import metodos
from app.tempo import agora_utc

PESO_OCULAR = 0.6
PESO_ORIENTACAO = 0.4

#: Janela de calibração pedida pelo spec e pela ticket 7.
DURACAO_CALIBRACAO = timedelta(seconds=60)

#: Quanto tempo sem rosto ainda conta como "ainda é a mesma calibração".
#: Uma piscada ou um frame perdido não podem custar o minuto inteiro; sumir de
#: fato da webcam, sim — é o que a ticket 7 chama de recalibração automática.
TOLERANCIA_AUSENCIA = timedelta(seconds=3)

#: Piso de amostras para fechar uma baseline. O tempo sozinho não basta: um
#: cliente que mandou três payloads em 60 s (rede ruim, aba em segundo plano)
#: daria uma mediana de três pontos, que é ruído com cara de referência.
MINIMO_DE_AMOSTRAS = 10

#: Desvio de yaw, em graus, a partir do qual a orientação não contribui mais.
#: É uma constante de escala da métrica, não uma referência pessoal: mede o
#: quanto o aluno virou *em relação à própria pose neutra*, e virar 45° para
#: fora do monitor é desviar o olhar em qualquer rosto.
YAW_MAXIMO_GRAUS = 45.0

#: Abaixo disto, a mediana calibrada não descreve um olho aberto — descreve uma
#: calibração feita de olhos fechados ou com o rosto mal detectado. Aceitá-la
#: faria qualquer leitura posterior saturar em `EAR_norm = 1`, e o aluno
#: apareceria como perfeitamente atento pelo resto da sessão. O valor é bem
#: abaixo do neutro plausível (0,20–0,35) justamente para não anular a
#: calibração de quem usa óculos, que é o caso que ela existe para atender.
EAR_NEUTRO_MINIMO = 0.10


@dataclass(frozen=True)
class Baseline:
    """O padrão neutro de um aluno: como são os olhos e a pose dele parado."""

    ear_neutro: float
    yaw_neutro: float


#: A referência da ticket 6, agora rebaixada ao papel de andaime: vale só
#: enquanto a baseline real do aluno não fica pronta.
BASELINE_PROVISORIA = Baseline(ear_neutro=0.30, yaw_neutro=0.0)


# --- Fadiga (ticket 8) -----------------------------------------------------

#: Janela deslizante sobre a qual a fadiga é avaliada. Fadiga é acúmulo: um
#: segundo de olho fechado não diz nada, um minuto com 30% de olho fechado diz.
JANELA_FADIGA = timedelta(seconds=60)

#: Fração da abertura neutra do aluno abaixo da qual o olho conta como fechado.
#: **Relativo, não absoluto.** O limiar clássico da literatura (EAR < 0,20)
#: pressupõe um olho médio; quem tem abertura neutra de 0,18 estaria
#: permanentemente "de olhos fechados" por ele. Metade da própria abertura
#: neutra é a mesma ideia da ticket 7 aplicada à fadiga.
FRACAO_OLHO_FECHADO = 0.5

#: PERCLOS — proporção do tempo com a pálpebra fechada — é a métrica clássica de
#: sonolência da literatura automotiva. Abaixo do limiar não há penalidade;
#: acima da saturação a penalidade é máxima; entre os dois ela cresce linear.
#: Piscar normalmente ocupa ~3–5% do tempo, então 15% já é pálpebra pesada.
PERCLOS_LIMIAR = 0.15
PERCLOS_SATURACAO = 0.40
PENALIDADE_PERCLOS_MAX = 25.0

#: Olho fechado por este tempo seguido não é piscada — é cochilo curto.
DURACAO_MICROSSONO = timedelta(seconds=2)
PENALIDADE_MICROSSONO = 15.0

#: MAR acima disto conta como boca aberta de bocejo.
#:
#: **Provisório, e sabidamente mal calibrado.** O valor herdado da trilha ML
#: (0,60) dispara em 7 clipes de 8570 do DAiSEE — bocejo nenhum seria detectado.
#: 0,30 fica acima do p99,9 observado (0,2884) e abaixo do máximo do dataset
#: (0,7460). A Sprint 11 do plano reserva tempo para recalibrar thresholds de
#: fadiga com dados reais de teste; este é o primeiro da fila.
LIMIAR_MAR_BOCEJO = 0.30

#: Um bocejo precisa durar para não ser confundido com falar, rir ou beber água.
#: Bocejos reais duram 4–6 s; dois segundos é folgado o suficiente para não
#: perder um bocejo curto e estrito o suficiente para descartar uma sílaba.
DURACAO_MINIMA_BOCEJO = timedelta(seconds=2)
PENALIDADE_POR_BOCEJO = 8.0

#: Teto do fator F. O IEE precisa continuar informando sobre atenção mesmo com
#: fadiga máxima detectada — se F pudesse zerar o score sozinho, a componente de
#: EAR e head pose viraria decoração.
FADIGA_MAXIMA = 40.0


@dataclass(frozen=True)
class Fadiga:
    """O fator `F` e as evidências que o produziram.

    Os campos de evidência não são diagnóstico decorativo: o relatório da ticket
    11 precisa dizer *por que* houve penalidade, e "seu score caiu 20 pontos"
    sem "você passou 30% do último minuto de olhos fechados" é um número que o
    aluno não tem como usar.
    """

    fator: float
    perclos: float
    maior_fechamento_s: float
    bocejos: int
    motivos: Tuple[str, ...] = ()


SEM_FADIGA = Fadiga(fator=0.0, perclos=0.0, maior_fechamento_s=0.0, bocejos=0)


#: Motivos de incerteza de captura que o navegador pode reportar (ticket 10).
#: A lista é fechada: o rótulo vai para o banco, e aceitar string livre do
#: cliente seria deixar o navegador escrever texto arbitrário em `log_engajamento`.
MOTIVOS_DE_INCERTEZA = ("baixa-luz", "reflexo-ocular", "oclusao")

#: Rótulo para uma incerteza reportada com motivo que este backend não conhece.
#: A marca vale — o cliente afirmou que a leitura não é confiável, e essa é a
#: parte que importa —, mas o texto dele não entra no banco.
INCERTEZA_DESCONHECIDA = "desconhecida"


def normalizar_incerteza(motivo: Optional[str]) -> Optional[str]:
    """Reduz o motivo vindo do cliente a um rótulo conhecido, ou `None`."""
    if not motivo:
        return None
    return motivo if motivo in MOTIVOS_DE_INCERTEZA else INCERTEZA_DESCONHECIDA


@dataclass(frozen=True)
class ResultadoIEE:
    """O score e o contexto que o produziu.

    `calibrando` não é detalhe de implementação vazando: é a diferença entre um
    score medido contra o aluno e um score medido contra um rosto genérico, e
    quem consome tem o direito de saber qual dos dois recebeu.

    `score is None` é a incerteza de captura da ticket 10 — e não é o mesmo que
    `score = 0`. Zero significa "não havia rosto", que é uma medição; `None`
    significa "havia rosto, mas as condições não sustentam nenhum número".
    """

    score: Optional[float]
    calibrando: bool
    baseline: Baseline
    fadiga: Fadiga = SEM_FADIGA
    incerteza: Optional[str] = None


def _entre_zero_e_um(valor: float) -> float:
    return max(0.0, min(valor, 1.0))


def calcular_iee(
    ear: float,
    yaw: float,
    baseline: Baseline,
    rosto_detectado: bool = True,
    fadiga: float = 0.0,
) -> float:
    """A fórmula do IEE, de 0 a 100, contra uma baseline qualquer.

    Função pura: não guarda estado, não sabe de quem é a baseline e não sabe se
    ela é a calibrada ou a provisória. Toda a decisão de *qual* baseline usar
    fica em `AnalistaEngajamento`.

    `rosto_detectado=False` é o `P(t) = 0` do spec. Sem rosto não há
    comportamento observável, e devolver qualquer outro número seria invenção —
    inclusive a última leitura repetida, que faria um aluno ausente parecer
    presente no gráfico.

    `fadiga` é o `F`, em pontos da mesma escala de 0 a 100. Na ticket 7 ele é
    sempre 0: quem o produz é o Random Forest da ticket 8.
    """
    if not rosto_detectado:
        return 0.0

    referencia = baseline.ear_neutro if baseline.ear_neutro > 0 else BASELINE_PROVISORIA.ear_neutro
    ocular = _entre_zero_e_um(ear / referencia)

    # O desvio é medido a partir da pose neutra do aluno, não do zero absoluto:
    # quem estuda com o monitor levemente de lado tem yaw neutro diferente de 0
    # e não está desatento por isso.
    desvio = abs(yaw - baseline.yaw_neutro)
    orientacao = 1.0 - _entre_zero_e_um(desvio / YAW_MAXIMO_GRAUS)

    bruto = 100.0 * (PESO_OCULAR * ocular + PESO_ORIENTACAO * orientacao)
    return max(0.0, bruto - fadiga)


#: Estados possíveis de uma amostra. `ausente` não é `fechado`: sem rosto não
#: sabemos o que a pálpebra estava fazendo, e contar ausência como fechamento
#: transformaria "saiu para pegar água" em "cochilou".
ABERTO, FECHADO, AUSENTE = "aberto", "fechado", "ausente"


class DetectorDeFadiga:
    """Deriva o fator `F` de regras diretas sobre a série de EAR e MAR.

    **Por que regra e não o Random Forest da ticket 2.** O modelo treinado no
    DAiSEE prevê *engajamento*, um construto subjetivo, e no split de teste ele
    empata com um classificador que responde sempre "engajado" — o `F` derivado
    dele seria constante, e a penalidade de fadiga seria código morto. Fadiga,
    ao contrário de engajamento, é um estado físico observável: "a pálpebra
    ficou fechada por mais de dois segundos" tem resposta objetiva, verificável
    e explicável ao aluno. Ver `resultado_18_08.md` para a medição que motivou
    a troca.

    Três sinais, somados e limitados por `FADIGA_MAXIMA`:

    - **PERCLOS** — proporção do último minuto com a pálpebra fechada. É a
      métrica clássica de sonolência, e a que captura pálpebra pesada contínua.
    - **Microssono** — um único fechamento longo, que a proporção dilui. Trinta
      segundos de olho fechado seguidos dão o mesmo PERCLOS que sessenta
      piscadas espalhadas, e não significam a mesma coisa.
    - **Bocejo** — MAR acima do limiar por tempo suficiente para não ser fala.

    O detector integra sobre o **tempo real entre amostras**, não sobre contagem
    de amostras: a telemetria chega a ~1 Hz, mas uma queda de rede ou uma aba em
    segundo plano abre buracos, e contar amostras trataria um buraco de trinta
    segundos como se fosse um segundo.
    """

    def __init__(self, janela: timedelta = JANELA_FADIGA) -> None:
        self._janela = janela
        #: (instante, estado do olho, boca aberta)
        self._amostras: Deque[Tuple[datetime, str, bool]] = deque()

    def observar(
        self,
        agora: datetime,
        ear: float,
        baseline: Baseline,
        mar: Optional[float] = None,
        rosto_detectado: bool = True,
    ) -> Fadiga:
        """Registra uma leitura e devolve o fator de fadiga da janela atual."""
        if not rosto_detectado:
            estado = AUSENTE
        else:
            limiar = FRACAO_OLHO_FECHADO * baseline.ear_neutro
            estado = FECHADO if ear < limiar else ABERTO

        # `mar` ausente não é boca fechada: é falta de informação. Trata como
        # não-bocejo porque é o único palpite seguro, mas sem fingir medição.
        boca_aberta = mar is not None and mar > LIMIAR_MAR_BOCEJO

        self._amostras.append((agora, estado, boca_aberta))
        self._descartar_antigas(agora)
        return self._avaliar()

    def _descartar_antigas(self, agora: datetime) -> None:
        corte = agora - self._janela
        while len(self._amostras) > 1 and self._amostras[0][0] < corte:
            self._amostras.popleft()

    def _intervalos(self):
        """(duração em segundos, estado, boca aberta) entre amostras vizinhas.

        A duração entre duas amostras é atribuída ao estado da **primeira**: é o
        que sabíamos durante aquele intervalo.
        """
        for (t0, estado, boca), (t1, _, _) in zip(self._amostras, list(self._amostras)[1:]):
            yield (t1 - t0).total_seconds(), estado, boca

    def _avaliar(self) -> Fadiga:
        observado = 0.0   # tempo com rosto — o denominador do PERCLOS
        fechado = 0.0
        maior_fechamento = 0.0
        corrida_atual = 0.0
        bocejos = 0
        bocejo_atual = 0.0

        for duracao, estado, boca in self._intervalos():
            if estado != AUSENTE:
                observado += duracao
            if estado == FECHADO:
                fechado += duracao
                corrida_atual += duracao
                maior_fechamento = max(maior_fechamento, corrida_atual)
            else:
                # Ausência interrompe a corrida: não dá para afirmar que a
                # pálpebra continuou fechada enquanto o rosto sumiu.
                corrida_atual = 0.0

            if boca:
                bocejo_atual += duracao
                if bocejo_atual >= DURACAO_MINIMA_BOCEJO.total_seconds() > bocejo_atual - duracao:
                    bocejos += 1
            else:
                bocejo_atual = 0.0

        perclos = fechado / observado if observado > 0 else 0.0

        motivos: List[str] = []
        fator = 0.0

        if perclos > PERCLOS_LIMIAR:
            excedente = (perclos - PERCLOS_LIMIAR) / (PERCLOS_SATURACAO - PERCLOS_LIMIAR)
            fator += PENALIDADE_PERCLOS_MAX * _entre_zero_e_um(excedente)
            motivos.append("palpebras-pesadas")

        if maior_fechamento >= DURACAO_MICROSSONO.total_seconds():
            fator += PENALIDADE_MICROSSONO
            motivos.append("olhos-fechados-prolongados")

        if bocejos:
            fator += PENALIDADE_POR_BOCEJO * bocejos
            motivos.append("bocejos")

        return Fadiga(
            fator=min(fator, FADIGA_MAXIMA),
            perclos=perclos,
            maior_fechamento_s=maior_fechamento,
            bocejos=bocejos,
            motivos=tuple(motivos),
        )


class AnalistaEngajamento:
    """Acompanha uma sessão: calibra a baseline do aluno e calcula o IEE.

    Uma instância por sessão de estudo — a baseline é de uma pessoa num dia, e
    reaproveitá-la entre sessões traria a pose de ontem para a medição de hoje.

    A calibração acumula apenas leituras **com rosto**. Ausência prolongada
    durante o minuto inicial descarta o que foi acumulado e recomeça, em vez de
    fechar uma baseline com dados incompletos: uma mediana tirada dos 12
    segundos em que o aluno estava na frente da webcam descreveria aqueles 12
    segundos, não o padrão neutro dele.
    """

    def __init__(
        self,
        duracao_calibracao: timedelta = DURACAO_CALIBRACAO,
        tolerancia_ausencia: timedelta = TOLERANCIA_AUSENCIA,
        minimo_de_amostras: int = MINIMO_DE_AMOSTRAS,
    ) -> None:
        self._duracao = duracao_calibracao
        self._tolerancia = tolerancia_ausencia
        self._minimo = minimo_de_amostras

        self._baseline: Optional[Baseline] = None
        self._ear: List[float] = []
        self._yaw: List[float] = []
        self._inicio: Optional[datetime] = None
        self._ultima_presenca: Optional[datetime] = None
        self._fadiga = DetectorDeFadiga()
        self._ultima_fadiga: Fadiga = SEM_FADIGA

    @property
    def baseline(self) -> Optional[Baseline]:
        """A baseline calibrada, ou `None` enquanto o minuto inicial não fecha."""
        return self._baseline

    @property
    def calibrando(self) -> bool:
        return self._baseline is None

    def validar_fadiga(self) -> Fadiga:
        """O fator de fadiga da última leitura observada.

        Nome exigido pelo spec, que prevê `AnalistaEngajamento.validar_fadiga`.
        A lógica vive em `DetectorDeFadiga` para ser testável sozinha; aqui é só
        o ponto de acesso.
        """
        return self._ultima_fadiga

    def observar(
        self,
        ear: float,
        yaw: float,
        rosto_detectado: bool = True,
        agora: Optional[datetime] = None,
        mar: Optional[float] = None,
        incerteza: Optional[str] = None,
    ) -> ResultadoIEE:
        """Registra uma leitura e devolve o IEE do instante.

        `incerteza` é o alerta da ticket 10, e o efeito dele é uniforme: a
        leitura **não entra em lugar nenhum**. Não calibra, porque uma baseline
        tirada de contornos mal detectados descreveria a má iluminação e não o
        aluno; não alimenta o PERCLOS como olho aberto ou fechado, porque não se
        sabe qual dos dois; e não vira score, porque um número derivado de
        landmarks em que não se confia é precisamente o score enganoso que a
        ticket 10 existe para não emitir.
        """
        agora = agora or agora_utc()
        incerteza = normalizar_incerteza(incerteza)

        # Sob incerteza a leitura é tratada como ausência de informação — que é
        # o que o detector de fadiga já sabe representar, e o motivo de `AUSENTE`
        # nunca ter sido sinônimo de `FECHADO`.
        confiavel = incerteza is None
        houve_rosto = rosto_detectado and confiavel

        if self._baseline is None and confiavel:
            self._acumular(ear, yaw, rosto_detectado, agora)

        baseline = self._baseline or BASELINE_PROVISORIA
        self._ultima_fadiga = self._fadiga.observar(
            agora=agora, ear=ear, baseline=baseline, mar=mar, rosto_detectado=houve_rosto
        )

        score = (
            None
            if not confiavel
            else calcular_iee(
                ear=ear,
                yaw=yaw,
                baseline=baseline,
                rosto_detectado=rosto_detectado,
                fadiga=self._ultima_fadiga.fator,
            )
        )

        return ResultadoIEE(
            score=score,
            calibrando=self._baseline is None,
            baseline=baseline,
            fadiga=self._ultima_fadiga,
            incerteza=incerteza,
        )

    # --- Calibração --------------------------------------------------------

    def _ausencia_longa(self, agora: datetime) -> bool:
        if self._ultima_presenca is None:
            return False
        return agora - self._ultima_presenca > self._tolerancia

    def _acumular(self, ear: float, yaw: float, rosto_detectado: bool, agora: datetime) -> None:
        if not rosto_detectado:
            if self._ausencia_longa(agora):
                self._reiniciar()
            return

        # Rosto de volta depois de um sumiço longo. O caso chega aqui, e não pelo
        # ramo acima, quando o cliente para de mandar payload em vez de mandar
        # `rosto_detectado: false` — queda de WebSocket, aba em segundo plano.
        if self._ausencia_longa(agora):
            self._reiniciar()

        if self._inicio is None:
            self._inicio = agora

        self._ultima_presenca = agora
        self._ear.append(ear)
        self._yaw.append(yaw)

        if agora - self._inicio >= self._duracao and len(self._ear) >= self._minimo:
            self._baseline = self._fechar_baseline()

    def _reiniciar(self) -> None:
        self._ear.clear()
        self._yaw.clear()
        self._inicio = None
        self._ultima_presenca = None

    def _fechar_baseline(self) -> Baseline:
        """Consolida as amostras acumuladas na baseline do aluno.

        **Mediana, não média.** O aluno pisca durante a calibração, e cada
        piscada é um EAR perto de zero. A média as absorve e devolve um neutro
        mais baixo que o real, o que infla o `EAR_norm` da sessão inteira. A
        mediana de ~60 amostras simplesmente não as enxerga.
        """
        ear_neutro = median(self._ear)
        if ear_neutro < EAR_NEUTRO_MINIMO:
            ear_neutro = BASELINE_PROVISORIA.ear_neutro

        return Baseline(ear_neutro=ear_neutro, yaw_neutro=median(self._yaw))


class RegistroDeAnalistas:
    """Guarda um analista por sessão de estudo, entre conexões de WebSocket.

    Existe por causa da reconexão automática da ticket 6: sem isto, cada queda
    de rede jogaria a baseline fora e recomeçaria a calibração do zero, e um
    aluno em rede instável passaria a sessão inteira sendo medido contra o rosto
    médio da ticket 6.

    A limpeza é preguiçosa, no mesmo espírito de `sessoes.encerrar_inativas`: em
    vez de um processo de fundo, cada acesso descarta o que envelheceu. O estado
    é de processo — um backend com mais de uma réplica no ECS (ticket 15) faria
    o aluno recalibrar a cada troca de instância, e aí a baseline precisa sair
    daqui para o banco.
    """

    def __init__(self, validade: Optional[timedelta] = None) -> None:
        self._validade = validade
        self._analistas: Dict[int, AnalistaEngajamento] = {}
        self._ultimo_uso: Dict[int, datetime] = {}

    def _limite(self) -> timedelta:
        # Não é um relógio próprio: é derivação do teto de ausência. Nenhuma
        # sessão sobrevive a mais que `metodos.TETO_DE_AUSENCIA` sem rosto na
        # câmera, logo uma baseline mais velha que o teto nunca pode ser
        # necessária. Amarrar ao teto, e não ao limite do método, é de propósito:
        # o registro é global e não sabe de qual sessão virá o próximo acesso.
        return self._validade or metodos.TETO_DE_AUSENCIA

    def obter(self, id_sessao: int, agora: Optional[datetime] = None) -> AnalistaEngajamento:
        agora = agora or agora_utc()
        self._descartar_vencidos(agora)

        analista = self._analistas.get(id_sessao)
        if analista is None:
            analista = AnalistaEngajamento()
            self._analistas[id_sessao] = analista

        self._ultimo_uso[id_sessao] = agora
        return analista

    def descartar(self, id_sessao: int) -> None:
        self._analistas.pop(id_sessao, None)
        self._ultimo_uso.pop(id_sessao, None)

    def _descartar_vencidos(self, agora: datetime) -> None:
        corte = agora - self._limite()
        vencidos = [id_sessao for id_sessao, uso in self._ultimo_uso.items() if uso <= corte]
        for id_sessao in vencidos:
            self.descartar(id_sessao)


#: Registro usado pelo canal de telemetria. Os testes montam o seu próprio.
registro = RegistroDeAnalistas()
