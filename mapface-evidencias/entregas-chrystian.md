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

> **Sobre os hashes citados nas §§1–5.** O histórico do repositório foi reescrito
> duas vezes depois de 07/11 (autoria dos commits), então os hashes daquela data
> mudaram. O build `f04a533`, em que rodaram a medição de 07/11 e as sessões 9 a
> 13, é hoje o commit **`9e60f4d`**: os dois têm a mesma árvore
> (`c9448741c93a…`), ou seja, o mesmo código byte a byte. A versão final, de
> 19/11, está na §6.

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
| Testes automatizados | 426 backend / 326 frontend / 244 ML | **506 / 350 / 272 (1.128)**, no commit `f2b675e` da versão final (§6.5) |
| §7.5 Custo do ambiente | Estimativa e "elegível ao nível gratuito" | Real: US$ 39,60 em 24 dias, e a lista do que o `destroy` não apaga (§3) |
| §8.4 Tabela 9 — WebSocket | Meta: até 200 ms | RTT p50 125 / p95 257 / máx. 344 ms; 278 de 300 dentro da meta (§2.4) |
| §8.4 / RNF06 — backend | Meta: até 100 ms | p50 10,6 / p95 142 / máx. 230 ms; 278 de 300 dentro da meta (§2.4) |
| Identificação do build | Ausente | Versão final: commit `f2b675e`, digest e task definition da §6.1 |
| Data da troca de meta | Ausente | 18/08/2026, com redação sugerida (§4) |
| Carga | Ausente | 10 sessões simultâneas sem perda (§6.3) |
| Reinício no ambiente publicado | Só local | Deploy forçado no meio da sessão (§6.4) |

---

## 6. Versão final na AWS (19/11/2026)

Os cinco itens do Chrystian na lista final, na ordem dela.

| # | Item | Estado em 19/11 |
| --- | --- | --- |
| 1 | Versão final no ar, com consentimento e objetivo de estudo, até a defesa | **Feito**: `f2b675e` no ar (§6.1). Crédito dá até ≈ 25/12 (§6.6) |
| 2 | Sessão curta no build novo, com o roteiro da sessão 10 | **Depende de uma pessoa com webcam** (roteiro na §6.7) |
| 3 | Reinício no ambiente publicado: deploy forçado durante uma sessão | **Feito** com sessão sintética (§6.4); repetir numa sessão real é opcional |
| 4 | CPU do processo de GPU do navegador numa sessão | **Depende de uma pessoa com webcam**: medir na mesma sessão do item 2 (§6.7) |
| 5 | Pacote de evidência: commit, Terraform sem segredos, comandos, saída dos testes | **Parte da AWS pronta** em [`evidencias/versao-final/`](./evidencias/versao-final/) (§6.5) |

### 6.1 O que está no ar

| Campo | Valor |
| --- | --- |
| Commit | `f2b675e` — inclui consentimento e revogação (RF02/RF19), objetivo de estudo (RF04/RF17), cobertura e lacunas no relatório (F03) e a correção da §6.2 |
| Imagem | `sha256:5fb7612f3f0f6b95459492779686e410db3e8c3c7a051763122e3a1c455dc585`, push 19/11/2026 21:35 UTC, gerada no CodeBuild a partir do commit exato (o Docker local não sobe sem VT-x; ver §1.3) |
| Task definition | `mapface-poc-backend:4` (0,25 vCPU, 512 MiB, 1 task, `--workers 1`) |
| `/health` | `{"status":"ok","build":"f2b675e"}` |
| Frontend | Compilado do mesmo commit, publicado no S3 com invalidação do CloudFront; o site serve o mesmo `main-*.js` gerado localmente |
| Terraform | `terraform plan -detailed-exitcode` sai com 0: nenhuma diferença entre o código e a AWS (55 recursos) |

### 6.2 Defeito encontrado e corrigido: a senha do banco envelhecia

Em 19/11, num teste de carga, **7 de 10 cadastros simultâneos voltaram 500**. O
log mostrou `password authentication failed for user "mapface"`.

