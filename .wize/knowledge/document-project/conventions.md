---
status: baseline
owner: Peggy Carter
created: 2026-09-19
last_refreshed: 2026-09-19
sampled: "12 arquivos entre backend/app, backend/tests, frontend/src/app, ml/ e a árvore de commits"
---

# Conventions (observed, not prescribed)

A convenção registrada é a que o código pratica, não a que seria preferível.

## Idioma

**Todo o código é em português.** Funções, classes, variáveis, exceções (`SessaoNaoEncontrada`,
`SessaoJaEncerrada`, `SessaoAtivaJaExiste`), nomes de teste, mensagens de erro HTTP, comentários
e documentação. Termos técnicos consagrados ficam em inglês (`score`, `baseline`, `seam`,
`PERCLOS`, `EAR`). Isso é consistente nas três partes — não há mistura.

## Naming

- Python: `snake_case` para funções e variáveis, `PascalCase` para classes, `UPPER_SNAKE_CASE`
  para constantes (`LIMIAR_MAR_BOCEJO`, `LIMITE_SENHA_BYTES`).
- TypeScript: `camelCase` para membros, `PascalCase` para classes e componentes,
  `UPPER_SNAKE_CASE` para constantes de módulo (`INTERVALO_DE_ENVIO_MS`, `URL_DA_TELEMETRIA`).
- Arquivos: `kebab-case` no Angular com sufixo de papel (`auth.service.ts`, `auth.guard.ts`,
  `grafico-iee.component.ts`); nome simples em Python (`analista.py`, `agregacao.py`).

## Estrutura de pastas

**Layer-first com um núcleo de domínio isolado**, dos dois lados.

No backend, `app/routers/*.py` é adaptador HTTP fino; a regra mora em `app/<assunto>.py` e não
importa FastAPI nem SQLAlchemy. No frontend, `core/` guarda serviços e aritmética, `pages/` as
telas, `shared/` o que é reusado. Dentro de `core/`, o agrupamento é por assunto
(`visao/`, `telemetria/`, `services/`, `guards/`, `interceptors/`).

Não existe camada de "service" genérica nem repositório no backend: os módulos de domínio
recebem a `Session` diretamente.

## Testes

- Co-localizados no frontend (`*.spec.ts` ao lado do arquivo), em diretório separado no backend
  e no ml (`tests/`).
- Nomes descritivos e longos, em português:
  `test_score_nao_passa_de_100_com_olhos_muito_abertos`.
- Agrupamento em classes por funcionalidade no backend (`TestRegistro`, `TestLogin`,
  `TestRotaProtegida`); fixtures em `conftest.py`, SQLite em memória com `StaticPool`.
- **Os testes batem nos seams acordados, não na implementação.** Há um commit explícito sobre
  isso: *"test(ml): testar a tolerância a NaN pela interface, não pela estrutura"*.
- Dados sintéticos em vez de fixtures reais: vídeos gerados com `cv2.VideoWriter`, landmarks
  construídos à mão, árvores DAiSEE montadas em `tmp_path`. A suíte do ml roda em segundos sem
  o dataset de 2,7 GB.

## Injeção de dependência para testabilidade

Padrão recorrente e deliberado: o recurso externo entra por parâmetro ou token, nunca por import
rígido.

- `ml/extracao.py` recebe o detector de landmarks injetado.
- `frontend/.../grafico-iee.component.ts` cria o gráfico via `CRIADOR_DE_GRAFICO` (InjectionToken),
  para dublar o Chart.js sem canvas real.
- `landmarks.service.ts` e `telemetria.service.ts` seguem a mesma forma.

## Comentários

Densos, e quase sempre explicando **por quê**, não o quê. São o traço mais forte deste
repositório. Exemplos: por que a baseline usa mediana e não média; por que a autenticação do
WebSocket vai na primeira mensagem; por que ausência de rosto não conta como olho fechado; por
que o áudio é desligado no `getUserMedia`.

A mesma prática aparece nos artefatos: `tickets.md` registra, em cada ticket fechada, as decisões
que valem a defesa e o que foi descartado.

## Angular

Standalone components em 100% do projeto, rotas por `loadComponent` (lazy), **signals**
(`signal`, `effect`, `input`, `viewChild`) em vez de `@Input`/RxJS nos serviços mais novos,
`ChangeDetectionStrategy.OnPush` onde há render pesado, e trabalho fora da `NgZone` no loop de
captura. `tsconfig.json` em modo estrito, com `strictTemplates`.

Estilo global em `styles.css` com custom properties em `:root` — não há CSS por componente.
Ícones são SVG de traço num componente fechado, não emoji (justificativa no próprio arquivo).

## Erros

No backend, exceção de domínio traduzida para HTTP num único lugar: o context manager
`_traduzindo_erros()` (`app/routers/sessoes.py:16-28`). No frontend, a regra de "o servidor já
resolveu isso" (401/404/409) vive no `SessaoService`.

Validação por Pydantic/SQLModel em `app/schemas.py`, com validadores customizados quando o limite
é do domínio (72 bytes do bcrypt).

## Git

Commits em português no formato `tipo(escopo): descrição`, com os tipos `feat`, `fix`, `test`,
`docs` e `chore`. O escopo é o assunto do produto (`auth`, `sessao`, `captura`, `telemetria`,
`iee`, `ml`, `interface`). Branches nomeadas `feat/tickets-N-M`, `design/…`, e uma
`descartada/…` para trabalho abandonado — o repositório preserva o que foi descartado em vez de
apagar.

## Desvios observados

- `frontend/src/app/core/telemetria/telemetria.service.ts:7` declara em comentário que a URL do
  WebSocket "deriva da API para não haver duas configurações", mas é uma segunda constante
  hardcoded independente de `core/api.ts:2`.
- `ml/esquema.py` usa `LIMIAR_BOCA_ABERTA = 0,60` enquanto o backend usa
  `LIMIAR_MAR_BOCEJO = 0,30` para a mesma grandeza, apesar de `ml/metricas.py` se declarar
  "referência de implementação para o frontend".
- O backend não tem `pytest.ini` nem `pyproject.toml`; o `ml/` tem. Configuração de teste não é
  uniforme entre as partes.
- Não há linter nem formatter configurado em nenhuma das três partes.
