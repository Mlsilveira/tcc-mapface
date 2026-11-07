# Entregas do Chrystian — plano do TC2 final (07–08/11/2026)

Tudo o que o plano pós-parecer atribuiu ao Chrystian, num arquivo só: o que foi
feito, o que foi medido, o que ainda depende de alguém e o número exato que vai
para o texto. Cada número vem de um comando ou de um commit citado na mesma
seção.

| Item do plano | O que é | Estado em 07/11 |
| --- | --- | --- |
| Etapa 1, item 1 | Publicar a imagem e anotar commit, hash e horário | **Feito**: build `f04a533` no ar desde 07/11/2026 21:50 UTC ([§1](#1-build-e-deploy-etapa-1-item-1)) |
| Etapa 1, item 4 | Latência do canal: RTT p50/p95/máx e processamento separado | **Feito**: 300 payloads no ambiente publicado, cliente e log do servidor conferem ([§2](#2-latência-do-canal-etapa-1-item-4)) |
| Etapa 1, item 8 | Custo real e o que sobra depois do `destroy` | **Feito** (custo até 07/11); repetir a consulta na véspera do `destroy` ([§3](#3-custo-real-e-o-que-fica-retido-etapa-1-item-8)) |
| Etapa 2 | Data da troca de meta (80% → acurácia balanceada > 0,65) | **Feito**: 18/08/2026, com redação sugerida ([§4](#4-a-data-da-troca-de-meta-etapa-2)) |
| Etapa 6 | Gerar o PDF V9 | **Depende do grupo**: é o último passo, depois das Etapas 2–5, e não há fonte editável do TCC ([§5](#5-pdf-v9-etapa-6)) |

**O que o resto do grupo já pode usar:** o build instrumentado está no ar, então
as sessões reais do Rian (itens 2, 3, 5 e 6) já saem com o `build` e com o
`processamento_ms` de cada segundo, e o item 7 do Matheus (carga) tem o script
pronto (§2.3).

O que o parecer mandou **preservar** não foi tocado por nada disto: o resultado
negativo do DAiSEE, o classificador de sonolência paralelo ao índice, os valores
nulos de incerteza e a identificação da sessão sintética (que, aliás, ficou mais
forte — ver §2.3).

---

## 1. Build e deploy (Etapa 1, item 1)

### 1.1 O que estava no ar antes

Levantado direto na AWS em 07/11/2026, antes do deploy (ECS e ECR, conta
481503226251, us-east-1):

| Campo | Valor |
| --- | --- |
| Serviço | `mapface-poc` / `mapface-poc-backend`, 1 task desejada, 1 rodando |
| Task definition | `mapface-poc-backend:1`, deploy de 14/10/2026 18:13 UTC, rollout `COMPLETED` |
| Imagem | `mapface-poc-backend:latest` |
| Digest em execução | `sha256:2521a999e596b0bcea1c4ebd092dc787837034141b04e4917678ea66acd8148b` |
| Push da imagem | 14/10/2026 18:08 UTC (15:08 em Brasília), 190,9 MB |
| Task atual iniciada em | 24/10/2026 17:12 UTC (o ECS substituiu a task; mesma imagem) |
| Commit | **Não identificável com certeza.** O push caiu entre `99ef8f9` (12:33) e `0f20337` (15:39) e foi feito a partir da árvore de trabalho, não de um commit. |

A última linha é o achado F02 do parecer em pessoa: a imagem que estava no ar não
dizia de qual código veio. É exatamente o que a instrumentação abaixo corrige.

### 1.2 O que foi feito

Commit `09b5208` — *feat(medicao): latência do canal e identificação do build*:

- `backend/Dockerfile` recebe `ARG BUILD_COMMIT` e o grava como variável de
  ambiente da imagem;
- `GET /health` passa a responder `{"status": "ok", "build": "<commit>"}`;
- o log da aplicação (logger `app`) passa a sair no CloudWatch. Antes, as linhas
  `INFO` da aplicação — inclusive `classificador de sonolência carregado` —
  nunca apareciam, porque só o logger do uvicorn tinha handler.

### 1.3 Como a imagem foi gerada

O Docker Desktop foi reinstalado nesta máquina em 07/11, mas não sobe: a
virtualização do processador (Intel VT-x) está desligada no firmware
(`VirtualizationFirmwareEnabled: False`). Em vez de depender da BIOS, o build
foi feito **na própria AWS, com CodeBuild**, a partir do commit exato:

1. `git archive f04a533:backend` → zip com 64 arquivos, incluindo o
   `app/modelos/sonolencia.joblib` versionado;
2. bucket S3, papel IAM e projeto CodeBuild **temporários** (`mapface-build-tmp`),
   com permissão só para ler o zip e fazer push no repositório do backend;
3. `docker build --build-arg BUILD_COMMIT=f04a533`, com o `Dockerfile` do
   repositório sem nenhuma alteração. A imagem base `python:3.11-slim` foi
   puxada do espelho oficial no ECR Public (o Docker Hub limita pulls anônimos
   vindos da AWS) e recebeu o nome que o `Dockerfile` pede;
4. o próprio build rodou a imagem e conferiu `BUILD_COMMIT=f04a533` antes do push;
5. push das tags `f04a533` e `latest`; build `SUCCEEDED` em 60 s;
6. projeto, papel, bucket e log group do CodeBuild **apagados em seguida e
   conferidos** — não entram na lista do que sobra (§3.2).

Depois, no PowerShell, em `infra/`:

```powershell
terraform plan  -var "tag_da_imagem=f04a533" -out tc2.plan   # 1 add, 1 change, 1 destroy: só task definition e serviço
terraform apply tc2.plan
```

Antes do deploy, o log da aplicação não tinha nenhuma requisição além do health
check nas 6 horas anteriores: ninguém teve sessão derrubada.

Para um próximo deploy com Docker funcionando, a sequência local equivalente é:

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

**Antes de qualquer deploy, confirmar que ninguém está gravando sessão**: a troca
de task derruba os WebSockets abertos.

### 1.4 Registro do deploy instrumentado

| Campo | Valor |
| --- | --- |
| Commit | `f04a533` (o código do backend é o de `09b5208`; os commits seguintes só mexem em `mapface-evidencias/`) |
| Digest da imagem | `sha256:36e325e62244b474e106985ba7bbaa6e28f94e2dc68f4c7eb171be91c2987b0c` (191,9 MB), tags `f04a533` e `latest` |
| Push no ECR | 07/11/2026 21:48:42 UTC |
| Task definition | `mapface-poc-backend:2` (a `:1` apontava para `:latest`; a `:2` aponta para a tag do commit) |
| `terraform apply` | 07/11/2026 21:50:24 → 21:50:29 UTC |
| `/health` → `build` | `f04a533` às 21:52:26 UTC; rollout `COMPLETED` com 1 task |
| Log de inicialização | `app.sonolencia: classificador de sonolência carregado de /app/app/modelos/sonolencia.joblib` |

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
ele já captura o `processamento_ms`, porque copia a mensagem inteira. Por isso o
frontend não precisou mudar: na sessão real, o RTT sai do gravador; na sessão
sintética, do script.

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

### 2.4 Resultado no ambiente publicado

| Campo | Valor |
| --- | --- |
| Ambiente | `https://d2qm0t6ecgabb2.cloudfront.net` → CloudFront → ALB → ECS Fargate (1 task, 0,25 vCPU, 512 MiB, `--workers 1`) → RDS, us-east-1 |
| Build | `f04a533` (lido do `/health` pelo próprio script) |
| Janela | 07/11/2026, 21:53:39 a 21:58:46 UTC |
| Cliente | Computador do Chrystian, no Brasil, conexão doméstica |
| Sessão | `id 8`, conta `medicao-sintetica-72f63364-0@example.com`, assunto `medicao-sintetica-latencia`, encerrada ao fim |
| Payloads | 300 enviados, 300 respondidos, 0 erros do canal |
| Arquivo | [`latencia-1cliente.json`](./latencia-1cliente.json) (resumo + as 300 medições cruas) |

| Medida | p50 (ms) | p95 (ms) | Máx. (ms) | Média (ms) |
| --- | ---: | ---: | ---: | ---: |
| **RTT** (cliente) | 125,31 | 256,71 | 344,35 | 139,02 |
| **Processamento** (backend) | 10,59 | 141,89 | 229,81 | 24,09 |
| **Rede + fila** (RTT − processamento) | 114,59 | 116,49 | 131,23 | 114,94 |

**O log do servidor confere com o cliente**, linha exportada do CloudWatch
(`/ecs/mapface-poc`, stream `backend/backend/1ade55f300364ab58f37e650d9616091`):

```text
INFO:     app.routers.telemetria: latencia do canal: sessao=8 n=300 p50=10.59ms p95=141.89ms max=229.81ms
```

**Leitura dos números, para o texto:**

- **A rede domina o RTT típico.** ≈ 115 ms de rede + fila, estável (p95 só
  2 ms acima do p50), é o trajeto São Paulo → us-east-1 e volta. O backend
  típico gasta ≈ 11 ms.
- **O processamento tem uma cauda, e ela tem ritmo.** 276 dos 300 payloads
  ficaram entre 9,6 e 41 ms. Os 24 acima de 50 ms (mediana 201 ms) caem, com
  exceção de dois, **a cada 10–11 payloads**, e não aparecem nos primeiros 60 s
  (a calibração de 6 janelas). O ritmo coincide com o fechamento da janela de
  10 s do classificador de sonolência (`DURACAO_DA_JANELA`), quando o Extra Trees
  (300 árvores) roda numa task de 0,25 vCPU. É a explicação mais provável, mas
  é inferida do padrão — o tempo do classificador não foi medido isoladamente.
- **Contra as metas da Tabela 9 e do RNF06:** o RNF06 (backend em até 100 ms) é
  atendido por **278 de 300** payloads (92,7%) e **não** no p95 (141,89 ms); o
  WebSocket até 200 ms é atendido por 278 de 300 e no p50 (125 ms), mas **não**
  no p95 (257 ms). Os payloads que estouram são os mesmos da cauda acima.
- **O que isso não é:** com o canal estritamente 1:1 e um envio por segundo,
  um RTT de 344 ms ainda chega antes do próximo envio — a tela nunca fica uma
  leitura atrás. A medição é de 1 cliente; carga é o item 7 do Matheus.
- **Uma hipótese, não testada:** o modelo foi treinado com `n_jobs=-1`
  (`ml/treino_fadiga.py`), e predizer uma linha com paralelismo numa task de
  0,25 vCPU costuma custar mais do que predizer em série. Se o grupo quiser
  atacar a cauda, o primeiro experimento é `n_jobs=1` no estimador carregado,
  medido de novo com este mesmo script. Não foi feito: mudaria o build medido.

**Para o item 7 (Matheus):** o mesmo script com `--clientes 5 --duracao 600`
gera `latencia-5clientes.json`. Exportar a linha `latencia do canal` de cada
sessão do CloudWatch **no mesmo dia**: o log group guarda só **7 dias**
(`retencao_de_log_dias`).

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
- ECR: `force_delete = true` — as imagens saem com o repositório (hoje são
  duas: a de 14/10, que perdeu a tag `latest`, e a `f04a533`);
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

Os recursos temporários do build de 07/11 (projeto CodeBuild, papel IAM, bucket
S3 e log group `mapface-build-tmp`) **não** estão nesta lista porque já foram
apagados no mesmo dia, com a remoção conferida um a um (§1.3).

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
| 21/09/2026 | `.wize/specs/spec-poc-iee/SPEC.md` (commit `2500fa3`) | "Proposto em `resultado_18_08.md`, ainda não aceito formalmente pela orientação" |
| 24/09/2026 | Treino do classificador no UTA-RLDD (0,6553) | Já sob a meta nova — o alvo foi fixado **antes** desse modelo existir |

Duas observações para o texto, que o parecer vai procurar:

- **A meta nova foi proposta depois de ver o resultado do DAiSEE**, e o próprio
  `resultado_18_08.md` diz que é um alvo que o trabalho atual atinge. Isso tem de
  aparecer escrito como está: a meta foi recalibrada à luz de um resultado
  negativo, e não definida às cegas. O resultado negativo do DAiSEE fica como
  está.
- O modelo que de fato roda (UTA-RLDD, 0,6553) **não** influenciou a escolha do
  0,65: foi treinado um mês depois.

**Data adotada no texto: 18/08/2026.** É a data real em que a meta de 0,65
entrou no projeto (commit `71e519a`, `resultado_18_08.md` §4); antes dela só
existia a de 80%, e nenhum commit posterior altera o número. Em 21/09, o
`.wize/specs/spec-poc-iee/SPEC.md` ainda registrava a troca como "proposta, ainda
não aceita formalmente pela orientação" — então o texto deve dizer **proposta e
adotada pelo grupo em 18/08/2026**, sem afirmar aprovação formal com data que
não está registrada.

Sugestão de redação para o TCC:

> A meta original de precisão superior a 80% (especificação de 13/08/2026) foi
> substituída em 18/08/2026, após a primeira execução contra o DAiSEE, por
> acurácia balanceada superior a 0,65 com o recall da classe minoritária
> reportado. A troca foi motivada pelo desbalanceamento da base, que tornava a
> meta original atingível por um modelo que quase nunca prevê a classe
> minoritária. A meta nova foi definida depois da fase de exploração no DAiSEE e
> antes do treino do classificador de sonolência no UTA-RLDD (24/09/2026), que
> foi avaliado contra ela sem que a meta fosse alterada de novo.

---

## 5. PDF V9 (Etapa 6)

O V9 é o **último passo do plano**: ele junta o texto das Etapas 2 a 5, que são
do Rian e do Matheus, e por isso não pode ser gerado antes delas. Além disso, o
único arquivo do TCC disponível é o **PDF V8** — não há `.docx`, LaTeX ou
documento compartilhado no repositório nem nesta máquina, e as figuras do V8 não
são reproduzíveis a partir do texto. Gerar o V9 depende de alguém indicar onde
está a fonte editável.

A parte do Chrystian que vai para o V9 já está pronta, neste arquivo:

| Onde no texto | Hoje (V8) | Vai para (V9) |
| --- | --- | --- |
| Testes automatizados | 426 backend / 326 frontend / 244 ML | **451** / 326 / 244 (**1.021**) |
| §7.5 Custo do ambiente | Estimativa e "elegível ao nível gratuito" | Real: US$ 39,60 em 24 dias, e a lista do que o `destroy` não apaga (§3) |
| §8.4 Tabela 9 — WebSocket | Meta: até 200 ms | RTT p50 125 / p95 257 / máx. 344 ms; 278 de 300 dentro da meta (§2.4) |
| §8.4 / RNF06 — backend | Meta: até 100 ms | p50 10,6 / p95 142 / máx. 230 ms; 278 de 300 dentro da meta (§2.4) |
| Identificação do build | Ausente | Commit `f04a533` e digest da tabela 1.4 |
| Data da troca de meta | Ausente | 18/08/2026, com redação sugerida (§4) |

---

## Pergunta em aberto

**PDF V9**: onde está o arquivo editável do TCC (Word, Google Docs, Overleaf)?
