"""Regras do ciclo de vida da sessão de estudo (ticket 4).

Concentra as decisões de negócio — quando uma sessão pode começar, quando ela
termina e o que conta como inatividade prolongada — fora do FastAPI, para que
sejam testáveis sem HTTP e reaproveitáveis pelo canal de telemetria da ticket 6.

O encerramento automático é uma varredura preguiçosa: roda a cada operação de
sessão, em vez de depender de um scheduler. Isso mantém a PoC sem processo de
background e ainda garante que ninguém observe uma sessão inativa como aberta —
quem consulta é justamente quem dispara a varredura.

Os **blocos** declarados (foco e pausa) são orquestrados daqui, mas a regra
deles mora em `app/blocos.py`, que não conhece banco. A divisão é a de sempre
neste projeto: lá se responde "esta declaração é válida? este ponto cai dentro
do bloco?", aqui se responde "qual linha abrir, qual fechar e em que
transação".
"""
from datetime import datetime, timedelta
from typing import List, Optional

from sqlmodel import Session, col, select

from app import analista, blocos, metodos, presenca, sumarizacao
from app.models import (
    ENCERRAMENTO_MANUAL,
    ENCERRAMENTO_POR_INATIVIDADE,
    BlocoEstudo,
    SessaoEstudo,
)
from app.tempo import agora_utc, como_utc


class SessaoAtivaJaExiste(Exception):
    """O aluno já tem uma sessão em andamento — só se estuda uma de cada vez."""


class SessaoNaoEncontrada(Exception):
    """A sessão não existe, ou não pertence ao aluno que pediu."""


class SessaoJaEncerrada(Exception):
    """A sessão já tem `fim` registrado (manualmente ou por inatividade)."""


class SessaoEmAndamento(Exception):
    """Pediram o relatório de uma sessão que ainda não terminou.

    Recusar não é limitação técnica — a série está lá e os indicadores sairiam.
    É a decisão de produto da ticket 9: o aluno não vê o próprio score enquanto
    estuda, porque o número compete com a tarefa que ele mede. Servir o
    relatório de uma sessão em andamento devolveria o dashboard ao vivo por uma
    porta lateral, bastando deixar a aba aberta.
    """


def limite_de_ausencia_da(sessao: SessaoEstudo) -> timedelta:
    """Quanto tempo sem rosto na câmera antes de encerrar **esta** sessão.

    O limite é por sessão porque é do método: quem declarou Pomodoro tem direito
    à pausa que o Pomodoro prescreve, e quem não declarou nada cai no valor
    legado. O teto absoluto de `app.metodos` fecha a porta para método mal
    parametrizado.

    Esta função substituiu `limite_inatividade()`, que devolvia o limite da
    série. As duas perguntas — "a sessão acabou?" e "este vão da série foi perda
    de captura?" — pareciam a mesma enquanto a série era a única evidência de
    presença que o sistema tinha. Desde que existe `ultima_presenca`, não são.
    """
    return metodos.limite_de_ausencia(sessao.pausa_maxima_s, presenca.limite_de_ausencia())


def _ultimo_sinal_de(sessao: SessaoEstudo) -> datetime:
    """O instante mais recente em que se sabe que o aluno estava na frente da webcam.

    `ultima_presenca` nula não é buraco a tapar: é a verdade sobre uma sessão em
    que nenhum rosto foi visto — webcam negada, modelo que não carregou, aluno
    que abriu e saiu. Cair em `inicio` faz essa sessão morrer contada a partir da
    abertura, que é o comportamento certo, e evita o desastre da migração (tratar
    nulo como ausência infinita mataria toda sessão viva no primeiro boot).

    **Não** usar `ultima_atividade` como alternativa: ela é renovada pelo
    heartbeat e por qualquer payload, com ou sem aluno na cadeira, e reimportaria
    por uma porta lateral exatamente o relógio que esta mudança desligou.
    """
    return sessao.ultima_presenca or sessao.inicio


