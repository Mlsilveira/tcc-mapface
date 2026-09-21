---
epic: E02-metodos-de-estudo
caps: [CAP-9, CAP-2]
tickets: [17]
status: ready-for-review
---

# Épico E02 — Métodos de estudo

Hoje o sistema trata toda sessão como **um bloco contínuo**. Para quem usa Pomodoro, essa premissa
inverte o resultado: os cinco minutos em que o estudante está corretamente longe da tela entram na
média e a derrubam. O sistema penaliza exatamente o comportamento que o método prescreve. Nas
palavras do Matheus:

> "se ele utiliza esse método de estudo não adianta a gente avaliar ele somente pelo período
> inteiro de estudo. A gente tem que criar alguns critérios."

Este épico fecha a metade visível da ticket 17. A metade invisível — o ciclo de vida da sessão
dirigido por presença — **já está entregue** e é pré-requisito, não escopo.

## O que já está pronto e deve ser reusado

Nada aqui deve ser reescrito. O épico é sobre consumir o que existe:

- `backend/app/metodos.py` — catálogo fechado dos cinco métodos, `TOLERANCIA_DE_RETORNO`,
  `TETO_DE_AUSENCIA` e `resolver_pausa_maxima`. Servido por `GET /metodos` com nome legível.
- `backend/app/blocos.py` — vocabulário (`foco`/`pausa`, `metodo`/`aluno`), `validar_declaracao`,
  `proximo_indice`, `duracao` e `recortar` (recorte **semiaberto** da série por bloco).
- `POST /sessoes/{id}/blocos` (declara transição, idempotente por tipo) e `GET .../blocos`.
- `POST /sessoes` já aceita `metodo`, `assunto` e `meta_de_blocos`; `pausa_maxima_s` é resolvido no
  servidor e **não existe no DTO de entrada**.
- `sessao_estudo` carrega o contexto congelado; `bloco_estudo` guarda o plano executado.
- `relatorio.resumir(sessao, serie)` — o seam puro que a E01 construiu. A E02-S02 o **decompõe**
  sem mudar sua assinatura nem seu comportamento.

## Slicing

| Story | Entrega |
|---|---|
| **E02-S01** | O estudante declara o método e o assunto, e o aplicativo conduz o ciclo |
| **E02-S02** | O relatório lê a sessão segundo o método declarado |

Duas e não três: a tela inicial e o cronômetro são a mesma jornada (declarar sem ser conduzido não
entrega nada, e conduzir sem ter declarado não tem o que conduzir), e os critérios de avaliação não
podem sair sem a tela que os mostra — uma story que "entrega um backend" é anti-padrão declarado
deste skill, e aqui seria pior que isso: `criterios.py` existe para que **todas as frases** que o
aluno lê sobre si nasçam no backend, onde a trava de tom já mora.

## A decisão de escopo que este épico carrega

O cronômetro na tela da sessão **reabre deliberadamente** a decisão de 27/08/2026, registrada em
`.wize/specs/spec-poc-iee/.decision-log.md` sob 21/09/2026. A constraint foi **reformulada**, não
alargada: um cronômetro não é "diagnóstico de equipamento", e esticar a exceção para acomodá-lo
seria desonesto. A régua passou a ser *nada na tela é derivado do comportamento medido do
estudante* — mais precisa que a anterior, e o score continua fora.

Isso não é prosa de contexto: é a AC-17-8, e ela tem teste próprio em cada story.

## Dependências

- Tickets 4, 6, 7, 8, 10, 11 e a primeira metade da 17 — todas fechadas.
- Nenhuma dependência externa nova. Nenhum pacote novo.

## Fora do épico

- Deploy (tickets 14, 15 e 16) — decisão de escopo do Matheus, fora por ora.
- Detectar "falsa pausa" como evento e comparar blocos entre sessões diferentes — exigiriam
  respectivamente dado que só existe se o app conduzir com meta obrigatória, e baseline estável
  entre sessões, que não existe (a calibração recomeça a cada sessão).
- Qualquer agregado entre sessões. Não é "depois": é proibido, pelo mesmo motivo da ticket 12.

## Sucesso

Um ciclo Pomodoro completo é executável ponta a ponta e o relatório o descreve por blocos, sem
emitir nota, sem percentual e sem afirmar estado interno. As duas suítes verdes, cobertura não
abaixo de 99% (backend) e 92,91% statements (frontend).
