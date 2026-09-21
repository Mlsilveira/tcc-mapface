"""Sumarização e retenção da série de engajamento (ticket 13).

`log_engajamento` é a tabela que cresce: um ponto por segundo, por aluno, por
sessão. Uma turma de 30 alunos estudando duas horas por dia gera ~6,5 milhões de
linhas por mês, e nada nunca as apaga. Esta ticket fecha isso — sem perder o
relatório, que é o produto da ticket 11 e não pode ser sacrificado à faxina.

**Duas operações, em dois momentos diferentes, e é aí que mora a decisão.**

1. **No encerramento**, os indicadores são calculados sobre a série completa e
   gravados em `resumo_sessao`. Congelar aqui não é otimização: média de médias
   não é média, e recalcular depois sobre a série já colapsada devolveria
   números *parecidos* com os certos. Parecido é a pior categoria de errado num
   relatório que o aluno vai comparar com o da semana passada.

2. **Depois da janela de retenção**, os pontos granulares são colapsados em
   médias por minuto. Não imediatamente, e isso é deliberado: a sessão que o
   aluno acabou de encerrar é justamente a que ele abre em seguida, e uma curva
   por minuto de uma sessão de oito minutos tem oito pontos. Passadas 24 horas o
   valor da série muda de natureza — ninguém revisita o segundo 1.847 de uma
   terça-feira, mas a forma da curva ainda diz algo.

A varredura é **preguiçosa**, no mesmo molde de `sessoes.encerrar_inativas`:
roda quando o aluno abre o histórico, em vez de depender de um scheduler. A PoC
segue sem processo de background, e quem paga o custo é quem se beneficia dele.
Em produção com muitos alunos isto vira job — está anotado na ticket 15.

**`bloco_estudo` fica de fora da retenção, de propósito.** Está escrito aqui
antes que alguém a inclua na faxina por simetria — "é tabela de sessão, some
junto" —, que é o raciocínio que a incluiria. O motivo de `log_engajamento` ser
colapsada é o volume: um ponto por segundo, por aluno, por sessão. Um bloco é
uma linha por transição declarada, algo entre zero e uma dezena por sessão; o
que se ganharia apagando isso não paga nem o `DELETE`. E o que se perderia é o
relatório inteiro do método: as durações dos blocos não são recalculáveis a
partir da série colapsada — é exatamente a impossibilidade silenciosa que fez a
tabela existir, e que o docstring de `models.BlocoEstudo` descreve.
"""
from collections import Counter
from datetime import datetime, timedelta
from statistics import mean
from typing import Dict, List, Optional, Sequence

from sqlmodel import Session, col, delete, select

from app import relatorio, telemetria
from app.models import LogEngajamento, ResumoSessao, SessaoEstudo
from app.tempo import agora_utc, como_utc

#: Por quanto tempo a série fica no detalhe de segundo depois do encerramento.
RETENCAO_GRANULAR = timedelta(hours=24)

#: Resolução da série depois do colapso. Um minuto é a menor janela em que a
#: média ainda descreve comportamento e não ruído de piscada.
JANELA_DE_RESUMO = timedelta(minutes=1)


def registrar_resumo(
    db: Session, sessao: SessaoEstudo, serie: Optional[Sequence[LogEngajamento]] = None
) -> ResumoSessao:
    """Congela os indicadores da sessão recém-encerrada.

    Idempotente: chamada duas vezes para a mesma sessão, a segunda não recalcula
    nada. Isso importa porque o encerramento tem dois caminhos — o clique do
    aluno e a varredura de inatividade — e nada impede que a mesma sessão passe
    pelos dois em sequência, num reload infeliz.
    """
    existente = db.get(ResumoSessao, sessao.id)
    if existente is not None:
        return existente

    if serie is None:
        serie = telemetria.buscar_logs(db, sessao.id)

    resumo = relatorio.resumir(sessao, serie)
    registro = ResumoSessao(
        id_sessao=sessao.id,
        media=resumo.media,
        pico=resumo.pico,
        vale=resumo.vale,
        pontos_medidos=resumo.pontos_medidos,
        pontos_incertos=resumo.pontos_incertos,
        pontos_zerados=resumo.pontos_zerados,
        duracao_presente_s=resumo.duracao_presente.total_seconds(),
        alertas_de_fadiga=dict(resumo.alertas_de_fadiga),
        motivos_de_incerteza=dict(resumo.motivos_de_incerteza),
    )
    db.add(registro)
    db.commit()
    db.refresh(registro)
    return registro


def buscar_resumo(db: Session, id_sessao: int) -> Optional[ResumoSessao]:
    """O resumo congelado da sessão, ou `None` se ela é anterior à ticket 13."""
    return db.get(ResumoSessao, id_sessao)


