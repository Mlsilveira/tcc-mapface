---
status: baseline
fase: sast
executado_em: 2026-09-21
scope: scope.md (modo sast-only, allowlist vazia)
alvo: /Users/matheussilveira/Documents/TCC @ feat/tickets-9-11 (e7f458a)
---

# Revisão de segurança do MapFace — relatório

Avaliação estática do código da aplicação, calibrada para o uso real previsto:
**duas ocasiões, poucas horas no ar, instância única na AWS, participantes
conhecidos, dado derivado de webcam de terceiros.** A severidade aqui não é a
genérica de um SaaS — é "isto impede o teste com usuários reais de acontecer,
ou torna desonesto o que se promete a eles?".

## O que não foi redescoberto

Quatro itens já registrados e deliberadamente fora deste relatório: ausência de
rate limiting; `POST /auth/registro` público; JWT em `localStorage` com janela
deslizante e teto de 12 h; WebSocket autenticado pela primeira mensagem. Eles
aparecem abaixo só quando **compõem** com um achado novo, e nesse caso estão
marcados como contexto, não como achado.

## O que a ausência dos artefatos do kit custou

A skill `wize-sec-red-teamer` pressupõe um pipeline (recon → enumerate → sast →
dast → report) apoiado em `.wize/security/scope.md`, e o kit pressupõe
`risk-profile.md`, `architecture.md` e `prd.md`. Nenhum existe. Adaptações e
custo:

1. **Sem alvo autorizado, três das cinco fases não rodaram.** O sistema não está
   publicado (tickets 14/15 não começaram), então `recon`, `enumerate` e `dast`
   não tinham contra o que rodar. Consequência concreta: **nada do que este
   relatório diz cobre TLS, grupo de segurança, RDS exposto à internet,
   cabeçalhos do balanceador ou o valor real de `AMBIENTE` na task publicada** —
   e é ali que, em deploys de PoC, costumam morar os furos mais caros. O que
   segue é a superfície do código, não a do ambiente.
2. **Sem `risk-profile.md`**, a régua de severidade foi construída neste
   relatório a partir do SPEC (`.wize/specs/spec-poc-iee/SPEC.md`: constraints,
   non-goals, "PoC acadêmica com prazo de banca") e do `risk-spots.md`. É uma
   régua defensável, mas é minha, não do projeto — se a orientação discordar do
   peso dado à privacidade dos participantes, os bloqueadores B5 e M5 mudam de
   lugar.
3. **Sem `architecture.md`**, o modelo de ameaça foi reconstruído lendo o
   código. O `architecture-snapshot.md` do `document-project` cobre componentes
   e fluxo, mas não fronteira de confiança nem ator hostil — então não há como
   afirmar que a lista de superfícies abaixo é exaustiva; é a que o código
   revelou.
4. **Nenhum gate do TEA rodou** neste projeto. Este relatório é a primeira
   passagem de segurança formal e não substitui `tea-nfr` / `tea-gate`.
5. **Dez ferramentas ausentes do PATH** (`gitleaks`, `osv-scanner`, `grype`,
   `trivy`, `semgrep`, `bandit`, `pip-audit`, `nuclei`, `nmap`, `nikto`). A
   skill não instala ferramenta sozinha. As checagens de segredo e de
   dependência foram feitas à mão (`git log --diff-filter=A`, `git grep`,
   leitura de `requirements.txt` e `package.json`) — cobertura menor que a
   automática, e assumo isso explicitamente.

---

# Bloqueadores para colocar usuários reais

Os quatro primeiros são de **disponibilidade**, e não de confidencialidade — o
que é a leitura correta para este sistema: o pior desfecho realista do teste
com colegas não é vazamento, é a aplicação travar com a turma na frente dela, e
o experimento inteiro se perder. B1 e B2 disparam com a **carga do próprio
experimento**, sem atacante nenhum.

