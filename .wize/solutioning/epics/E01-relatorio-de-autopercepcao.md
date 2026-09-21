---
epic: E01-relatorio-de-autopercepcao
caps: [CAP-9, CAP-10, CAP-8]
tickets: [11, 12, 13]
status: done
---

# Épico E01 — Relatório de autopercepção

Fecha a lacuna entre o que o sistema mede e o que o estudante recebe. Hoje a série do IEE é
gravada a 1 Hz e **nada a lê**: o aluno estuda, encerra, e não vê nada. A interface já promete o
contrário — `home.component.html:120` diz *"O relatório da sessão é só seu."*

Cobre as tickets 11, 12 e 13 do `tickets.md`, que formam um bloco de dependência: 12 e 13 estão
bloqueadas pela 11.

## Por que este épico primeiro

CAP-9 é a única capacidade do `SPEC.md` totalmente ausente, e é o produto declarado. O critério
mínimo de sucesso do projeto — "PoC funcionando ponta a ponta: webcam → landmarks → IEE → banco →
relatório" — termina exatamente aqui.

## O que já está pronto e deve ser reusado

- `backend/app/telemetria.py::buscar_logs(db, id_sessao)` — a série em ordem cronológica. O lado
  de leitura **já existe**; não reescrever.
- `frontend/src/app/shared/grafico-iee.component.ts` — o gráfico, com spec próprio, escala 0–100
  e quebra de linha em intervalos de incerteza. Está órfão desde a ticket 9; esta é a página que
  faltava para consumi-lo.
- `LogEngajamento` já carrega `score` (nulo = incerteza), `fadiga` e `alerta`. O docstring do
  modelo diz textualmente que essas colunas entraram *para este relatório*.

## Slicing

O skill exige que cada story caiba em um PR. A ticket 11 não cabe — são endpoint novo, DTO, rota,
página, cálculo de indicadores, recomendações e caso de interrupção. Fatiamento adotado:

| Story | Entrega | Ticket |
|---|---|---|
| **E01-S01** | Ao encerrar, o estudante vê a curva e os indicadores da sessão | 11 |
| E01-S02 | O relatório nomeia os alertas de fadiga e recomenda o que fazer | 11 |
| E01-S03 | Sessão interrompida ainda rende relatório | 11 |
| E01-S04 | O estudante revisita sessões anteriores | 12 |
| E01-S05 | Logs granulares são sumarizados e indexados | 13 |

**Fechado em 21/09/2026.** As cinco stories saíram numa leva só, em vez de um PR por story: o
Matheus pediu as tickets 11, 12 e 13 inteiras. O detalhe do que foi entregue, e os três desvios do
contrato de teste, estão em `E01-S01.md`.

A decisão de escopo acima — corrigir a duração dentro da S01 em vez de abrir uma `E01-S00` —
sobreviveu: `app/presenca.py` nasceu junto com o relatório, que é quem expõe o número.

**Fechado em 21/09/2026.** As cinco stories saíram numa leva só, em vez de um PR por story: o
Matheus pediu as tickets 11, 12 e 13 inteiras. O detalhe do que foi entregue, e os três desvios do
contrato de teste, estão em `E01-S01.md`.

A decisão de escopo acima — corrigir a duração dentro da S01 em vez de abrir uma `E01-S00` —
sobreviveu: `app/presenca.py` nasceu junto com o relatório, que é quem expõe o número.

**Decisão de escopo em E01-S01:** a duração da sessão é um indicador do relatório, e hoje ela está
errada — o heartbeat do navegador bate incondicionalmente, a varredura de inatividade nunca dispara
e cadeira vazia vira tempo de estudo. Corrigir isso entrou como AC da S01 em vez de virar uma fase
de refatoração separada, porque é a S01 que expõe o número ao usuário. Se em revisão a S01 ficar
grande demais, o conserto sai como `E01-S00`.

## Fora do épico

- Publicação em nuvem (tickets 14 e 15) — outro épico.
- Validação das metas do capítulo 8 (ticket 16) — depende deste épico estar entregue.
- Modularização de `analista.py`, `landmarks.service.ts` e `home.component.ts` — decidido em
  19/09/2026 que a refatoração vem **depois** deste épico, quando as fronteiras corretas estiverem
  visíveis e a suíte de 98% servir de rede.
