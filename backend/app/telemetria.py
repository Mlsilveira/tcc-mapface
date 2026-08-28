"""Persistência da série de engajamento de uma sessão (ticket 6).

Como `app/sessoes.py`, este módulo não conhece HTTP nem WebSocket.

O **cálculo** do score morava aqui na ticket 6, como fórmula provisória contra
constantes iguais para todo mundo. A ticket 7 o moveu para `app/analista.py`,
onde ele passou a ser medido contra a baseline calibrada de cada aluno. O que
sobra aqui é o que sempre foi de persistência: gravar e ler os pontos da série.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Sequence

from sqlalchemy import func
from sqlmodel import Session, select

from app.models import LogEngajamento
from app.tempo import agora_utc


def registrar_log(
    db: Session,
    id_sessao: int,
    score: float,
    agora: Optional[datetime] = None,
    fator_fadiga: float = 0.0,
    alertas: Sequence[str] = (),
    direcao_olhar: Optional[float] = None,
    ear: Optional[float] = None,
    mar: Optional[float] = None,
    captura_confiavel: bool = True,
) -> LogEngajamento:
    """Grava um ponto da série de engajamento da sessão.

    Tudo além de `score` tem default porque a série continua fazendo sentido sem
    esses campos: um payload sem `mar` não produz alerta de bocejo, e um instante
    sem rosto não produz direção de olhar. Gravar zero ou vazio ali é registrar o
    que de fato se observou, e não um buraco.

    `alertas` chega como sequência e é achatado numa string separada por vírgula.
    A alternativa — uma tabela de alertas por log — seria a modelagem correta se
    alertas tivessem atributos próprios; eles não têm, são rótulos. Uma tabela
    para guardar rótulo custaria um join em toda leitura do relatório para não
    guardar nada a mais.
    """
    log = LogEngajamento(
        id_sessao=id_sessao,
        score=score,
        horario_registro=agora or agora_utc(),
        fator_fadiga=fator_fadiga,
        # O flag é derivado aqui, num lugar só, para não haver como gravar uma
        # linha em que ele discorde do fator.
        flag_fadiga=fator_fadiga > 0,
        alerta_gerado=",".join(alertas) or None,
        direcao_olhar=direcao_olhar,
        ear=ear,
        mar=mar,
        captura_confiavel=captura_confiavel,
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


@dataclass(frozen=True)
class AgregadoDaSessao:
    """Os números de uma sessão, sem carregar a série inteira dela."""

    n_leituras: int
    score_medio: float
    teve_fadiga: bool


def agregar_por_sessao(db: Session, ids: Sequence[int]) -> Dict[int, AgregadoDaSessao]:
    """Resumo de várias sessões numa **única** consulta (ticket 12).

    O histórico precisa mostrar como foi cada sessão, e montar o relatório
    completo de cada uma para isso seria uma consulta por linha da lista — o
    N+1 clássico, que numa tela de 50 sessões vira 51 idas ao banco e carrega
    dezenas de milhares de logs para calcular três números.

    A média é **ponderada por `n_leituras`**, pela mesma razão do relatório:
    depois da sumarização da ticket 13 uma linha pode valer um minuto inteiro, e
    tratá-la como uma leitura faria o mesmo histórico mudar de número conforme
    as sessões fossem sendo resumidas.
    """
    if not ids:
        return {}

    peso = func.sum(LogEngajamento.n_leituras)
    linhas = db.exec(
        select(
            LogEngajamento.id_sessao,
            peso,
            func.sum(LogEngajamento.score * LogEngajamento.n_leituras),
            func.max(LogEngajamento.flag_fadiga),
        )
        .where(LogEngajamento.id_sessao.in_(ids))
        .group_by(LogEngajamento.id_sessao)
    ).all()

    return {
        id_sessao: AgregadoDaSessao(
            n_leituras=int(total or 0),
            score_medio=float(soma) / float(total) if total else 0.0,
            teve_fadiga=bool(fadiga),
        )
        for id_sessao, total, soma, fadiga in linhas
    }


def buscar_logs(db: Session, id_sessao: int) -> List[LogEngajamento]:
    """Série de engajamento de uma sessão, em ordem cronológica."""
    return db.exec(
        select(LogEngajamento)
        .where(LogEngajamento.id_sessao == id_sessao)
        .order_by(LogEngajamento.horario_registro)
    ).all()
