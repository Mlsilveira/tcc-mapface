import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.analista import registro
from app.config import settings
from app.database import criar_tabelas
from app.routers import auth, sessoes, telemetria


def _configurar_log_da_aplicacao() -> None:
    """Faz os `logger.info` dos módulos `app.*` aparecerem de verdade.

    **O defeito que isto corrige.** O uvicorn configura só os loggers dele; o
    logger raiz fica no nível padrão do Python, `WARNING`. Todo `logger.info` da
    aplicação era descartado em silêncio — inclusive a linha
    "classificador de sonolência carregado", que o tutorial de deploy manda
    procurar no log para confirmar que o modelo subiu. Ela nunca apareceu, em
    nenhum ambiente, e ninguém tinha como saber se o modelo estava carregado.

    O handler vai no logger `app`, e não no raiz, para não ligar de carona o
    `INFO` de toda biblioteca instalada. `propagate` continua ligado: é por ele
    que o `caplog` dos testes enxerga as mensagens.
    """
    raiz_da_aplicacao = logging.getLogger("app")
    if raiz_da_aplicacao.handlers:
        return
    saida = logging.StreamHandler()
    saida.setFormatter(logging.Formatter("%(levelname)s:     %(name)s: %(message)s"))
    raiz_da_aplicacao.addHandler(saida)
    raiz_da_aplicacao.setLevel(logging.INFO)


_configurar_log_da_aplicacao()


@asynccontextmanager
async def lifespan(app: FastAPI):
    criar_tabelas()
    # O classificador de sonolência entra aqui, e não na primeira sessão: são
    # alguns segundos de `joblib.load`, e pagá-los no meio do primeiro payload
    # atrasaria o loop de telemetria de um aluno de verdade. Ausência do
    # artefato não impede o boot — ver `app.sonolencia.carregar`.
    registro.preparar()
    yield


app = FastAPI(title="IEE — API", lifespan=lifespan)

# O endereço do frontend vem da configuração, e em produção a lista é **vazia**:
# o CloudFront serve o site e encaminha as rotas da API para cá, então navegador
# e API compartilham origem, e mesma origem não passa por CORS. O padrão
# (`http://localhost:4200`) serve o desenvolvimento local, onde `ng serve` e
# `uvicorn` são duas origens de verdade.
#
# Registrar o middleware mesmo com a lista vazia é de propósito: ele não libera
# nada que a lista não diga, e mantém um lugar só para a decisão — em vez de um
# `if` no boot que faria a aplicação ter duas formas possíveis.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.lista_de_origens,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(sessoes.router)
# O catálogo de métodos mora no mesmo módulo, mas não sob `/sessoes`: ele não é
# um recurso da sessão, e sim o vocabulário que ela declara.
app.include_router(sessoes.router_metodos)
app.include_router(telemetria.router)


@app.get("/health")
def health() -> dict:
    """Saúde da aplicação e **qual build está respondendo**.

    O build vai junto por causa do parecer do TC2 (F02): toda evidência do
    ambiente publicado — sessão real, medição de latência, relatório — precisa
    dizer de qual versão do código veio. Com a imagem marcada como `latest` isso
    era impossível de afirmar depois do fato, porque `latest` é uma etiqueta que
    anda. O commit é gravado na imagem no `docker build` e não muda mais.
    """
    return {"status": "ok", "build": settings.build_commit}
