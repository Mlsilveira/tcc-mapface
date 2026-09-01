# MapFace — Índice de Engajamento no Estudo (IEE)

Prova de conceito de uma aplicação web que ajuda o estudante a **perceber quando perdeu o foco** durante uma sessão de estudo solitária.

O estudante inicia uma sessão, autoriza a webcam, e seus sinais visuais comportamentais — abertura dos olhos (EAR), orientação da cabeça (Head Pose) e indícios de bocejo (MAR) — são extraídos **inteiramente no navegador** via MediaPipe Face Mesh. O backend calcula o Índice de Engajamento no Estudo, uma métrica de 0 a 100 calibrada individualmente, e ao final entrega um relatório de autopercepção.

O sistema **não diagnostica, não avalia e não julga**. Ele mede proxies comportamentais visuais e devolve isso ao próprio estudante.

## Privacidade por design

Nenhuma imagem ou vídeo sai do navegador — apenas coordenadas numéricas trafegam para o backend, e o schema do banco não tem campo para dados brutos de imagem. Os dados de um estudante são visíveis apenas para ele: não existe papel de professor, coordenação ou administrador.

A avaliação de qualidade da captura (ticket 10) mede a luminância do quadro, e essa é a única leitura de pixels do sistema fora do MediaPipe. Ela também não atravessa: o que sobe é o veredito — um rótulo como `baixa-luz` —, nunca o número que o produziu.

## Stack

| Camada | Tecnologia |
|---|---|
| Frontend | Angular 18 (standalone components, signals) |
| Backend | FastAPI + SQLModel |
| Banco | SQLite na PoC; PostgreSQL previsto para o deploy |
| Autenticação | JWT (python-jose) + bcrypt |
| Visão computacional | MediaPipe Face Mesh (client-side) |
| ML | Random Forest treinado com o dataset DAISEE |
| Infra | AWS (S3, ECR, ECS Fargate, RDS) via Terraform |

## Interface

O visual segue o repertório das plataformas de estudo brasileiras — tela de acesso dividida entre um painel de marca e o formulário, uma cor primária forte, cards arredondados —, mas com o tom da proposta: o MapFace é um espelho, não um vendedor de curso. Nada de contagem de aprovados ou urgência; o que o painel de acesso promete é privacidade e calibração individual.

O sistema de design mora inteiro em [`frontend/src/styles.css`](./frontend/src/styles.css): tokens de cor, tipografia, botões e campos. Índigo é a cor de ação e de marca; verde é reservado ao que está vivo (sessão em andamento, rosto detectado), para não virar decoração. As fontes vêm do Google Fonts, com fallback para a fonte do sistema quando não há rede.

O layout responde em três faixas: abaixo de 960px a tela de acesso empilha o painel de marca sobre o formulário; abaixo de 860px a sessão passa a uma coluna só e o preview da webcam ganha um teto de altura, para que rosto e métricas continuem visíveis juntos; acima de 1600px o painel de marca ganha respiro em vez de esticar o texto.

Antes de a câmera acender, a tela do estudante explica em três passos o que vai acontecer — pedir webcam sem explicar é o jeito mais rápido de o aluno negar a permissão.

**Durante a sessão, a tela não mostra o score.** Um número de atenção competiria com a tarefa que ele mede: o aluno olha para o número, e o ato de olhar derruba o número. O MapFace é um espelho retrospectivo — a leitura vem no relatório, quando ele tem distância para agir sobre ela. O que aparece enquanto ele estuda é só o que dá para resolver na hora: o preview da webcam, o FPS e o alerta de incerteza de captura.

## Estado atual

Implementado:

