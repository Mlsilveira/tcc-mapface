---
status: baseline
owner: Pepper Potts + Peggy Carter
created: 2026-09-19
last_refreshed: 2026-09-19
---

# Open Questions

Perguntas que o código não responde. Cada uma tem um humano como destino — sem dono, pergunta
não é respondida.

| Pergunta | Por que importa | Quem responde |
|---|---|---|
| A Definition of Done troca "precisão > 80%" por "acurácia balanceada > 0,65 com recall reportado"? | `resultado_18_08.md` seção 4 mostra que a meta atual é satisfeita por um modelo que quase nunca opina. Enquanto a DoD não mudar, o critério oficial do projeto premia o silêncio. | Orientação (Prof.ª Stephany / Prof. Quinello) |
| O deploy na AWS é requisito de banca ou stretch goal? | O spec chama de stretch (`spec-poc-iee.md:124`); o plano de sprints reserva as sprints 8–9 e o cap. 8 do TCC promete "provisionamento total via IaC" como evidência de sucesso. As duas leituras levam a planos de trabalho muito diferentes daqui até novembro. | Orientação + equipe |
| Quem tem a conta AWS, quem paga e qual o teto de gasto? | A sprint 7 previa "criar conta/organização AWS e configurar IAM" — não há evidência no repositório de que isso aconteceu. Sem conta e orçamento, as tickets 14 e 15 não começam. | Equipe (Matheus & Rian) |
| O DAiSEE ainda está em disco e os artefatos do treino existem em algum lugar? | `ml/dados/` e `ml/artefatos/` estão vazios no ambiente atual, embora `resultado_18_08.md` documente uma execução completa. Se a banca pedir para reproduzir, são horas de reprocessamento e um formulário de acesso que levou semanas. | Chrystian |
| O `LIMIAR_MAR_BOCEJO` = 0,30 vai ser recalibrado com dados reais de teste? | Foi escolhido a partir do p99,9 do DAiSEE, não de bocejos observados. A sprint 11 reserva tempo para isso. Sem recalibrar, o sinal de bocejo do fator de fadiga é uma aposta. | Chrystian |
| A constante equivalente em `ml/esquema.py` (0,60) fica desalinhada de propósito? | O backend usa 0,30 e o `ml/` usa 0,60 para a mesma grandeza. `ml/metricas.py` é declarado como "referência de implementação para o frontend" — duas fontes de verdade divergentes para o mesmo limiar. | Chrystian |
| Qual a prioridade entre a ticket 11 (relatório) e as tickets 14–15 (infra/deploy)? | A 11 é o produto declarado e destrava 12 e 13; a 14 não é bloqueada por nada e pode correr em paralelo. Hoje nenhuma das duas começou, e o calendário original já passou do ponto em que ambas deveriam estar prontas. | Equipe |
| O cronograma vai ser replanejado? | O plano previa a sprint 6 (relatório) concluída em 24/09 e o deploy em 15/10. Em 19/09 o último commit é de 27/08 e a ticket 11 não começou. O plano em vigor e o estado real divergem. | Equipe + orientação |
| Alembic entra junto com o PostgreSQL na ticket 15? | `backend/app/database.py` já documenta a própria migração caseira como insuficiente e aponta a ticket 15 como o momento de trocar. A decisão precisa ser explícita, senão o deploy leva a migração de PoC para produção. | Matheus & Rian |
| A autoria dos commits precisa refletir os três integrantes? | 20 dos 22 commits estão atribuídos a "Clauderson (via Claude)". Se a banca ou a instituição avaliar contribuição individual pelo histórico git, o registro atual não sustenta. | Equipe + orientação |