- **Causa.** A AWS troca a senha do RDS **a cada 7 dias** (senha gerenciada no
  Secrets Manager). O ECS injetava a senha numa variável de ambiente uma única
  vez, quando a task nascia. A task estava de pé desde 10/11, e a senha tinha
  mudado em 18/11 às 05:18 UTC. As conexões abertas antes da troca seguiam
  funcionando — o PostgreSQL não derruba sessão já autenticada —, e por isso só
  falhava quem precisava de uma conexão **nova**. Passaram exatamente os
  cadastros que pegaram uma das conexões antigas.
- **Correção** (commit `f2b675e`). A task recebe só o ARN do segredo, e um gancho
  do SQLAlchemy lê a senha atual em **cada conexão nova**
  (`backend/app/senha_do_banco.py`). A permissão de leitura saiu da role de
  execução do ECS e foi para a role da aplicação. 8 testes novos.
- **Prova no ambiente publicado.** Com a versão corrigida no ar, forcei uma
  rotação da senha (`aws secretsmanager rotate-secret`, concluída 21:41:39 UTC)
  **sem reiniciar a task**, e repeti os 10 cadastros simultâneos: 10 de 10 com
  201, e nenhum `password authentication failed` nem 500 no log desde o deploy.
- **Para o texto.** É um defeito de continuidade (achado F07 do parecer) que só
  aparece com o ambiente de pé por mais de 7 dias — nenhum teste local o
  pegaria. Vale descrever como encontrado, diagnosticado e corrigido.

### 6.3 Dez sessões simultâneas

Medido em 19/11/2026, 21:17–21:21 UTC, com `medir_latencia.py --clientes 10
--duracao 180`, contas e sessões sintéticas identificadas. Rodou no build
`abd7098`, o anterior à correção da §6.2 — a mudança da §6.2 não toca o caminho
da telemetria. Arquivo: [`latencia-10clientes.json`](./latencia-10clientes.json).

| Medida | p50 (ms) | p95 (ms) | Máx. (ms) |
| --- | ---: | ---: | ---: |
| RTT | 124,53 | 240,94 | 428,27 |
| Processamento (backend) | 9,34 | 83,89 | 194,55 |
| Rede + fila | 114,66 | 160,70 | 389,44 |

- 1.804 de 1.804 respostas, 0 erros do canal.
- WebSocket até 200 ms: 1.654 de 1.804 (91,7%). Backend até 100 ms: 1.731 de
  1.804 (96,0%).
- CPU da task (CloudWatch, média por minuto): 23% com as 10 sessões abertas; o
  pico de 100% foi a rajada dos 10 cadastros no início (o hash da senha é caro
  numa task de 0,25 vCPU: cada cadastro levou 8–11 s com os 10 juntos). Memória:
  32%.
- Rede + fila subiu de 116 ms (p95, 1 cliente) para 161 ms (p95, 10 clientes):
  é a fila do processo único.
- **Escala.** É uma réplica com um processo, por desenho: a calibração vive na
  memória do processo. Cresce verticalmente (CPU da task no Terraform); para
  várias réplicas, a calibração teria de ir para o banco. Não foi medido o
  limite.

### 6.4 Reinício no ambiente publicado (F06)

`mapface-evidencias/teste_reinicio.py`: sessão sintética identificada (conta
`teste-sintetico-reinicio-…`, assunto `teste-sintetico-reinicio`), telemetria a
1 Hz e reconexão com o **mesmo backoff do frontend** (1 s, dobrando até 30 s). Depois
da calibração, o próprio script força `update-service --force-new-deployment`.
Rodou em 19/11/2026 21:51–21:58 UTC, build `f2b675e`, sessão `26`. Arquivo:
[`evidencias/teste-reinicio-publicado.json`](./evidencias/teste-reinicio-publicado.json).

