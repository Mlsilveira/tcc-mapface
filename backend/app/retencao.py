"""Sumarização e retenção dos logs de engajamento (ticket 13).

Uma sessão de uma hora grava 3600 linhas, uma por segundo. Guardar isso para
sempre, para toda sessão de todo aluno, é acumular dado bruto sem uso — e o spec
é explícito ao pedir que os logs granulares sejam resumidos em médias depois do
fim da sessão.

**A sumarização colapsa, não copia.** As linhas granulares de uma janela viram
uma linha só, com as médias da janela, e as originais são apagadas. Copiar para
uma tabela de resumos e manter as granulares não reduziria nada — só duplicaria.

**A janela é de um minuto.** O gráfico do relatório continua legível: uma sessão
de uma hora vira 60 pontos em vez de 3600, o que é mais do que qualquer tela
consegue desenhar de forma distinguível. O que se perde é a resolução de
segundo, que só importa durante a sessão — e durante a sessão os logs ainda
estão granulares, porque a sumarização só roda depois do encerramento.

**A varredura é preguiçosa**, no mesmo espírito de `sessoes.encerrar_inativas`:
em vez de um processo de fundo, cada operação que já toca a sessão aproveita
para sumarizar o que ficou para trás. É o que garante que uma sessão encerrada
pela varredura de inatividade — que não passa por endpoint nenhum — também seja
resumida, sem precisar de scheduler.
"""
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Sequence

from sqlmodel import Session, select

from app.models import LogEngajamento, SessaoEstudo
from app.tempo import como_utc

#: Tamanho da janela de resumo.
JANELA_RESUMO = timedelta(seconds=60)


def _media(valores: Sequence[float]) -> float:
    return sum(valores) / len(valores) if valores else 0.0


def _resumir_janela(logs: List[LogEngajamento]) -> LogEngajamento:
    """Colapsa as linhas de uma janela numa só, com as médias dela.

    As médias são **ponderadas por `n_leituras`**: resumir de novo uma série que
    já foi resumida não pode dar peso igual a uma linha que vale um segundo e a
    outra que vale um minuto.
    """
    pesos = [log.n_leituras for log in logs]
    total = sum(pesos) or 1

    def ponderada(valores: Sequence[Optional[float]]) -> Optional[float]:
        pares = [(v, p) for v, p in zip(valores, pesos) if v is not None]
        if not pares:
            # Nenhuma leitura da janela teve rosto: `None` continua dizendo
            # "não observado", que é diferente de zero.
            return None
        return sum(v * p for v, p in pares) / sum(p for _, p in pares)

    alertas: Dict[str, None] = {}
    for log in logs:
        for alerta in (log.alerta_gerado or "").split(","):
            if alerta:
                # Dict em vez de set para preservar a ordem de aparição — o
                # relatório lista alertas, e ordem estável evita diff espúrio.
                alertas.setdefault(alerta, None)

    return LogEngajamento(
        id_sessao=logs[0].id_sessao,
        # O horário do resumo é o **início** da janela: é o instante a partir do
        # qual aquelas médias valem, e é o que o eixo do gráfico espera.
        horario_registro=como_utc(logs[0].horario_registro),
        score=sum(log.score * p for log, p in zip(logs, pesos)) / total,
        n_leituras=total,
        fator_fadiga=sum(log.fator_fadiga * p for log, p in zip(logs, pesos)) / total,
        # Basta um instante de fadiga na janela para que a janela tenha tido
        # fadiga: a média já conta o quanto, e zerar o flag por diluição
        # esconderia o episódio do relatório.
        flag_fadiga=any(log.flag_fadiga for log in logs),
        alerta_gerado=",".join(alertas) or None,
        direcao_olhar=ponderada([log.direcao_olhar for log in logs]),
        ear=ponderada([log.ear for log in logs]),
        mar=ponderada([log.mar for log in logs]),
    )


def _janelas(logs: List[LogEngajamento], janela: timedelta) -> List[List[LogEngajamento]]:
    """Agrupa em blocos de `janela`, contados a partir da primeira leitura."""
    if not logs:
        return []

    origem = como_utc(logs[0].horario_registro)
    segundos = janela.total_seconds()
    blocos: Dict[int, List[LogEngajamento]] = {}
    for log in logs:
        indice = int((como_utc(log.horario_registro) - origem).total_seconds() // segundos)
        blocos.setdefault(indice, []).append(log)
    return [blocos[chave] for chave in sorted(blocos)]


def sumarizar_sessao(
    db: Session, sessao: SessaoEstudo, janela: timedelta = JANELA_RESUMO
) -> int:
    """Colapsa os logs de uma sessão encerrada. Devolve quantas linhas ficaram.

    Não faz nada com sessão ainda aberta: resumir no meio da medição jogaria
    fora a resolução de segundo que o dashboard ao vivo está usando naquele
    instante. Idempotente — uma sessão já marcada como resumida é ignorada.
    """
    if sessao.fim is None or sessao.resumida:
        return 0

    logs = list(
        db.exec(
            select(LogEngajamento)
            .where(LogEngajamento.id_sessao == sessao.id)
            .order_by(LogEngajamento.horario_registro)
        ).all()
    )

    resumos = [_resumir_janela(bloco) for bloco in _janelas(logs, janela)]
    for log in logs:
        db.delete(log)
    for resumo in resumos:
        db.add(resumo)

    # A marca é gravada mesmo quando não havia log nenhum: uma sessão sem
    # medição está tão resumida quanto pode ficar, e reexaminá-la a cada
    # varredura seria trabalho perpétuo sobre nada.
    sessao.resumida = True
    db.add(sessao)
    db.commit()
    return len(resumos)


def sumarizar_encerradas(db: Session, janela: timedelta = JANELA_RESUMO) -> List[int]:
    """Sumariza toda sessão encerrada que ainda não passou por aqui.

    Varredura preguiçosa: quem consulta é quem dispara, como em
    `sessoes.encerrar_inativas`. Sem isto, uma sessão encerrada pela varredura
    de inatividade — que não passa por endpoint nenhum — ficaria granular para
    sempre.
    """
    pendentes = db.exec(
        select(SessaoEstudo).where(
            SessaoEstudo.fim.is_not(None),
            SessaoEstudo.resumida == False,  # noqa: E712 — SQLModel exige o ==
        )
    ).all()

    resumidas = []
    for sessao in pendentes:
        sumarizar_sessao(db, sessao, janela)
        resumidas.append(sessao.id)
    return resumidas
