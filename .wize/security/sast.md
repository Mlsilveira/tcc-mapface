---
fase: sast
executado_em: 2026-09-21
scope_mode: sast-only (allowlist de alvos ativos vazia)
relatorio: report.md
---

# SAST — índice de achados

Severidade calibrada para o contexto declarado: instância única, poucas horas
no ar, participantes conhecidos, dado derivado de webcam de terceiros.

| id | severidade | achado | evidência |
|---|---|---|---|
| B1 | bloqueador | WebSocket prende conexão do pool (5+10) pela sessão inteira | `backend/app/routers/telemetria.py:139`; `backend/app/database.py:63,265-267`; `backend/app/telemetria.py:42` |
| B2 | bloqueador | Handler WS `async` com I/O de banco síncrono no event loop | `backend/app/routers/telemetria.py:137,160,211-217`; `backend/app/sessoes.py:116,165` |
| B3 | bloqueador | `nome` sem `max_length` no registro público; sem limite de corpo | `backend/app/schemas.py:79` (cf. `:20`, `:48`) |
| B4 | bloqueador | WS aceita antes de autenticar, sem timeout, sem teto, sem checar `Origin` | `backend/app/routers/telemetria.py:147,150`; `backend/app/main.py:134-140` |
| B5 | bloqueador (ético) | Retenção de 24 h só roda se o próprio aluno abrir o histórico | `backend/app/sumarizacao.py:121,50`; `backend/app/routers/sessoes.py:236` |
| M1 | médio | Enumeração de conta por tempo de resposta no login | `backend/app/routers/auth.py:30-34`; `backend/app/security.py:64` |
| M2 | médio | `/docs`, `/redoc`, `/openapi.json` públicos | `backend/app/main.py:132` |
| M3 | médio | Sem `pool_pre_ping` contra RDS | `backend/app/database.py:63` |
| M4 | médio | Varredura global de sessões disparável por qualquer aluno | `backend/app/sessoes.py:116,165` |
| M5 | médio | Google Fonts de terceiro, sem SRI, no produto cujo eixo é privacidade | `frontend/src/index.html:17-22` |
| M6 | médio | `verificar_configuracao` aceita origem `http://` com `AMBIENTE=producao` | `backend/app/config.py:146-198` |
| D1 | dívida | `python-jose==3.3.0` sem manutenção (CVEs não alcançáveis aqui) | `backend/requirements.txt:12`; `backend/app/security.py:113` |
| D2 | dívida | Base `python:3.9-slim-bookworm` fora de suporte | `backend/Dockerfile:24` |
| D3 | dívida | Interceptor anexa `Authorization` a qualquer URL | `frontend/src/app/core/interceptors/auth.interceptor.ts:37-57` |
| D4 | dívida | `allow_credentials=True` sem uso de cookie | `backend/app/main.py:137` |
| D5 | dívida | Sem HSTS/CSP (sem sink de XSS encontrado no frontend) | `backend/app/main.py:120-155` |
| D6 | dívida | Migração caseira `ALTER TABLE` no boot | `backend/app/database.py:104-130` |
| D7 | dívida | Canal WS não reage ao encerramento da sessão por HTTP | `backend/app/routers/telemetria.py:160` |

## Verificado e sólido

Autorização por dono com 404 em vez de 403; sessão do WS resolvida no servidor;
`pausa_maxima_s` resolvido no servidor; nenhuma SQL crua com entrada de usuário;
higiene de log declarada e aplicada; configuração falha fechada no import;
nenhum segredo versionado (hoje ou no histórico); contêiner sem privilégio, sem
`--reload`, sem `--workers`; WASM e modelo do MediaPipe auto-hospedados;
`LogEngajamento` sem coluna de imagem, com teste travando as colunas.

## degraded_checks

Ausentes do PATH, não instaladas (a skill não auto-instala): `gitleaks`,
`osv-scanner`, `grype`, `trivy`, `semgrep`, `bandit`, `pip-audit`, `nuclei`,
`nmap`, `nikto`.

Substituições manuais: varredura de segredos por `git ls-files`, `git grep -nIE`
e `git log --all --diff-filter=A`; dependências por leitura de
`backend/requirements.txt` e `frontend/package.json` com avaliação de
alcançabilidade no código.

## fases não executadas

`recon`, `enumerate`, `dast` — sem alvo autorizado em `scope.md` e sem sistema
publicado. Consequência registrada em `report.md`: TLS, grupo de segurança, RDS
e configuração da task publicada estão **fora** da cobertura deste relatório.
