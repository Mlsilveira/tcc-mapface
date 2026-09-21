---
status: baseline
owner: Pepper Potts + Peggy Carter
created: 2026-09-19
last_refreshed: 2026-09-19
---

# Project Documentation Index

**Projeto:** MapFace — Índice de Engajamento no Estudo (IEE)
**Tipo:** multi-part (backend · frontend · ml)
**Fase atual:** implementação, tickets 1–8 e 10 concluídas; 11–16 abertas

## Brownfield Baseline

Escrita em 19/09/2026 a partir da leitura dos documentos do projeto e da inspeção das três
partes do código. É o retrato do **estado real**, não do estado desejado.

- [Overview](./overview.md) — o que é, quem usa, tamanho, história, o que entrega hoje
- [Architecture Snapshot](./architecture-snapshot.md) — entry points, componentes, fluxo ponta a ponta, seams
- [Conventions](./conventions.md) — o que o código pratica (código em português, DI para teste, comentários de "porquê")
- [Dependencies](./dependencies.md) — os três ambientes e o que falta em cada um
- [Risk Spots](./risk-spots.md) — o que bloqueia deploy, o que corrompe o dado, segurança, reprodutibilidade
- [Open Questions](./open-questions.md) — o que o código não responde, com dono

## Documentação existente no repositório

- [README.md](../../../README.md) — visão geral, setup e organização do código
- [spec-poc-iee.md](../../../spec-poc-iee.md) — problema, 35 histórias, decisões, out of scope
- [tickets.md](../../../tickets.md) — 16 fatias verticais e o racional de cada decisão
- [ml/README.md](../../../ml/README.md) — a trilha de ML e a contestação da meta de 80%
- [resultado_18_08.md](../../../resultado_18_08.md) — relatório da execução contra o DAiSEE real
- `Plano_de_Sprints_TCC.pdf` — 13 sprints, 13/08 a 12/11/2026, e a Definition of Done
- `revisao-arquitetura-2026-08-13.pdf` — 5 candidatos a refactor sobre as tickets 3 e 4
- `TCC_EM_ABNT (1).pdf` — texto acadêmico, com as metas técnicas do capítulo 8

## Ainda não gerado

Documentos que o kit prevê e que esta baseline não produziu. Nenhum é pré-requisito para
retomar o trabalho:

- Source tree analysis · Component inventory · API contracts formais (OpenAPI já é servido em `/docs`)
- Deployment guide — **só faz sentido depois que as tickets 14 e 15 existirem**
- Contribution guide

---

_Baseline escrita seguindo `wize-document-project`. Mantida viva pelo passo de Knowledge Update
de cada story e consolidada por `wize-refresh-knowledge` ao fim do sprint._
