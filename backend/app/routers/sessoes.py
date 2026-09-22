from contextlib import contextmanager
from typing import Iterator, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from app import (
    blocos,
    criterios,
    metodos,
    presenca,
    relatorio,
    sessoes,
    sumarizacao,
    telemetria,
)
from app.database import get_session
from app.deps import get_aluno_atual
from app.models import ENCERRAMENTO_POR_INATIVIDADE, Aluno, BlocoEstudo, SessaoEstudo
from app.schemas import (
    BlocoPublico,
    MetodoPublico,
    NovaSessao,
    RelatorioPublico,
    SessaoNoHistorico,
    SessaoPublica,
    TransicaoDeBloco,
)

router = APIRouter(prefix="/sessoes", tags=["sessões de estudo"])

#: O catálogo de métodos não é um recurso da sessão, então não entra sob
#: `/sessoes` — mas mora neste arquivo porque é o mesmo assunto e um módulo
#: novo custaria mais linhas de cerimônia do que tem de conteúdo. Fica exigindo
#: autenticação como todo o resto: a tela que o consome é a tela inicial, que já
#: está atrás do login, e abrir uma rota pública por conveniência é como se
#: abrem rotas públicas.
router_metodos = APIRouter(prefix="/metodos", tags=["métodos de estudo"])


@router_metodos.get("", response_model=List[MetodoPublico])
def catalogo(_: Aluno = Depends(get_aluno_atual)) -> List[MetodoPublico]:
    """Os métodos de estudo que o aluno pode declarar, com nome legível.

    Servido do catálogo em código, e não de tabela: o porquê está no docstring
    de `app/metodos.py`. O cliente usa `foco_s` e `pausa_longa_s` para conduzir
    o cronômetro, e manda de volta só o `codigo` — o `pausa_maxima_s` da sessão
    sai daqui, no servidor, e nunca do corpo do request.
    """
    return MetodoPublico.catalogo()


#: Quantos caracteres do valor recusado cabem numa mensagem de erro daqui.
#:
#: As três mensagens 422 deste módulo repetem o que chegou — "Método de estudo
#: desconhecido: 'feynman'" —, e repetir é metade do que as torna úteis: sem o
#: valor, o aluno que mandou `"Pomodoro"` com maiúscula lê "desconhecido" e não
#: tem onde olhar. O defeito medido em auditoria não era repetir, era repetir
#: **sem teto**: 5.000 caracteres de `metodo` viravam 5.097 bytes de resposta, de
#: graça para quem mandou.
#:
#: O `max_length` de `app/schemas.py` já impede que um valor desses chegue até
#: aqui. Esta constante é a segunda linha, e é deliberadamente **independente**
#: daquela: se um dia o teto de um código subir, o tamanho desta mensagem não
#: sobe junto de carona, sem ninguém decidir que sobe.
#:
#: 24 porque o maior código de todo o vocabulário desta API tem 10 caracteres
#: (`timeboxing`): 24 mostra o engano inteiro — o código digitado duas vezes, o
#: espaço colado no fim, o acento a mais — e ainda assim faz o tamanho da
#: resposta parar de depender do tamanho do request.
LIMITE_DE_ECO_DO_VALOR = 24


def _recortado(valor: str) -> str:
    """O valor recebido, do jeito que a mensagem de erro pode repeti-lo.

    Sai sempre em `repr`, como as mensagens já faziam: as aspas em volta são o
    que deixa `'foco '` distinguível de `'foco'` na tela de quem está depurando,
    e é exatamente essa diferença que costuma ser a causa do erro.

    O corte leva `…` no fim para não trocar um defeito por uma mentira: sem a
    marca, a mensagem afirmaria que o valor recusado era o pedaço mostrado, e o
    cliente iria procurar o erro num texto que nunca mandou.
    """
    if len(valor) > LIMITE_DE_ECO_DO_VALOR:
        return repr(valor[:LIMITE_DE_ECO_DO_VALOR] + "…")
    return repr(valor)


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
    except sessoes.SessaoEmAndamento:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="O relatório fica disponível quando a sessão for encerrada",
        )


