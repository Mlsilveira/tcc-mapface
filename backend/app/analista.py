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

from app.config import settings
from app.qualidade import CAPTURA_CONFIAVEL, DetectorDeIncerteza, Qualidade
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
#:
#: Medido numa sessão real de 92 s (28/08/2026), o piscar involuntário deu 3,3%
#: — dentro do esperado. O que passava de 15% era o PERCLOS somado aos episódios
#: longos, que já são cobrados pelo microssono; ver `_avaliar`.
PERCLOS_LIMIAR = 0.15
PERCLOS_SATURACAO = 0.40
PENALIDADE_PERCLOS_MAX = 25.0

#: Tempo máximo que uma única amostra pode representar.
#:
#: A telemetria chega a ~1 Hz, mas buracos acontecem — numa sessão real medida
#: em 28/08, 12% dos intervalos passaram de 1,5 s, chegando a 4 s durante o
#: aquecimento do MediaPipe. Sem este teto, a amostra anterior ao buraco tem seu
#: estado esticado por todo ele: **uma piscada capturada antes de um intervalo de
#: 4 segundos vira 4 segundos de olho fechado**, e sozinha dispara o microssono.
#:
#: Buraco é informação ausente, não estado que persistiu — é o mesmo princípio
#: que faz ausência de rosto não contar como pálpebra fechada, aplicado ao tempo.
INTERVALO_MAXIMO_ATRIBUIVEL = timedelta(seconds=1.5)

#: Olho fechado por este tempo seguido não é piscada — é cochilo curto.
DURACAO_MICROSSONO = timedelta(seconds=2)
PENALIDADE_MICROSSONO = 15.0

#: MAR acima disto conta como boca aberta de bocejo.
#:
#: Calibrado contra **rosto real**, e não contra o DAiSEE. Um bocejo medido por
#: webcam em 28/08 desenhou a curva 0,21 → 0,69 → 0,79 → **0,83** → 0,76 antes
#: de voltar a 0,01 — ou seja, ultrapassou o 0,8 que a docstring de
#: `ml/metricas.py` descreve como bocejo escancarado. A fórmula sempre esteve
#: certa.
#:
#: O que enganou foi o DAiSEE, cujo máximo em ~24 h de vídeo é 0,746 e cuja
#: mediana é 0,0036: aquele dataset não tem bocejos francos, provavelmente por
#: enquadramento de sala de aula em vez de webcam próxima. O valor chegou a ser
#: baixado para 0,30 por causa dele; com a evidência de rosto real, 0,50 ganha
#: especificidade contra fala e riso sem perder o bocejo, que passa longe disso.
LIMIAR_MAR_BOCEJO = 0.50

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


