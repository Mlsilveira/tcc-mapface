from contextlib import contextmanager
from typing import Iterator, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from app import relatorio, retencao, sessoes, telemetria
from app.database import get_session
from app.deps import get_aluno_atual
from app.models import Aluno, SessaoEstudo
from app.schemas import ItemDoHistoricoPublico, RelatorioPublico, SessaoPublica

router = APIRouter(prefix="/sessoes", tags=["sessões de estudo"])


@contextmanager
def _traduzindo_erros() -> Iterator[None]:
    """Converte as exceções de domínio de `app.sessoes` em respostas HTTP."""
    try:
        yield
    except sessoes.SessaoNaoEncontrada:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Sessão de estudo não encontrada"
        )
    except sessoes.SessaoJaEncerrada:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Esta sessão de estudo já foi encerrada"
        )


@router.post("", response_model=SessaoPublica, status_code=status.HTTP_201_CREATED)
def iniciar(
    aluno_atual: Aluno = Depends(get_aluno_atual),
    db: Session = Depends(get_session),
) -> SessaoEstudo:
    try:
        return sessoes.iniciar(db, aluno_atual.id)
    except sessoes.SessaoAtivaJaExiste:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Já existe uma sessão de estudo em andamento",
        )


@router.get("", response_model=list[ItemDoHistoricoPublico])
def historico(
    aluno_atual: Aluno = Depends(get_aluno_atual),
    db: Session = Depends(get_session),
) -> list[relatorio.ItemDoHistorico]:
    """Sessões do aluno, da mais recente para a mais antiga (ticket 12).

    Só as do aluno autenticado: o `id_aluno` vem do token, nunca da URL. Aceitar
    um identificador do cliente aqui deixaria qualquer um listar as sessões de
    qualquer outro, e o spec é explícito em que os dados de um estudante são
    visíveis apenas para ele.
    """
    # Aproveita a passagem para resumir o que a varredura de inatividade tiver
    # encerrado desde a última visita — inclusive sessões que nunca passaram por
    # endpoint algum.
    retencao.sumarizar_encerradas(db)

    sessoes_do_aluno = sessoes.listar(db, aluno_atual.id)
    agregados = telemetria.agregar_por_sessao(db, [s.id for s in sessoes_do_aluno])
    return relatorio.historico(sessoes_do_aluno, agregados)


@router.get("/ativa", response_model=Optional[SessaoPublica])
def ativa(
    aluno_atual: Aluno = Depends(get_aluno_atual),
    db: Session = Depends(get_session),
) -> Optional[SessaoEstudo]:
    """Sessão em andamento do aluno, ou `null`. Também varre as inativas."""
    return sessoes.buscar_ativa(db, aluno_atual.id)


@router.post("/{id_sessao}/atividade", response_model=SessaoPublica)
def registrar_atividade(
    id_sessao: int,
    aluno_atual: Aluno = Depends(get_aluno_atual),
    db: Session = Depends(get_session),
) -> SessaoEstudo:
    """Sinal de vida do navegador: enquanto chega, a sessão não expira."""
    with _traduzindo_erros():
        return sessoes.registrar_atividade(db, id_sessao, aluno_atual.id)


@router.post("/{id_sessao}/encerrar", response_model=SessaoPublica)
def encerrar(
    id_sessao: int,
    aluno_atual: Aluno = Depends(get_aluno_atual),
    db: Session = Depends(get_session),
) -> SessaoEstudo:
    with _traduzindo_erros():
        encerrada = sessoes.encerrar(db, id_sessao, aluno_atual.id)

    # Sumariza aqui e não em `sessoes.encerrar` para manter aquele módulo sem
    # saber de retenção de log. A varredura pega também as sessões encerradas
    # pela inatividade, que não passam por endpoint nenhum.
    retencao.sumarizar_encerradas(db)
    db.refresh(encerrada)
    return encerrada


@router.get("/{id_sessao}/relatorio", response_model=RelatorioPublico)
def relatorio_da_sessao(
    id_sessao: int,
    aluno_atual: Aluno = Depends(get_aluno_atual),
    db: Session = Depends(get_session),
) -> relatorio.Relatorio:
    """Relatório de autopercepção da sessão (ticket 11).

    Aceita sessão ainda aberta de propósito: é o relatório parcial que a ticket
    pede para o caso de a sessão ter sido interrompida por erro. O campo
    `parcial` diz qual dos dois casos o aluno está vendo.
    """
    with _traduzindo_erros():
        sessao = sessoes.buscar(db, id_sessao, aluno_atual.id)

    # Ler o relatório é a outra porta por onde uma sessão encerrada pela
    # varredura de inatividade passa. Sumarizar aqui não muda o que o aluno vê:
    # as médias da janela descrevem os mesmos dados, com menos linhas.
    retencao.sumarizar_encerradas(db)
    return relatorio.montar(sessao, telemetria.buscar_logs(db, id_sessao=id_sessao))
