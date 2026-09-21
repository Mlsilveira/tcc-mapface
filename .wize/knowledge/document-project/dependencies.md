---
status: baseline
owner: Pepper Potts
created: 2026-09-19
last_refreshed: 2026-09-19
sampled: "backend/requirements.txt, frontend/package.json, ml/requirements.txt"
---

# Dependencies

Três ambientes isolados de propósito. O `ml/` soma centenas de MB (MediaPipe, OpenCV,
scikit-learn) e é mantido fora da imagem do backend — decisão registrada em `ml/README.md:5`.

## Backend — Python 3.9 (`backend/requirements.txt`)

Versões travadas com `==`, sem lockfile com hash.

| Pacote | Versão | Papel neste repo | Load-bearing? |
|---|---|---|---|
| `fastapi` | 0.115.0 | API REST e WebSocket | sim |
| `uvicorn[standard]` | 0.30.6 | Servidor ASGI | sim |
| `sqlmodel` | 0.0.22 | Modelos e ORM (sobre SQLAlchemy + Pydantic) | sim |
| `bcrypt` | 5.0.0 | Hash de senha — usado direto, sem passlib | sim |
| `python-jose[cryptography]` | 3.3.0 | Emissão e validação do JWT (HS256) | sim |
| `pydantic-settings` | 2.5.2 | Configuração via `.env` (`app/config.py`) | sim |
| `python-multipart` | 0.0.9 | Form data do fluxo OAuth2 do login | sim |
| `email-validator` | 2.2.0 | Validação de e-mail no registro | sim |
| `pytest` | 8.3.3 | Testes | dev |
| `httpx` | 0.27.2 | Cliente do `TestClient` | dev |

**Ausências que importam:** não há `psycopg2`/`asyncpg` (o spec prevê PostgreSQL), não há
`alembic` (migração é caseira), não há biblioteca de rate limiting, não há `scikit-learn` nem
`joblib` — o backend não carrega o modelo.

Um commit registra a troca deliberada de `passlib` por `bcrypt` puro, cobrindo o limite de
72 bytes.

## Frontend — Node/npm (`frontend/package.json`)

| Pacote | Versão | Papel neste repo | Load-bearing? |
|---|---|---|---|
| `@angular/*` | ^18.2.0 | Framework (common, compiler, core, forms, platform-browser, router) | sim |
| `@mediapipe/tasks-vision` | ^1.0.1 | Face Mesh no navegador; WASM copiado no build | sim |
| `chart.js` | ^4.5.1 | Gráfico do IEE — **adicionada e ainda não commitada** | ainda não |
| `rxjs` | ~7.8.0 | Fluxos assíncronos | sim |
| `zone.js` | ~0.14.10 | Change detection do Angular | sim |
| `tslib` | ^2.3.0 | Helpers do TypeScript | sim |
| `@angular-devkit/build-angular`, `@angular/cli`, `@angular/compiler-cli` | ^18.2.0 | Build | dev |
| `karma` + `karma-*` | ~6.4 / ~2.2 / ~5.1 | Runner de teste e coverage | dev |
| `jasmine-core`, `@types/jasmine` | ~5.2 / ~5.1 | Framework de teste | dev |
| `puppeteer` | ^25.6.0 | Fornece o Chromium do `ng test` | dev |
| `typescript` | ~5.5.0 | Compilador | dev |

**Ausências que importam:** `@angular/material` e `jwt-decode` são citados no capítulo 7 do TCC
mas **não estão instalados** — a UI é CSS próprio e o token não é decodificado no cliente. Não
há ESLint nem Prettier. O TCC também cita `@mediapipe/face_mesh`; o pacote realmente usado é
`@mediapipe/tasks-vision`.

**Asset externo:** `face_landmarker.task` (~3 MB) não vem por npm nem pelo git — download manual
documentado em `README.md:81-89`. Sem ele a sessão roda sem métricas.

## ML — Python 3.11 (`ml/requirements.txt`)

Python 3.11 é obrigatório: `mediapipe` 0.10 não publica wheel para o 3.9 do backend.

| Pacote | Versão | Papel neste repo | Load-bearing? |
|---|---|---|---|
| `mediapipe` | 0.10.14 | Face Mesh offline sobre os vídeos do DAiSEE | sim |
| `opencv-python` | 4.10.0.84 | Leitura de vídeo e `solvePnP` do head pose | sim |
| `numpy` | 1.26.4 | Álgebra das métricas | sim |
| `pandas` | 2.2.3 | Tabulação de frames e clipes | sim |
| `scikit-learn` | 1.5.2 | Random Forest, imputação, Pipeline | sim |
| `joblib` | 1.4.2 | Serialização do artefato | sim |
| `pyarrow` | 17.0.0 | Escrita dos `.parquet` (shards, frames, clipes) | sim |
| `pytest` | 8.3.3 | Testes | dev |

## Observações transversais

- **Divergência de runtime Python** entre backend (3.9.6) e ml (3.11) é a razão prática de a
  integração do `.joblib` ser custosa — `ml/treino.py:428-449` já emite warning quando a versão
  do scikit-learn diverge entre treino e carregamento.
- **Nenhum audit de vulnerabilidade foi executado nesta baseline.** `npm audit --omit=dev` e um
  scanner equivalente para os dois `requirements.txt` continuam pendentes.
- Nenhuma dependência duplicada fazendo o mesmo trabalho foi encontrada nas três listas.
