"""O classificador de sonolência treinado no UTA-RLDD, dentro da aplicação.

É a única peça do backend que conhece scikit-learn. Tudo o que vem antes —
`app.janela`, que monta as 39 features a partir da telemetria — é aritmética
pura, e tudo o que vem depois recebe um número entre 0 e 1. Essa fronteira é o
que permite testar o ciclo inteiro sem carregar modelo nenhum.

**O que ele responde, e o que não responde.** A pergunta é "esta janela de dez
segundos parece a de alguém sonolento?", treinada contra 60 pessoas que
declararam o próprio estado em três níveis. Não é engajamento: o modelo nunca
viu um rótulo de engajamento, e usá-lo como medida de atenção seria afirmar o
que ele não mede. O desempenho medido é 0,6553 de acurácia balanceada em
validação cruzada por participante — acerta cerca de dois terços, o que é
informação real e está longe de um veredito.

**Ele não decide nada sozinho, e isso é deliberado.** O fator de fadiga que
entra na fórmula do IEE continua vindo das regras do `DetectorDeFadiga` —
PERCLOS, fechamento prolongado, bocejo —, que são objetivas, explicáveis ao
aluno e não dependem de modelo nenhum. A leitura daqui é registrada e mostrada
**ao lado**, como segunda opinião medida. Promovê-la a decisão é uma linha de
código e uma conversa com a orientação, não um efeito colateral desta entrega.

**A ausência do artefato não derruba nada.** Quem não tiver o `.joblib` — um
checkout sem o modelo, um ambiente sem scikit-learn — roda a aplicação inteira
com a sonolência em `None`, que é a mesma representação de "não dá para afirmar"
que a ticket 10 já usa para a incerteza de captura. A degradação é silenciosa de
propósito: o produto não depende desta leitura para funcionar.
"""
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from app.janela import nomes_das_features

logger = logging.getLogger(__name__)

#: Onde o artefato mora dentro do pacote. Fica junto do código, e não num
#: diretório de dados, porque ele é versionado com o backend: um modelo e um
#: código que esperam features diferentes produzem número plausível e errado,
#: então os dois precisam andar no mesmo commit.
CAMINHO_PADRAO = Path(__file__).parent / "modelos" / "sonolencia.joblib"

#: Acima disto a janela é classificada como sonolenta. Meio a meio porque o
#: modelo foi treinado com classes equilibradas e avaliado neste corte — mover o
#: limiar sem refazer a medição trocaria um número medido por um palpite.
LIMIAR_DE_SONOLENCIA = 0.5


@dataclass(frozen=True)
class LeituraDeSonolencia:
    """O que o modelo diz sobre uma janela de dez segundos.

    A probabilidade é o que se registra e se mostra; `sonolento` é só ela
    comparada ao limiar. Guardar o número contínuo, e não apenas o booleano, é o
    que permite ao relatório desenhar uma curva em vez de uma sequência de
    acendeu/apagou — e o que permitiria mudar o limiar depois sem reprocessar
    sessão nenhuma.
    """

    probabilidade: float
    sonolento: bool


class ClassificadorDeSonolencia:
    """Envolve o pipeline do scikit-learn no vocabulário da aplicação."""

    def __init__(self, estimador, colunas: List[str], indice_positivo: int) -> None:
        self._estimador = estimador
        self._colunas = list(colunas)
        self._indice_positivo = indice_positivo

    def avaliar(self, features: Dict[str, float]) -> LeituraDeSonolencia:
        """A probabilidade de sonolência para uma janela já calibrada.

        As colunas são reordenadas para a ordem com que o modelo treinou. Sem
        isso, um dicionário com as mesmas chaves noutra ordem preveria errado
        sem reclamar de nada — o estimador recebe posições, não nomes.
        """
        import pandas as pd

        faltando = [coluna for coluna in self._colunas if coluna not in features]
        if faltando:
            raise ValueError(f"features faltando para classificar: {faltando}")

        linha = pd.DataFrame([[features[coluna] for coluna in self._colunas]], columns=self._colunas)
        probabilidade = float(self._estimador.predict_proba(linha)[0][self._indice_positivo])

        return LeituraDeSonolencia(
            probabilidade=probabilidade,
            sonolento=probabilidade >= LIMIAR_DE_SONOLENCIA,
        )


#: Cache por caminho. São ~4,5 MB de árvores e alguns segundos de `joblib.load`,
#: e o estimador não guarda estado entre predições — reler por sessão custaria
#: tempo e memória sem mudar resposta nenhuma.
_CARREGADOS: Dict[str, Optional["ClassificadorDeSonolencia"]] = {}


def esquecer_cache() -> None:
    """Descarta o que foi carregado. Existe para o teste trocar de artefato."""
    _CARREGADOS.clear()


def carregar(caminho: Optional[Path] = None) -> Optional[ClassificadorDeSonolencia]:
    """Carrega o artefato, ou devolve `None` se ele não puder ser usado.

    **Devolve `None` em vez de levantar** porque a alternativa seria um backend
    que se recusa a subir por causa de uma leitura secundária. A sessão de
    estudo, o IEE, o fator de fadiga por regras e o relatório inteiro funcionam
    sem isto; derrubar tudo por um arquivo ausente trocaria uma degradação
    graciosa por uma indisponibilidade.

    O que acontece fica no log, e não em silêncio: um modelo que sumiu em
    produção precisa aparecer em algum lugar.
    """
    caminho = caminho or CAMINHO_PADRAO
    if str(caminho) in _CARREGADOS:
        return _CARREGADOS[str(caminho)]

    _CARREGADOS[str(caminho)] = _carregar(caminho)
    return _CARREGADOS[str(caminho)]


def _carregar(caminho: Path) -> Optional[ClassificadorDeSonolencia]:
    if not caminho.is_file():
        logger.info("classificador de sonolência ausente em %s; seguindo sem ele", caminho)
        return None

    try:
        import joblib
    except ImportError:
        logger.info("scikit-learn não instalado; seguindo sem o classificador de sonolência")
        return None

    try:
        artefato = joblib.load(caminho)
        estimador = artefato["estimador"]
        colunas = list(artefato["colunas"])
        rotulos = [int(r) for r in artefato["rotulos"]]
    except Exception:  # noqa: BLE001 — artefato corrompido, de versão antiga, o que for
        logger.exception("não foi possível carregar o classificador de sonolência")
        return None

    esperadas = nomes_das_features()
    if sorted(colunas) != sorted(esperadas):
        # O modelo e o montador de janelas discordam sobre o que é uma feature.
        # Recusar é obrigatório: preencher o que falta com zero produziria uma
        # previsão bem-comportada sobre uma entrada que ninguém mediu.
        logger.error(
            "o classificador espera features diferentes das que a janela monta; "
            "faltando=%s sobrando=%s",
            sorted(set(colunas) - set(esperadas)),
            sorted(set(esperadas) - set(colunas)),
        )
        return None

    if 1 not in rotulos:
        logger.error("o classificador não tem a classe positiva: rotulos=%s", rotulos)
        return None

    logger.info("classificador de sonolência carregado de %s", caminho)
    return ClassificadorDeSonolencia(
        estimador=estimador, colunas=colunas, indice_positivo=rotulos.index(1)
    )