| Instante | O que aconteceu |
| --- | --- |
| 0 s | Sessão aberta, canal autenticado, calibrando |
| 64 s | Calibração concluída |
| 93 s | Deploy forçado no ECS |
| 93–234 s | O canal **continua na task antiga** enquanto a nova sobe e o balanceador a registra (inclui os 30 s de drenagem) |
| 234 s | Canal cai com código **1006** |
| 235,5 s | Reconectado na primeira tentativa (1 s de espera), **mesma sessão** |
| 235,6 s | **Calibração recomeça do zero** |
| 296 s | Calibração concluída de novo |
| 387 s | Sessão ainda ativa (`/sessoes/ativa` = 26); encerrada com 200 |

- **Maior vão sem score: 3,3 s.** Nenhum dado perdido além desse vão.
- O relatório final saiu **completo**, não parcial: 376 pontos, 0 incertos.
- **Limitação a declarar:** a linha de base vive na memória do processo, então a
  troca de task obriga a recalibrar, e o relatório **não marca** que houve
  recalibração — os 60 s de score provisório entram na média como qualquer outro
  ponto. Um teste local com o processo derrubado deu o mesmo comportamento.

### 6.5 Pacote de evidência — a parte da AWS

Em [`evidencias/versao-final/`](./evidencias/versao-final/), gerados em
19/11/2026 contra o commit `f2b675e`:

| Arquivo | O que tem |
| --- | --- |
| `testes-backend.txt` | 506 passando — `cd backend && .venv/Scripts/python.exe -m pytest -q` |
| `testes-frontend.txt` | 350 passando — `cd frontend && npx ng test --watch=false --browsers=ChromeHeadless` |
| `testes-ml.txt` | 272 passando — `cd ml && .venv/Scripts/python.exe -m pytest -q` |
| `terraform-plan.txt` | `No changes`: a AWS está igual ao código |
| `terraform-recursos.txt` | Os 55 recursos, só por endereço |
| `aws-estado.txt` | `/health`, digest da imagem, task definition, CPU/memória e a rotação da senha |

**Terraform sem segredos, conferido:** nenhum `*.tfstate` nem `terraform.tfvars`
versionado (só o `terraform.tfvars.example`); nenhuma chave de acesso, chave
privada ou senha no repositório — as únicas ocorrências de "senha" são valores
falsos dos testes de `test_config.py`. A senha do banco nunca passou pelo
Terraform (`manage_master_user_password`), e agora nem pela task definition.

Os comandos de build e deploy estão nas §§1.3 e 6.1, e no relatório
`relatorios&mermaid/06-deploy-na-aws.md`.

### 6.6 Até quando o ambiente fica no ar

Consumo até 19/11: **US$ 59,17** (US$ 29,02 em outubro e US$ 30,15 em novembro),
a **US$ 1,69 por dia**. Dos US$ 120 de crédito, restam ≈ US$ 60,80: dá até
**≈ 25/12/2026**. No plano gratuito, a conta fecha quando o crédito acaba. Se a
defesa for depois disso, é preciso converter a conta em paga ou desligar antes.

### 6.7 O que falta, e precisa de uma pessoa com webcam (itens 2 e 4)

Uma sessão só cobre os dois, no Edge ou no Chrome, em `https://d2qm0t6ecgabb2.cloudfront.net`:

1. Entrar (conta antiga pede o aceite do termo uma vez) e conferir em
   `/health` que o build é `f2b675e`.
2. Abrir o console (F12) e colar `mapface-evidencias/gravador_mapface.js`.
3. Abrir o **Gerenciador de tarefas do navegador** (Shift+Esc), deixar visível
   a linha **Processo da GPU** e a da aba do MapFace.
4. Fazer o roteiro da sessão 10: Pomodoro curto (~15 min) com uma pausa
   declarada, bocejos marcados com **B**.
5. Anotar a cada minuto a coluna **CPU** do Processo da GPU e da aba (item 4).
6. Na tela do relatório, sem recarregar: `__mapface.baixar()` e salvar como
   `mapface-evidencias/evidencias/sessao-versao-final.json`.
7. `py analisar_sessao.py evidencias\sessao-versao-final.json --rotulo "Sessão na versão final" -o evidencias\sessao-versao-final.md`
   (na pasta `mapface-evidencias`).

---

## Pergunta em aberto

**PDF V9**: onde está o arquivo editável do TCC (Word, Google Docs, Overleaf)?
