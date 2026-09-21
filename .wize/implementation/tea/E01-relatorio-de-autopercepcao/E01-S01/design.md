---
gate: design
story_id: E01-S01
epic: E01-relatorio-de-autopercepcao
ac_ids: [AC-11-1, AC-11-2, AC-11-5]
status: PASS
created_at: 2026-09-19T23:55:00Z
test_split:
  unit: { count: 7, description: "app/relatorio.py puro — indicadores, séries degeneradas, duração por presença real" }
  integration: { count: 4, description: "GET /sessoes/{id}/relatorio via TestClient — caminho feliz, autorização, UTC explícito" }
  component: { count: 3, description: "página do relatório em TestBed — repasse da série, estados de UI, navegação ao encerrar" }
  e2e: { count: 0, description: "não há runner de E2E no projeto; introduzir um está fora do escopo desta story" }
fixtures:
  - "session — SQLite em memória com StaticPool (conftest.py)"
  - "client — TestClient com get_session sobrescrito (conftest.py)"
  - "cabecalhos — headers autenticados do aluno dono (test_sessoes.py)"
  - "cabecalhos_outro_aluno — segundo aluno, para o teste de autorização"
  - "registro_de_analistas_limpo — autouse, já existente"
  - "_serie_de_teste(session, pontos) — novo helper, no molde de _sessao_de_teste de test_telemetria.py"
mocks:
  - "Nenhum mock de rede: o projeto não usa MSW e o backend é testado de verdade contra SQLite em memória"
  - "Frontend: jasmine.createSpyObj para o RelatorioService, no padrão de login.component.spec.ts"
  - "Chart.js dublado por CRIADOR_DE_GRAFICO — o dublê GraficoFalso já existe em grafico-iee.component.spec.ts"
environment: "local. Backend: pytest + SQLite em memória. Frontend: Karma + ChromeHeadless do puppeteer, singleRun."
risk_links: []
edges:
  - "E1 série vazia — sessão encerrada antes do primeiro ponto"
  - "E2 série inteiramente incerta — todos os pontos com score null"
  - "E3 buraco de incerteza no meio — não interpolar, não zerar"
  - "E4 relatório de sessão ainda em andamento"
  - "E5 pontos da janela de calibração, antes de haver baseline"
  - "E6 datetime sem fuso explícito desloca a curva no navegador"
  - "E7 sessão inexistente vs. sessão de outro aluno — ambas 404"
---

## Nota de contexto

`wize-tea-risk` ainda não rodou neste projeto: não existe `risk-profile.md`, então `risk_links` está
vazio. Os riscos citados abaixo vêm de `.wize/knowledge/document-project/risk-spots.md`, que os
mapeia com nível de confiança.

O perfil ativo é só `core` — não há overlay web, logo não há playbook de Playwright e não há runner
de E2E no repositório. O split abaixo troca a fatia de E2E por testes de componente em TestBed, que
é o que a stack realmente suporta hoje.

## Per-AC assertion shapes

- **AC-11-1** — *Relatório gerado automaticamente ao encerrar a sessão.*
  Haverá um teste de **integração** que encerra a sessão via `POST /sessoes/{id}/encerrar` e em
  seguida chama `GET /sessoes/{id}/relatorio`, esperando 200 e a série exatamente como foi gravada
  por `telemetria.registrar_log`. Haverá um teste de **componente** que dispara `encerrarSessao()` e
  espera `Router.navigate` chamado com `['/relatorio', id]` — no molde do
  `spyOn(TestBed.inject(Router), 'navigate').and.resolveTo(true)` de `login.component.spec.ts`.

- **AC-11-2** — *Inclui gráfico do IEE, indicadores-chave e alertas de fadiga registrados.*
  Haverá testes **unitários** sobre `app/relatorio.py` que, dada uma série sintética, esperam os
  indicadores com valores **calculados à mão a partir da definição**, nunca extraídos da
  implementação — é a regra que `test_analista.py` estabeleceu no cabeçalho e que torna o teste
  capaz de pegar regressão. Haverá um teste de **componente** que passa uma série com nulos à página
  e espera que o `GraficoIeeComponent` receba a série **com os nulos preservados**.

  > Não re-testar o desenho. `grafico-iee.component.spec.ts` já cobre a quebra de linha nos pontos
  > não medidos e a descrição textual sem inventar número. O que falta afirmar é o **repasse**.

- **AC-11-5** — *A duração reflete presença real, não tempo de aba aberta.*
  Haverá um teste **unitário** que monta uma sessão com atividade real nos primeiros 5 minutos e
  nada além disso, com a aba "aberta" por mais 15, e espera duração de 5 minutos.
  **Este teste deve falhar contra a implementação de hoje.** Se ele passar antes do conserto, ele
  não está medindo o bug — está medindo outra coisa.

- **Autorização** (não é AC, é restrição da story).
  Haverá testes de **integração** que pedem o relatório de uma sessão de outro aluno usando
  `cabecalhos_outro_aluno` e esperam **404, não 403** — 403 confirmaria que a sessão existe. Sem
  token, 401.

- **Privacidade** (comportamento protegido).
  O teste existente que trava a lista de colunas de `LogEngajamento` deve continuar passando **sem
  nenhuma edição**. Se esta story precisar tocá-lo, a fronteira de privacidade se moveu e isso é
  assunto de gate, não de implementação.

## Split detalhado

### Unit — `app/relatorio.py` (7)

O seam de maior valor: função pura de série + sessão → indicadores, sem banco, HTTP nem UI. Mesmo
molde que tornou `test_analista.py` barato de escrever e de manter.