def como_resumo_da_sessao(
    registro: ResumoSessao, duracao_total: timedelta
) -> relatorio.ResumoDaSessao:
    """Converte o resumo gravado de volta para o tipo que o relatório consome.

    `duracao_total` não vem do registro porque ela é derivada de `inicio` e
    `fim` da sessão, que já estão no banco — guardar uma segunda cópia seria
    criar a chance de as duas discordarem.
    """
    return relatorio.ResumoDaSessao(
        media=registro.media,
        pico=registro.pico,
        vale=registro.vale,
        pontos_medidos=registro.pontos_medidos,
        pontos_incertos=registro.pontos_incertos,
        pontos_zerados=registro.pontos_zerados,
        alertas_de_fadiga=dict(registro.alertas_de_fadiga or {}),
        motivos_de_incerteza=dict(registro.motivos_de_incerteza or {}),
        duracao_total=duracao_total,
        duracao_presente=timedelta(seconds=registro.duracao_presente_s),
    )


def aplicar_retencao(
    db: Session, id_aluno: int, agora: Optional[datetime] = None
) -> List[int]:
    """Colapsa a série das sessões do aluno que já passaram da janela.

    Devolve os ids das sessões colapsadas nesta passagem — é o que os testes
    observam, e o que um log de operação registraria.
    """
    agora = agora or agora_utc()
    corte = agora - RETENCAO_GRANULAR

    candidatas = db.exec(
        select(SessaoEstudo).where(
            SessaoEstudo.id_aluno == id_aluno, col(SessaoEstudo.fim).is_not(None)
        )
    ).all()

    colapsadas: List[int] = []
    for sessao in candidatas:
        if como_utc(sessao.fim) > corte:
            continue

        registro = registrar_resumo(db, sessao)
        if registro.granular_descartado:
            continue

        _colapsar(db, sessao)
        registro.granular_descartado = True
        db.add(registro)
        db.commit()
        colapsadas.append(sessao.id)

    return colapsadas


def _colapsar(db: Session, sessao: SessaoEstudo) -> None:
    """Troca os pontos por segundo da sessão por um ponto por minuto."""
    serie = telemetria.buscar_logs(db, sessao.id)
    if not serie:
        return

    resumidos = _medias_por_minuto(serie)

    db.exec(delete(LogEngajamento).where(LogEngajamento.id_sessao == sessao.id))
    for ponto in resumidos:
        db.add(ponto)
    db.commit()


def _medias_por_minuto(serie: Sequence[LogEngajamento]) -> List[LogEngajamento]:
    """Uma linha por minuto, com a média dos scores medidos naquele minuto.

    Três decisões que o colapso não pode errar, todas herdadas da ticket 10:

    - Um minuto **com alguma medida** vira a média das medidas, e os pontos
      incertos daquele minuto simplesmente não entram na conta. Incluí-los como
      zero é exatamente o score enganoso que a ticket 10 existe para recusar.
    - Um minuto **inteiramente incerto** vira um ponto com `score = None`. Ele
      precisa sobreviver ao colapso: sem ele a curva ligaria os dois lados do
      buraco como se nada tivesse acontecido no meio.
    - O rótulo de `alerta` que sobrevive é o mais frequente do minuto, e é
      escolhido **dentro do mesmo vocabulário** — fadiga entre os pontos
      medidos, incerteza entre os não medidos. Misturar os dois produziria uma
      linha com score e motivo de incerteza, que nenhum leitor sabe interpretar.
    """
    baldes: Dict[datetime, List[LogEngajamento]] = {}
    for ponto in serie:
        baldes.setdefault(_inicio_do_minuto(ponto.horario_registro), []).append(ponto)

    resumidos: List[LogEngajamento] = []
    for minuto in sorted(baldes):
        pontos = baldes[minuto]
        medidos = [p for p in pontos if p.score is not None]

        resumidos.append(
            LogEngajamento(
                id_sessao=pontos[0].id_sessao,
                horario_registro=minuto,
                score=mean(p.score for p in medidos) if medidos else None,
                fadiga=mean(p.fadiga for p in medidos) if medidos else 0.0,
                alerta=_alerta_dominante(medidos if medidos else pontos),
            )
        )

    return resumidos


def _inicio_do_minuto(instante: datetime) -> datetime:
    instante = como_utc(instante)
    return instante.replace(second=0, microsecond=0)


def _alerta_dominante(pontos: Sequence[LogEngajamento]) -> Optional[str]:
    """O rótulo mais frequente do balde; empate resolve em ordem alfabética.

    O desempate importa: sem ele, o mesmo minuto colapsado duas vezes poderia
    produzir relatórios diferentes, e "o relatório mudou sozinho" é o tipo de
    bug que ninguém consegue reproduzir.
    """
    contagem = Counter(p.alerta for p in pontos if p.alerta)
    if not contagem:
        return None
    return max(sorted(contagem), key=contagem.get)
