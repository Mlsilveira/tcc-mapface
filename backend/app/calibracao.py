"""Persistência da calibração de baseline (ticket 7).

Como `app/sessoes.py`, este módulo não conhece HTTP nem WebSocket: ele traduz
entre a linha da tabela `calibracao` e os dataclasses de domínio, e é aí que os
testes batem.

Por que o estado da calibração vai ao banco a cada payload, em vez de ficar na
memória da conexão: a calibração leva 60 segundos e o WebSocket da ticket 6
reconecta sozinho quando a conexão cai. Um acumulador preso à conexão perderia
tudo numa queda no segundo 30, e numa rede ruim a calibração nunca terminaria.
O deploy da ticket 15 é ECS Fargate, com mais de uma instância — a reconexão
pode cair em outro processo, e memória de processo não atravessa isso. Então o
analista é reconstruído a partir do banco a cada mensagem, e a única coisa que
uma reconexão custa é uma leitura.

Uma linha por sessão, garantida por unicidade no schema. Uma sessão de estudo
tem exatamente uma janela de calibração; permitir duas linhas abriria a porta
para "qual delas vale?" na leitura, e a resposta não seria determinística.
"""
from datetime import datetime
from typing import Callable, NamedTuple, Optional

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.analista import Baseline, EstadoCalibracao
from app.models import Calibracao
from app.tempo import agora_utc, como_utc


class CalibracaoJaConcluida(Exception):
    """Tentou-se acumular numa calibração que já fechou.

    A janela é final: quem quiser recalibrar chama `descartar` antes. Sem essa
    porta única, um payload atrasado sobrescreveria `amostras` — coluna que a
    baseline concluída também usa — e a contagem por trás dela viraria ficção.
    """


class LeituraCalibracao(NamedTuple):
    """O que o banco sabe sobre a calibração de uma sessão.

    É uma tupla `(baseline, estado)` de propósito: o chamador que só quer
    desempacotar os dois valores consegue, e quem prefere perguntar em voz alta
    tem as propriedades abaixo. Os três estados são mutuamente exclusivos e
    cobrem todo o espaço — não existe leitura que não caia em exatamente um
    deles.
    """

    baseline: Optional[Baseline]
    estado: Optional[EstadoCalibracao]

    @property
    def concluida(self) -> bool:
        """A baseline já está pronta: é hora de calcular o IEE de verdade."""
        return self.baseline is not None

    @property
    def em_andamento(self) -> bool:
        """Há acumulado, mas a janela ainda não fechou."""
        return self.baseline is None and self.estado is not None

    @property
    def nao_iniciada(self) -> bool:
        """Primeira mensagem da sessão: não há nada no banco ainda."""
        return self.baseline is None and self.estado is None


def carregar(db: Session, id_sessao: int) -> LeituraCalibracao:
    """Lê a calibração da sessão, se houver."""
    linha = _buscar(db, id_sessao)
    if linha is None:
        return LeituraCalibracao(baseline=None, estado=None)

    return LeituraCalibracao(baseline=_para_baseline(linha), estado=_para_estado(linha))


def salvar_estado(db: Session, id_sessao: int, estado: EstadoCalibracao) -> None:
    """Grava o acumulador da sessão, criando a linha na primeira vez.

    Idempotente por construção: a linha é procurada antes, e chamar duas vezes
    para a mesma sessão atualiza em vez de duplicar.

    Levanta `CalibracaoJaConcluida` se a janela já fechou — nesse ponto só
    `descartar` reabre a sessão para uma nova calibração.
    """

    def aplicar(linha: Calibracao) -> None:
        if linha.concluida_em is not None:
            raise CalibracaoJaConcluida
        linha.inicio = estado.inicio
        linha.soma_ear = estado.soma_ear
        linha.soma_yaw = estado.soma_yaw
        linha.soma_pitch = estado.soma_pitch
        linha.amostras = estado.amostras

    _gravar(db, id_sessao, aplicar, lambda: Calibracao(id_sessao=id_sessao))


