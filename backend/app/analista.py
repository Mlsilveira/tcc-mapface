"""Núcleo de inferência do IEE — o seam principal do projeto (ticket 7).

Este módulo existe para que a regra que define o Índice de Engajamento no Estudo
não fique presa a WebSocket, banco ou UI: ele não importa `sqlmodel`, `fastapi`
nem `app.models`, e por isso pode ser exercitado com vetores sintéticos, sem
subir nada. É o módulo que o spec chama de mais valioso para testar isolado.

Duas decisões moldam a forma da classe:

**O tempo entra por parâmetro.** `processar` recebe `agora` em vez de chamar
`datetime.now()`, como já fazem `app/sessoes.py` e `app/tempo.py`. É o que torna
a janela de 60 segundos da calibração testável sem `sleep`.

**O analista não guarda estado entre payloads.** Ele nasce com o que veio do
banco (baseline e acumulador de calibração), devolve no `Resultado` a versão
atualizada e morre. Quem chama persiste. Assim uma reconexão de WebSocket no
meio da calibração não perde o minuto já medido: o estado é um dado
serializável, não um objeto vivo na memória do processo.

Por que normalizar contra a baseline individual, e não contra constantes: um
aluno de óculos tem o EAR achatado pela armação e pelo reflexo, e alguém com
assimetria facial tem uma pose neutra que não é o frontal perfeito. Medidos
contra um padrão "típico", os dois pareceriam permanentemente dispersos —
alertas injustos, que é justamente o que a história 13 do spec proíbe.
"""
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

PESO_OCULAR = 0.6
PESO_ORIENTACAO = 0.4

#: Duração da janela de calibração, fixada pelo spec (histórias 12 a 14): tempo
#: suficiente para o aluno acomodar postura e piscar várias vezes, e curto o
#: bastante para não comer uma fatia relevante da sessão de estudo.
DURACAO_CALIBRACAO_SEGUNDOS = 60

#: Desvio angular, em graus, a partir do qual a cabeça não contribui mais para o
#: índice. Herdado da constante provisória da ticket 6: virar ~45° em relação à
#: própria pose neutra já é olhar para fora da tela.
DESVIO_ANGULAR_MAXIMO_GRAUS = 45.0

#: Piso para o divisor da normalização ocular. Um olho aberto, mesmo achatado
#: por óculos, não desce a esse patamar — abaixo disso a medida é indistinguível
#: de olho fechado ou de captura ruim, e usá-la como divisor faria quase
#: qualquer EAR normalizar em 1,0, isto é, "olho fechado = plenamente engajado".
EAR_NEUTRO_MINIMO = 0.10

SCORE_MINIMO = 0.0
SCORE_MAXIMO = 100.0


@dataclass(frozen=True)
class Baseline:
    """O padrão neutro do aluno, medido nos primeiros 60s da sessão dele."""

    ear_neutro: float
    yaw_neutro: float
    pitch_neutro: float
    amostras: int


@dataclass(frozen=True)
class EstadoCalibracao:
    """Acumulador da calibração em andamento — serializável, para sobreviver a
    reconexão. Guarda somas em vez de médias para que cada payload novo entre
    com uma adição, sem precisar reprocessar o que já passou."""

    inicio: datetime
    soma_ear: float
    soma_yaw: float
    soma_pitch: float
    amostras: int


@dataclass(frozen=True)
class Resultado:
    score: float
    calibrando: bool
    baseline: Optional[Baseline]
    estado: Optional[EstadoCalibracao]


#: Referências usadas enquanto a baseline do aluno ainda não existe. São as
#: mesmas constantes provisórias da ticket 6 (`app/telemetria.py`), repetidas
#: aqui porque aquele módulo importa `sqlmodel` e este seam não pode depender de
#: banco. "Calibração silenciosa" quer dizer que o aluno não é interrogado, não
#: que o score suma: durante o primeiro minuto o dashboard da ticket 9 mostra um
#: número calculado contra este padrão genérico, e não uma tela em branco.
BASELINE_PADRAO = Baseline(ear_neutro=0.30, yaw_neutro=0.0, pitch_neutro=0.0, amostras=0)


