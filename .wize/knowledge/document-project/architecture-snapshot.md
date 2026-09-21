---
status: baseline
owner: Pepper Potts + Tony Stark
created: 2026-09-19
last_refreshed: 2026-09-19
sampled: "backend/app/**, frontend/src/app/**, ml/*.py, angular.json, revisao-arquitetura-2026-08-13.pdf"
---

# Architecture Snapshot

Estado real em 19/09/2026, não o estado desejado. Onde o desenho diverge do que o TCC
promete, a divergência está registrada.

## Forma geral

Cliente-servidor desacoplado, com **três partes que não compartilham runtime**:

| Parte | Runtime | Papel |
|---|---|---|
| `frontend/` | Angular 18, navegador | Captura, visão computacional, UI |
| `backend/` | Python 3.9, FastAPI | Auth, sessões, cálculo do IEE, persistência |
| `ml/` | Python 3.11, offline | Extração do DAiSEE e treino do Random Forest |

O `ml/` **não é chamado por ninguém em tempo de execução** — ver "Integrações".

## Entry points

- **Backend:** `backend/app/main.py:16` (`FastAPI(title="IEE — API", lifespan=lifespan)`).
  O `lifespan` (`main.py:10-13`) roda `criar_tabelas()` no boot. Sobe com
  `uvicorn app.main:app --reload` na porta 8000. Não há Dockerfile nem comando de produção.
- **Frontend:** `frontend/src/main.ts:6`, `bootstrapApplication` — nenhum `NgModule` no projeto.
  `ng serve` na 4200; `ng build` sai em `dist/frontend`.
- **ML:** dois CLIs manuais — `ml/extrair_features.py --raiz <DAiSEE>` e `ml/treinar.py`.

## Componentes

### Backend

Camada HTTP fina em `app/routers/` delegando a módulos de domínio puros no nível de `app/`,
que não importam FastAPI nem SQLAlchemy:

- `app/sessoes.py` — ciclo de vida da sessão; exceções de domínio (`SessaoNaoEncontrada`,
  `SessaoJaEncerrada`, `SessaoAtivaJaExiste`).
- `app/analista.py` — `AnalistaEngajamento` (calibração + fórmula do IEE),
  `DetectorDeFadiga` (`analista.py:232-395`) e `RegistroDeAnalistas` (`analista.py:510-559`).
- `app/telemetria.py` — só persistência da série.
- `app/security.py` — bcrypt e JWT; `app/tempo.py` — normalização UTC.
- `app/database.py:23-74` — `criar_tabelas()` mais uma migração caseira
  (`_acrescentar_colunas_faltantes`, só `ALTER TABLE ADD COLUMN`).

Endpoints:

| Método | Rota | Observação |
|---|---|---|
| `GET` | `/health` | sem auth |
| `POST` | `/auth/registro` | 409 se e-mail duplicado |
| `POST` | `/auth/login` | devolve JWT |
| `GET` | `/auth/me` | protegida |
| `POST` | `/sessoes` | 409 se já há sessão ativa |
| `GET` | `/sessoes/ativa` | **também escreve**: varre e encerra inativas |
| `POST` | `/sessoes/{id}/atividade` | heartbeat |
| `POST` | `/sessoes/{id}/encerrar` | encerramento manual |
| `WS` | `/telemetria` | auth pela primeira mensagem JSON |

### Frontend

Três rotas apenas (`app.routes.ts`): `login`, `registro`, `home` (protegida por `authGuard`).
Não existe rota de relatório nem de histórico.

- `core/visao/metricas.ts` e `core/visao/qualidade.ts` — aritmética pura, não importam MediaPipe.
- `core/visao/landmarks.service.ts` — único ponto que conhece `@mediapipe/tasks-vision`.
- `core/telemetria/` — `telemetria.service.ts` (WebSocket, backoff) e `agregacao.ts`.
- `shared/grafico-iee.component.ts` — **existe mas está órfão**: nenhuma página o importa.
- `styles.css` (1000 linhas) — design system inteiro em folha global.

### ML

