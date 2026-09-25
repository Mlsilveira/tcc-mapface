/**
 * Infraestrutura da PoC do MapFace (ticket 14).
 *
 * Três módulos, mais a rede que o banco exige para existir:
 *
 *   rede      VPC, sub-redes e rota de saída
 *   site      S3 + CloudFront para o Angular compilado
 *   registro  ECR para a imagem do FastAPI
 *   banco     RDS PostgreSQL, criptografado em repouso
 *
 * A ticket 15 acrescentou o módulo `servico` — ECS Fargate, ALB, IAM e o
 * segredo da aplicação — e ligou o backend ao CloudFront como segundo origin.
 *
 * **A imagem precisa existir no ECR antes do primeiro `apply` completo.** Um
 * serviço apontando para repositório vazio entra em ciclo permanente de falha
 * de deploy. Para quebrar o ovo e a galinha:
 *
 *     terraform apply -target=module.rede -target=module.registro
 *     ... docker build && docker push ...
 *     terraform apply
 *
 * Alternativa sem `-target`: subir com `replicas = 0`, publicar a imagem e
 * voltar para 1.
 */

provider "aws" {
  region = var.regiao

  default_tags {
    tags = merge(
      {
        Projeto   = var.projeto
        Ambiente  = var.ambiente
        Terraform = "true"
      },
      var.tags_extras,
    )
  }
}

locals {
  nome = "${var.projeto}-${var.ambiente}"
}

module "rede" {
  source = "./modules/rede"

  nome        = local.nome
  cidr_da_vpc = var.cidr_da_vpc
}

module "site" {
  source = "./modules/site"

  nome = local.nome

  # É isto que faz site e API compartilharem domínio — e, com isso, elimina o
  # CORS, viabiliza o `wss` e deixa o frontend sem nenhuma URL de ambiente.
  dominio_do_backend = var.publicar_backend ? module.servico[0].dominio_do_balanceador : null
}

module "registro" {
  source = "./modules/registro"

  nome = local.nome
}

module "banco" {
  source = "./modules/banco"

  nome              = local.nome
  id_da_vpc         = module.rede.id_da_vpc
  subredes_privadas = module.rede.subredes_privadas
  cidr_da_vpc       = var.cidr_da_vpc
  # Com serviço, a porta 5432 deixa de aceitar a VPC inteira e passa a aceitar
  # só o security group da task — a regra estreita está logo abaixo.
  abrir_para_a_vpc        = !var.publicar_backend
  versao_do_postgres      = var.versao_do_postgres
  classe_da_instancia     = var.classe_do_banco
  armazenamento_gb        = var.armazenamento_do_banco_gb
  retencao_de_backup_dias = var.retencao_de_backup_dias
  protecao_contra_remocao = var.protecao_contra_remocao
}

module "servico" {
  source = "./modules/servico"
  count  = var.publicar_backend ? 1 : 0

  nome              = local.nome
  id_da_vpc         = module.rede.id_da_vpc
  subredes_publicas = module.rede.subredes_publicas

  url_do_repositorio = module.registro.url_do_repositorio
  tag_da_imagem      = var.tag_da_imagem

  endereco_do_banco       = module.banco.endereco
  porta_do_banco          = module.banco.porta
  nome_do_banco           = module.banco.nome_do_banco
  usuario_do_banco        = module.banco.usuario
  arn_do_segredo_do_banco = module.banco.arn_do_segredo_da_senha

  replicas = var.replicas_do_backend
}

# A regra estreita do banco mora **na raiz**, e não dentro de um dos módulos,
# porque ela depende dos dois: o security group é do `banco`, e quem ela
# autoriza é do `servico`. Colocá-la em qualquer um deles criaria dependência
# circular entre módulos.
resource "aws_vpc_security_group_ingress_rule" "banco_aceita_a_task" {
  count = var.publicar_backend ? 1 : 0

  security_group_id = module.banco.id_do_security_group
  description       = "PostgreSQL apenas a partir da task do backend"

  referenced_security_group_id = module.servico[0].id_do_security_group_da_task
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}
