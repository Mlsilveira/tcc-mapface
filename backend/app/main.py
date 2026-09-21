from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import criar_tabelas
from app.routers import auth, sessoes, telemetria


@asynccontextmanager
async def lifespan(app: FastAPI):
    criar_tabelas()
    yield


app = FastAPI(title="IEE — API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200"],
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
