"""Montagem da aplicação FastAPI: CORS, rotas de saúde, log e falha genérica.

O que este módulo tem além dos routers é o que separa "roda na minha máquina" de
"dá para publicar": de onde vêm as origens aceitas (§1.4), o que as sondas do
orquestrador realmente medem (§2.2), o que sai no log (§2.3) e o que o cliente
vê quando algo estoura fora do previsto (§2.4).
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app import database, observabilidade
from app.config import settings
from app.limites import LimiteDeCorpo
from app.database import criar_tabelas
from app.observabilidade import banco_sem_segredo, registrar
from app.routers import auth, sessoes, telemetria

logger = observabilidade.obter_logger("main")

#: O que o cliente recebe quando uma exceção não prevista chega ao topo. É
#: deliberadamente sem informação: ver `_tratar_falha_inesperada`.
FALHA_GENERICA = "Erro interno. A falha foi registrada."


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Prepara o banco e deixa no log o retrato do que subiu.

    As três linhas do boot — ambiente, banco, origens de CORS — são as que
    respondem "por que não funciona?" sem ninguém precisar abrir o console da
    AWS: aplicação apontando para o banco errado, `AMBIENTE` que ficou em
    desenvolvimento, origem do frontend que não entrou na lista. São exatamente
    os três erros de configuração possíveis depois de §1.4 e §1.5, e todos os
    três são invisíveis de fora.

    A URL passa por `banco_sem_segredo` antes de virar log: em produção ela
    carrega a senha do RDS, e a linha de boot é o lugar mais provável do sistema
    para uma credencial vazar por conveniência.
    """
    criar_tabelas()
    registrar(
        logger,
        logging.INFO,
        "aplicação iniciada",
        {
            "ambiente": settings.ambiente,
            "banco": banco_sem_segredo(settings.database_url),
            "origens_de_cors": settings.origens_de_cors(),
        },
    )
    yield
    registrar(logger, logging.INFO, "aplicação encerrada", {"ambiente": settings.ambiente})


def _banco_responde() -> bool:
    """`SELECT 1` no banco — a menor pergunta que prova que a conexão existe.

    Lê `database.engine` pelo módulo, e não por um `from ... import engine` no
    topo, porque a sonda precisa enxergar o engine **atual**: é assim que o
    teste de indisponibilidade troca o banco por um que não responde sem ter que
    derrubar um Postgres de verdade.

    Uma consulta a uma tabela do domínio (`SELECT count(*) FROM aluno`) foi
    considerada e descartada: ela responderia à mesma pergunta e passaria a
    falhar também quando o schema estivesse em migração, transformando a sonda
    numa segunda opinião sobre o estado das tabelas. Aqui só se pergunta se há
    conexão.
    """
    try:
        with database.engine.connect() as conexao:
            conexao.execute(text("SELECT 1"))
        return True
    except Exception:
        registrar(
            logger,
            logging.ERROR,
            "banco inacessível na verificação de prontidão",
            {"banco": banco_sem_segredo(settings.database_url)},
            exc_info=True,
        )
        return False


async def _tratar_falha_inesperada(request: Request, exc: Exception) -> JSONResponse:
    """Resposta genérica para o cliente, detalhe completo no log.

    Sem este handler, uma exceção não tratada sobe até o servidor, e o que chega
    ao navegador depende de como o uvicorn foi iniciado — com `--reload`, o
    stack trace inteiro, com nomes de arquivo, trechos de código e a estrutura
    do projeto. Isso é vazamento de informação e, numa defesa de TCC projetada
    na parede, é a pior forma possível de um erro aparecer.

    O corpo devolvido não diz **nada** sobre a causa, nem um identificador de
    erro. A alternativa era carimbar um id de correlação na resposta para casar
    com a linha do log, que é a prática certa num sistema com suporte — e aqui
    não há suporte, há um aluno na frente da tela e um log que quem opera lê por
    horário. O id seria um enfeite que precisa ser mantido.

    Só o método e o **caminho** entram no log: a query string não, porque é o
    lugar por onde um parâmetro de aluno entraria numa linha de log sem ninguém
    decidir que entraria.
    """
    registrar(
        logger,
        logging.ERROR,
        "falha não tratada",
        {"metodo": request.method, "caminho": request.url.path},
        exc_info=True,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": FALHA_GENERICA},
    )


