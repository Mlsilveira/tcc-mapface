"""Persistência da série de engajamento de uma sessão (ticket 6).

Como `app/sessoes.py`, este módulo não conhece HTTP nem WebSocket.

O **cálculo** do score morava aqui na ticket 6, como fórmula provisória contra
constantes iguais para todo mundo. A ticket 7 o moveu para `app/analista.py`,
onde ele passou a ser medido contra a baseline calibrada de cada aluno. O que
sobra aqui é o que sempre foi de persistência: gravar e ler os pontos da série.
"""

from datetime import datetime
from typing import List, Optional

from sqlmodel import Session, select

from app.models import LogEngajamento
from app.tempo import agora_utc


def registrar_log(
    db: Session,
    id_sessao: int,
    score: Optional[float],
    fadiga: float = 0.0,
    alerta: Optional[str] = None,
    agora: Optional[datetime] = None,
) -> LogEngajamento:
    """Grava um ponto da série de engajamento da sessão.

    `score=None` é o ponto de incerteza da ticket 10: a leitura chegou, foi
    registrada no tempo certo, e não produziu número. O ponto existe para que o
    relatório da ticket 11 consiga dizer "aqui não deu para medir" em vez de
    apresentar um buraco indistinguível de uma pausa.

    **`flush` + `expunge` no lugar do `refresh` depois do `commit`.** Era
    `commit(); refresh(log)`, e esse par é caro justamente aqui: `commit`
    devolve a conexão ao pool e invalida os atributos carregados; o `refresh`
    seguinte **reabre uma transação** para reler a mesma linha que acabou de ser
    escrita, e essa transação fica aberta — com a conexão presa — até alguém
    fechar a sessão. Esta função roda uma vez por segundo por aluno com a webcam
    ligada, então era um `SELECT` por segundo por aluno e uma conexão retida
    entre um payload e o outro.

    A ordem daqui não custa ida-e-volta nenhuma: `flush` emite o `INSERT` que o
    `commit` emitiria de qualquer jeito, e é ele quem preenche o `id` gerado
    pelo banco. `expunge` tira a instância da sessão **antes** do `commit`, que
    é o que a impede de ser invalidada — quem recebe o retorno leva um retrato
    com os valores dentro, em vez de um objeto que dispara consulta no primeiro
    atributo lido.

    *A alternativa descartada* foi simplesmente apagar o `refresh` e devolver o
    objeto como o `commit` o deixa. Seria uma linha a menos e devolveria uma
    instância cujos atributos só existem enquanto a sessão de banco estiver
    aberta — um retorno que funciona em todo teste de hoje e quebra no dia em
    que alguém ler `log.id` depois do `with`.
    """
    log = LogEngajamento(
        id_sessao=id_sessao,
        score=score,
        fadiga=fadiga,
        alerta=alerta,
        horario_registro=agora or agora_utc(),
    )
    db.add(log)
    db.flush()
    db.expunge(log)
    db.commit()
    return log


def buscar_logs(db: Session, id_sessao: int) -> List[LogEngajamento]:
    """Série de engajamento de uma sessão, em ordem cronológica."""
    return db.exec(
        select(LogEngajamento)
        .where(LogEngajamento.id_sessao == id_sessao)
        .order_by(LogEngajamento.horario_registro)
    ).all()
