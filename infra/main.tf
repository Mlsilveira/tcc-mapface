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
 * O ECS Fargate **não** está aqui. Ele é critério da ticket 15, e provisionar
 * um serviço antes de existir imagem publicada no ECR criaria um serviço que
 * nasce em falha permanente de deploy. Os módulos abaixo já entregam o que ele
 * vai precisar — sub-redes públicas, o endereço do banco e o do repositório.
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
}

module "registro" {
  source = "./modules/registro"

  nome = local.nome
}

module "banco" {
  source = "./modules/banco"

  nome                    = local.nome
  id_da_vpc               = module.rede.id_da_vpc
  subredes_privadas       = module.rede.subredes_privadas
  cidr_da_vpc             = var.cidr_da_vpc
  versao_do_postgres      = var.versao_do_postgres
  classe_da_instancia     = var.classe_do_banco
  armazenamento_gb        = var.armazenamento_do_banco_gb
  retencao_de_backup_dias = var.retencao_de_backup_dias
  protecao_contra_remocao = var.protecao_contra_remocao
}