def encerrar_inativas(db: Session, agora: Optional[datetime] = None) -> List[SessaoEstudo]:
    """Encerra toda sessão aberta sem rosto na câmera além do limite dela.

    O `fim` gravado é o último sinal de presença, não o instante da varredura: o
    tempo de cadeira vazia não é tempo de estudo e não pode inflar a duração.

    O corte é calculado por sessão, e não uma vez para todas, porque cada uma
    carrega o limite do próprio método. A query não muda — as abertas já eram
    carregadas e filtradas em Python.

    O bloco em andamento é fechado junto, com o mesmo `fim` da sessão. Este é o
    caminho em que esquecer disso seria mais fácil e mais caro: a sessão
    derrubada por queda de conexão é exatamente a que ninguém fecha a mão, e ela
    ficaria para sempre com um bloco aberto dentro de uma sessão encerrada.
    """
    agora = agora or agora_utc()

    abertas = db.exec(select(SessaoEstudo).where(SessaoEstudo.fim.is_(None))).all()
    encerradas = [
        s
        for s in abertas
        if como_utc(_ultimo_sinal_de(s)) <= agora - limite_de_ausencia_da(s)
    ]

    for sessao in encerradas:
        sessao.fim = _ultimo_sinal_de(sessao)
        sessao.encerramento = ENCERRAMENTO_POR_INATIVIDADE
        db.add(sessao)
        _fechar_bloco_aberto(db, sessao.id, sessao.fim)

    if encerradas:
        db.commit()
        for sessao in encerradas:
            db.refresh(sessao)
            # A baseline calibrada desta sessão não serve a mais ninguém: o
            # registro é por sessão e esta acabou. Deixá-la vencer sozinha pelo
            # TTL só atrasa a liberação, e o TTL agora é o teto de ausência.
            analista.registro.descartar(sessao.id)
            # O relatório de uma sessão interrompida (AC-11-4) sai por aqui: a
            # queda de conexão ou o navegador fechado não geram clique nenhum,
            # e é esta varredura que fecha a sessão e congela os indicadores.
            sumarizacao.registrar_resumo(db, sessao)

    return encerradas


def buscar_ativa(
    db: Session, id_aluno: int, agora: Optional[datetime] = None
) -> Optional[SessaoEstudo]:
    agora = agora or agora_utc()
    encerrar_inativas(db, agora=agora)

    return db.exec(
        select(SessaoEstudo).where(
            SessaoEstudo.id_aluno == id_aluno, SessaoEstudo.fim.is_(None)
        )
    ).first()


def iniciar(
    db: Session,
    id_aluno: int,
    agora: Optional[datetime] = None,
    metodo: Optional[str] = None,
    assunto: Optional[str] = None,
    meta_de_blocos: Optional[int] = None,
) -> SessaoEstudo:
    """Abre uma sessão, congelando nela o contexto declarado pelo aluno.

    `pausa_maxima_s` é resolvido **aqui**, a partir do código do método — o
    cliente escolhe o método, nunca o número. E é congelado na linha: se o
    catálogo for reparametrizado amanhã, o relatório de hoje não muda junto,
    pelo mesmo motivo que a ticket 13 congelou os indicadores em `resumo_sessao`.

    Método desconhecido estoura antes de qualquer escrita — é entrada do aluno, e
    entrada do aluno se valida contra o catálogo, não se aceita e se conserta
    depois.

    **Nenhum bloco é aberto aqui, e isso é decisão, não esquecimento.** Abrir um
    bloco de foco junto com a sessão pareceria conveniente e mentiria em três
    frentes. (a) Entre o `POST /sessoes` e o primeiro segundo de estudo há a
    permissão da webcam, o carregamento do MediaPipe e os 60 s de calibração da
    baseline; contar esse trecho como foco declarado infla o primeiro bloco de
    toda sessão, sempre para o mesmo lado. (b) A sessão em que o aluno nega a
    câmera e some ficaria com um bloco de foco que ninguém executou — e bloco é
    "plano executado", não "plano proposto". (c) `origem` não teria resposta
    honesta: nem o método nem o aluno declararam aquela transição, o servidor a
    inventou. Quem sabe a hora em que o estudo começou é quem tem o cronômetro
    na tela, e é ele que declara, por `declarar_bloco`. Uma regra só, valendo
    para o primeiro bloco e para todos os outros.
    """
    agora = agora or agora_utc()
    pausa_maxima_s = metodos.resolver_pausa_maxima(metodo)

    if buscar_ativa(db, id_aluno, agora=agora) is not None:
        raise SessaoAtivaJaExiste

    sessao = SessaoEstudo(
        id_aluno=id_aluno,
        inicio=agora,
        ultima_atividade=agora,
        metodo=metodo,
        assunto=assunto,
        meta_de_blocos=meta_de_blocos,
        pausa_maxima_s=pausa_maxima_s,
    )
    db.add(sessao)
    db.commit()
    db.refresh(sessao)
    return sessao


def registrar_presenca(
    db: Session, sessao: SessaoEstudo, agora: Optional[datetime] = None
) -> SessaoEstudo:
    """Marca que houve **rosto na câmera** agora, adiando o encerramento.

    Recebe a sessão já carregada, e não um par de ids, de propósito: quem chama é
    o canal de telemetria, a 1 Hz, e ele já resolveu a sessão a partir do aluno
    autenticado. Passar pelos ids obrigaria a repetir a busca e a varredura de
    inativas uma vez por segundo — a varredura preguiçosa a 1 Hz não é preguiçosa,
    é um cron disfarçado.

    Quem decide *se* houve presença é o chamador, que é quem enxerga
    `rosto_detectado` e a incerteza de captura. Este módulo não recebe métrica
    facial e não vai receber.
    """
    agora = agora or agora_utc()
    sessao.ultima_presenca = agora
    db.add(sessao)
    db.commit()
    db.refresh(sessao)
    return sessao