@dataclass(frozen=True)
class ResultadoIEE:
    """O score e o contexto que o produziu.

    `calibrando` não é detalhe de implementação vazando: é a diferença entre um
    score medido contra o aluno e um score medido contra um rosto genérico, e
    quem consome tem o direito de saber qual dos dois recebeu.
    """

    score: float
    calibrando: bool
    baseline: Baseline
    fadiga: Fadiga = SEM_FADIGA
    qualidade: Qualidade = CAPTURA_CONFIAVEL


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

    def _segmentos(self):
        """(duração efetiva, estado, boca aberta, instante final, houve buraco).

        A duração entre duas amostras é atribuída ao estado da **primeira**: é o
        que sabíamos durante aquele intervalo. Mas só até
        `INTERVALO_MAXIMO_ATRIBUIVEL` — o excedente é tempo sobre o qual não
        temos observação nenhuma, e não entra em conta alguma.
        """
        teto = INTERVALO_MAXIMO_ATRIBUIVEL.total_seconds()
        amostras = list(self._amostras)
        for (t0, estado, boca), (t1, _, _) in zip(amostras, amostras[1:]):
            bruto = (t1 - t0).total_seconds()
            yield min(bruto, teto), estado, boca, t1, bruto > teto

    def _recencia(self, fim: datetime, agora: datetime) -> float:
        """Peso de um episódio pelo quanto ele é recente, de 1 a 0.

        Sem isto a penalidade é um degrau: um cochilo de quatro segundos cobra
        os mesmos 15 pontos no segundo seguinte e 59 segundos depois, e some de
        uma vez. Numa sessão real medida em 28/08, três episódios espaçados
        deixaram 88 das 92 leituras com penalidade cheia — o número parava de
        informar quando o aluno estava piorando ou se recuperando.
        """
        idade = (agora - fim).total_seconds()
        return _entre_zero_e_um(1.0 - idade / self._janela.total_seconds())

    def _avaliar(self) -> Fadiga:
        if len(self._amostras) < 2:
            return SEM_FADIGA

        agora = self._amostras[-1][0]
        observado = 0.0          # tempo com rosto
        fechado = 0.0            # tempo com pálpebra fechada
        episodios_longos = []    # (duração, fim) dos fechamentos que viram microssono
        bocejos_datados = []     # fim de cada bocejo confirmado
        corrida, corrida_fim = 0.0, agora
        maior_corrida = 0.0
        bocejo_atual, bocejo_fim = 0.0, agora

        def fecha_corrida():
            nonlocal corrida, maior_corrida
            maior_corrida = max(maior_corrida, corrida)
            if corrida >= DURACAO_MICROSSONO.total_seconds():
                episodios_longos.append((corrida, corrida_fim))
            corrida = 0.0

        def fecha_bocejo():
            """Um bocejo é datado pelo **fim**, não pelo instante em que passa
            dos 2 s. Datá-lo na largada faria um bocejo ainda em curso perder
            peso enquanto acontece, que é o oposto do que deveria."""
            nonlocal bocejo_atual
            if bocejo_atual >= DURACAO_MINIMA_BOCEJO.total_seconds():
                bocejos_datados.append(bocejo_fim)
            bocejo_atual = 0.0

        for duracao, estado, boca, fim, houve_buraco in self._segmentos():
            if estado != AUSENTE:
                observado += duracao

            # **Olho fechado durante bocejo não é cochilo.** Gente fecha os olhos
            # ao bocejar — numa sessão real de 28/08, o bocejo derrubou o EAR a
            # 0,095 e o mesmo evento cobrou duas vezes: 8 pontos de bocejo mais
            # 15 de microssono. É o mesmo erro de categoria já corrigido entre
            # PERCLOS e microssono, agora entre bocejo e microssono: o
            # fechamento aqui é parte do bocejo, que já está sendo cobrado.
            if estado == FECHADO and not boca:
                fechado += duracao
                corrida += duracao
                corrida_fim = fim
            else:
                # Ausência interrompe a corrida: não dá para afirmar que a
                # pálpebra continuou fechada enquanto o rosto sumiu.
                fecha_corrida()

            if boca:
                bocejo_atual += duracao
                bocejo_fim = fim
            else:
                fecha_bocejo()

            # Um buraco não deixa afirmar continuidade de coisa alguma.
            if houve_buraco:
                fecha_corrida()
                fecha_bocejo()
        fecha_corrida()
        fecha_bocejo()

        # **Um evento não é cobrado duas vezes.** Um fechamento de quatro
        # segundos já é penalizado como microssono; deixá-lo também no PERCLOS
        # faria a mesma pálpebra pagar dois preços — e foi o que inflou o PERCLOS
        # a 15,2% na sessão real, quando o piscar involuntário dava 3,3%. O
        # PERCLOS passa a medir o que sobra: o fechamento difuso.
        tempo_longo = sum(duracao for duracao, _ in episodios_longos)
        difuso = max(0.0, fechado - tempo_longo)
        base = max(0.0, observado - tempo_longo)
        perclos = difuso / base if base > 0 else 0.0

        motivos: List[str] = []
        fator = 0.0

        if perclos > PERCLOS_LIMIAR:
            excedente = (perclos - PERCLOS_LIMIAR) / (PERCLOS_SATURACAO - PERCLOS_LIMIAR)
            fator += PENALIDADE_PERCLOS_MAX * _entre_zero_e_um(excedente)
            motivos.append("palpebras-pesadas")

        if episodios_longos:
            # O episódio mais penalizante manda, e não a soma: dois cochilos não
            # são o dobro de um: são o mesmo estado observado duas vezes.
            fator += max(
                PENALIDADE_MICROSSONO * self._recencia(fim, agora)
                for _, fim in episodios_longos
            )
            motivos.append("olhos-fechados-prolongados")

        if bocejos_datados:
            fator += sum(
                PENALIDADE_POR_BOCEJO * self._recencia(fim, agora) for fim in bocejos_datados
            )
            motivos.append("bocejos")

        return Fadiga(
            fator=min(fator, FADIGA_MAXIMA),
            perclos=perclos,
            maior_fechamento_s=maior_corrida,
            bocejos=len(bocejos_datados),
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
        self._incerteza = DetectorDeIncerteza()

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
    ) -> ResultadoIEE:
        """Registra uma leitura e devolve o IEE do instante."""
        agora = agora or agora_utc()
        qualidade = self._incerteza.observar(
            ear=ear, rosto_detectado=rosto_detectado, agora=agora
        )

        # **Leitura não confiável não alimenta nada.** Calibrar contra landmarks
        # instáveis fixaria uma baseline ruim para a sessão inteira, e um EAR que
        # salta produziria fechamentos e microssonos que nunca aconteceram. O
        # buraco que isso abre nas janelas é tratado como tempo não observado,
        # que é exatamente o que ele é.
        if qualidade.confiavel:
            if self._baseline is None:
                self._acumular(ear, yaw, rosto_detectado, agora)

        baseline = self._baseline or BASELINE_PROVISORIA
        if qualidade.confiavel:
            self._ultima_fadiga = self._fadiga.observar(
                agora=agora, ear=ear, baseline=baseline, mar=mar, rosto_detectado=rosto_detectado
            )
        else:
            # **Captura duvidosa não afirma fadiga.** Manter o último valor
            # medido congelaria uma penalidade que ninguém consegue mais
            # verificar, e ela ficaria de pé pelo tempo que a captura levasse a
            # melhorar. "Não sabemos" vale para tudo o que se derivaria daquela
            # leitura, não só para o score.
            #
            # A janela do detector não é limpa: quando a captura voltar, o
            # histórico anterior à instabilidade continua lá e a fadiga real
            # reaparece — o buraco no meio é tratado como tempo não observado.
            self._ultima_fadiga = SEM_FADIGA

        return ResultadoIEE(
            score=calcular_iee(
                ear=ear,
                yaw=yaw,
                baseline=baseline,
                rosto_detectado=rosto_detectado,
                fadiga=self._ultima_fadiga.fator,
            ),
            calibrando=self._baseline is None,
            baseline=baseline,
            fadiga=self._ultima_fadiga,
            qualidade=qualidade,
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
        # Casado com a inatividade da sessão: enquanto a sessão pode estar viva,
        # a baseline dela também precisa estar.
        return self._validade or timedelta(minutes=settings.sessao_inatividade_minutos)

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