@router.post("", response_model=SessaoPublica, status_code=status.HTTP_201_CREATED)
def iniciar(
    corpo: Optional[NovaSessao] = None,
    aluno_atual: Aluno = Depends(get_aluno_atual),
    db: Session = Depends(get_session),
) -> SessaoEstudo:
    """Abre a sessão com o contexto declarado na tela inicial.

    O corpo é opcional inteiro: sessão sem método, sem assunto e sem meta é um
    estado legítimo — é o que o aluno tem quando não quer declarar nada — e
    continua sendo o que acontece num `POST` sem corpo.

    Método fora do catálogo responde **422**, e não 400: é falha de validação de
    um campo do corpo, que é exatamente o que o 422 significa no resto desta
    API. A mensagem aponta para `GET /metodos` em vez de listar os códigos,
    porque a lista muda e uma mensagem de erro não é lugar de manter catálogo.
    """
    corpo = corpo or NovaSessao()

    try:
        return sessoes.iniciar(
            db,
            aluno_atual.id,
            metodo=corpo.metodo,
            assunto=corpo.assunto,
            meta_de_blocos=corpo.meta_de_blocos,
        )
    except metodos.MetodoDesconhecido:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Método de estudo desconhecido: {_recortado(corpo.metodo)}. "
                "Os métodos disponíveis estão em GET /metodos."
            ),
        )
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


@router.post(
    "/{id_sessao}/blocos", response_model=BlocoPublico, status_code=status.HTTP_200_OK
)
def declarar_bloco(
    id_sessao: int,
    corpo: TransicaoDeBloco,
    aluno_atual: Aluno = Depends(get_aluno_atual),
    db: Session = Depends(get_session),
) -> BlocoEstudo:
    """Declara que a sessão entrou em foco ou em pausa, agora.

    Fecha o bloco anterior e abre o novo na mesma borda. A resposta é sempre o
    bloco que passou a estar em andamento.

    **200, e não 201**, porque declarar a transição que já está em vigor não
    cria nada: o endpoint é idempotente por tipo, e devolver 201 para uma
    retentativa afirmaria uma criação que não houve. O motivo de absorver a
    repetição em vez de recusá-la está em `sessoes.declarar_bloco`.

    Erros: **404** se a sessão não existe ou é de outro aluno (a mesma resposta
    para os dois casos, senão a diferença vira um oráculo de existência),
    **409** se ela já foi encerrada — inclusive quando quem a encerrou foi a
    varredura de ausência disparada por este mesmo request — e **422** se o tipo
    ou a origem estão fora do vocabulário.
    """
    with _traduzindo_erros():
        try:
            return sessoes.declarar_bloco(
                db, id_sessao, aluno_atual.id, tipo=corpo.tipo, origem=corpo.origem
            )
        except blocos.TipoDeBlocoDesconhecido:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Tipo de bloco desconhecido: {_recortado(corpo.tipo)}. "
                    f"Os tipos são {blocos.TIPO_FOCO!r} e {blocos.TIPO_PAUSA!r}."
                ),
            )
        except blocos.OrigemDeBlocoDesconhecida:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Origem de bloco desconhecida: {_recortado(corpo.origem)}. "
                    f"As origens são {blocos.ORIGEM_METODO!r} e {blocos.ORIGEM_ALUNO!r}."
                ),
            )


@router.get("/{id_sessao}/blocos", response_model=List[BlocoPublico])
def listar_blocos(
    id_sessao: int,
    aluno_atual: Aluno = Depends(get_aluno_atual),
    db: Session = Depends(get_session),
) -> List[BlocoEstudo]:
    """Os blocos declarados da sessão, em ordem.

    Existe para o mesmo serviço que `GET /sessoes/ativa` presta: depois de um
    reload, o cliente precisa saber qual bloco está aberto e desde quando para
    recolocar o cronômetro no lugar certo. Sem isso, recarregar a página no meio
    de um Pomodoro reiniciaria o bloco — e o aluno aprenderia a não recarregar,
    que é a pior correção possível.

    Aceita sessão em andamento **e** encerrada, ao contrário do relatório. A
    razão da recusa do relatório é que ele mostra o score ao vivo por uma porta
    lateral; blocos não têm score nenhum dentro — são carimbos de tempo de
    cliques que o próprio aluno deu.
    """
    sessao = db.get(SessaoEstudo, id_sessao)
    if sessao is None or sessao.id_aluno != aluno_atual.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Sessão de estudo não encontrada"
        )

    return sessoes.listar_blocos(db, id_sessao)