| # | O que afirma |
|---|---|
| U1 | Indicadores sobre série normal — média, pico, vale, tempo medido, contra números calculados à mão |
| U2 | Série vazia devolve relatório vazio; é um **estado**, não um erro |
| U3 | Série 100% incerta devolve "não foi possível medir" — nunca zero |
| U4 | Buraco de incerteza no meio: os nulos saem da média em vez de entrarem como zero |
| U5 | Score zerado é indicador próprio, separado da incerteza — **corrigido em 20/09**, ver nota abaixo |
| U6 | Alertas registrados são agregados por motivo, preservando o rótulo gravado em `alerta` |
| U7 | Duração por presença real (AC-11-5) — deve falhar hoje |

A distinção que U3, U4 e U5 defendem é a que a ticket 10 comprou: **"não deu para medir" não é "o
aluno não estava lá"**. Um relatório que colapsa os dois em zero desfaz a ticket 10 sem tocar em
nenhuma linha dela — e nenhum teste existente perceberia.

> **Correção de 20/09/2026 — U5.** Este contrato declarava, na versão original, que o U5 separaria
> *tempo em incerteza* de *tempo com rosto ausente*. **Isso não é implementável com os dados que
> existem.** `calcular_iee` termina em `max(0.0, bruto - fadiga)`, então `score = 0.0` tem duas
> causas: `P(t) = 0` (rosto ausente) e aluno presente cuja fadiga zerou o score. A tabela
> `log_engajamento` não guarda `rosto_detectado`, logo nenhuma implementação distingue as duas.
>
> O U5 passa a afirmar o que é verificável: **score zerado é indicador próprio, separado da
> incerteza** — `pontos_zerados`, não `pontos_ausentes`. A limitação está registrada em
> `risk-spots.md` sob a data de hoje. Separar de verdade exige coluna nova e migração, e isso é
> escopo de outra story.
>
> Descoberto durante a implementação, antes do commit do ciclo. Decisão tomada com o Matheus.

### Integration — `GET /sessoes/{id}/relatorio` (4)

Via `client` + `cabecalhos`, no padrão de classes de `test_sessoes.py` (`TestRelatorio`).

| # | O que afirma |
|---|---|
| I1 | Encerrar e então buscar devolve 200 com a série gravada, em ordem cronológica |
| I2 | Sessão de outro aluno → 404 |
| I3 | Sem token → 401 |
| I4 | Os datetimes chegam com fuso explícito (o `field_validator` de `schemas.py`) |

I4 não é preciosismo: `SessaoPublica` já carrega esse validador com um comentário explicando que,
sem fuso explícito, o navegador lê o instante como hora local e o horário aparece deslocado. Um DTO
novo sem o mesmo cuidado desloca a curva inteira do relatório.

### Component — página do relatório (3)

| # | O que afirma |
|---|---|
| C1 | A série chega ao `GraficoIeeComponent` com os nulos preservados |
| C2 | Estados de carregando, vazio e erro são renderizados |
| C3 | `encerrarSessao()` navega para o relatório da sessão encerrada |

Seletores por `data-teste` (`relatorio-grafico`, `relatorio-indicadores`, `relatorio-duracao`,
`relatorio-vazio`) ou por classe semântica, seguindo o que o projeto já faz. **Não usar
`data-testid`** — a convenção aqui é `data-teste`, ver `home.component.html:26`.

## Edge cases (testes próprios)

- **E1** Série vazia → `buscar_logs` devolve `[]`. Relatório existe e diz que não há dados.
- **E2** Série 100% incerta → todos com `score = None`. Indicadores não podem exibir 0.
- **E3** Buraco no meio → média sobre os medidos; a curva quebra (já garantido pelo componente).
- **E4** Sessão ainda em andamento → decidir e travar: 404, ou relatório parcial? A story manda o
  parcial para E01-S03, então aqui o comportamento esperado é **recusar**, e o teste trava isso.
- **E5** Pontos da janela de calibração — os primeiros 60 s produzem leitura antes de existir
  baseline. O teste trava a decisão tomada, seja incluir ou omitir.
- **E6** Datetime sem `tzinfo` → coberto por I4.
- **E7** Sessão inexistente e sessão de outro aluno devolvem **a mesma resposta**. Se divergirem, o
  404 vira oráculo de existência.

## Run plan

- **Todo PR:** `cd backend && .venv/bin/python -m pytest` e `cd frontend && npm test`, ambos verdes.
- **Piso de cobertura:** não cair abaixo do medido em 19/09/2026 — backend 98%, frontend 92,91%
  statements. `pytest-cov` foi instalado ad hoc para medir e **não está no `requirements.txt`**; se
  a cobertura virar gate, precisa ser declarado.
- Não há lint no projeto. Esta story não introduz um.

## Alerta sobre a própria rede de segurança

`login.component.spec.ts:100` e `registro.component.spec.ts:125` clicam num `button[type="submit"]`
dentro de `<form (ngSubmit)>`. O submit nativo dispara, o Karma acusa
`Some of your tests did a full page reload!` — **e ainda assim sai com código 0**.

Enquanto isso não for corrigido, "suíte verde" é uma afirmação mais fraca do que parece: o que roda
depois do reload não é confiável. Recomendo consertar como `wize-quick-dev` antes de abrir o PR
desta story, já que é justamente esta suíte que vai atestar as ACs acima.

## Hand-off

Contrato de teste da E01-S01 pronto. 7 unit, 4 integração, 3 componente, 7 edges, 0 E2E (sem runner
no projeto). Shuri pode começar — e o teste U7 é o termômetro: se ele passar antes de a AC-11-5 ser
implementada, o contrato está medindo a coisa errada. Confiro tudo no `tea-trace` quando o PR abrir.
