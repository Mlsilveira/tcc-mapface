---
status: baseline
owner: Pepper Potts + Tony Stark
created: 2026-09-19
last_refreshed: 2026-09-19
---

# Risk Spots

Um mapa, não um backlog de refactor. Tony decide o que vira trabalho; isto só torna as escolhas
visíveis. Confiança é quanto acreditamos no diagnóstico, não quanto o problema dói.

## Bloqueiam o deploy

| Área | Sintoma | Causa provável | Confiança |
|---|---|---|---|
| `frontend/src/app/core/api.ts:2` e `core/telemetria/telemetria.service.ts:7` | Build de produção aponta para `localhost:8000`; a aplicação não funciona fora da máquina do dev | Nunca houve ambiente que não fosse local; o Angular CLI não tem `environment.ts` configurado | alta |
| `telemetria.service.ts:7` | URL em `ws://`, não `wss://` | Mesma causa; atrás de HTTPS quebra por mixed content | alta |
| `backend/app/config.py:14` + `backend/.env` | `SECRET_KEY` é a string de exemplo do repositório, em uso hoje | Default hardcoded que nunca foi trocado; o README avisa, o `.env` não acompanhou | alta |
| `backend/app/main.py:18-24` | CORS fixo em `http://localhost:4200`, não configurável por env | Lista literal no código em vez de vir de `Settings` | alta |
| `backend/app/config.py:13` | SQLite em arquivo como banco | PoC começou assim; RDS/PostgreSQL é previsto e não implementado | alta |
| Repositório inteiro | Sem Dockerfile, sem Terraform, sem CI, sem `infra/` | Tickets 14 e 15 não começaram | alta |

## Corrompem o dado que o produto vende

| Área | Sintoma | Causa provável | Confiança |
|---|---|---|---|
| `sessao.service.ts` + `inactivity.service.ts` + `app/sessoes.py` | Cadeira vazia vira tempo de estudo: o heartbeat de 60 s bate enquanto a aba está aberta, então a varredura de inatividade nunca dispara | Três módulos, três relógios, três constantes sem derivação — diagnosticado em 13/08 e não endereçado | alta |
| `app/analista.py:510-559` (`RegistroDeAnalistas`) | Baseline vive num dict em memória de processo; trocar de réplica recomeça a calibração | Estado de sessão no processo; o próprio código documenta a limitação | alta |
| `app/analista.py:113` (`LIMIAR_MAR_BOCEJO = 0,30`) | Sinal de bocejo calibrado pelo p99,9 do DAiSEE, não por bocejos observados | O limiar herdado (0,60) disparava em 7 de 8570 clipes; o novo valor é uma estimativa de distribuição | média |
| `ml/esquema.py` vs `backend/app/analista.py` | Duas constantes divergentes (0,60 e 0,30) para a mesma grandeza | Recalibração feita só de um lado; `ml/metricas.py` se declara a referência, mas não é a usada | alta |

## Segurança

| Área | Sintoma | Causa provável | Confiança |
|---|---|---|---|
| `/auth/login` e `/auth/registro` | Sem rate limiting — brute force e enumeração de e-mail livres | Nenhuma dependência ou middleware de limite instalado | alta |
| `auth.service.ts:23` | JWT em `localStorage`, legível por qualquer XSS | Escolha comum em SPA; não há cookie `httpOnly` nem refresh token | alta |
| `app/routers/telemetria.py:96-186` | WebSocket sem limite de tamanho de payload, throttling ou timeout próprio | Canal escrito para o caminho feliz; o encerramento por inatividade é em minutos | média |
| `backend/app/database.py:23-74` | Migração caseira roda `ALTER TABLE` a cada boot | Alternativa deliberada ao Alembic na PoC; o próprio docstring alerta sobre corrida entre réplicas | alta |

## Reprodutibilidade e evidência para a banca

| Área | Sintoma | Causa provável | Confiança |
|---|---|---|---|
| `ml/dados/` e `ml/artefatos/` | Diretórios **vazios**, embora `resultado_18_08.md` documente 8570 clipes processados | Não versionados por decisão; a execução foi feita em disco local e não deixou rastro no repo | alta |
| Dataset DAiSEE | 2,7 GB atrás de formulário do IIIT Hyderabad, fora do repositório | Licenciamento — não é redistribuível | alta |
| `ml/artefatos/random_forest.joblib` | Modelo treinado não é carregado por ninguém | Ticket 8 trocou o Random Forest por regras, com medição registrada | alta |
| Definition of Done do plano de sprints | Critério oficial ("precisão > 80%") é satisfeito por um modelo que quase não opina | Meta definida antes de qualquer medição; correção proposta e ainda não aceita formalmente | alta |
| Histórico git | 20 de 22 commits atribuídos a "Clauderson (via Claude)" | Configuração de `user.name` do ambiente | alta |

## Produto incompleto

| Área | Sintoma | Causa provável | Confiança |
|---|---|---|---|
| Ticket 11 | O relatório de autopercepção — o produto declarado — não existe. A série é gravada e nada a lê | Não iniciada; é a próxima na ordem de dependência | alta |
| `shared/grafico-iee.component.ts` | Componente completo e testado, mas órfão: nenhuma página o importa | Primeira peça da ticket 11, escrita antes da página que a consome | alta |
| `frontend/` | Sem linter, sem testes e2e | Nunca configurados | alta |
| Branch `feat/tickets-9-11` | Trabalho relevante não commitado (componente novo, `chart.js`, alterações em 6 arquivos) | Trabalho em andamento | alta |

## 2026-09-20 — E01-S01

- **Risco novo:** `score = 0.0` em `log_engajamento` tem **duas causas indistinguíveis** —
  `P(t) = 0` (rosto ausente) e `max(0.0, bruto - fadiga)` de um aluno presente que a fadiga zerou
  (`analista.py`, fim de `calcular_iee`). A tabela não guarda `rosto_detectado`, então o relatório
  não consegue dizer ao aluno se ele saiu da mesa ou se estava ali e exausto. Confiança: alta.
  Mitigação adotada: o indicador se chama `pontos_zerados`, não `pontos_ausentes` — mede o que
  de fato mede. Separar de verdade exige coluna nova e migração, fora do escopo da E01-S01.
