# MapFace — Índice de Engajamento no Estudo (IEE)

Prova de conceito de uma aplicação web que ajuda o estudante a **perceber quando perdeu o foco** durante uma sessão de estudo solitária.

O estudante inicia uma sessão, autoriza a webcam, e seus sinais visuais comportamentais — abertura dos olhos (EAR), orientação da cabeça (Head Pose) e indícios de bocejo (MAR) — são extraídos **inteiramente no navegador** via MediaPipe Face Landmarker. O backend calcula o Índice de Engajamento no Estudo, uma métrica de 0 a 100 calibrada individualmente, e ao final entrega um relatório de autopercepção.

O sistema **não diagnostica, não avalia e não julga**. Ele mede proxies comportamentais visuais e devolve isso ao próprio estudante.

## Privacidade por design

Nenhuma imagem ou vídeo sai do navegador — apenas coordenadas numéricas trafegam para o backend, e o schema do banco não tem campo para dados brutos de imagem. Os dados de um estudante são visíveis apenas para ele: não existe papel de professor, coordenação ou administrador.

## Stack

| Camada | Tecnologia |
|---|---|
| Frontend | Angular 18 (standalone components, signals) |
| Backend | FastAPI + SQLModel |
| Banco | SQLite na PoC; PostgreSQL previsto para o deploy |
| Autenticação | JWT (python-jose) + bcrypt |
| Visão computacional | `@mediapipe/tasks-vision` (FaceLandmarker), client-side |
| Telemetria | WebSocket (FastAPI) |
| ML | Random Forest treinado com o dataset DAISEE |
| Infra | AWS (S3, ECR, ECS Fargate, RDS) via Terraform |

## Estado atual

Implementado:

- **Ticket 3 — Cadastro e login.** Registro com hashing bcrypt, login com JWT, rotas protegidas no Angular e expiração por inatividade.
- **Ticket 4 — Ciclo de vida da sessão de estudo.** Iniciar e encerrar sessão, associada ao aluno autenticado, com encerramento automático por inatividade prolongada.
- **Ticket 5 — Captura client-side.** Permissão de webcam com mensagem por tipo de falha, preview durante a sessão, extração de landmarks via MediaPipe e cálculo local de EAR, MAR e Head Pose, com FPS medido na tela.
- **Ticket 6 — Canal de telemetria.** WebSocket autenticado pela primeira mensagem (nunca por query param), score provisório calculado a cada payload, log persistido em `log_engajamento`, agregação client-side a 1 Hz e reconexão automática com backoff exponencial.

Também já tem design próprio, à frente do cronograma de tickets: as telas de login/cadastro e o estado inicial da área do estudante (antes de a sessão começar). O estado *durante* a sessão segue com acabamento mínimo de propósito — ele muda com as tickets 9 e 10, e ganha o design definitivo na ticket 17.

O plano completo, com as 17 fatias verticais e suas dependências, está em [`tickets.md`](./tickets.md). O problema, as histórias de usuário e as decisões de arquitetura estão em [`spec-poc-iee.md`](./spec-poc-iee.md).

## Rodando localmente

Pré-requisitos: Python 3.9+, Node 18+.

### Backend

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
.venv/bin/python -m uvicorn app.main:app --reload
```

A API sobe em `http://localhost:8000`, com documentação interativa em `http://localhost:8000/docs`.

Antes de rodar em qualquer ambiente real, troque a `SECRET_KEY` no `.env` por um valor aleatório. O `.env` não é versionado.

### Frontend

```bash
cd frontend
npm install
npm start
```

A aplicação sobe em `http://localhost:4200` e espera o backend em `http://localhost:8000`.

#### Modelo do MediaPipe

Os binários WASM vêm no pacote npm e são copiados pelo build. O arquivo do modelo, não — ele precisa ser baixado uma vez para `frontend/src/assets/mediapipe/`:

```bash
mkdir -p frontend/src/assets/mediapipe && curl -L -o frontend/src/assets/mediapipe/face_landmarker.task https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task
```

Sem ele a sessão ainda inicia e é registrada, mas sem métricas de engajamento — a interface avisa. O arquivo tem ~3 MB e não é versionado.

A webcam só é liberada pelo navegador em contexto seguro: `localhost` funciona, mas um IP na rede local, não.

## Testes

```bash
cd backend && .venv/bin/python -m pytest
```

```bash
cd frontend && npm test
```

A suíte do Angular usa o Chromium que vem com o puppeteer, então não depende de um navegador instalado na máquina.

## Organização do código

```
backend/
  app/
    sessoes.py      regras do ciclo de vida da sessão, sem depender de HTTP
    telemetria.py   score provisório e persistência do log de engajamento
    security.py     hashing de senha e emissão/validação de JWT
    tempo.py        normalização de datetimes para UTC
    models.py       tabelas aluno, sessao_estudo e log_engajamento
    routers/        endpoints de autenticação, sessão e o WebSocket de telemetria
  tests/
frontend/src/app/
  core/
    services/       auth, sessão de estudo, inatividade, webcam
    visao/          metricas.ts (EAR/MAR/Head Pose) e a ponte com o MediaPipe
    telemetria/     agregação a 1 Hz e o canal WebSocket com reconexão
    guards/         bloqueio de rotas protegidas
    interceptors/   anexa o JWT às requisições
  pages/            login, registro, área do estudante
```

As regras de negócio ficam fora do FastAPI de propósito — `app/sessoes.py` não conhece HTTP, banco de requisição nem UI, e é onde os testes de comportamento batem. O mesmo vale para `app/telemetria.py`, que já está desenhado para a ticket 7 trocar as constantes fixas do score provisório pela baseline calibrada de cada aluno sem mudar o formato, e para o `AnalistaEngajamento`, que entra nas tickets 7 e 8.

No frontend a divisão é a mesma: `core/visao/metricas.ts` e `core/telemetria/agregacao.ts` são funções puras e não importam o MediaPipe nem o WebSocket. Só `landmarks.service.ts` conhece a biblioteca de visão computacional, e só `telemetria.service.ts` conhece o WebSocket — trocar qualquer um dos dois mexe num arquivo só.

## Equipe

Trabalho de Conclusão de Curso. Duas trilhas em paralelo: **ML** (extração de features do DAISEE e treino do Random Forest) e **App/Infra** (aplicação e provisionamento), convergindo na ticket 8.
