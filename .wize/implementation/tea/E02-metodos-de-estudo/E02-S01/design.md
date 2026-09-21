---
gate: design
story_id: E02-S01
epic: E02-metodos-de-estudo
ac_ids: [AC-17-6, AC-17-7, AC-17-8]
status: PASS
created_at: 2026-09-21T18:40:00Z
test_split:
  unit: { count: 5, description: "montagem do corpo do POST, conta do tempo restante, estado do bloco corrente a partir da lista do servidor" }
  component: { count: 8, description: "tela inicial e tela da sessão em TestBed — catálogo, campos, cronômetro, transições, e a trava da AC-17-8" }
  integration: { count: 0, description: "o contrato do backend já está coberto por test_sessoes.py; repetir aqui testaria o TestClient, não a story" }
  e2e: { count: 0, description: "não há runner de E2E no projeto; introduzir um segue fora de escopo, como na E01-S01" }
fixtures:
  - "CATALOGO_DE_TESTE — resposta de GET /metodos com pomodoro (foco 1500 s), flow (foco null) e livre"
  - "SESSAO_EM_ANDAMENTO / SESSAO_ENCERRADA — já existem em home.component.spec.ts"
  - "SESSAO_SEM_METODO — sessão legada com metodo/pausa_maxima_s/meta_de_blocos nulos"
  - "BLOCOS_EM_FOCO — resposta de GET /sessoes/{id}/blocos com um bloco de foco aberto"
mocks:
  - "HttpTestingController — o projeto não usa MSW; a borda HTTP é dublada pelo backend de teste do Angular"
  - "LandmarksServiceFalso e TelemetriaServiceFalso — já existem no spec da home"
  - "navigator.mediaDevices.getUserMedia — spy já montado no beforeEach existente"
environment: "local. Karma + ChromeHeadless do puppeteer, singleRun (`npm test` já roda com --watch=false)."
risk_links: []
edges:
  - "E1 catálogo indisponível — GET /metodos falha"
  - "E2 método sem duração de foco prescrita (Flow, foco_s null)"
  - "E3 F5 no meio de um bloco — o cronômetro precisa vir do servidor, não de estado local"
  - "E4 sessão legada (metodo IS NULL) retomada na tela"
  - "E5 POST /sessoes/{id}/blocos falha na rede"
  - "E6 assunto no teto de 120 caracteres, e acima dele"
  - "E7 o bloco estoura o tempo prescrito e o aluno não pausa"
  - "E8 meta de blocos não declarada — nada de 'bloco 2 de 4'"
---

## Nota de contexto

`risk-profile.md` continua não existindo neste projeto, então `risk_links` está vazio. Os riscos
citados vêm de `.wize/knowledge/document-project/risk-spots.md`.

O perfil ativo é só `core`: não há overlay web, logo não há playbook de Playwright e não há runner
de E2E. O split troca a fatia de E2E por teste de componente em TestBed — a mesma solução que a
E01-S01 adotou, pelo mesmo motivo.

**Esta story é a metade visível de um backend que já está pronto e testado.** Repetir aqui os
testes de `POST /sessoes` e `POST /sessoes/{id}/blocos` mediria o `TestClient`, não a story. O que
falta afirmar é o **repasse** e a **condução** — mesma distinção que a E01-S01 fez com o gráfico.

## Per-AC assertion shapes

- **AC-17-6** — *Declarar método, assunto e meta.*
  Haverá um teste **unitário** sobre o `SessaoService` que, dado `{metodo, assunto, meta_de_blocos}`,
  espera o corpo exato no `POST /sessoes` — e espera `{}` quando nada foi declarado, porque o
  caminho de corpo vazio é comportamento protegido. Haverá um teste de **componente** que renderiza
  as opções a partir de `CATALOGO_DE_TESTE` e espera os **nomes legíveis** na tela, nunca os
  códigos: se `52-17` aparecer para o aluno, o `metodo_nome` que o backend devolve está sendo
  ignorado.

