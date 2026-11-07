# Entregas do Chrystian — plano do TC2 final (07–08/11/2026)

Tudo o que o plano pós-parecer atribuiu ao Chrystian, num arquivo só: o que foi
feito, o que foi medido, o que ainda depende de alguém e o número exato que vai
para o texto. Cada número vem de um comando ou de um commit citado na mesma
seção.

| Item do plano | O que é | Estado em 07/11 |
| --- | --- | --- |
| Etapa 1, item 1 | Publicar a imagem e anotar commit, hash e horário | **Bloqueado**: instrumentação pronta e testada, mas o Docker Desktop foi desinstalado desta máquina em 28/10 ([§1](#1-build-e-deploy-etapa-1-item-1)) |
| Etapa 1, item 4 | Latência do canal: RTT p50/p95/máx e processamento separado | **Pronto para rodar**: backend instrumentado, script escrito e validado localmente; falta só o deploy ([§2](#2-latência-do-canal-etapa-1-item-4)) |
| Etapa 1, item 8 | Custo real e o que sobra depois do `destroy` | **Feito** (custo até 07/11); repetir a consulta no dia do `destroy` ([§3](#3-custo-real-e-o-que-fica-retido-etapa-1-item-8)) |
| Etapa 2 | Data da troca de meta (80% → acurácia balanceada > 0,65) | **Datas do repositório levantadas**; falta a data da aprovação da orientadora ([§4](#4-a-data-da-troca-de-meta-etapa-2)) |
| Etapa 6 | Gerar o PDF V9 | **Bloqueado**: não há fonte editável do TCC no repositório ([§5](#5-pdf-v9-etapa-6)) |

O que o parecer mandou **preservar** não foi tocado por nada disto: o resultado
negativo do DAiSEE, o classificador de sonolência paralelo ao índice, os valores
nulos de incerteza e a identificação da sessão sintética (que, aliás, ficou mais
forte — ver §2.3).

---

## 1. Build e deploy (Etapa 1, item 1)

### 1.1 O que está no ar hoje

Levantado direto na AWS em 07/11/2026 (ECS e ECR, conta 481503226251, us-east-1):

| Campo | Valor |
| --- | --- |
| Serviço | `mapface-poc` / `mapface-poc-backend`, 1 task desejada, 1 rodando |
| Task definition | `mapface-poc-backend:1`, deploy de 14/10/2026 18:13 UTC, rollout `COMPLETED` |
| Imagem | `mapface-poc-backend:latest` |
| Digest em execução | `sha256:2521a999e596b0bcea1c4ebd092dc787837034141b04e4917678ea66acd8148b` |
| Push da imagem | 14/10/2026 18:08 UTC (15:08 em Brasília), 190,9 MB |
| Task atual iniciada em | 24/10/2026 17:12 UTC (o ECS substituiu a task; mesma imagem) |
| Commit | **Não identificável com certeza.** O push caiu entre `99ef8f9` (12:33) e `0f20337` (15:39) e foi feito a partir da árvore de trabalho, não de um commit. |

A última linha é o achado F02 do parecer em pessoa: a imagem que está no ar não
diz de qual código veio. É exatamente o que a instrumentação abaixo corrige.

### 1.2 O que foi feito

Commit `09b5208` — *feat(medicao): latência do canal e identificação do build*:

- `backend/Dockerfile` recebe `ARG BUILD_COMMIT` e o grava como variável de
  ambiente da imagem;
- `GET /health` passa a responder `{"status": "ok", "build": "<commit>"}`;
- o log da aplicação (logger `app`) passa a sair no CloudWatch. Antes, as linhas
  `INFO` da aplicação — inclusive `classificador de sonolência carregado` —
  nunca apareciam, porque só o logger do uvicorn tinha handler.

### 1.3 O que falta, e o comando exato

O Docker Desktop foi **desinstalado desta máquina em 28/10/2026** (log em
`C:\ProgramData\DockerDesktop\install-log-admin.txt`), e não há WSL com
distribuição instalada. Sem ele não há como gerar a imagem. Quando houver Docker
(reinstalado aqui ou na máquina de outro integrante), a sequência é esta, no
PowerShell, a partir de `D:\tcc`:

```powershell
$COMMIT = git rev-parse --short HEAD
$ECR = "481503226251.dkr.ecr.us-east-1.amazonaws.com/mapface-poc-backend"

docker build --build-arg BUILD_COMMIT=$COMMIT -t "${ECR}:$COMMIT" -t "${ECR}:latest" backend
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin 481503226251.dkr.ecr.us-east-1.amazonaws.com
docker push "${ECR}:$COMMIT"
docker push "${ECR}:latest"

cd infra
terraform plan  -var "tag_da_imagem=$COMMIT"   # deve mudar só a task definition e o serviço
terraform apply -var "tag_da_imagem=$COMMIT"
```

Depois do `apply`, anotar na tabela 1.4: o commit, o digest (`aws ecr
describe-images --repository-name mapface-poc-backend --image-ids
imageTag=$COMMIT`), a revisão nova da task definition e o horário. Conferir:

- `https://d2qm0t6ecgabb2.cloudfront.net/health` devolve o `build` igual ao commit;
- o log da task tem a linha `classificador de sonolência carregado`.

**Antes do deploy, confirmar que ninguém está gravando sessão**: a troca de task
derruba os WebSockets abertos.

### 1.4 Registro do deploy instrumentado (preencher)

| Campo | Valor |
| --- | --- |
| Commit | |
| Digest da imagem | |
| Task definition | `mapface-poc-backend:` |
| Horário do `apply` (UTC) | |
| `/health` → `build` | |

---

## 2. Latência do canal (Etapa 1, item 4)

### 2.1 O que é medido, e o que não é somado

Três números por payload, e só uma subtração:

| Medida | Onde é medida | O que inclui |
| --- | --- | --- |
| **RTT** | No cliente, do `send` à chegada do `score` | Tudo: rede de ida, fila, processamento, rede de volta |
| **Processamento** | No backend (`processamento_ms`), do payload em memória até a resposta sair | Conferência da credencial, fórmula do índice, janela do classificador e o `INSERT` com `commit` |
| **Rede + fila** | RTT − processamento | O que sobra |

O processamento **já está dentro** do RTT. Somar os dois conta o backend duas
vezes.

O pareamento de cada resposta com o seu envio é pelo carimbo `t0`, que o backend
devolve intacto. O canal é estritamente 1:1 (cada payload gera uma resposta),
então o gravador do Rian, que pareia pela ordem de chegada, também é válido — e
ele já captura o `processamento_ms` quando o build novo estiver no ar, porque
copia a mensagem inteira.

Percentil por **posto mais próximo, sem interpolação**: o p95 é sempre uma
medição que aconteceu, e dá para apontar o segundo em que ela ocorreu.

### 2.2 Instrumentação no backend (commit `09b5208`)

- cada `score` traz `processamento_ms` (3 casas) e o `t0` devolvido;
- carimbo malformado (booleano, texto, lista) é ignorado sem derrubar o score;
- **uma** linha de log por conexão, ao fechar:
  `latencia do canal: sessao=<id> n=<payloads> p50=… p95=… max=…`
  — uma por conexão e não por payload, para não afogar o log a 1 Hz;
- 16 testes novos em `backend/tests/test_medicao.py`. Suíte do backend:
  **451 passando** (eram 435).

Nada disso muda o que o aluno vê: o frontend ignora os campos novos.

### 2.3 O script: `mapface-evidencias/medir_latencia.py`

Abre uma sessão sintética **identificada no banco**: conta própria por cliente,
com nome `Medição sintética de latência`, e-mail `medicao-sintetica-…@example.com`
e assunto `medicao-sintetica-latencia`. A senha é gerada e descartada. Ao fim,
encerra a sessão. Os payloads são fixos (olhos abertos, rosto de frente): o
script mede o canal, não o índice.

```bash
backend/.venv/Scripts/python.exe mapface-evidencias/medir_latencia.py --duracao 300 --saida mapface-evidencias/latencia-1cliente.json
```

Com `--clientes N`, abre N alunos simultâneos (conta e sessão próprias cada um)
— serve ao item de carga do Matheus. O JSON de saída traz o `build` lido do
`/health`, o horário de início e fim em UTC, o resumo e as medições cruas.

**Validação local** (07/11, backend em `127.0.0.1` com SQLite, 2 clientes a 2 Hz
por 6 s): 24 de 24 pares, 0 perdas, e a linha de log do servidor bateu com o
número de payloads de cada conexão. Esses números (RTT p50 ≈ 10 ms) são **da
máquina local e não vão para o texto** — servem só para mostrar que o script e o
servidor concordam.

### 2.4 O que rodar, quando o build novo estiver no ar

1. `medir_latencia.py --duracao 300` (1 cliente, 5 min) → `latencia-1cliente.json`;
2. o mesmo com `--clientes 5` → `latencia-5clientes.json`;
3. exportar as linhas `latencia do canal` do CloudWatch **no mesmo dia** — o log
   group `/ecs/mapface-poc` guarda só **7 dias** (`retencao_de_log_dias`).

Para o texto, por cenário: RTT p50/p95/máx, processamento p50/p95/máx e
rede + fila p50/p95/máx, com o commit do build e a janela de horário.

| Cenário | RTT p50 / p95 / máx (ms) | Processamento p50 / p95 / máx (ms) | Rede + fila p50 / p95 / máx (ms) |
| --- | --- | --- | --- |
| 1 cliente, 300 s | | | |
| 5 clientes, 300 s | | | |

---

## 3. Custo real e o que fica retido (Etapa 1, item 8)

### 3.1 Custo real, do Cost Explorer

Período: **14/10/2026 a 07/11/2026** (24 dias de ambiente no ar), consultado em
07/11/2026. Todo o valor foi abatido do crédito do plano gratuito; nada foi
cobrado no cartão.

| Serviço | US$ | O que gera o custo |
| --- | ---: | --- |
| Elastic Load Balancing | 12,71 | ALB ligado 24 h, cobra por hora existindo |
| RDS | 10,81 | Instância PostgreSQL ligada 24 h |
| VPC | 8,47 | **IPv4 público** (ALB e task), cobrado por hora desde 2024 |
| ECS (Fargate) | 6,97 | 1 task ligada 24 h |
| Secrets Manager | 0,61 | Segredos da aplicação |
| ECR | 0,01 | 190,9 MB de imagem |
| S3 | < 0,01 | Site estático |
| CloudFront | 0,00 | Dentro da cota gratuita |
| **Total** | **39,60** | ≈ **US$ 1,68/dia** ≈ US$ 51/mês |

**O custo é quase todo de existir, não de usar.** ALB, RDS, IPv4 e Fargate
cobram por hora ligados, com ou sem aluno conectado; o uso real (requisições,
WebSocket, transferência) não aparece na conta.

**Crédito restante: ≈ US$ 80,40**, o que dá **≈ 48 dias** no ritmo atual — o
crédito acaba por volta de **24/12/2026**, bem antes do fim do plano gratuito
(30/03/2027). No plano gratuito, a conta é encerrada quando o crédito acaba, a menos
que seja convertida em paga. Ou seja: há folga para as medições da equipe, mas o
`destroy` não pode ficar para depois das férias.

### 3.2 O que o `terraform destroy` apaga, e o que não apaga

Apaga junto, sem sobra (configurado assim de propósito):

- RDS: `skip_final_snapshot = true` e `deletion_protection = false` por padrão
  — não fica snapshot final; os backups automáticos (1 dia) saem com a instância;
- ECR: `force_delete = true` — as imagens saem com o repositório;
- S3 do site: `force_destroy = true` — inclusive as versões antigas do
  versionamento;
- Secrets Manager: `recovery_window_in_days = 0` — sem a janela de 7–30 dias;
- log group do CloudWatch.

**Não** é apagado pelo `destroy`, porque não foi criado pelo Terraform:

| O que | Onde | O que fazer |
| --- | --- | --- |
| Usuário IAM `mapface-deploy` e as chaves de acesso | IAM | Desativar e apagar as chaves; apagar o usuário |
| Orçamento "Budget mensal aws" | Billing | Pode ficar (não custa) ou ser apagado |
| Service-linked roles (ECS, RDS, ELB) | IAM | Podem ficar; a AWS as recria quando precisa |
| `infra/terraform.tfstate` | **Esta máquina** | Contém os segredos (inclusive a `SECRET_KEY`) em texto puro. Fora do Git (`.gitignore`), mas apagar depois do `destroy` |
| `backend/.env` e `database/` locais | Esta máquina | Fora do Git; apagar ou manter conforme o uso local |

### 3.3 Checklist do dia do `destroy` (Etapa 6)

1. Confirmar que Rian e Matheus terminaram as medições no ambiente publicado;
2. exportar o que precisa ficar do CloudWatch (7 dias de retenção) e do banco
   (`backend/scripts/inspecionar_banco.py`, rodado de dentro da task);
3. repetir a consulta do Cost Explorer até a véspera e atualizar a tabela 3.1;
4. `terraform destroy` em `infra/`;
5. limpar a lista da tabela 3.2.

---

## 4. A data da troca de meta (Etapa 2)

O que o repositório registra, em ordem:

| Data | Evidência | O que diz |
| --- | --- | --- |
| 13/08/2026 | Commit `c49213e` (spec da PoC) | A Definition of Done pede **precisão superior a 80%** |
| 18/08/2026 23:14 | Commit `71e519a`, `resultado_18_08.md` §4 | **Proposta** de trocar por **acurácia balanceada > 0,65**, com recall da classe minoritária reportado. O melhor modelo no DAiSEE dava 0,6572 |
| 19/09/2026 | `.wize/knowledge/document-project/open-questions.md` | A troca ainda aparece como **pergunta aberta para a orientação** |
| 24/09/2026 | Treino do classificador no UTA-RLDD (0,6553) | Já sob a meta nova — o alvo foi fixado **antes** desse modelo existir |

Duas observações para o texto, que o parecer vai procurar:

- **A meta nova foi proposta depois de ver o resultado do DAiSEE**, e o próprio
  `resultado_18_08.md` diz que é um alvo que o trabalho atual atinge. Isso tem de
  aparecer escrito como está: a meta foi recalibrada à luz de um resultado
  negativo, e não definida às cegas. O resultado negativo do DAiSEE fica como
  está.
- O modelo que de fato roda (UTA-RLDD, 0,6553) **não** influenciou a escolha do
  0,65: foi treinado um mês depois.

**Pendente:** a anotação do plano diz "antes das férias", mas o repositório só
tem a proposta (18/08) e a pendência (19/09). A data da **aprovação** pela
orientadora — se houve — não está em nenhum arquivo. Ver pergunta no fim.

---

## 5. PDF V9 (Etapa 6)

O único arquivo do TCC disponível é o **PDF V8**. Não há `.docx`, LaTeX ou
documento compartilhado no repositório nem nesta máquina, e as figuras do V8 não
são reproduzíveis a partir do texto. Gerar o V9 depende de alguém indicar onde
está a fonte editável.

Quando houver a fonte, entram no V9 os números deste arquivo:

| Onde no texto | Hoje (V8) | Vai para (V9) |
| --- | --- | --- |
| Testes automatizados | 426 backend / 326 frontend / 244 ML | **451** / 326 / 244 (**1.021**) |
| Custo do ambiente | Estimativa | Real: US$ 39,60 em 24 dias (tabela 3.1) |
| Latência | Sem medição no ambiente publicado | Tabela 2.4 |
| Identificação do build | Ausente | Commit e digest da tabela 1.4 |
| Data da troca de meta | Ausente | Seção 4 |

---

## Perguntas em aberto

1. **Docker**: reinstalo o Docker Desktop nesta máquina para o deploy, ou alguém
   da equipe faz o build com os comandos do §1.3?
2. **Data da meta**: "antes das férias" é a data em que a orientadora aprovou a
   troca? Há registro (e-mail, ata) com o dia?
3. **PDF V9**: onde está o arquivo editável do TCC (Word, Google Docs, Overleaf)?
