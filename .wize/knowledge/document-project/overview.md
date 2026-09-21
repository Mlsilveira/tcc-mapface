---
status: baseline
owner: Pepper Potts + Peggy Carter
created: 2026-09-19
last_refreshed: 2026-09-19
sampled: "README, spec-poc-iee.md, tickets.md, ml/README.md, resultado_18_08.md, Plano_de_Sprints_TCC.pdf, revisao-arquitetura-2026-08-13.pdf, TCC_EM_ABNT.pdf, git log completo"
---

# Overview

**Projeto:** MapFace — Índice de Engajamento no Estudo (IEE)

## O que é

Prova de Conceito de uma aplicação web que devolve ao estudante um retrato do próprio
comportamento durante uma sessão de estudo solitária. O aluno inicia a sessão, autoriza a
webcam, e sinais visuais comportamentais — abertura dos olhos (EAR), orientação da cabeça
(Head Pose) e indícios de bocejo (MAR) — são extraídos **no navegador** via MediaPipe Face
Mesh. O backend calcula o IEE, métrica de 0 a 100 calibrada individualmente, e ao final
entrega um relatório de autopercepção.

Fórmula, conforme `spec-poc-iee.md:90`:

```
IEE(t) = P(t) × [(0.6 × EAR_norm) + (0.4 × HP_norm)] − F
```

O sistema não diagnostica, não avalia e não julga. Mede proxies comportamentais visuais e
devolve isso ao próprio estudante.

## Contexto

Trabalho de Conclusão de Curso em Ciência da Computação — Universidade Paulista (UNIP),
2026. Três autores: Chrystian Natanael Magalhães Silva Nascimento, Rian Gabriel dos Santos
Abreu e Matheus Luiz Ramos Silveira. Orientação: Prof.ª Me. Stephany Mendes Oliveira;
coorientação: Prof. Dr. Mário da Silva Quinello.

Duas trilhas correm em paralelo e convergem na ticket 8: **ML** (DAiSEE, Random Forest) e
**App/Infra** (aplicação e provisionamento).

## Quem usa

Um único ator: o **estudante**, sobre os próprios dados. Não existe papel de professor,
coordenação ou administrador — é uma decisão de produto registrada em `README.md:11` e em
*Out of Scope* no spec, não uma lacuna de implementação.

## Tamanho

| Parte | Arquivos | Linhas |
|---|---|---|
| `backend/app` | 16 | 1.390 |
| `backend/tests` | 10 | 1.852 |
| `frontend/src` | 42 | 7.128 (dos quais 1.000 em `styles.css`) |
| `ml` | 17 | 4.764 |

Contagem de `.py`, `.ts`, `.html` e `.css`, excluindo `.venv`, `node_modules`, `dist` e caches.

Testes: 8 suítes pytest no backend, 16 specs Jasmine no frontend, 7 suítes pytest no ml
(168 testes declarados em `ml/README.md:213`).

## História

22 commits, de 13/08/2026 a 27/08/2026, concentrados em ~2 semanas. Autoria git: 20 commits
como "Clauderson (via Claude)" e 2 como "Matheus Silveira" — a identidade git não reflete a
divisão de trabalho descrita no plano de sprints.

Branch atual: `feat/tickets-9-11`. Existem branches de trabalho anteriores (`feat/tickets-5-6`,
`design/interface-mapface`) e uma marcada como abandonada (`descartada/ticket-7-calibracao-persistida`).

## Estado por ticket

Concluídas: **1, 2** (trilha ML), **3, 4, 5, 6, 7, 8, 10** (trilha App).
Descartada: **9** (dashboard ao vivo — retirada do produto em 27/08/2026, absorvida pela 11).
Abertas: **11** (relatório de autopercepção), **12** (histórico), **13** (sumarização/retenção),
**14** (Terraform), **15** (deploy AWS), **16** (validação de performance).

Trabalho em andamento não commitado: `frontend/src/app/shared/grafico-iee.component.ts` e seu
spec, mais alterações em `telemetria.service.ts`, `home.component.ts`, `styles.css`, `README.md`,
`spec-poc-iee.md` e `tickets.md`.

## O que ele entrega hoje

Cadastro e login com JWT; ciclo de vida da sessão de estudo com encerramento por inatividade;
captura client-side com preview e FPS; telemetria por WebSocket a 1 Hz com reconexão; cálculo
do IEE com baseline individual calibrada nos primeiros 60 s; fator de fadiga por regras
(PERCLOS, microssono, bocejo); e abstenção de medida sob condições adversas de captura.

O que ainda **não** existe ponta a ponta: o relatório que o aluno lê no fim da sessão — que é
o produto declarado. A série é gravada no banco, mas nada a apresenta.

## Documentos de referência no repositório

- `spec-poc-iee.md` — problema, 35 histórias de usuário, decisões de implementação e teste, out of scope.
- `tickets.md` — 16 fatias verticais em ordem de dependência, com o racional de cada decisão.
- `ml/README.md` e `resultado_18_08.md` — a trilha de ML e por que a meta de 80% foi contestada.
- `Plano_de_Sprints_TCC.pdf` — 13 sprints semanais, 13/08 a 12/11/2026, e a Definition of Done.
- `revisao-arquitetura-2026-08-13.pdf` — revisão de arquitetura sobre as tickets 3 e 4, com 5 candidatos a refactor.
- `TCC_EM_ABNT (1).pdf` — o texto acadêmico, com as metas técnicas do capítulo 8.
