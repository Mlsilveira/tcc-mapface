---
status: sast-only
mode: passive
active_targets: []
created: 2026-09-21
owner: Matheus
scope_sha256: ff7da882404289ece9352fbb1338ecdffba43e0739154331aa44134fe3462e9b
---

# Escopo da avaliação de segurança — MapFace

## Modo desta execução: SAST-ONLY

Nenhum alvo de rede foi autorizado, e nenhuma ação ofensiva foi executada.
O MapFace ainda não está publicado (tickets 14 e 15 não começaram — ver
`README.md`, "Limites conhecidos"), então não existe host, porta ou URL contra
o qual as fases `recon`, `enumerate` e `dast` da skill pudessem rodar.

## Allowlist de alvos ativos

(vazia — deny-all)

| host | portas | caminhos |
|---|---|---|
| — | — | — |

Qualquer execução futura de `recon`/`enumerate`/`dast` exige que esta tabela
seja preenchida pelo dono do sistema e que o `scope_sha256` seja recalculado
(`/wize-sec-pentest --sign-scope`).

## O que foi avaliado

Leitura estática do código da aplicação no diretório de trabalho:

- `backend/app/**` (FastAPI, SQLModel, WebSocket, configuração, observabilidade)
- `frontend/src/**` (Angular 18: auth, interceptor, guard, telemetria, visão)
- `backend/Dockerfile`, `backend/.dockerignore`, `docker-compose.yml`, `.gitignore`
- `backend/requirements.txt`, `frontend/package.json`
- histórico do git, à procura de segredo versionado

Fora de avaliação: `ml/` (trilha offline, não publicada), infraestrutura
(não existe), e o `backend/.env` local (não versionado, não lido).

## Checagens degradadas (ferramenta ausente no PATH)

`gitleaks`, `osv-scanner`, `grype`, `trivy`, `semgrep`, `bandit`, `pip-audit`,
`nuclei`, `nmap`, `nikto`. Nenhuma foi instalada — a skill não instala
ferramenta sozinha. As verificações correspondentes foram feitas à mão e estão
declaradas como tal em `sast.md`.

## Autorização

Read-only sobre o código, a pedido do dono do repositório. Nenhum arquivo da
aplicação foi modificado. Nada foi commitado.