def salvar_baseline(
    db: Session, id_sessao: int, baseline: Baseline, agora: Optional[datetime] = None
) -> None:
    """Fecha a janela: grava a baseline e marca a calibração como concluída.

    O acumulador que a gerou é preservado ao lado — é a evidência de onde a
    baseline saiu, e o relatório da ticket 11 vai querer mostrá-la.

    As somas são **reconstruídas** da baseline em vez de herdadas da linha, e
    isso não é um detalhe: o payload que fecha a janela entra na média mas nunca
    chega a ser acumulado (o analista devolve `estado=None` justamente porque
    acabou de fechar). Herdar as somas deixaria a linha uma amostra atrasada em
    relação a `amostras`, e `soma_ear / amostras` deixaria de bater com
    `ear_neutro` — a contradição interna que esta função existe para evitar.
    Como `ear_neutro` é, por construção, a soma dividida pela contagem,
    multiplicar de volta recupera a soma verdadeira, sem inventar nada.
    """
    concluida_em = agora or agora_utc()

    def aplicar(linha: Calibracao) -> None:
        linha.soma_ear = baseline.ear_neutro * baseline.amostras
        linha.soma_yaw = baseline.yaw_neutro * baseline.amostras
        linha.soma_pitch = baseline.pitch_neutro * baseline.amostras
        linha.ear_neutro = baseline.ear_neutro
        linha.yaw_neutro = baseline.yaw_neutro
        linha.pitch_neutro = baseline.pitch_neutro
        linha.amostras = baseline.amostras
        linha.concluida_em = concluida_em

    _gravar(db, id_sessao, aplicar, lambda: Calibracao(id_sessao=id_sessao))


def descartar(db: Session, id_sessao: int) -> bool:
    """Joga fora a calibração da sessão. Devolve se havia algo para jogar.

    É a recalibração da ticket 7: se o aluno se ausenta durante os 60 segundos,
    o acumulado mistura rosto presente com rosto ausente, e uma média assim é
    pior que média nenhuma. A linha é apagada por inteiro em vez de zerada para
    que a leitura seguinte devolva "não iniciada" — o mesmo estado da primeira
    mensagem — e a janela recomece com o `inicio` do próximo payload.

    Chamar em sessão sem calibração é inofensivo de propósito: o chamador roda
    isto a cada ausência de rosto e não deveria ter que perguntar antes.
    """
    linha = _buscar(db, id_sessao)
    if linha is None:
        return False

    db.delete(linha)
    db.commit()
    return True


def _gravar(
    db: Session,
    id_sessao: int,
    aplicar: Callable[[Calibracao], None],
    criar: Callable[[], Calibracao],
) -> None:
    """Cria ou atualiza a única linha da sessão, absorvendo a corrida do INSERT.

    A leitura prévia resolve o caso comum e garante a idempotência. Ela não
    resolve, porém, dois payloads quase simultâneos da mesma sessão: ambos leem
    "ainda não existe", e o segundo INSERT bate na unicidade do schema. Aí a
    recusa do banco vira uma atualização sobre a linha que ganhou a corrida —
    o payload mais recente vence, que é exatamente o que o acumulador quer.
    """
    linha = _buscar(db, id_sessao)
    if linha is not None:
        aplicar(linha)
        _persistir(db, linha)
        return

    nova = criar()
    aplicar(nova)
    try:
        _persistir(db, nova)
    except IntegrityError:
        db.rollback()
        vencedora = _buscar(db, id_sessao)
        if vencedora is None:
            # A unicidade de `id_sessao` não foi o que estourou: é outra coisa,
            # e engolir aqui só esconderia o problema real.
            raise
        aplicar(vencedora)
        _persistir(db, vencedora)


def _persistir(db: Session, linha: Calibracao) -> None:
    db.add(linha)
    db.commit()
    db.refresh(linha)


def _buscar(db: Session, id_sessao: int) -> Optional[Calibracao]:
    return db.exec(select(Calibracao).where(Calibracao.id_sessao == id_sessao)).first()


def _para_baseline(linha: Calibracao) -> Optional[Baseline]:
    if linha.concluida_em is None:
        return None
    return Baseline(
        ear_neutro=linha.ear_neutro,
        yaw_neutro=linha.yaw_neutro,
        pitch_neutro=linha.pitch_neutro,
        amostras=linha.amostras,
    )


def _para_estado(linha: Calibracao) -> EstadoCalibracao:
    # `como_utc` não é decoração: o SQLite devolve datetime sem fuso, e sem a
    # normalização o `inicio` voltaria ingênuo e quebraria a subtração que
    # decide se os 60 segundos já passaram.
    return EstadoCalibracao(
        inicio=como_utc(linha.inicio),
        soma_ear=linha.soma_ear,
        soma_yaw=linha.soma_yaw,
        soma_pitch=linha.soma_pitch,
        amostras=linha.amostras,
    )