- **Ticket 3 — Cadastro e login.** Registro com hashing bcrypt, login com JWT, rotas protegidas no Angular e expiração por inatividade.
- **Ticket 4 — Ciclo de vida da sessão de estudo.** Iniciar e encerrar sessão, associada ao aluno autenticado, com encerramento automático por inatividade prolongada.
- **Ticket 5 — Captura client-side.** Permissão de webcam com mensagem por tipo de falha, preview durante a sessão, extração de landmarks via MediaPipe e cálculo local de EAR, MAR e Head Pose, com FPS medido na tela.
- **Ticket 6 — Canal de telemetria.** WebSocket autenticado pela primeira mensagem, agregação a 1 Hz no cliente, reconexão automática com backoff e log persistido em `log_engajamento`.
- **Ticket 7 — Fórmula real do IEE.** `AnalistaEngajamento` calibra a baseline individual do aluno nos primeiros 60 s e passa a medir EAR e Head Pose contra ela, em vez de contra constantes iguais para todo mundo.
- **Ticket 8 — Fator de fadiga.** `DetectorDeFadiga` penaliza o IEE por pálpebra pesada (PERCLOS), fechamento prolongado e bocejo, com os limiares relativos à baseline do aluno. O fator vem de regras, e não do Random Forest — o porquê está em [`resultado_18_08.md`](./resultado_18_08.md).
- **Ticket 10 — Incerteza de captura.** Em pouca luz, com reflexo nos óculos ou com o rosto parcialmente ocluso, o sistema se abstém de medir em vez de emitir um score enganoso: a interface diz o que ajustar e o banco grava o ponto com `score` nulo e o motivo em `alerta`.

O plano completo, com as 16 fatias verticais e suas dependências, está em [`tickets.md`](./tickets.md). O problema, as histórias de usuário e as decisões de arquitetura estão em [`spec-poc-iee.md`](./spec-poc-iee.md).

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

Do npm 11 em diante, os scripts de instalação das dependências vêm bloqueados por padrão — e o do puppeteer é justamente quem baixa esse Chromium. Em máquina limpa, o `npm test` falha por falta do binário do Chrome sem dizer o porquê. Se acontecer, baixe o navegador explicitamente:

```bash
cd frontend && npx puppeteer browsers install chrome
```

## Organização do código

```
backend/
  app/
    sessoes.py       regras do ciclo de vida da sessão, sem depender de HTTP
    analista.py      calibração da baseline, fórmula do IEE e fator de fadiga
    telemetria.py    persistência da série de engajamento
    security.py      hashing de senha e emissão/validação de JWT
    tempo.py         normalização de datetimes para UTC
    models.py        tabelas aluno, sessao_estudo e log_engajamento
    database.py      engine, criação de tabelas e migração leve de colunas
    routers/         endpoints de autenticação e de sessão
  tests/
frontend/src/app/
  core/
    services/        auth, sessão de estudo, inatividade, webcam
    visao/           metricas.ts (EAR/MAR/Head Pose), qualidade.ts (incerteza)
                     e landmarks.service.ts, a ponte com o MediaPipe
    guards/          bloqueio de rotas protegidas
    interceptors/    anexa o JWT às requisições
  pages/             login, registro, área do estudante
  shared/            marca (logo) e ícones de traço usados nas três telas
frontend/src/styles.css   sistema de design: tokens, botões, campos, telas
```

As regras de negócio ficam fora do FastAPI de propósito — `app/sessoes.py` e `app/analista.py` não conhecem HTTP, banco de requisição nem UI, e é onde os testes de comportamento batem. O `AnalistaEngajamento` é o seam principal do spec: entrou na ticket 7 com a calibração e a fórmula do IEE, e recebe o fator de fadiga na ticket 8.

No frontend a divisão é a mesma: `core/visao/metricas.ts` e `core/visao/qualidade.ts` são aritmética pura — sobre pontos e sobre sinais de captura — e não importam o MediaPipe. Só `landmarks.service.ts` conhece a biblioteca de visão computacional, então trocá-la mexe num arquivo só.

`criar_tabelas` acrescenta ao banco as colunas que os modelos ganharam desde a última execução. `SQLModel.metadata.create_all` só cria tabela nova: numa tabela existente ele não faz nada e não avisa, então uma coluna acrescentada a um modelo só apareceria no primeiro INSERT, como erro no meio da sessão de estudo de alguém. A migração é estreita de propósito — acrescenta coluna, e nada mais. Remover, renomear ou mudar tipo exige decidir o que fazer com os dados já gravados, e é aí que uma ferramenta de migração de verdade passa a valer o próprio peso; a ticket 15 é a candidata natural.

## Equipe

Trabalho de Conclusão de Curso. Duas trilhas em paralelo: **ML** (extração de features do DAISEE e treino do Random Forest) e **App/Infra** (aplicação e provisionamento), convergindo na ticket 8.