`esquema.py` é o contrato de colunas que os dois lados importam. `daisee.py` (layout em disco),
`extracao.py` (vídeo → frame, com detector injetado), `metricas.py` (EAR/MAR/head pose),
`agregacao.py` (frames → clipe, 39 features), `treino.py`, `relatorio.py`.

## Fluxo de dados — sessão de estudo ponta a ponta

```
navegador                                          backend                    banco
─────────                                          ───────                    ─────
getUserMedia (camera.service)
   │
   ├─ <video> preview  ──────────── nada sai daqui
   │
   └─ FaceLandmarker (GPU→CPU fallback)
        │ requestAnimationFrame, fora da NgZone
        ▼
      metricas.ts  → EAR, MAR, yaw/pitch/roll, assimetria
      qualidade.ts → veredito: baixa-luz | reflexo-ocular | oclusao
        │            (luminância medida por canvas MORRE AQUI)
        ▼
      agregacao.ts  amostra 250 ms, envia 1 Hz
        │  payload = { ear, yaw, mar, rosto_detectado, incerteza }
        │  ← a fronteira de privacidade do projeto
        ▼
     WebSocket ws://…/telemetria
        │  1ª mensagem = { token }
        ▼────────────────────────────►  resolve sessão ativa pelo token
                                        (cliente não escolhe id_sessao)
                                          │
                                          ▼
                                     AnalistaEngajamento
                                       baseline: mediana dos 60 s
                                       IEE = P(t)×[0,6·EAR_n + 0,4·HP_n] − F
                                          │
                                     DetectorDeFadiga
                                       PERCLOS · microssono · bocejo
                                       teto de 40 pontos
                                          │
                                          ├──────────────────────► LogEngajamento
                                          │                         score pode ser NULL
                                          ▼                         (incerteza + motivo)
        ◄───── { tipo, score, calibrando, fadiga, motivos_fadiga, incerteza }
        │
        └─ o cliente recebe o score e DELIBERADAMENTE não o mostra
           (tickets.md:127-137 — decisão de 27/08/2026)
```

O último passo do produto — o relatório que lê essa série de volta — **não existe**. A série é
gravada e nada a apresenta.

## Integrações

- **Banco:** SQLite em arquivo (`app/config.py:13`, `backend/app.db`). PostgreSQL/RDS é previsto
  no spec e no TCC, não implementado.
- **MediaPipe:** roda no navegador. WASM vem do `node_modules` via `angular.json:23-27`; o modelo
  `face_landmarker.task` (~3 MB) **não é versionado** e precisa de download manual.
- **Random Forest:** o artefato `ml/artefatos/random_forest.joblib` **não é carregado pelo backend**.
  `backend/app/analista.py` não importa `sklearn` nem `joblib`. A ticket 8 substituiu o modelo por
  regras, com a medição registrada em `resultado_18_08.md`.
- **Nuvem:** nenhuma. Sem Dockerfile, sem Terraform, sem CI.

## Seams

O spec elege `AnalistaEngajamento` como seam principal, e ele cumpriu: recebe features, devolve
score e alertas, sem banco, WebSocket nem UI — testável com vetores sintéticos
(`backend/tests/test_analista.py`, 328 linhas).

Seams secundários que se mantiveram: `metricas.ts`/`qualidade.ts` (aritmética pura),
`landmarks.service.ts` (troca de biblioteca de visão mexe num arquivo só), e o detector injetado
em `ml/extracao.py`.

## Dívida de arquitetura já diagnosticada

A revisão de 13/08/2026 (`revisao-arquitetura-2026-08-13.pdf`) levantou 5 candidatos sobre as
tickets 3 e 4. Dois continuam válidos e **não foram endereçados**:

1. **Presença na sessão decidida em três módulos com três relógios** (`sessao.service.ts` 60 s,
   `inactivity.service.ts` 15 min, `app/sessoes.py` 10 min). O heartbeat bate incondicionalmente
   enquanto a aba está aberta, então a varredura do backend não dispara e cadeira vazia vira tempo
   de estudo. Numa PoC cujo produto é um relatório, a duração da sessão é o número que sustenta o resto.
2. **`buscar_ativa` varre e comita** — uma leitura que escreve, com `SELECT` global de todas as
   sessões abertas de todos os alunos, em toda operação de sessão.