def registrar_atividade(
    db: Session, id_sessao: int, id_aluno: int, agora: Optional[datetime] = None
) -> SessaoEstudo:
    """Marca que a **aba** continua aberta (heartbeat do navegador).

    Não adia mais o encerramento automático, e essa era a função inteira dela
    até os métodos de estudo entrarem. O heartbeat bate sozinho enquanto a aba
    existir, com ou sem aluno na cadeira — usá-lo como evidência de presença
    transformava tempo de aba aberta em tempo de estudo.

    Continua existindo porque o cliente precisa de um caminho barato para
    descobrir que o servidor já encerrou a sessão (o 409 desta rota é o que
    dispara a ressincronização na tela), e porque `ultima_atividade` ainda é o
    registro honesto de quando a aba esteve viva.
    """
    agora = agora or agora_utc()
    sessao = _buscar_em_andamento(db, id_sessao, id_aluno, agora)

    sessao.ultima_atividade = agora
    db.add(sessao)
    db.commit()
    db.refresh(sessao)
    return sessao


def encerrar(
    db: Session, id_sessao: int, id_aluno: int, agora: Optional[datetime] = None
) -> SessaoEstudo:
    agora = agora or agora_utc()
    sessao = _buscar_em_andamento(db, id_sessao, id_aluno, agora)

    sessao.fim = agora
    sessao.encerramento = ENCERRAMENTO_MANUAL
    db.add(sessao)
    _fechar_bloco_aberto(db, sessao.id, agora)
    db.commit()
    db.refresh(sessao)

    # A baseline desta sessão não serve a mais nenhuma. `descartar` era público
    # e não era chamado de lugar nenhum: cada sessão encerrada deixava o próprio
    # analista em memória até vencer sozinho, e o TTL passou a ser o teto de
    # ausência (20 min), o que só piora a espera. Uma linha, aqui, onde a
    # informação "acabou" existe.
    analista.registro.descartar(sessao.id)

    # O relatório é gerado no encerramento (AC-11-1), e não no primeiro acesso:
    # os indicadores são calculados sobre a série completa, enquanto ela ainda
    # está no detalhe de segundo.
    sumarizacao.registrar_resumo(db, sessao)
    return sessao


def listar_blocos(db: Session, id_sessao: int) -> List[BlocoEstudo]:
    """Os blocos da sessão, na ordem em que aconteceram.

    Ordenado por `indice`, e não por `inicio`: os dois coincidem hoje, mas o
    índice é o que o aluno lê no relatório ("bloco 3"), e é ele que precisa sair
    em ordem mesmo que dois blocos acabem gravados com o mesmo carimbo de tempo
    por um relógio de servidor de baixa resolução.
    """
    return db.exec(
        select(BlocoEstudo)
        .where(BlocoEstudo.id_sessao == id_sessao)
        .order_by(col(BlocoEstudo.indice))
    ).all()


def bloco_aberto(db: Session, id_sessao: int) -> Optional[BlocoEstudo]:
    """O bloco em andamento da sessão, ou `None` se não há nenhum.

    "Nenhum" é um estado legítimo e comum: é o da sessão recém-aberta, enquanto
    a webcam é liberada e a baseline calibra, porque `iniciar` não abre bloco
    nenhum (o porquê está lá). O cliente usa isto para restaurar o cronômetro
    depois de um reload, que é o mesmo serviço que `GET /sessoes/ativa` presta
    para a sessão.
    """
    return db.exec(
        select(BlocoEstudo)
        .where(BlocoEstudo.id_sessao == id_sessao, col(BlocoEstudo.fim).is_(None))
        .order_by(col(BlocoEstudo.indice).desc())
    ).first()


