# Tutorial: subir o MapFace para a AWS

Do momento em que você recebe o acesso à conta até a aplicação no ar.

> ## Estado deste tutorial
>
> **A ticket 15 foi escrita.** O Terraform provisiona a infraestrutura inteira —
> rede, S3 + CloudFront, ECR, RDS, ECS Fargate, ALB, IAM e os segredos —, e os
> *behaviors* do CloudFront encaminham a API pelo mesmo domínio do site.
>
> Tudo aqui está validado com `terraform fmt -check` e `terraform validate`,
> mas **nunca rodou contra uma conta AWS de verdade**. O primeiro `apply` é o
> primeiro teste real; os pontos onde ele tem mais chance de tropeçar estão em
> [Os erros mais prováveis](#os-erros-mais-prováveis).

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
6. [Publicar a imagem do backend](#6-publicar-a-imagem-do-backend)
7. [Ligar o backend](#7-ligar-o-backend)
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

Cinco ferramentas. Esta seção é para **Windows 11**, que é onde o projeto foi
desenvolvido.

### 2.0 Onde digitar os comandos

Os comandos de **instalação** precisam de privilégio de administrador:

1. Tecla **Windows**
2. Digite `powershell`
3. Botão **direito** em *Windows PowerShell* → **Executar como administrador**
4. Confirme o aviso do Windows

A janela que abre — fundo azul, título "Administrador" — é onde vão os comandos
da seção 2. Os comandos do resto do tutorial (`terraform`, `aws`, `npm`) rodam
num PowerShell **normal**, sem administrador.

> **A pegadinha que pega todo mundo.** Depois de instalar um programa, o
> terminal que já estava aberto **não o enxerga**. O `PATH` é lido uma vez, na
> abertura. Se um comando recém-instalado der "não é reconhecido", feche a
> janela e abra outra **antes** de desconfiar da instalação.

### 2.1 O que já costuma estar lá

```powershell
node --version; npm --version; python --version; git --version
```

- **Node 18+** — compila o Angular. Se faltar: [nodejs.org](https://nodejs.org)
- **Python 3.11+** — roda a suíte do backend
- **Git** — já está, se você clonou o projeto

### 2.2 AWS CLI e Terraform

A forma curta, com o gerenciador de pacotes que já vem no Windows 11:

```powershell
winget install --id Amazon.AWSCLI --accept-source-agreements --accept-package-agreements
```

```powershell
winget install --id Hashicorp.Terraform --accept-source-agreements --accept-package-agreements
```

Se o `winget` não existir ou falhar, baixe na mão:

| Ferramenta | Link | Observação |
| --- | --- | --- |
| **AWS CLI v2** | [awscli.amazonaws.com/AWSCLIV2.msi](https://awscli.amazonaws.com/AWSCLIV2.msi) | instalador comum, duplo clique |
| **Terraform ≥ 1.9** | [developer.hashicorp.com/terraform/install](https://developer.hashicorp.com/terraform/install) | vem em ZIP: extraia em `C:\terraform` e acrescente a pasta ao `PATH` |

### 2.3 Docker — três etapas, e uma delas reinicia o computador

O Docker constrói a imagem do backend. No Windows ele roda sobre o **WSL2**, e é
por isso que esta é a instalação mais trabalhosa das cinco.

**Antes de começar**, confirme que a virtualização está ligada na BIOS:

```powershell
(Get-CimInstance Win32_ComputerSystem).HypervisorPresent
```

Se responder `False`, entre na BIOS e habilite *Intel VT-x* ou *AMD-V*. Sem
isso, nada do resto desta seção funciona.

**Etapa 1 — instalar o WSL2.** Na janela de administrador:

```powershell
wsl --install
```

Leva uns 5 minutos e **pede para reiniciar**. Reinicie de verdade — o Docker não
instala sem isso.

Depois do reboot o Windows abre sozinho uma janela do Ubuntu pedindo usuário e
senha. **Pode fechar.** Você não precisa do Ubuntu, só do motor que ele trouxe.

**Etapa 2 — instalar o Docker Desktop.** Abra o PowerShell como administrador de
novo:

```powershell
winget install --id Docker.DockerDesktop --accept-source-agreements --accept-package-agreements
```

**Etapa 3 — abrir o Docker uma vez, na mão.** É o passo mais esquecido: o Docker
Desktop **não liga sozinho** depois de instalado.

1. Tecla **Windows** → `Docker Desktop` → Enter
2. Aceite os termos — é gratuito para uso pessoal e acadêmico
3. Pode pular o login
4. **Espere a baleia no canto inferior esquerdo ficar verde**, com "Engine
   running"

Só depois disso o comando `docker` responde.

### 2.3.1 Uma armadilha do Git Bash

O projeto é desenvolvido no Windows, e muita gente roda os comandos no **Git
Bash** por causa da sintaxe POSIX. Ele tem um comportamento que estraga
comandos da AWS sem avisar:

> Quando um argumento **começa com `/`**, o Git Bash assume que é um caminho
> POSIX e o traduz para Windows antes de entregar a um programa nativo. Para um
> caminho de arquivo isso salva o dia. Para o nome de um log group — que por
> acaso começa com `/` e não é caminho nenhum — ele destrói o valor:
>
> ```
> você escreve:   /ecs/mapface-poc
> o aws.exe recebe:  C:/Program Files/Git/ecs/mapface-poc
> ```
>
> O erro que aparece é `InvalidParameterException ... failed to satisfy
> constraint`, e não menciona o Git Bash em lugar nenhum.

**Duas saídas:** prefixe com `MSYS_NO_PATHCONV=1`, ou rode esse comando no
PowerShell, que não faz a tradução. Os comandos deste tutorial que precisam
disso já vêm com o prefixo.

Só afeta argumento que começa com `/`. ARNs, nomes de bucket, ids de
distribuição e tags de imagem não começam, e passam intactos.

### 2.4 Conferir tudo

Feche as janelas abertas, abra um PowerShell **normal** e rode:

```powershell
aws --version; terraform version; docker --version; node --version; python --version
```

As cinco precisam responder com um número de versão. Se alguma reclamar, volte
para a subseção dela — e lembre de abrir um terminal novo antes.

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

**Suba primeiro sem o backend.** Um serviço ECS apontando para um repositório
ECR vazio entra em ciclo permanente de falha de deploy, e a imagem ainda não
existe:

```bash
cd /d/tcc/infra && terraform apply -var publicar_backend=false
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
em HTTPS. Ao tentar entrar, a requisição ainda falha — o backend só entra no
passo 7. É o esperado nesta altura.

> **A coisa mais importante aqui já funciona:** o site está em **HTTPS**, e é
> isso que faz o navegador liberar a webcam. Foi por causa disso que o
> CloudFront entrou no desenho.

---

## 6. Publicar a imagem do backend

Autentique o Docker no ECR:

```bash
cd /d/tcc/infra && aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin "$(terraform output -raw repositorio_do_backend | cut -d/ -f1)"
```

Construa e envie:

```bash
cd /d/tcc/backend && docker build -t mapface-backend . && docker tag mapface-backend:latest "$(cd ../infra && terraform output -raw repositorio_do_backend):latest" && docker push "$(cd ../infra && terraform output -raw repositorio_do_backend):latest"
```

A imagem tem ~400 MB — scikit-learn, numpy, scipy e pandas somam a maior parte.
O primeiro envio leva alguns minutos; os seguintes reaproveitam as camadas.

---

## 7. Ligar o backend

Agora que existe imagem, suba o resto:

```bash
cd /d/tcc/infra && terraform apply
```

Isto cria o cluster ECS, a task, o serviço, o ALB, as roles de IAM e o segredo
da aplicação — e acrescenta o backend como segundo origin do CloudFront, com os
*behaviors* de `/auth`, `/sessoes`, `/metodos`, `/telemetria` e `/health`.

**Leva de 5 a 8 minutos**, quase tudo esperando o CloudFront propagar a
distribuição atualizada.

Três coisas acontecem aqui, e vale saber:

- A `SECRET_KEY` é gerada e guardada no Secrets Manager. **Ela não aparece em
  lugar nenhum que você precise copiar** — o ECS a injeta direto no contêiner.
- O banco **fecha**: a porta 5432 deixa de aceitar a VPC inteira e passa a
  aceitar só o security group da task.
- O ALB nasce público mas só atende a lista de prefixos do CloudFront. Acessar
  o DNS dele direto do seu navegador dá timeout, e isso é o comportamento
  correto.

### Nos deploys seguintes

Depois de um `docker push`, force o ECS a pegar a imagem nova:

```bash
cd /d/tcc/infra && aws ecs update-service --cluster "$(terraform output -raw cluster_do_backend)" --service "$(terraform output -raw servico_do_backend)" --force-new-deployment --region us-east-1
```

---

## 8. Verificar que funciona

Na ordem, do mais barato ao mais caro:

**A API responde:**

```bash
curl -i "$(cd /d/tcc/infra && terraform output -raw endereco_do_site)/health"
```

**O log da task não tem erro de boot:**

```bash
MSYS_NO_PATHCONV=1 aws logs tail /ecs/mapface-poc --since 10m --region us-east-1
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

## 8.1 Olhar dentro do banco

O RDS é **inalcançável do seu notebook**, e isso é o desenho: sub-rede sem rota
para a internet, `publicly_accessible = false`, e security group que só aceita o
grupo da task. Um banco com dados comportamentais de estudantes não deve estar a
um cliente SQL de distância de qualquer mesa.

O caminho é perguntar **de dentro**: uma task avulsa, com a mesma imagem, as
mesmas credenciais e a mesma rede do backend.

```bash
cd /d/tcc/infra && aws ecs run-task --cluster "$(terraform output -raw cluster_do_backend)" --task-definition mapface-poc-backend --launch-type FARGATE --network-configuration "awsvpcConfiguration={subnets=[$(terraform output -json subredes_publicas | tr -d '[]
 "' )],securityGroups=[$(aws ec2 describe-security-groups --filters Name=group-name,Values=mapface-poc-task --region us-east-1 --query 'SecurityGroups[0].GroupId' --output text)],assignPublicIp=ENABLED}" --overrides '{"containerOverrides":[{"name":"backend","command":["python","-m","scripts.inspecionar_banco"]}]}' --region us-east-1 --query 'tasks[0].taskArn' --output text
```

A task leva ~40 segundos. O resultado sai no CloudWatch, no fluxo
`backend/backend/<id-da-task>`:

```bash
cd /d/tcc/infra && MSYS_NO_PATHCONV=1 aws logs tail "$(terraform output -raw grupo_de_log_do_backend)" --since 5m --region us-east-1
```

`scripts/inspecionar_banco.py` mostra alunos, sessões, pontos da série, blocos e
resumos — **sem senha nem hash**. Hash é inútil para diagnóstico e perigoso num
log que fica guardado.

> **O script só existe na imagem a partir do build em que ele entrou.** Se o seu
> `docker push` é anterior a ele, use um `python -c` com a consulta direto no
> `command`, ou reconstrua a imagem.

**As alternativas, e por que não são o caminho padrão.** Abrir o banco para o
seu IP (`publicly_accessible = true` mais uma regra de ingress) funciona e
permite usar DBeaver — mas é mudança de postura de segurança que alguém precisa
lembrar de reverter, e "alguém precisa lembrar" é como furos nascem. Habilitar
`enable_execute_command` dá um shell interativo dentro da task, é melhor para
depurar de verdade, e custa uma permissão de SSM na role da task mais um novo
deploy.

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

**Backend**
- [x] ECS, ALB, IAM e behaviors escritos e validados no Terraform
- [x] `SECRET_KEY` vindo do Secrets Manager
- [ ] Imagem construída e enviada ao ECR
- [ ] `terraform apply` completo, com `publicar_backend` no padrão
- [ ] `/health` respondendo pelo endereço do CloudFront
- [ ] Uma sessão de estudo completa, do login ao relatório

---

## Os erros mais prováveis

> Nada do que está escrito aqui jamais rodou contra uma conta AWS de verdade —
> o Terraform está validado, não aplicado. Estes são os pontos onde o primeiro
> `apply` tem mais chance de tropeçar.

**A task sobe e morre em ciclo.** Veja o log com
`MSYS_NO_PATHCONV=1 aws logs tail "$(terraform output -raw grupo_de_log_do_backend)" --since 10m`.
As três causas prováveis, em ordem: a imagem não existe no ECR; o banco ainda
não aceita a task (confira que o `apply` completo rodou, e não o
`-var publicar_backend=false`); ou a `DATABASE_PASSWORD` chegou como o JSON
inteiro em vez da senha — o que significa que o sufixo `:password::` do
`valueFrom` não foi aplicado.

**`terraform apply` falha dizendo que o nome do segredo já existe.** É a janela
de recuperação do Secrets Manager. O módulo usa `recovery_window_in_days = 0`
justamente para evitar isso, mas se o segredo foi criado antes dessa
configuração, espere ou apague com
`aws secretsmanager delete-secret --force-delete-without-recovery`.

**O ALB fica com o target *unhealthy*.** O health check bate em `/health` e
espera 200. Se a task está de pé e o check falha, quase sempre é o security
group: a task precisa aceitar a porta 8000 vinda do grupo do ALB.



**A webcam não é pedida.** O site não está em contexto seguro. Confira que você
abriu o endereço do **CloudFront** (`https://...cloudfront.net`) e não o do
bucket S3.

**Login falha com erro de rede.** Se o backend já subiu, confira os *behaviors*
do CloudFront: quando `/auth` não está encaminhado para o ALB, a distribuição
tenta servir do S3 e devolve 403. Lembre também que a propagação do CloudFront
leva alguns minutos depois do `apply`.

**A tela abre a versão antiga depois do deploy.** Faltou a invalidação do
CloudFront. Rode o comando do passo 5 e espere de 2 a 5 minutos.