## B1 — Cada WebSocket prende uma conexão do banco pela sessão inteira; o pool tem 15

**Evidência**
- `backend/app/routers/telemetria.py:139` — `db: Session = Depends(get_session)`
  no handler do WebSocket. Dependência com `yield` num WS vive enquanto o canal
  viver: horas.
- `backend/app/database.py:265-267` — `get_session` abre `Session(engine)` e
  segura até o handler retornar.
- `backend/app/database.py:63` — `create_engine(url, connect_args=...)`, sem
  `pool_size` nem `max_overflow`. Vale o default do SQLAlchemy: **5 + 10 = 15
  conexões**.
- `backend/app/telemetria.py:42` — `registrar_log` termina em `db.refresh(log)`,
  que reabre transação logo depois do commit. Entre dois payloads a conexão fica
  retida; e quando `rosto_detectado` é falso não há o commit de presença
  (`routers/telemetria.py:238-239`) que a soltaria.

**Cenário** — 16 colegas com a webcam ligada ao mesmo tempo. A décima sexta
conexão e **todo request HTTP** (login, heartbeat, `/sessoes/ativa`, `/pronto`)
ficam esperando o pool, estouram o timeout de 30 s e voltam 500. `/pronto`
falhando faz o orquestrador tirar a task da rotação (`main.py:192-203`); como a
topologia é de instância única e por requisito (README, "Uma réplica"), não há
para onde o tráfego ir. O teste acaba ali, e os dados da sessão de quem estava
no meio ficam pela metade.

Não é preciso atacante. É a turma.

**Recomendação** — dimensionar o pool para (participantes + folga):
`create_engine(url, pool_size=40, max_overflow=20, pool_pre_ping=True)`; ou,
melhor, tirar o `Depends(get_session)` do WS e abrir uma `Session` curta por
payload dentro do loop. Depois, medir com o número real de participantes antes
de marcar a data — este é o tipo de limite que não aparece em teste com duas
abas.

## B2 — O handler do WebSocket é `async` e faz I/O de banco síncrono no event loop

**Evidência**
- `backend/app/routers/telemetria.py:137` — `async def telemetria_ws(...)`.
- `backend/app/routers/telemetria.py:160` — chama `sessoes.buscar_ativa`, que
  chama `sessoes.encerrar_inativas` (`backend/app/sessoes.py:165` → `:116`):
  **varredura de todas as sessões abertas de todos os alunos**, com escrita e
  commit.
- `backend/app/routers/telemetria.py:211-217` — `telemetria.registrar_log`:
  INSERT + COMMIT + REFRESH, **uma vez por segundo por aluno**.
- Nada disso passa por `run_in_threadpool`. As rotas HTTP são `def` (síncronas)
  e por isso vão para o threadpool do Starlette; só o WebSocket é `async`, e é
  justamente ele que está no caminho quente.

**Cenário** — cada commit bloqueia o loop inteiro do processo. Com 20 alunos a
1 Hz contra um RDS com 20 ms de latência, o loop passa a ter ~40% do tempo
parado em I/O síncrono, e isso atinge tudo que o processo faz — inclusive
`/vivo` e `/pronto`. Pior: uma oscilação de Wi-Fi na sala faz os 20 clientes
reconectarem quase juntos (backoff inicial de 1 s,
`frontend/src/app/core/telemetria/telemetria.service.ts:39`), e cada reconexão
dispara uma varredura global de sessões abertas dentro do loop. É o cenário de
uma sala de aula com um roteador só.

**Recomendação** — `await run_in_threadpool(...)` em torno das três chamadas de
banco do handler, e tirar `encerrar_inativas` do caminho da conexão (ela não
precisa rodar quando um canal abre; precisa rodar periodicamente).

## B3 — `nome` sem teto no endpoint público de registro, e nenhum limite de tamanho de corpo

**Evidência**
- `backend/app/schemas.py:79` — `nome: str = Field(min_length=1)`. Sem
  `max_length`.