def declarar_bloco(
    db: Session,
    id_sessao: int,
    id_aluno: int,
    tipo: str,
    origem: str = blocos.ORIGEM_METODO,
    agora: Optional[datetime] = None,
) -> BlocoEstudo:
    """Registra a transição: fecha o bloco que estava aberto e abre o novo.

    **Uma transição, uma borda.** O `fim` do bloco que acaba é o mesmo instante
    que o `inicio` do que começa — sem buraco entre os dois e sem sobreposição.
    O ponto da série que cai exatamente aí pertence ao bloco que começa, e o
    porquê está em `blocos.recortar`.

    **Declaração repetida não vira bloco novo.** Se o tipo declarado já é o que
    está aberto, devolve o bloco aberto sem tocar em nada: uma retentativa de
    rede e uma segunda aba dizendo a mesma coisa não podem partir a pausa do
    aluno em duas, sendo a primeira de duração zero. O instante preservado é o
    da primeira declaração — a que o aluno de fato fez. A alternativa (recusar
    com erro) ensinaria o cliente a tratar retentativa como falha, e o cliente
    que evita retentativa é o que perde a transição de vez.

    A validação do vocabulário vem antes de qualquer escrita, pelo mesmo motivo
    que em `iniciar`: tipo inventado não estoura em lugar nenhum, ele só some do
    relatório.
    """
    agora = agora or agora_utc()
    blocos.validar_declaracao(tipo, origem)

    sessao = _buscar_em_andamento(db, id_sessao, id_aluno, agora)

    aberto = bloco_aberto(db, sessao.id)
    if blocos.e_redundante(tipo, aberto.tipo if aberto is not None else None):
        return aberto

    if aberto is not None:
        aberto.fim = agora
        db.add(aberto)

    existentes = listar_blocos(db, sessao.id)
    novo = BlocoEstudo(
        id_sessao=sessao.id,
        indice=blocos.proximo_indice(bloco.indice for bloco in existentes),
        tipo=tipo,
        inicio=agora,
        origem=origem,
    )
    db.add(novo)
    db.commit()
    db.refresh(novo)
    return novo


def listar_encerradas(db: Session, id_aluno: int) -> List[SessaoEstudo]:
    """Histórico do aluno, da mais recente para a mais antiga (ticket 12).

    Varre as inativas antes de listar pelo mesmo motivo que `buscar_ativa`: uma
    sessão abandonada ontem precisa aparecer aqui como encerrada, e não sumir do
    histórico por estar tecnicamente "em andamento" desde então.
    """
    encerrar_inativas(db)

    return db.exec(
        select(SessaoEstudo)
        .where(SessaoEstudo.id_aluno == id_aluno, col(SessaoEstudo.fim).is_not(None))
        .order_by(col(SessaoEstudo.inicio).desc())
    ).all()


def buscar_encerrada(
    db: Session, id_sessao: int, id_aluno: int, agora: Optional[datetime] = None
) -> SessaoEstudo:
    """A sessão encerrada do aluno, pronta para virar relatório.

    A varredura roda antes da checagem de propriedade de propósito: a sessão
    interrompida por queda de conexão ainda está aberta no banco até alguém
    olhar, e o aluno que abre o relatório dela é exatamente esse alguém.
    """
    agora = agora or agora_utc()
    encerrar_inativas(db, agora=agora)

    sessao = db.get(SessaoEstudo, id_sessao)
    if sessao is None or sessao.id_aluno != id_aluno:
        # Mesma resposta para sessão inexistente e sessão de outro aluno. Se as
        # duas divergissem, a diferença viraria um oráculo de existência.
        raise SessaoNaoEncontrada
    if sessao.fim is None:
        raise SessaoEmAndamento

    return sessao


def _buscar_em_andamento(
    db: Session, id_sessao: int, id_aluno: int, agora: datetime
) -> SessaoEstudo:
    encerrar_inativas(db, agora=agora)

    sessao = db.get(SessaoEstudo, id_sessao)
    if sessao is None or sessao.id_aluno != id_aluno:
        # Sessão de outro aluno é indistinguível de sessão inexistente: nada
        # sobre os dados de um estudante vaza para outro.
        raise SessaoNaoEncontrada
    if sessao.fim is not None:
        raise SessaoJaEncerrada

    return sessao


def _fechar_bloco_aberto(
    db: Session, id_sessao: int, fim: datetime
) -> Optional[BlocoEstudo]:
    """Fecha o bloco em andamento com o `fim` da sessão que está terminando.

    Bloco com `fim IS NULL` dentro de uma sessão encerrada é dado corrompido, e
    do pior tipo: não estoura em lugar nenhum, não aparece em teste de rota e só
    se manifesta semanas depois como um bloco de duração infinita no relatório
    de alguém. Os dois caminhos de encerramento passam por aqui.

    **O `max` não é defensivo, é um caso real.** A varredura grava
    `fim = ultima_presenca`, que é um instante do passado. O aluno que declarou
    a pausa e não voltou mais tem um bloco cujo `inicio` é *posterior* a essa
    última presença — fechá-lo com o `fim` da sessão o deixaria terminando antes
    de começar. Colapsar em duração zero é a leitura certa: o bloco foi
    declarado e não foi executado. Não adiantaria confiar só no `max` de
    `blocos.duracao`, porque quem lê a tabela por SQL não passa por ele.

    Não faz `commit`: quem chama está no meio de uma transação que também grava
    o `fim` da sessão, e as duas escritas precisam cair juntas ou não cair.
    """
    aberto = bloco_aberto(db, id_sessao)
    if aberto is None:
        return None

    aberto.fim = max(como_utc(fim), como_utc(aberto.inicio))
    db.add(aberto)
    return aberto
