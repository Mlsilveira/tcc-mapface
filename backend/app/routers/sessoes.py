from contextlib import contextmanager
from typing import Iterator, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from app import relatorio, sessoes, telemetria
from app.database import get_session
from app.deps import get_aluno_atual
from app.models import Aluno, SessaoEstudo
from app.schemas import RelatorioPublico, SessaoPublica

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
        return sessoes.encerrar(db, id_sessao, aluno_atual.id)


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
    return relatorio.montar(sessao, telemetria.buscar_logs(db, id_sessao=id_sessao))