- Contraste com a disciplina que o próprio projeto pratica:
  `backend/app/schemas.py:20` (`LIMITE_SENHA_BYTES = 72`),
  `backend/app/schemas.py:48` (`LIMITE_ASSUNTO_CARACTERES = 120`, com três
  parágrafos justificando por que existe teto). O campo `nome` ficou de fora da
  mesma regra.
- Não há limite de corpo em lugar nenhum: nem no uvicorn (`Dockerfile:87`), nem
  em middleware.

**Cenário** — `POST /auth/registro` com um `nome` de dezenas de MB é aceito,
carregado inteiro na memória da única instância e gravado no RDS. Repetido — e
não há rate limiting (contexto conhecido) —, enche o armazenamento do banco que
guarda os dados do experimento. O agravante **novo** não é a ausência de limite
de taxa: é que **um request só já é grande**, então mesmo um limite de taxa
frouxo não protegeria.

**Recomendação** — `Field(min_length=1, max_length=120)` em `nome` (uma linha,
coerente com o resto do módulo) e limite de corpo no proxy/ALB (64 KB para esta
API é generoso).

## B4 — O WebSocket aceita a conexão antes de autenticar, sem timeout e sem teto

**Evidência**
- `backend/app/routers/telemetria.py:147` — `await websocket.accept()` acontece
  **antes** de `_autenticar` (linha 154).
- `backend/app/routers/telemetria.py:150` — `await websocket.receive_json()` sem
  `wait_for`: um cliente que abre e cala fica pendurado para sempre.
- Não há validação de `Origin` no handshake. O `CORSMiddleware`
  (`backend/app/main.py:134-140`) **não** cobre WebSocket — é uma confusão comum
  e vale registrar explicitamente.
- Não há teto de conexões por aluno nem por IP.

**Cenário** — um script abre milhares de conexões e nunca manda a primeira
mensagem. Cada uma custa um socket e uma task no event loop da instância única.
O handshake não cobra autenticação nenhuma, então não é preciso ter conta. A
aplicação para durante a apresentação, e o log não mostra nada além de conexões.

**O que *não* é problema, e vale dizer** — sequestro cross-site do canal
(CSWSH) não se aplica: a autenticação é por token na primeira mensagem, e uma
página de outra origem não consegue ler o `localStorage` da origem do MapFace.
A decisão de autenticar pela primeira mensagem (contexto conhecido) sai bem
deste exame. O problema é esgotamento, não roubo de sessão.

**Recomendação** — `asyncio.wait_for(websocket.receive_json(), timeout=5)` antes
da autenticação; validar `websocket.headers.get("origin")` contra
`settings.origens_de_cors()`; e um teto de canais por aluno (a regra de negócio
já diz que há **uma** sessão ativa por aluno — `sessoes.SessaoAtivaJaExiste`).

## B5 — A retenção de 24 h que o sistema promete só roda se o próprio aluno voltar

**Evidência**
- `backend/app/sumarizacao.py:121` — `aplicar_retencao(db, id_aluno, ...)`,
  janela de 24 h (`sumarizacao.py:50`).
