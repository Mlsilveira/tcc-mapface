---
gate: design
story_id: E02-S02
epic: E02-metodos-de-estudo
ac_ids: [AC-17-9, AC-17-10, AC-17-11]
status: PASS
created_at: 2026-09-21T18:45:00Z
test_split:
  unit: { count: 14, description: "app/criterios.py puro, a decomposição de resumir_serie, e as duas travas (tipo e frase)" }
  integration: { count: 4, description: "GET /sessoes/{id}/relatorio via TestClient — com método, sem método, blocos vazios, autorização" }
  component: { count: 6, description: "página do relatório e histórico em TestBed — blocos, cadência em contagem, traço" }
  e2e: { count: 0, description: "sem runner de E2E no projeto" }
fixtures:
  - "session / client / cabecalhos / cabecalhos_outro_aluno — já existem em conftest.py e test_relatorio_api.py"
  - "_serie_de_teste(session, id_sessao, pontos, inicio) — helper existente, reusar"
  - "_blocos_de_teste — novo, no mesmo molde: lista de (indice, tipo, offset_inicio_s, offset_fim_s)"
  - "SESSAO_POMODORO — 4 blocos de foco (24, 27, 31 e 12 min) e 3 pausas de 5 min"
  - "SESSAO_SEM_METODO — metodo NULL, sem blocos"
mocks:
  - "Nenhum mock de rede no backend: SQLite em memória com StaticPool, como no resto da suíte"
  - "Frontend: jasmine.createSpyObj para o RelatorioService, padrão de login.component.spec.ts"
  - "Chart.js dublado por CRIADOR_DE_GRAFICO — GraficoFalso já existe"
environment: "local. Backend pytest + SQLite em memória. Frontend Karma + ChromeHeadless, singleRun."
risk_links: []
edges:
  - "E1 bloco curto demais para média (< 60 pontos medidos)"
  - "E2 sessão com um bloco só — não há o que comparar"
  - "E3 bloco declarado e não executado (fim == inicio)"
  - "E4 sessão com metodo NULL e, separadamente, sessão com metodo mas sem bloco nenhum"
  - "E5 série já colapsada pela retenção de 24 h"
  - "E6 lacuna de captura de 30 a 59 s logo após uma piscada — fadiga fabricada"
  - "E7 bloco inteiramente em incerteza"
  - "E8 método sem duração prescrita (Flow) — não há cadência a comparar"
---

## Nota de contexto

Mesmo enquadramento da E02-S01: sem `risk-profile.md`, sem overlay web, sem runner de E2E.

O peso do split está no **unit** porque o valor desta story está num módulo puro. `criterios.py` é
o seam: recebe blocos e série, devolve critérios e frases, e não conhece HTTP, banco nem UI. É o
mesmo molde que tornou `test_analista.py` e `test_presenca.py` baratos de manter.

## Per-AC assertion shapes

- **AC-17-9** — *Estrutura executada e indicadores por bloco.*
  Haverá testes **unitários** sobre `criterios.avaliar` com blocos e série sintéticos, esperando
  números **calculados à mão a partir da definição** — nunca extraídos da implementação. Haverá um
  teste unitário afirmando que os pontos das pausas **não entram** na média dos blocos de foco: é a
  correção que a ticket 17 inteira existe para fazer, e ela precisa de um teste que a nomeie.
  Haverá um teste de **integração** que encerra uma sessão com blocos e espera o relatório com a
  lista deles em ordem de índice.

- **AC-17-10** — *Contagem, nunca razão.* **Duas travas, e a segunda é a que segura.**
  1. Teste **unitário** sobre a contagem: dado alvo de 25 min e blocos de 24, 27, 31 e 12, esperar
     `blocos_na_faixa == 2` — a faixa é `|duração − alvo| ≤ 0,2 × alvo`, ou seja 20 a 30 min, com os
     limites conferidos à mão. E um teste de borda para o bloco de exatamente 30 min.

     > **Correção de 21/09/2026.** Este contrato dizia `== 3`, e estava errado: `|31 − 25| = 6 > 5`,
     > então o bloco de 31 min fica **fora** da faixa. O número foi escrito antes da conta, que é
     > exatamente o vício que a regra da casa — *o esperado se calcula à mão a partir da definição* —
     > existe para impedir. Vale como lembrete de que o contrato de teste também precisa da conta
     > feita, e não só o teste.
  2. Teste **estrutural** sobre o DTO: nenhum campo é razão normalizada. Varre os campos do
     contrato de critério e falha se aparecer `float` derivado de divisão entre observado e
     declarado.

  > **Por que a trava precisa ser de tipo.** `"aderência: 62%"` **não afirma estado interno nenhum**
  > — é aritmética sobre carimbos de tempo — e passaria em silêncio pelo teste parametrizado de tom
  > que já existe em `test_recomendacoes.py`. A régua que ela atravessa é a outra, a que a ticket 12
  > enunciou: *"oferecer a linha do tempo é útil; desenhar uma seta para cima em cima dela seria
  > afirmar mais do que o dado sustenta."* Teste de string é conselho; teste de tipo é regra.

  Haverá também a extensão do teste parametrizado de tom com a família de julgamento
  (`"você não seguiu"`, `"você cumpriu"`, `"aderência de"`, `"nota"`, `"desempenho"`, `"falhou"`,
  `"%"`), aplicada às frases de `criterios.py`.