@router.get("/historico", response_model=List[SessaoNoHistorico])
def historico(
    aluno_atual: Aluno = Depends(get_aluno_atual),
    db: Session = Depends(get_session),
) -> List[SessaoNoHistorico]:
    """As sessões encerradas do aluno, da mais recente para a mais antiga.

    Declarada **antes** de `/{id_sessao}/relatorio` de propósito: o FastAPI casa
    as rotas na ordem em que são registradas, e uma rota dinâmica declarada
    antes engoliria `/historico` como se fosse um id.

    É também o momento de faxina do sistema (ticket 13). A varredura de retenção
    roda aqui porque é aqui que o aluno está olhando para o próprio passado — o
    custo cai sobre quem se beneficia dele, e a PoC segue sem scheduler.
    """
    sumarizacao.aplicar_retencao(db, aluno_atual.id)

    linhas: List[SessaoNoHistorico] = []
    for sessao in sessoes.listar_encerradas(db, aluno_atual.id):
        resumo = _resumo_de(db, sessao)
        linhas.append(
            SessaoNoHistorico.de(
                sessao, resumo, parcial=sessao.encerramento == ENCERRAMENTO_POR_INATIVIDADE
            )
        )

    return linhas


@router.get("/{id_sessao}/relatorio", response_model=RelatorioPublico)
def relatorio_da_sessao(
    id_sessao: int,
    aluno_atual: Aluno = Depends(get_aluno_atual),
    db: Session = Depends(get_session),
) -> RelatorioPublico:
    """O relatório de autopercepção de uma sessão encerrada (ticket 11).

    Só o dono abre, e sessão de outro aluno responde **404**, não 403: um 403
    confirmaria que aquela sessão existe, e a lista de ids é sequencial.
    """
    with _traduzindo_erros():
        sessao = sessoes.buscar_encerrada(db, id_sessao, aluno_atual.id)

    serie = telemetria.buscar_logs(db, sessao.id)
    avaliacao = criterios.avaliar(
        sessao.metodo,
        sessoes.listar_blocos(db, sessao.id),
        serie,
        meta_de_blocos=sessao.meta_de_blocos,
        resolucao_da_serie_s=_resolucao_da_serie(db, sessao),
    )
    return RelatorioPublico.de(
        relatorio.montar(sessao, serie, _resumo_de(db, sessao, serie), avaliacao)
    )


def _resolucao_da_serie(db: Session, sessao: SessaoEstudo) -> int:
    """Quantos segundos cada ponto da série representa hoje.

    Um, enquanto a série está granular; um minuto depois que
    `sumarizacao.aplicar_retencao` a colapsou. Quem pergunta é `criterios`, para
    decidir se um bloco tem medida suficiente para receber média — e sem esta
    resposta todo bloco de uma sessão de ontem diria "curto demais para uma
    média", uma frase falsa produzida pela faxina do banco.

    A flag vem do registro congelado, e não da forma da série: contar pontos e
    adivinhar a resolução confundiria uma sessão colapsada com uma sessão cuja
    captura só subiu de vez em quando.
    """
    congelado = sumarizacao.buscar_resumo(db, sessao.id)
    if congelado is not None and congelado.granular_descartado:
        return int(sumarizacao.JANELA_DE_RESUMO.total_seconds())
    return 1


def _resumo_de(db: Session, sessao: SessaoEstudo, serie=None) -> relatorio.ResumoDaSessao:
    """Os indicadores da sessão: os congelados, se houver; senão, calculados.

    A preferência pelo congelado não é cache — é correção. Depois que a série é
    colapsada em médias por minuto (ticket 13), recalcular daria uma média de
    médias, que é um número diferente do que o aluno leu ontem sobre a mesma
    sessão.

    Sessões encerradas antes da ticket 11 não têm resumo gravado e caem no
    cálculo direto, que continua exato porque a série delas nunca foi colapsada.
    """
    congelado = sumarizacao.buscar_resumo(db, sessao.id)
    if congelado is not None:
        return sumarizacao.como_resumo_da_sessao(
            congelado, presenca.duracao_total(sessao.inicio, sessao.fim)
        )

    if serie is None:
        serie = telemetria.buscar_logs(db, sessao.id)
    return relatorio.resumir(sessao, serie)
