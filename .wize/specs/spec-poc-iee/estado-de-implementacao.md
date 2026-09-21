# Estado de implementação — 19/09/2026

Companion de `SPEC.md`. Existe porque a fonte (`spec-poc-iee.md:5`) declara *"greenfield — nenhum
código existe ainda"*, escrito em 13/08/2026. Oito tickets foram fechadas desde então. Esta é a
reconciliação; a fonte não foi editada.

## Capacidade → ticket → estado

| Cap | Tickets | Estado | Observação |
|---|---|---|---|
| CAP-1 Conta e acesso | 3 | ✅ | |
| CAP-2 Controle da sessão | 4 | ⚠️ | Funciona, mas o encerramento por inatividade **nunca dispara** — ver Defeitos |
| CAP-3 Captura client-side | 5 | ✅ | FPS medido na tela; metas do cap. 8 ainda não verificadas |
| CAP-4 Baseline individual | 7 | ✅ | Estado em memória de processo — ver Defeitos |
| CAP-5 Índice contínuo | 6, 7, 8 | ✅ | `F` por regras, não pelo modelo |
| CAP-6 Abstenção sob incerteza | 10 | ✅ | |
| CAP-7 Telemetria resiliente | 6 | ✅ | Reconexão com backoff; calibração sobrevive |
| CAP-8 Persistência não identificável | 6, 13 | ⚠️ parcial | Schema sem campo de imagem ✅ e travado por teste. Sumarização, retenção e índice temporal ✗ (ticket 13). Cifra em repouso depende de infra |
| CAP-9 Relatório | 11 | ✗ | **O produto declarado.** A série é gravada e nada a lê |
| CAP-10 Histórico | 12 | ✗ | Bloqueada por 11 |
| CAP-11 Ambiente reproduzível | 14, 15 | ✗ | Nenhum artefato de infra existe no repositório |

Tickets fora do mapa de capacidades:

- **1 e 2** (trilha ML) ✅ — concluíram em achado, não em modelo usado. Ver `resultado_18_08.md`.
- **9** — descartada em 27/08/2026, absorvida pela 11. Virou non-goal no kernel.
- **16** — validação das metas abaixo. Não iniciada.

## Metas técnicas a verificar (ticket 16)

Do capítulo 8 do TCC. Nenhuma foi medida ainda. As quatro primeiras são mensuráveis localmente;
só uptime exige ambiente publicado.

| Meta | Alvo | Onde se mede |
|---|---|---|
| FPS da webcam | 15–30 | Cliente |
| CPU client-side | ≤ 25% | Cliente |
| Latência do canal de telemetria | < 200 ms | Cliente ↔ servidor |
| Tempo de resposta do backend | < 100 ms | Servidor |
| Ciclo de feedback completo | < 1 s | Ponta a ponta |
| Taxa de erro sob condições adversas | ≤ 5% | Cenários de baixa luz, óculos, oclusão |
| Uptime em teste de estresse | 99,9% | Ambiente publicado |

## Suíte de testes

Medida em 19/09/2026, com as três suítes verdes.

| Parte | Testes | Cobertura |
|---|---|---|
| Backend | 124 | 98% (13 de 568 statements) |
| ML | 168 | 98% (15 de 795) |
| Frontend | 204 | 92,91% stmts · 85,03% branches · 91,66% functions |

Mais fracos no frontend: `landmarks.service.ts` (82,14%), `grafico-iee.component.ts` (86,84%).

**Não existe:** teste E2E, teste de integração contra o banco de produção (tudo roda em SQLite em
memória), teste de carga ou concorrência, linter.

**Defeito na própria suíte:** `login.component.spec.ts:100` e `registro.component.spec.ts:125`
clicam num `button[type="submit"]` dentro de `<form (ngSubmit)>`. O submit nativo dispara, o Karma
acusa `Some of your tests did a full page reload!` — e ainda assim sai com código 0. O que roda
depois do reload não é confiável.

## Defeitos que afetam a corretude de capacidades

**Três relógios decidem presença** (CAP-2, e por consequência CAP-9). O heartbeat do navegador bate
a cada 60 s incondicionalmente enquanto a aba estiver aberta, então a varredura de inatividade do
servidor não dispara, e cadeira vazia é gravada como tempo de estudo. A duração da sessão é
justamente o número que o relatório da CAP-9 vai exibir.

**Baseline em memória de processo** (CAP-4). Com mais de uma réplica, trocar de instância recomeça
a calibração no meio da sessão.

**Leitura que escreve.** A busca da sessão ativa varre e comita todas as sessões abertas de todos os
alunos, e roda a cada sinal de atividade — ou seja, uma varredura global por segundo por estudante.

## Peça pronta da CAP-9

`frontend/src/app/shared/grafico-iee.component.ts` já existe, com spec próprio: gráfico da série,
escala fixa 0–100, quebra a linha em intervalos de incerteza em vez de interpolar, descrição textual
acessível. **Está órfão** — nenhuma página o importa, e a dependência `chart.js` ainda não foi
commitada. É a primeira peça do relatório, escrita antes da página que a consome.
