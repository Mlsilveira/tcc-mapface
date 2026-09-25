# Tutorial: subir o MapFace para a AWS

Do momento em que você recebe o acesso à conta até a aplicação no ar.

> ## Leia isto primeiro
>
> **A trilha para no passo 6.** O Terraform de hoje (ticket 14) provisiona rede,
> S3 + CloudFront, ECR e RDS. Ele **não** cria o ECS, o ALB nem os *behaviors*
> do CloudFront que encaminham a API — isso é a ticket 15, e ela não está
> escrita.
>
> Na prática: você consegue subir toda a infraestrutura e publicar o frontend.
> O backend fica sem lugar para rodar, e a aplicação abre mas não faz login.
>
> A [seção 6](#6-o-que-falta-a-ticket-15) lista exatamente o que falta.

> ## Sobre as credenciais
>
> **Não me mande o e-mail e a senha da conta**, e não os coloque em nenhum
> arquivo do repositório. Eu não preciso deles para nada do que está escrito
> aqui — todos os comandos abaixo rodam na sua máquina, com as suas
> credenciais.
>
> A senha da conta raiz é a chave mestra da AWS: quem a tem pode apagar tudo,
> criar recursos ilimitados e ver qualquer dado. Ela é usada **duas vezes** no
> passo 1 e depois nunca mais.

---

## Sumário

1. [Proteger a conta (30 min, uma vez só)](#1-proteger-a-conta)
2. [Preparar a máquina](#2-preparar-a-máquina)
3. [Configurar as credenciais](#3-configurar-as-credenciais)
4. [Provisionar a infraestrutura](#4-provisionar-a-infraestrutura)
5. [Publicar o frontend](#5-publicar-o-frontend)
6. [O que falta — a ticket 15](#6-o-que-falta-a-ticket-15)
7. [Publicar o backend *(depois da 15)*](#7-publicar-o-backend-depois-da-15)
8. [Verificar que funciona](#8-verificar-que-funciona)
9. [Desmontar e controlar custo](#9-desmontar-e-controlar-custo)
10. [Checklist](#10-checklist)

---

## 1. Proteger a conta

Faça isto **antes** de qualquer outra coisa. São 30 minutos que evitam o tipo de
problema que não tem desfazer.

### 1.1 MFA na conta raiz

Entre em [console.aws.amazon.com](https://console.aws.amazon.com) com o e-mail e
a senha. Depois:

**Canto superior direito → Security credentials → Multi-factor authentication
(MFA) → Assign MFA device.**

Use um app autenticador (Google Authenticator, Authy, 1Password). Guarde os
códigos de recuperação em lugar seguro.

> **Por que isso primeiro.** Sem MFA, a senha sozinha dá acesso total. Contas de
> estudante com crédito são alvo conhecido de mineração de criptomoeda — o
> prejuízo típico é o crédito inteiro queimado em dias, e a AWS nem sempre
> estorna.

### 1.2 Alarme de gastos

**Billing and Cost Management → Budgets → Create budget.**

- Tipo: *Cost budget*
- Período: mensal
- Valor: **US$ 30**
- Alerta em 50%, 80% e 100% do valor, para o seu e-mail

Isso não impede gastos — apenas avisa. Mas avisa a tempo.

### 1.3 Um usuário IAM para o dia a dia

**IAM → Users → Create user.**

- Nome: `mapface-deploy`
- Marque *Provide user access to the AWS Management Console* se quiser entrar
  pelo console
- Permissões: anexe a política gerenciada **`AdministratorAccess`**
- Depois de criado: **Security credentials → Create access key → Command Line
  Interface (CLI)**

Guarde o `Access key ID` e o `Secret access key`. O secret aparece **uma vez
só**.

> **Por que não usar a conta raiz.** Duas razões. A raiz não tem como ser
> restringida nem revogada sem trocar a senha da conta inteira; e uma chave de
> acesso da raiz vazada é o fim da conta. A AWS recomenda **nunca** criar chave
> de acesso para a raiz — e a partir daqui você não precisa mais entrar como
> raiz.

### 1.4 Confirme a região

Este projeto assume **`us-east-1`** (Norte da Virgínia). É o padrão em
`infra/variables.tf` e o lugar mais barato para quase tudo. Se quiser trocar,
mude lá — mas note que certificado do ACM para CloudFront **só** existe em
`us-east-1`, então a troca não é trivial.

---

## 2. Preparar a máquina

Cinco ferramentas. Confira cada uma:

```bash
aws --version && terraform version && docker --version && node --version && python --version
```

O que instalar, se faltar:

| Ferramenta | Para quê | Onde |
| --- | --- | --- |
| **AWS CLI v2** | falar com a AWS | [aws.amazon.com/cli](https://aws.amazon.com/cli/) |
| **Terraform ≥ 1.9** | provisionar | [developer.hashicorp.com/terraform/install](https://developer.hashicorp.com/terraform/install) |
| **Docker Desktop** | construir a imagem do backend | [docker.com](https://www.docker.com/products/docker-desktop/) |
| **Node 18+** | compilar o Angular | [nodejs.org](https://nodejs.org) |
| **Python 3.11** | rodar a suíte do backend | já instalado no projeto |

> O Docker é o único que costuma dar trabalho no Windows: ele exige WSL2
> habilitado e virtualização ligada na BIOS. Resolva isso antes do dia da
> demonstração, não no dia.

---

## 3. Configurar as credenciais

```bash
aws configure
```

Responda com a chave do usuário `mapface-deploy` (nunca a da raiz):

```
AWS Access Key ID:     AKIA...
AWS Secret Access Key: ...
Default region name:   us-east-1
Default output format: json
```

Confirme que está falando com a conta certa:

```bash
aws sts get-caller-identity
```

Deve responder com o `Arn` terminando em `user/mapface-deploy`. Se terminar em
`:root`, você configurou a chave errada — apague e refaça.

---

## 4. Provisionar a infraestrutura

```bash
cd /d/tcc/infra && terraform init
```

Veja o que será criado **antes** de criar:

```bash
cd /d/tcc/infra && terraform plan
```

Deve listar ~19 recursos. Confira que não há nada sendo destruído (é a primeira
execução, então não deveria haver).

```bash
cd /d/tcc/infra && terraform apply
```

Digite `yes` quando pedir. **Leva de 8 a 12 minutos**, quase tudo esperando o
RDS — os outros recursos sobem em segundos, com exceção do CloudFront, que leva
alguns minutos para propagar mesmo depois de o Terraform terminar.

### O que subiu

```bash
cd /d/tcc/infra && terraform output
```

| Saída | Para quê |
| --- | --- |
| `endereco_do_site` | a URL do MapFace |
| `bucket_do_site` | destino do `aws s3 sync` |
| `id_da_distribuicao` | para invalidar o cache |
| `repositorio_do_backend` | destino do `docker push` |
| `arn_do_segredo_da_senha` | a senha do banco, no Secrets Manager |
| `database_url_sem_senha` | conferência de host, porta e usuário |

> **A senha do banco nunca passa pelo Terraform.** A AWS gera e guarda no
> Secrets Manager; daqui sai só o ARN. Se precisar dela para um `psql` de
> depuração: **Secrets Manager → o segredo → Retrieve secret value**.

---

## 5. Publicar o frontend

Três comandos. O primeiro baixa o modelo do MediaPipe se ele não estiver lá e
compila:

```bash
cd /d/tcc/frontend && npm ci && npm run build
```

Envie para o S3:

```bash
cd /d/tcc/frontend && aws s3 sync dist/frontend/browser "s3://$(cd ../infra && terraform output -raw bucket_do_site)" --delete
```

E invalide o cache do CloudFront, senão a versão antiga fica servida por até 24
horas:

```bash
cd /d/tcc/infra && aws cloudfront create-invalidation --distribution-id "$(terraform output -raw id_da_distribuicao)" --paths "/*"
```

Abra o endereço:

```bash
cd /d/tcc/infra && terraform output -raw endereco_do_site
```

**O que você vai ver:** a tela de login carrega, com a marca e o design certos,
em HTTPS. Ao tentar entrar, a requisição falha — não há backend. É o esperado
até a ticket 15 existir.

> **A coisa mais importante aqui já funciona:** o site está em **HTTPS**, e é
> isso que faz o navegador liberar a webcam. Foi por causa disso que o
> CloudFront entrou no desenho.

---

## 6. O que falta: a ticket 15

A partir daqui o tutorial descreve trabalho que ainda não foi escrito.

### O que precisa ser criado no Terraform

| Recurso | Papel |
| --- | --- |
| `aws_ecs_cluster` | onde a task roda |
| `aws_ecs_task_definition` | 0,25 vCPU, 0,5 GB, a imagem do ECR, as variáveis de ambiente |
| `aws_ecs_service` | mantém **uma** task viva (`desired_count = 1`) |
| `aws_lb` + `aws_lb_target_group` + `aws_lb_listener` | endereço estável e health check em `/health` |
| `aws_security_group` × 2 | ALB aceita do CloudFront; task aceita do ALB |
| `aws_iam_role` × 2 | execução (puxar do ECR, ler segredo, escrever log) e da task |
| `aws_secretsmanager_secret` | a `SECRET_KEY` da aplicação |
| `aws_cloudwatch_log_group` | log da task |
| *no módulo `site`* | segundo origin (o ALB) + behaviors para `/auth`, `/sessoes`, `/metodos` e `/telemetria` |

### As três decisões já tomadas que isso precisa respeitar

**Uma réplica só.** `desired_count = 1`, e um worker no uvicorn. A baseline
calibrada de cada aluno vive na memória do processo — com duas tasks, o mesmo
aluno recalibraria ao reconectar na outra.

**Os behaviors do CloudFront precisam de cache desligado** e de encaminhar todos
os headers (`AllViewerExceptHostHeader`), senão a API é cacheada e o WebSocket
não estabelece.

**A `SECRET_KEY` tem que vir do Secrets Manager.** Hoje ela tem um placeholder
como padrão em `app/config.py`. **Subir assim significa que qualquer pessoa que
leia o repositório consegue forjar um token de qualquer aluno.** É o único item
desta lista que é bloqueante por segurança, não por funcionalidade.

### Por que o ALB, e não algo mais barato

O CloudFront precisa de um endereço **estável** na origem, e uma task Fargate
com IP público não tem. O ALB é ~US$ 18/mês e é 43% da conta — não há
substituto sem trocar a arquitetura.

E ele entra como **segundo origin do mesmo CloudFront**, não como domínio
próprio: o ACM não emite certificado para nome de ALB, então HTTPS direto no
balanceador exigiria registrar e validar um domínio.

---

## 7. Publicar o backend *(depois da 15)*

Autentique o Docker no ECR:

```bash
cd /d/tcc/infra && aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin "$(terraform output -raw repositorio_do_backend | cut -d/ -f1)"
```

Construa e envie:

```bash
cd /d/tcc/backend && docker build -t mapface-backend . && docker tag mapface-backend:latest "$(cd ../infra && terraform output -raw repositorio_do_backend):latest" && docker push "$(cd ../infra && terraform output -raw repositorio_do_backend):latest"
```

Force o ECS a pegar a imagem nova:

```bash
aws ecs update-service --cluster mapface-poc --service mapface-poc-backend --force-new-deployment --region us-east-1
```

> **Na primeira vez, construa a imagem antes de criar o serviço ECS.** Um
> serviço apontando para um repositório vazio entra em ciclo de falha de deploy,
> e diagnosticar isso custa mais que inverter a ordem.

---

## 8. Verificar que funciona

Na ordem, do mais barato ao mais caro:

**A API responde:**

```bash
curl -i "$(cd /d/tcc/infra && terraform output -raw endereco_do_site)/health"
```

**O log da task não tem erro de boot:**

```bash
aws logs tail /ecs/mapface-poc --since 10m --region us-east-1
```

Procure por `Application startup complete` e por
`classificador de sonolência carregado`.

**Uma sessão completa, no navegador** — e é isto que fecha a ticket 15:

1. Abrir o endereço em HTTPS
2. Criar uma conta e entrar
3. Autorizar a webcam — **se o navegador não pedir permissão, o site não está em
   contexto seguro**, e é aí que o CloudFront estaria faltando
4. Declarar um método e iniciar a sessão
5. Esperar passar do primeiro minuto (calibração)
6. Encerrar e conferir o relatório: curva, indicadores, sinais e a leitura de
   sonolência

---

## 9. Desmontar e controlar custo

**Entre demonstrações, desmonte.** É o que mantém o crédito.

```bash
cd /d/tcc/infra && terraform destroy
```

Funciona sem passo manual: o bucket tem `force_destroy`, o ECR tem
`force_delete` e o banco tem `skip_final_snapshot`. **Os dados do banco são
perdidos** — é o desenho de uma PoC que é montada e desmontada.

Se quiser proteger o banco antes de uma demonstração importante, ligue a
proteção em `terraform.tfvars`:

```
protecao_contra_remocao = true
```

E confira o gasto de tempos em tempos:

```bash
aws ce get-cost-and-usage --time-period Start=2026-09-01,End=2026-09-30 --granularity MONTHLY --metrics UnblendedCost --region us-east-1
```

### Estimativa

| Cenário | Custo |
| --- | --- |
| Conta nova, nível gratuito | ~US$ 28/mês |
| Fora do nível gratuito | ~US$ 42/mês |
| Com `destroy` entre demonstrações | centavos |

Com US$ 100 de crédito: cerca de três meses contínuos, ou a entrega inteira com
folga larga se o ambiente subir só para testar e demonstrar.

---

## 10. Checklist

**Segurança da conta**
- [ ] MFA na conta raiz
- [ ] Budget de US$ 30 com alertas
- [ ] Usuário IAM `mapface-deploy` criado
- [ ] **Nenhuma** chave de acesso criada para a raiz
- [ ] `aws sts get-caller-identity` mostra o usuário, não `:root`

**Infraestrutura**
- [ ] `terraform apply` concluído
- [ ] Outputs anotados
- [ ] Endereço do site abre em HTTPS

**Frontend**
- [ ] `npm run build` sem erro
- [ ] `s3 sync` concluído
- [ ] Cache invalidado
- [ ] Tela de login carrega

**Backend** *(bloqueado pela ticket 15)*
- [ ] ECS, ALB, IAM e behaviors escritos no Terraform
- [ ] **`SECRET_KEY` vindo do Secrets Manager** ← bloqueante por segurança
- [ ] Imagem construída e enviada ao ECR
- [ ] `/health` respondendo pelo endereço do CloudFront
- [ ] Uma sessão de estudo completa, do login ao relatório

---

## Os três erros mais prováveis

**A webcam não é pedida.** O site não está em contexto seguro. Confira que você
abriu o endereço do **CloudFront** (`https://...cloudfront.net`) e não o do
bucket S3.

**Login falha com erro de rede.** É o caso esperado antes da ticket 15 — não há
backend. Depois dela, confira os behaviors do CloudFront: se `/auth` não estiver
encaminhado para o ALB, o CloudFront tenta servir do S3 e devolve 403.

**A tela abre a versão antiga depois do deploy.** Faltou a invalidação do
CloudFront. Rode o comando do passo 5 e espere de 2 a 5 minutos.