- **AC-17-7** — *O aplicativo conduz o ciclo.*
  Haverá um teste **unitário** da conta do tempo restante, com valores calculados à mão a partir de
  `foco_s` e do `inicio` do bloco — nunca lidos da implementação. Haverá testes de **componente**,
  em `fakeAsync`, que: avançam o relógio e esperam o cronômetro descer; esperam o aviso de pausa
  aparecer **na virada**, e não antes; e esperam `POST /sessoes/{id}/blocos` com `{tipo: "pausa"}`
  na transição, e `{tipo: "foco"}` na volta.

- **AC-17-8** — *Nada na tela vem da medição.* **Esta é a trava, e ela precisa poder falhar.**
  Haverá um teste de **componente** que, com a sessão em andamento e a telemetria alimentada com um
  score conhecido, varre o texto renderizado e falha se o valor do score aparecer. O teste tem que
  ser escrito de forma que **acrescentar** um indicador na tela o quebre — se ele só verificar a
  ausência de um `data-teste` específico, não protege nada.

  > Não re-testar a decisão. O `home.component.ts` já documenta que o score não aparece. O que este
  > teste trava é a **régua nova**, reformulada em 21/09/2026: o cronômetro passa porque não deriva
  > da medição; qualquer coisa que derive, não passa.

## Edge cases (testes próprios)

- **E1 Catálogo indisponível** → a tela precisa continuar permitindo iniciar sessão **sem método**.
  Bloquear o início porque um `GET` auxiliar falhou trocaria uma feature opcional por uma regressão
  no caminho principal.
- **E2 Flow (`foco_s: null`)** → não há tempo prescrito, logo **não há cronômetro de contagem
  regressiva e não há aviso de pausa**. Mostrar `00:00` ou contar para cima sem alvo seria inventar
  prescrição que o método não faz. O teste trava a ausência.
- **E3 F5 no meio do bloco** → depois do reload, o estado do bloco vem de
  `GET /sessoes/{id}/blocos`. Se vier de estado local, o cronômetro reinicia e o aluno aprende a
  não recarregar — a pior correção possível.
- **E4 Sessão legada (`metodo IS NULL`)** → retomada não mostra cronômetro nem declara bloco. Sem
  isso a sessão aberta antes do recurso ganha um bloco inventado no meio.
- **E5 Transição falha na rede** → o cliente retenta. O servidor absorve repetição (200, idempotente
  por tipo), então retentar é seguro e **perder a borda do bloco não é**. O teste afirma a
  retentativa, não o silêncio.
- **E6 Assunto no teto** → 120 caracteres passa, 121 é barrado antes do POST. O servidor já valida;
  o cliente não pode ser a única barreira, mas também não pode deixar o aluno digitar 200 caracteres
  para tomar 422 no final.
- **E7 O bloco estoura** → passado o tempo prescrito sem o aluno pausar, o aviso persiste e o
  cronômetro não vira número negativo. Nada de juízo sobre o estouro: o aviso é operacional.
- **E8 Sem meta declarada** → nenhum "bloco 2 de 4" na tela. Sem denominador declarado, não há
  denominador — inventá-lo é o primeiro passo para o boletim que a E02-S02 existe para evitar.

## Run plan

- **Todo PR:** `cd backend && .venv/bin/python -m pytest` e `cd frontend && npm test`, ambos verdes,
  mais `npx ng build`.
- **Piso de cobertura:** não cair abaixo de 99% (backend) e 92,91% statements (frontend).
- Não há lint no projeto; esta story não introduz um. Prettier com `--print-width 100 --single-quote`.

## Alerta sobre a própria rede de segurança

`npm test` roda com `--watch=false` desde 21/09/2026. O `Some of your tests did a full page reload!`
que aparecia antes **não vinha dos specs de login e registro**, como um contrato anterior afirmou:
vinha do builder do `ng test`, que reconstrói depois do `singleRun` e recarrega o contexto do Karma.
Não reintroduzir watch, e não "consertar" os specs de login.

## Hand-off

Contrato da E02-S01 pronto: 5 unit, 8 componente, 0 integração, 0 E2E, 8 edges. O termômetro é a
trava da AC-17-8 — se ela não quebrar ao acrescentar um indicador na tela, ela não está medindo
nada.