class AnalistaEngajamento:
    """Calcula o IEE de um payload de telemetria, calibrando-se pelo aluno.

    `IEE(t) = P(t) × [(0,6 × EAR_norm) + (0,4 × HP_norm)] − F`, em escala 0–100.
    """

    def __init__(
        self,
        baseline: Optional[Baseline] = None,
        estado: Optional[EstadoCalibracao] = None,
    ) -> None:
        self._baseline = baseline
        self._estado = estado

    def processar(
        self,
        ear: float,
        yaw: float,
        pitch: float,
        rosto_detectado: bool,
        agora: datetime,
        fadiga: float = 0.0,
    ) -> Resultado:
        """Devolve o score do instante e o estado de calibração a persistir.

        `fadiga` é a penalidade `F` da fórmula, em pontos da mesma escala 0–100
        do score — 0 até a ticket 8 entregar o classificador. Fica como
        parâmetro, e não embutida, para que o encaixe já exista sem que este
        módulo precise conhecer o Random Forest.
        """
        if not rosto_detectado:
            # É o P(t) = 0 do spec, e vale dentro e fora da calibração: sem
            # rosto não há comportamento observável, e devolver um número
            # degradado seria invenção.
            if self._baseline is not None:
                return Resultado(
                    score=0.0,
                    calibrando=False,
                    baseline=self._baseline,
                    estado=None,
                )

            # Ausência no meio da calibração: o acumulado é descartado e a
            # janela recomeça quando o rosto voltar (história 14 do spec).
            # Calibrar com o minuto pela metade produziria uma baseline que não
            # representa ninguém.
            #
            # Um único payload sem rosto já descarta, sem tolerância: a 1 Hz um
            # payload é um segundo inteiro sem rosto observável, e o acumulador
            # é um dado serializado no banco — uma tolerância precisaria de um
            # contador de ausências que ele não tem, e um contador que vivesse
            # só na memória se perderia na reconexão, tornando o critério
            # silenciosamente diferente conforme a rede. O custo do rigor é
            # baixo: refazer 60 segundos silenciosos de uma sessão de estudo.
            return Resultado(score=0.0, calibrando=True, baseline=None, estado=None)

        if self._baseline is not None:
            return self._pontuar(
                self._baseline, ear, yaw, pitch, fadiga, calibrando=False, estado=None
            )

        estado = self._acumular(ear, yaw, pitch, agora)

        if not self._janela_encerrada(estado, agora):
            return self._pontuar(
                BASELINE_PADRAO, ear, yaw, pitch, fadiga, calibrando=True, estado=estado
            )

        baseline = self._media(estado)
        return self._pontuar(
            baseline, ear, yaw, pitch, fadiga, calibrando=False, estado=None
        )

    def _acumular(
        self, ear: float, yaw: float, pitch: float, agora: datetime
    ) -> EstadoCalibracao:
        anterior = self._estado
        if anterior is None:
            # Primeiro payload com rosto da sessão (ou o primeiro depois de uma
            # ausência): é ele que marca o início da janela de 60 segundos.
            return EstadoCalibracao(
                inicio=agora,
                soma_ear=ear,
                soma_yaw=yaw,
                soma_pitch=pitch,
                amostras=1,
            )

        return EstadoCalibracao(
            inicio=anterior.inicio,
            soma_ear=anterior.soma_ear + ear,
            soma_yaw=anterior.soma_yaw + yaw,
            soma_pitch=anterior.soma_pitch + pitch,
            amostras=anterior.amostras + 1,
        )

    @staticmethod
    def _janela_encerrada(estado: EstadoCalibracao, agora: datetime) -> bool:
        return agora - estado.inicio >= timedelta(seconds=DURACAO_CALIBRACAO_SEGUNDOS)

    @staticmethod
    def _media(estado: EstadoCalibracao) -> Baseline:
        return Baseline(
            ear_neutro=estado.soma_ear / estado.amostras,
            yaw_neutro=estado.soma_yaw / estado.amostras,
            pitch_neutro=estado.soma_pitch / estado.amostras,
            amostras=estado.amostras,
        )

    @staticmethod
    def _pontuar(
        baseline: Baseline,
        ear: float,
        yaw: float,
        pitch: float,
        fadiga: float,
        calibrando: bool,
        estado: Optional[EstadoCalibracao],
    ) -> Resultado:
        # A baseline guarda o que foi medido; é aqui, na hora de dividir, que a
        # medida degenerada é contida — o registro da calibração continua fiel.
        divisor = max(baseline.ear_neutro, EAR_NEUTRO_MINIMO)
        ear_norm = min(ear / divisor, 1.0)

        # Head Pose é yaw *e* pitch. Os dois viram um desvio angular único pela
        # norma euclidiana no plano yaw/pitch: virar 30° para o lado e 30° para
        # baixo ao mesmo tempo afasta mais da tela do que 30° num eixo só, e a
        # combinação não privilegia nenhum dos eixos.
        desvio = math.hypot(yaw - baseline.yaw_neutro, pitch - baseline.pitch_neutro)
        hp_norm = 1.0 - min(desvio / DESVIO_ANGULAR_MAXIMO_GRAUS, 1.0)

        bruto = 100.0 * (PESO_OCULAR * ear_norm + PESO_ORIENTACAO * hp_norm) - fadiga

        return Resultado(
            score=_na_escala(bruto),
            calibrando=calibrando,
            baseline=None if calibrando else baseline,
            estado=estado,
        )


def _na_escala(valor: float) -> float:
    """Prende o score em [0, 100].

    O teto protege de um EAR atípico; o piso é o que impede a subtração do fator
    de fadiga (ticket 8) de produzir score negativo.
    """
    return max(SCORE_MINIMO, min(valor, SCORE_MAXIMO))
