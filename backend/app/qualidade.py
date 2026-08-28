"""Confiabilidade da captura: o alerta de Incerteza de Captura (ticket 10).

Módulo separado de propósito. `analista.py` responde *quanto* o aluno está
engajado; aqui se responde uma pergunta anterior e diferente: **dá para
confiar nesta medição?** Misturar as duas faria o score carregar a dúvida sobre
si mesmo, quando o que o produto precisa é justamente distinguir "o aluno se
dispersou" de "a câmera não conseguiu ver".

**Não afirmamos a causa.** A ticket fala em baixa luz, óculos reflexivos e
oclusão, mas nada do que chega ao backend distingue os três — só coordenadas
numéricas. O que dá para afirmar é que a captura ficou instável, e é isso que o
nome do alerta diz. Prometer o diagnóstico da causa seria inventar.

Dois sinais, ambos calibrados contra sessões reais de webcam de 28/08/2026:

**Detecção instável.** Sumiços curtos e repetidos do rosto. Quem se levanta
produz uma ausência longa e única; landmarks que não se firmam produzem
piscadas de detecção. Nas sessões boas medidas houve *zero* sumiços breves — a
única ausência foi o aluno saindo do quadro por cinco segundos seguidos.

**Medida instável.** O EAR pulando de leitura para leitura muito além do
fisiológico. Nas sessões boas, o jitter **mediano** entre leituras vizinhas foi
0,034, com p90 de 0,095 — e isso já incluindo um bocejo deliberado, que produz
saltos legítimos. Usar a mediana, e não a média, é o que impede que um único
bocejo ou piscada dispare o alerta: para a mediana subir, a maioria dos pares
precisa estar saltando.
"""
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import median
from typing import Deque, List, Optional, Tuple

from app.tempo import agora_utc

#: Janela sobre a qual a qualidade é avaliada. Menor que a da fadiga: a captura
#: piora e melhora rápido — uma nuvem passa, o aluno se mexe — e uma janela
#: longa demais manteria o alerta de pé depois de a condição já ter passado.
JANELA_QUALIDADE = timedelta(seconds=30)

#: Ausência até esta duração conta como "sumiço breve", o sintoma de detecção
#: instável. Acima disso é o aluno tendo saído de fato, que não é problema de
#: captura e já é tratado pelo `P(t) = 0` da ticket 7.
DURACAO_SUMICO_BREVE = timedelta(seconds=3)

#: Quantos sumiços breves na janela caracterizam detecção instável. Nas sessões
#: reais medidas houve zero; três é folgado o suficiente para não disparar com
#: um tropeço isolado do detector.
MINIMO_SUMICOS_BREVES = 3

#: Jitter mediano do EAR acima do qual a medida não é confiável. As sessões boas
#: deram 0,034 de mediana; 0,10 é o triplo disso, e exige que a *maioria* dos
#: pares vizinhos esteja saltando — não um bocejo isolado.
LIMIAR_JITTER_MEDIANO = 0.10

#: Abaixo disto a janela é curta demais para uma mediana significar algo, e o
#: começo de toda sessão seria marcado como incerto.
MINIMO_DE_AMOSTRAS = 8

#: O rótulo que chega ao aluno. Um só, porque é uma coisa só que ele precisa
#: saber: o número daquele trecho não é confiável.
ALERTA_INCERTEZA = "incerteza-de-captura"

MOTIVO_DETECCAO = "deteccao-instavel"
MOTIVO_MEDIDA = "medida-instavel"


@dataclass(frozen=True)
class Qualidade:
    """O veredito sobre a captura, e a evidência que o sustenta.

    `motivo` existe para diagnóstico e calibração — é o que permite descobrir,
    depois de uma sessão ruim, qual dos dois sinais disparou. O aluno vê só o
    alerta.
    """

    confiavel: bool
    motivo: Optional[str] = None
    sumicos_breves: int = 0
    jitter_mediano: float = 0.0

    @property
    def alertas(self) -> Tuple[str, ...]:
        return () if self.confiavel else (ALERTA_INCERTEZA,)


CAPTURA_CONFIAVEL = Qualidade(confiavel=True)


class DetectorDeIncerteza:
    """Avalia se dá para confiar na captura dos últimos 30 segundos."""

    def __init__(self, janela: timedelta = JANELA_QUALIDADE) -> None:
        self._janela = janela
        #: (instante, rosto detectado, ear) — `ear` é `None` sem rosto.
        self._amostras: Deque[Tuple[datetime, bool, Optional[float]]] = deque()

    def observar(
        self,
        ear: float,
        rosto_detectado: bool = True,
        agora: Optional[datetime] = None,
    ) -> Qualidade:
        agora = agora or agora_utc()
        self._amostras.append((agora, rosto_detectado, ear if rosto_detectado else None))
        self._descartar_antigas(agora)
        return self._avaliar()

    def _descartar_antigas(self, agora: datetime) -> None:
        corte = agora - self._janela
        while len(self._amostras) > 1 and self._amostras[0][0] < corte:
            self._amostras.popleft()

    def _contar_sumicos_breves(self) -> int:
        """Episódios de ausência que começaram e terminaram dentro da janela.

        Uma ausência ainda em curso no fim da janela **não** conta: enquanto ela
        não termina, não dá para saber se foi um tropeço do detector ou o aluno
        tendo se levantado, e chutar o primeiro produziria alerta de captura toda
        vez que alguém saísse da mesa.
        """
        breves = 0
        inicio: Optional[datetime] = None

        for instante, presente, _ in self._amostras:
            if not presente and inicio is None:
                inicio = instante
            elif presente and inicio is not None:
                if instante - inicio <= DURACAO_SUMICO_BREVE:
                    breves += 1
                inicio = None
        return breves

    def _jitter_mediano(self) -> float:
        ears: List[float] = [ear for _, presente, ear in self._amostras if presente and ear is not None]
        if len(ears) < 3:
            return 0.0
        return median(abs(b - a) for a, b in zip(ears, ears[1:]))

    def _avaliar(self) -> Qualidade:
        if len(self._amostras) < MINIMO_DE_AMOSTRAS:
            return CAPTURA_CONFIAVEL

        sumicos = self._contar_sumicos_breves()
        jitter = self._jitter_mediano()

        # A detecção instável manda quando os dois disparam: sem rosto firme, o
        # EAR nem chega a ser medido de forma comparável, então o jitter é
        # consequência e não causa.
        if sumicos >= MINIMO_SUMICOS_BREVES:
            motivo = MOTIVO_DETECCAO
        elif jitter > LIMIAR_JITTER_MEDIANO:
            motivo = MOTIVO_MEDIDA
        else:
            return Qualidade(
                confiavel=True, sumicos_breves=sumicos, jitter_mediano=jitter
            )

        return Qualidade(
            confiavel=False,
            motivo=motivo,
            sumicos_breves=sumicos,
            jitter_mediano=jitter,
        )