def criar_app() -> FastAPI:
    """Monta uma aplicação nova a partir da configuração atual.

    Era um `app = FastAPI(...)` no corpo do módulo. Virou função porque as
    origens de CORS deixaram de ser literais: com a montagem no import, a única
    configuração testável é a que estiver valendo no processo do pytest, e o
    teste de "recusa origem não declarada" não teria como declarar origem
    nenhuma. O `app` do módulo continua existindo logo abaixo — quem só importa
    `app.main:app`, uvicorn incluído, não percebe diferença.
    """
    observabilidade.configurar_logs(settings.nivel_de_log)

    app = FastAPI(title="IEE — API", lifespan=lifespan)

    # Teto de tamanho de corpo (ver `app/limites.py`). Registrado **antes** do
    # CORS de propósito: o Starlette põe o último middleware registrado por
    # fora, e o 413 precisa sair com os cabeçalhos de CORS — senão o navegador
    # reporta erro de rede genérico em vez do erro real, e quem estiver
    # depurando procura no lugar errado.
    app.add_middleware(LimiteDeCorpo)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.origens_de_cors(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Registrado na classe base `Exception` de propósito: `HTTPException` e erro
    # de validação já têm resposta própria e continuam com ela. O que este
    # handler pega é só o que ninguém previu.
    app.add_exception_handler(Exception, _tratar_falha_inesperada)

    app.include_router(auth.router)
    app.include_router(sessoes.router)
    # O catálogo de métodos mora no mesmo módulo, mas não sob `/sessoes`: ele não é
    # um recurso da sessão, e sim o vocabulário que ela declara.
    app.include_router(sessoes.router_metodos)
    app.include_router(telemetria.router)

    _registrar_rotas_de_saude(app)
    return app


def _registrar_rotas_de_saude(app: FastAPI) -> None:
    """Duas sondas com perguntas diferentes, e um apelido para não quebrar ninguém.

    **Por que duas rotas e não uma com detalhe no corpo.** Quem lê estas rotas é
    um orquestrador, e ele não lê corpo: lê código HTTP e age. As duas perguntas
    levam a ações opostas —

    - *vivo?* (`/vivo`): o processo responde? Se não, **reinicie a task**.
    - *pronto?* (`/pronto`): as dependências respondem? Se não, **tire da
      rotação**, e espere.

    Uma rota só, respondendo pelas duas, obriga a escolher um dos dois erros.
    Se ela checar o banco e servir de liveness, uma indisponibilidade do RDS
    vira reinício em laço da aplicação — que estava perfeitamente viva — e o
    log do incidente passa a ser sobre contêineres morrendo, não sobre o banco.
    Se ela não checar nada e servir de readiness, é o defeito que existe hoje:
    a task entra na rotação com o banco fora e o aluno recebe 500 de uma
    aplicação que o painel jura estar saudável. Responder no corpo em vez do
    código HTTP não resolve nenhum dos dois, porque exigiria que a sonda
    interpretasse JSON — e a sonda que o ECS configura não interpreta.

    **`/health` continua existindo**, com o mesmo corpo `{"status": "ok"}` de
    sempre, e passa a ser a sonda de prontidão. Apontá-lo para `/vivo` seria
    mais conservador (nunca falharia) e manteria exatamente a mentira que §2.2
    existe para desfazer; quem já aponta para `/health` está perguntando "posso
    mandar tráfego?", e agora recebe a resposta verdadeira. O corpo fica como
    era para não quebrar quem o consome.
    """

    @app.get("/vivo")
    def vivo() -> dict:
        """O processo está de pé e respondendo. Não toca em nada externo."""
        return {"status": "vivo"}

    @app.get("/pronto")
    def pronto(response: Response) -> dict:
        """O processo está de pé **e** o banco responde.

        Devolve 503 quando não, que é o código que faz o balanceador tirar a
        task da rotação sem matá-la.
        """
        if _banco_responde():
            return {"status": "pronto", "banco": "ok"}

        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "indisponivel", "banco": "inacessivel"}

    @app.get("/health", deprecated=True)
    def health(response: Response) -> dict:
        """Apelido histórico de `/pronto`, com o corpo original preservado.

        Mantido porque pode haver sonda apontada para cá. Novos consumidores
        usam `/vivo` ou `/pronto`, que dizem qual pergunta estão fazendo.
        """
        if _banco_responde():
            return {"status": "ok"}

        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "indisponivel", "banco": "inacessivel"}


app = criar_app()
