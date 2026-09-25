"""Monta, a partir da telemetria, a janela de 10 segundos que o modelo espera.

Entre o que chega pelo WebSocket — uma leitura por segundo — e o que o
classificador de sonolência recebe — um vetor de 39 números descrevendo dez
segundos — existe uma tradução, e ela mora aqui. É código puro: sem HTTP, sem
banco, sem scikit-learn. O modelo entra por `app.sonolencia`; este módulo não
sabe que ele existe.

**As 39 features são as mesmas do treino, montadas do mesmo jeito.** Os nomes,
a ordem e os limiares vêm de `ml/esquema.py`, e estão repetidos aqui como
constantes porque a trilha de ML não é importável do backend — ela vive noutro
ambiente, com MediaPipe e OpenCV, que não entram na imagem do FastAPI. A cópia é
deliberada e tem teste travando cada valor: se alguém mudar `LIMIAR_OLHOS_FECHADOS`
de um lado e não do outro, o modelo passa a receber uma feature que significa
outra coisa, e o resultado seria um número plausível e errado.

**A janela fecha por relógio, não por contagem.** Dez leituras não são dez
segundos quando a aba foi para segundo plano ou o WebSocket caiu no meio. Fechar
por tempo mantém a unidade comparável com a do treino, onde a janela é uma
fatia de dez segundos de vídeo; e uma janela que perdeu leituras demais é
descartada, pelo mesmo motivo que a última janela incompleta é descartada na
extração: `n_frames` é feature, e o desvio de uma janela pela metade não é
comparável ao de uma inteira.

**A calibração é a mesma dos primeiros 60 segundos da sessão.** O modelo foi
treinado com as features centradas na mediana das primeiras seis janelas da
gravação — exatamente o que a `AnalistaEngajamento` já faz com EAR e head pose.
Enquanto essas seis janelas não fecham, nenhuma leitura de sonolência é emitida:
não há baseline, e um número sem baseline seria medido contra um rosto genérico,
que é o que a ticket 7 existe para recusar.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import fmean, median, stdev
from typing import Dict, List, Optional, Sequence, Tuple

#: As sete métricas por leitura, na ordem em que o esquema do treino as declara.
METRICAS: Tuple[str, ...] = ("ear_esq", "ear_dir", "ear", "mar", "yaw", "pitch", "roll")

#: As cinco agregações aplicadas a cada métrica. A ordem importa: o vetor de
#: entrada do modelo é posicional.
AGREGACOES: Tuple[str, ...] = ("media", "desvio", "mediana", "min", "max")

#: As quatro features que não são agregação simples de uma métrica.
DERIVADAS: Tuple[str, ...] = (
    "prop_frames_com_rosto",
    "prop_olhos_fechados",
    "prop_boca_aberta",
    "n_frames",
)

#: Espelham `ml/esquema.py`. Ver a nota sobre a cópia no topo do módulo.
LIMIAR_OLHOS_FECHADOS = 0.20
LIMIAR_BOCA_ABERTA = 0.60

#: Duração da janela. Dez segundos é a unidade do treino, que por sua vez é a
#: duração do clipe do DAiSEE — as features só são comparáveis na mesma escala.
DURACAO_DA_JANELA = timedelta(seconds=10)

#: Quantas janelas formam a baseline da sessão. Seis de dez segundos são os
#: mesmos 60 segundos de `analista.DURACAO_CALIBRACAO`.
JANELAS_DE_CALIBRACAO = 6

#: Mínimo de leituras para uma janela valer. Abaixo disso a janela descreve mais
#: a queda de conexão que o aluno.
LEITURAS_MINIMAS = 6


def nomes_das_features() -> List[str]:
    """Os 39 nomes, na ordem canônica — a mesma de `ml/esquema.colunas_features()`."""
    agregadas = [f"{metrica}_{agg}" for metrica in METRICAS for agg in AGREGACOES]
    return agregadas + list(DERIVADAS)


@dataclass(frozen=True)
class Leitura:
    """Uma linha da telemetria, já agregada pelo navegador naquele segundo.

    Os campos são opcionais porque o navegador manda payload válido mesmo sem
    rosto: há quadro de vídeo, não há rosto, e as métricas não existem. `None` é
    ausência de medida — nunca zero, que seria olho fechado e cabeça de frente.
    """

    horario: datetime
    rosto_detectado: bool
    ear: Optional[float] = None
    ear_esq: Optional[float] = None
    ear_dir: Optional[float] = None
    mar: Optional[float] = None
    yaw: Optional[float] = None
    pitch: Optional[float] = None
    roll: Optional[float] = None

    def valor(self, metrica: str) -> Optional[float]:
        return getattr(self, metrica)

    @property
    def mensuravel(self) -> bool:
        """Houve rosto **e** as métricas vieram. Só isso entra nas agregações."""
        return self.rosto_detectado and self.ear is not None


def features_da_janela(leituras: Sequence[Leitura]) -> Dict[str, float]:
    """As 39 features de um conjunto de leituras.

    Leituras sem rosto ficam fora das agregações mas contam em `n_frames` e em
    `prop_frames_com_rosto` — a ausência é um dado, não um buraco. Uma janela
    sem nenhuma leitura mensurável agrega para `nan`, e não para 0,0: zero
    afirmaria "olhos fechados, cabeça de frente", que é uma leitura, e não a
    falta dela.
    """
    if not leituras:
        raise ValueError("janela sem leituras não é agregável")

    com_rosto = [leitura for leitura in leituras if leitura.mensuravel]
    features: Dict[str, float] = {}

    for metrica in METRICAS:
        valores = [
            valor
            for leitura in com_rosto
            if (valor := leitura.valor(metrica)) is not None
        ]
        for agregacao in AGREGACOES:
            features[f"{metrica}_{agregacao}"] = _agrega(valores, agregacao)

    features.update(_derivadas(leituras, com_rosto))
    return features


def _agrega(valores: List[float], agregacao: str) -> float:
    if not valores:
        return float("nan")
    if agregacao == "desvio":
        # Com uma observação só não existe dispersão. `nan`, e não 0,0, que
        # afirmaria uma estabilidade que ninguém mediu — o mesmo que o `ddof=1`
        # do pandas faz na extração.
        return stdev(valores) if len(valores) > 1 else float("nan")
    return {
        "media": fmean,
        "mediana": median,
        "min": min,
        "max": max,
    }[agregacao](valores)


def _derivadas(leituras: Sequence[Leitura], com_rosto: Sequence[Leitura]) -> Dict[str, float]:
    total = len(leituras)
    n_com_rosto = len(com_rosto)

    return {
        "prop_frames_com_rosto": n_com_rosto / total,
        "prop_olhos_fechados": _fracao(
            [l.ear for l in com_rosto if l.ear is not None and l.ear < LIMIAR_OLHOS_FECHADOS],
            n_com_rosto,
        ),
        "prop_boca_aberta": _fracao(
            [l.mar for l in com_rosto if l.mar is not None and l.mar > LIMIAR_BOCA_ABERTA],
            n_com_rosto,
        ),
        "n_frames": float(total),
    }


def _fracao(satisfazem: List[float], n_com_rosto: int) -> float:
    if n_com_rosto == 0:
        return float("nan")
    return len(satisfazem) / n_com_rosto


class AcumuladorDeJanelas:
    """Junta leituras de 1 Hz e devolve a janela calibrada quando ela fecha.

    O ciclo é: as seis primeiras janelas viram baseline e **não** produzem
    saída; da sétima em diante, cada janela fechada sai com a mediana da
    baseline subtraída de cada feature. É a mesma calibração por sessão com que
    o modelo foi treinado.
    """

    def __init__(
        self,
        duracao: timedelta = DURACAO_DA_JANELA,
        janelas_de_calibracao: int = JANELAS_DE_CALIBRACAO,
        leituras_minimas: int = LEITURAS_MINIMAS,
    ) -> None:
        self._duracao = duracao
        self._janelas_de_calibracao = janelas_de_calibracao
        self._leituras_minimas = leituras_minimas

        self._abertas: List[Leitura] = []
        self._inicio: Optional[datetime] = None
        self._calibracao: List[Dict[str, float]] = []
        self._baseline: Optional[Dict[str, float]] = None

    @property
    def calibrando(self) -> bool:
        return self._baseline is None

    @property
    def janelas_de_baseline(self) -> int:
        """Quantas janelas já entraram na baseline — para a interface informar."""
        return len(self._calibracao)

    def observar(self, leitura: Leitura) -> Optional[Dict[str, float]]:
        """Acumula a leitura e devolve as features calibradas se a janela fechou.

        Devolve `None` na maioria das chamadas — só uma em cada dez fecha janela,
        e as seis primeiras que fecham vão para a baseline em vez de sair.
        """
        if self._inicio is None:
            self._inicio = leitura.horario

        # Relógio para trás: aba suspensa e retomada, ou relógio do cliente
        # ajustado. Recomeçar a janela é mais honesto que produzir uma de
        # duração negativa.
        if leitura.horario < self._inicio:
            self._abertas = []
            self._inicio = leitura.horario

        self._abertas.append(leitura)

        if leitura.horario - self._inicio < self._duracao:
            return None

        return self._fechar()

    def _fechar(self) -> Optional[Dict[str, float]]:
        leituras, self._abertas = self._abertas, []
        self._inicio = leituras[-1].horario

        # A leitura que fechou a janela é o primeiro ponto da próxima: ela marca
        # o instante do corte, e descartá-la abriria um vão de um segundo entre
        # janelas consecutivas.
        self._abertas.append(leituras[-1])

        if len(leituras) < self._leituras_minimas:
            return None

        features = features_da_janela(leituras)

        if self._baseline is None:
            self._calibracao.append(features)
            if len(self._calibracao) >= self._janelas_de_calibracao:
                self._baseline = _mediana_das_janelas(self._calibracao)
            return None

        return _centrar(features, self._baseline)


def _mediana_das_janelas(janelas: List[Dict[str, float]]) -> Dict[str, float]:
    """Mediana de cada feature entre as janelas de calibração.

    Mediana e não média pelo mesmo motivo de `analista.Baseline`: um único
    segundo com landmark mal detectado desloca a média e não move a mediana.
    """
    baseline: Dict[str, float] = {}
    for nome in nomes_das_features():
        valores = [j[nome] for j in janelas if _finito(j.get(nome))]
        baseline[nome] = median(valores) if valores else float("nan")
    return baseline


def _centrar(features: Dict[str, float], baseline: Dict[str, float]) -> Dict[str, float]:
    """Subtrai a baseline, deixando `nan` onde não há o que subtrair."""
    return {
        nome: (
            features[nome] - baseline[nome]
            if _finito(features.get(nome)) and _finito(baseline.get(nome))
            else float("nan")
        )
        for nome in nomes_das_features()
    }


def _finito(valor: Optional[float]) -> bool:
    return valor is not None and valor == valor