- `backend/app/routers/sessoes.py:236` — **único** ponto de chamada, dentro de
  `GET /sessoes/historico`. O docstring assume isso ("o custo cai sobre quem se
  beneficia dele, e a PoC segue sem scheduler").

**Cenário** — é o comportamento esperado de um participante de experimento:
faz a sessão, fecha o navegador e não volta mais. A série ponto-a-segundo dele
— proxy comportamental derivado de webcam — fica granular no RDS
**indefinidamente**. Somado à ausência de rota de exclusão (contexto
conhecido), o que se pode honestamente dizer a um participante hoje é: "seus
dados ficam armazenados até eu apagar o banco à mão".

Isto é bloqueador não por risco técnico, e sim porque **o teste envolve pessoas
que precisam receber uma descrição verdadeira do que acontece com o dado
delas**. O eixo declarado do TCC é privacidade; uma retenção que não executa é
exatamente o tipo de promessa que a banca tem o direito de cobrar.

**Recomendação** (barata, nesta ordem):
1. Chamar a varredura de retenção para todos os alunos no `lifespan`
   (`backend/app/main.py:29-56`) — cobre quem nunca volta, a cada deploy.
2. Descrever aos participantes a retenção **real**, não a pretendida.
3. Ter um procedimento manual de exclusão combinado antes do teste (um `DELETE`
   por aluno, documentado), já que a rota não existe.

---

# Médios — corrija se houver tempo; não bloqueiam

## M1 — Oráculo de existência de conta pelo tempo de resposta do login

`backend/app/routers/auth.py:30-34` — quando o e-mail não existe,
`verificar_senha` nem chega a ser chamado; quando existe, o bcrypt (custo
padrão, `backend/app/security.py:64`) gasta centenas de milissegundos. A
diferença é medível com **um** request, sem precisar de volume.

É distinto do 409 explícito do registro (`auth.py:15-19`), que entrega a mesma
informação pela porta da frente. O impacto real neste contexto: descobrir quais
colegas participaram do estudo — que, num TCC sobre monitoramento de
comportamento, é informação sobre a pessoa.

Correção: verificar contra um hash fictício no ramo "não existe", para que os
dois caminhos custem o mesmo.

## M2 — `/docs`, `/redoc` e `/openapi.json` abertos na instância publicada

`backend/app/main.py:132` — `FastAPI(title=..., lifespan=...)` sem
`docs_url=None`. Entrega o mapa completo da API a quem achar a URL. Numa PoC de
vida curta com URL não divulgada, o risco é baixo; o custo de fechar é uma
linha, e o de manter aberto é ter que contar com a obscuridade da URL.

## M3 — Sem `pool_pre_ping` contra RDS

`backend/app/database.py:63`. Conexão ociosa derrubada pelo RDS ou por NAT vira
500 na primeira requisição depois de um intervalo parado — que é exatamente o
que acontece **entre o teste com os colegas e o dia da banca**. Uma linha:
`pool_pre_ping=True`.

## M4 — A varredura de sessões inativas é global e disparável por qualquer aluno autenticado

`backend/app/sessoes.py:116` (dentro de `buscar_ativa`, `sessoes.py:165`),
chamada em `GET /sessoes/ativa` e na abertura de cada WebSocket. Um aluno em
laço sobre `GET /sessoes/ativa` — sem rate limiting, contexto conhecido — faz a
aplicação varrer e **escrever** nas sessões de todos os outros.

Não é quebra de autorização: nada de outro aluno é lido de volta, e a regra que
encerra é a mesma que rodaria sozinha. Mas é escrita cruzada entre contas
disparável por um usuário qualquer, e o README documenta o custo da varredura
sem mencionar que ela é global e disparável de fora.

## M5 — Google Fonts de terceiro, na aplicação cujo eixo é privacidade

`frontend/src/index.html:17-22` — `preconnect` e stylesheet para
`fonts.googleapis.com` e `fonts.gstatic.com`, sem SRI.

É a **única** requisição cross-origin do produto. E aqui vale o crédito: o WASM
do MediaPipe e o modelo `face_landmarker.task` são **auto-hospedados**
(`frontend/angular.json:29-33`, `frontend/src/app/core/visao/landmarks.service.ts:7-11`),
em vez de virem do CDN da jsDelivr como o padrão do MediaPipe sugere — o código
que toca a webcam não é baixado de terceiro em tempo de execução. Essa decisão
está certa e merece ser dita na defesa.

Sobra a fonte. O IP, o user-agent e o horário exato em que cada participante
abriu a tela de estudo vão para um terceiro fora do país. A imagem não sai do
navegador; o fato de a pessoa estar estudando naquele minuto, sai. Correção:
baixar os dois `.woff2` para `src/assets/` e servir do próprio domínio.

## M6 — `verificar_configuracao` não exige HTTPS nas origens de produção

`backend/app/config.py:146-198` recusa três combinações (ambiente desconhecido,
chave de exemplo fora de dev/teste, curinga no CORS) — desenho certo, e o
módulo diz por quê. Mas `AMBIENTE=producao` com
`ORIGENS_PERMITIDAS=http://alguma-coisa` **passa**.

Pela própria lógica do módulo isso deveria ser recusado: o SPEC declara que "a
webcam exige contexto seguro; sem HTTPS não há captura, logo não há produto"
(`.wize/specs/spec-poc-iee/SPEC.md`, Constraints). Uma origem `http://` em
produção é uma configuração que **não pode funcionar**, e recusar configuração
que não pode funcionar é exatamente o trabalho desta função. Três linhas.

---

# Dívida aceitável numa PoC de vida curta

Registrada para não ser redescoberta, e explicitamente **não** recomendada para
correção antes da banca.

| # | Item | Evidência | Por que é aceitável aqui |
|---|---|---|---|
| D1 | `python-jose[cryptography]==3.3.0`, sem manutenção, com dois avisos públicos (confusão de algoritmo; bomba de descompressão em JWE) | `backend/requirements.txt:12` | **Nenhum dos dois é alcançável**: `backend/app/security.py:113` fixa `algorithms=[settings.algorithm]` (HS256) e o projeto nunca chama `jwe.decrypt`. Trocar de biblioteca agora custa mais risco que resolve. |
| D2 | Imagem base `python:3.9-slim-bookworm`, fora do suporte upstream | `backend/Dockerfile:24` | Decisão declarada e justificada no próprio arquivo (linhas 18-23), amarrada ao pin do `sqlmodel`. Janela de exposição de horas. |
| D3 | O interceptor anexa `Authorization` a **qualquer** URL, sem checar se é a API | `frontend/src/app/core/interceptors/auth.interceptor.ts:37-57` | Hoje a aplicação só chama a própria API, então nada vaza. Vira achado real no dia em que alguém fizer um `http.get` para um terceiro. |
| D4 | `allow_credentials=True` sem que a aplicação use cookie algum | `backend/app/main.py:137` | O token vai em header. Não abre buraco; sugere um modelo de sessão que não existe, e é o que força a recusa do curinga em `config.py:193`. |
| D5 | Nenhum cabeçalho de segurança (HSTS, CSP, X-Content-Type-Options) | ausência, em `backend/app/main.py:120-155` | O risco que uma CSP mitigaria é o XSS que levaria o token do `localStorage` — e **não há sink de injeção**: nenhum `innerHTML`, `bypassSecurityTrust*` ou `eval` em `frontend/src/app`, Angular escapa por padrão, e o único texto autoral (`assunto`, 120 caracteres) é interpolado. O item conhecido do token em `localStorage` está hoje sem caminho de exploração dentro da aplicação. Se for adicionar um cabeçalho, HSTS é o de maior valor. |
| D6 | Migração caseira com `ALTER TABLE` no boot | `backend/app/database.py:104-130` | Documentada no README. Com **uma** instância não há corrida — e uma instância é requisito de correção por outro motivo (baseline em memória). |
| D7 | O canal WS não reage ao encerramento da sessão pelo HTTP | `backend/app/routers/telemetria.py:160` vs. `backend/app/routers/sessoes.py:135-142` | Integridade de dado, não segurança: um cliente feito à mão pode continuar gravando em `log_engajamento` e atualizando `ultima_presenca` de uma sessão já encerrada. O cliente real chama `parar()` (`telemetria.service.ts:156`). |

---

# O que foi verificado e está sólido

Não é cortesia: cada item abaixo é uma hipótese de ataque que foi testada
contra o código e não se sustentou. Isso é material de defesa.

- **Autorização por dono, sem oráculo de existência.** Sessão de outro aluno
  responde 404 e não 403, em todos os caminhos:
  `backend/app/routers/sessoes.py:212-216`, `:250-262` (o docstring explicita o
  raciocínio), `backend/app/sessoes.py:402-424`. Os ids são sequenciais, e a
  escolha do 404 é o que impede que isso vire enumeração.
- **A sessão do WebSocket é resolvida no servidor**, nunca aceita do cliente
  (`backend/app/routers/telemetria.py:160`, com o motivo escrito no docstring da
  linha 141) — o caminho óbvio para gravar telemetria na sessão de outra pessoa
  está fechado.
- **`pausa_maxima_s` vem do catálogo no servidor, não do corpo do request**
  (`backend/app/models.py:91-99`, `backend/app/schemas.py:497-505`): "sessão que
  nunca encerra" não é um campo de request.
- **Nenhuma SQL crua com entrada de usuário.** As únicas `text()` do projeto
  (`backend/app/database.py:124-262`) interpolam **nomes de tabela e coluna
  vindos do `SQLModel.metadata`**, não de request. Todo o resto é `select()`
  parametrizado.
- **Higiene de log.** `backend/app/observabilidade.py:29-42` declara o que nunca
  entra numa linha (conteúdo autoral, e-mail, senha da URL do banco) e
  `banco_sem_segredo` (`:142-161`) é aplicado na linha de boot (`main.py:51`). O
  handler global (`main.py:88-117`) devolve corpo genérico e registra só método
  e caminho — sem query string, deliberadamente.
- **Configuração falha fechada no import** (`backend/app/config.py:184-198`):
  chave de exemplo em produção derruba o processo no boot, não no primeiro
  aluno.
- **Nenhum segredo versionado, nem hoje nem no histórico.** `git ls-files` e
  `git log --all --diff-filter=A` não trazem `.env`, `.db`, `.pem` ou chave —
  só `backend/.env.example`, que é marcador declarado. O `.dockerignore` e o
  `Dockerfile` (que copia apenas `app/`) fecham a porta de a `SECRET_KEY` real
  viajar dentro da imagem.
- **Contêiner roda como usuário sem privilégio** (`backend/Dockerfile:65-66`),
  sem `--reload` (que devolveria stack trace ao cliente) e sem `--workers`.
- **O código que toca a webcam é auto-hospedado** — WASM e modelo saem do
  próprio domínio (`frontend/angular.json:29-33`), não de CDN de terceiro.
- **O contrato de privacidade do banco tem trava executável**: não há coluna de
  imagem, vídeo ou landmark em `LogEngajamento`
  (`backend/app/models.py:195-233`), e existe teste que congela a lista de
  colunas.

---

# Ordem sugerida

**Antes de abrir para os colegas** (as quatro primeiras são de código e somam
poucas horas):

1. B3 — `max_length` em `nome` (uma linha).
2. B1 — dimensionar o pool + `pool_pre_ping` (M3 vem junto, mesma linha).
3. B4 — timeout na primeira mensagem do WS + checagem de `Origin`.
4. B2 — tirar o I/O de banco do event loop (a maior das quatro).
5. B5 — decidir e **escrever** o que será dito aos participantes sobre retenção
   e exclusão, e combinar o procedimento manual de apagar.

**Antes da banca**, se sobrar tempo: M5 (fonte local), M1 (hash fictício no
login), M2 (`docs_url=None`), M6 (recusar origem `http` em produção).

**Fora do alcance deste relatório, e precisa de alguém olhando**: TLS de ponta
a ponta, RDS sem acesso público, grupo de segurança da task, e a confirmação de
que `AMBIENTE=producao` e a `SECRET_KEY` real estão de fato na task publicada.
Nada disso existe ainda em código (tickets 14 e 15), e nenhuma leitura estática
substitui olhar o ambiente depois que ele subir.