- **AC-17-11** — *Sessão sem método abre com traço.*
  Haverá um teste de **integração** que pede o relatório de uma sessão com `metodo IS NULL` e espera
  200 **sem** seção de método, cadência ou bloco. Haverá um teste de **componente** que espera o
  traço, e não "Sem método" — `NULL` e `"livre"` dizem coisas diferentes, e colapsá-los na tela
  desfaz na renderização a distinção que o modelo custou a preservar.

- **Decomposição de `resumir`** (não é AC, é restrição da story).
  `test_relatorio.py` deve continuar passando **sem nenhuma edição**. Se esta story precisar tocá-lo,
  a decomposição virou redesenho e isso é assunto de gate, não de implementação. Haverá um teste
  novo afirmando que `resumir_serie(serie)` e `resumir(sessao, serie)` concordam nos indicadores
  para a mesma série — é o que impede a decomposição de mudar valor em silêncio.

- **Privacidade** (comportamento protegido).
  O teste que trava as colunas de `LogEngajamento` continua passando sem edição, e nenhuma coluna
  nova entra lá.

## Edge cases (testes próprios)

- **E1 Bloco curto demais** → menos de 60 pontos medidos reporta `media = None`, e o relatório diz
  "curto demais para uma média". Num bloco de 12 min um ponto espúrio é 1 em 720; numa sessão de
  2 h ele sumia em 7.200. O projeto já tem a disciplina do `media = None` — ela nunca foi exercitada
  com n pequeno, e é aqui que ela passa a valer.
- **E2 Um bloco só** → não há comparação entre primeiro e último. O critério se abstém em vez de
  comparar o bloco consigo mesmo.
- **E3 Bloco declarado e não executado** (`fim == inicio`, caso real produzido pela varredura, já
  travado em `test_sessoes.py`) → duração zero, sem média, e **não conta** como bloco na faixa.
- **E4 Sem método × sem bloco** → são dois estados diferentes e precisam de testes diferentes.
  `metodo IS NULL` é "anterior ao recurso"; método declarado sem bloco nenhum é "o aluno não
  conduziu". O segundo não pode ser renderizado como o primeiro.
- **E5 Série colapsada** → depois de 24 h a série vira médias por minuto. O relatório por blocos
  precisa continuar abrindo, e os **números da sessão** continuam vindo do `resumo_sessao`
  congelado. Se o relatório mudar de valor no dia seguinte, a ticket 13 foi desfeita.
- **E6 Fadiga fabricada por lacuna** → `DetectorDeFadiga._intervalos` atribui a duração entre duas
  amostras ao estado da **primeira**. Uma parada de captura de 30 a 59 s logo depois de uma piscada
  computa o intervalo inteiro como pálpebra fechada (acima de 60 s a janela descarta). Diluído em
  2 h isso some; dentro de um bloco de 12 min vira o rótulo daquele bloco no relatório. O teste
  monta esse caso e trava o que o relatório diz sobre ele.
- **E7 Bloco inteiramente incerto** → `media = None` por incerteza, não por n pequeno, e a frase
  precisa distinguir os dois: "não deu para medir" e "curto demais" são diagnósticos diferentes.
- **E8 Flow** → sem `foco_s`, não há cadência a comparar. O critério de cadência não aparece; o de
  continuidade, sim.

## Run plan

- **Todo PR:** as duas suítes verdes e `npx ng build` limpo.
- **Piso de cobertura:** 99% backend, 92,91% statements frontend.
- `pytest-cov` continua instalado ad hoc e **fora do `requirements.txt`** — se a cobertura virar
  gate, precisa ser declarado. Esta story não o declara.

## Hand-off

Contrato da E02-S02 pronto: 14 unit, 4 integração, 6 componente, 0 E2E, 8 edges. O termômetro é a
trava estrutural do DTO — ela é a única que pega o risco real desta story, porque o boletim passa
por todas as travas de texto que já existem.
