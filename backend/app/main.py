from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import criar_tabelas
from app.routers import auth, sessoes, telemetria


@asynccontextmanager
async def lifespan(app: FastAPI):
    criar_tabelas()
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
    return {"status": "ok"}
