# Infraestrutura (ticket 14)

Toda a infraestrutura AWS da PoC do MapFace, em Terraform. Um `terraform apply`
levanta rede, hospedagem do frontend, registro de imagens e banco — sem nenhum
passo no console.

```
infra/
  versions.tf          versão do Terraform, do provider e a nota sobre o estado
  variables.tf         tudo que se ajusta, com os padrões da PoC
  main.tf              provider, tags padrão e a ligação entre os módulos
  outputs.tf           o que o deploy da ticket 15 vai precisar saber
  modules/
    rede/              VPC, sub-redes, internet gateway
    site/              S3 privado + CloudFront (o Angular compilado)
    registro/          ECR (a imagem do FastAPI)
    banco/             RDS PostgreSQL criptografado
```

## O que sobe

| Recurso | Para quê |
|---|---|
| VPC /16, 2 sub-redes públicas e 2 privadas em 2 AZs | Rede própria, reproduzível em qualquer conta |
| Bucket S3 privado, versionado, cifrado | Onde vive o `dist/` do Angular |
| Distribuição CloudFront com OAC | Serve o site **em HTTPS**, sem abrir o bucket |
| Repositório ECR com varredura e expiração | Onde vive a imagem do backend |
| RDS PostgreSQL 17, `db.t4g.micro`, AES-256 | O banco, inalcançável pela internet |

O **ECS Fargate não está aqui de propósito**: é critério da ticket 15, e
provisionar um serviço antes de existir imagem publicada criaria um serviço que
nasce em falha permanente de deploy. O que ele vai precisar — sub-redes, o
endereço do banco, o ARN do segredo da senha, a URL do repositório — já sai nos
outputs.

## Por que CloudFront, e não só o S3

O navegador só libera `getUserMedia` em **contexto seguro**, e o endpoint de
site estático do S3 serve **apenas HTTP**. Publicar o Angular direto no S3
entregaria uma aplicação que carrega, faz login, deixa iniciar a sessão de
estudo e falha na única coisa que ela existe para fazer: acender a webcam.

A consequência disso recai sobre a ticket 15: com o site em HTTPS, o WebSocket
de telemetria tem que ser `wss://`. Página segura falando `ws://` é conteúdo
misto, e o navegador bloqueia sem perguntar — então o backend vai precisar de
TLS, na prática um ALB com certificado do ACM.

## Pré-requisitos

- Terraform **1.9 ou mais novo**
- Credenciais AWS no ambiente (`aws configure`, `AWS_PROFILE` ou variáveis)
- Permissão para criar VPC, S3, CloudFront, ECR, RDS e segredos no Secrets Manager

## Como usar

```bash
cd infra
cp terraform.tfvars.example terraform.tfvars   # opcional: os padrões já servem
terraform init
terraform plan
terraform apply
```

O `apply` do RDS é o passo demorado — de 5 a 10 minutos. O resto sobe em
segundos, com a exceção da distribuição do CloudFront, que leva alguns minutos
para propagar mesmo depois de o Terraform terminar.

Para desmontar:

```bash
terraform destroy
```

O `destroy` funciona sem passo manual: o bucket tem `force_destroy`, o ECR tem
`force_delete` e o banco tem `skip_final_snapshot`. Se `protecao_contra_remocao`
estiver ligada, o banco recusa — ligue-a só quando houver dado que valha guardar.

## Depois do apply

Os outputs dizem o que fazer com o que subiu:

```bash
terraform output endereco_do_site        # a URL que abre o MapFace
terraform output bucket_do_site          # destino do aws s3 sync
terraform output repositorio_do_backend  # destino do docker push
```

O deploy em si — build do Angular, `aws s3 sync`, invalidação do cache,
`docker push`, serviço no ECS — é a ticket 15.

## Senha do banco

O Terraform **nunca vê a senha**. `manage_master_user_password = true` faz a AWS
gerar e guardar a credencial no Secrets Manager; daqui sai só o ARN do segredo,
em `arn_do_segredo_da_senha`, que é o que a task definition do ECS vai ler.

A alternativa comum — `random_password` alimentando o campo `password` — grava a
senha **em texto claro no arquivo de estado**. Marcar a variável como
`sensitive` esconde a senha do log do `apply` e não muda nada disso.

## Estado

O estado fica **local**, e isso é limitação conhecida: com três pessoas no time,
o `terraform.tfstate` no disco de quem aplicou é a única fonte de verdade, e
duas aplicações simultâneas se sobrescrevem sem aviso. Na prática da PoC, **uma
pessoa aplica**. A correção está comentada em `versions.tf` — um backend S3, que
precisa de um bucket criado fora deste código para não virar o ovo antes da
galinha.

O `.terraform.lock.hcl` **é versionado**: é ele que garante que todo mundo use a
mesma versão do provider.

## Custo

`db.t4g.micro` com 20 GB é elegível ao nível gratuito nos primeiros 12 meses da
conta; fora dele, a instância é a maior parte da conta. S3, ECR e CloudFront, no
volume de uma PoC, ficam em centavos. **Não há NAT Gateway** — ele custaria, por
hora, mais que todo o resto junto, e nada aqui precisa dele.

Entre demonstrações, `terraform destroy` zera o custo, e um `apply` reconstrói
tudo. É por isso que `protecao_contra_remocao` vem desligada.
