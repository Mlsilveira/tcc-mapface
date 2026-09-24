terraform {
  required_version = ">= 1.9"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  # O estado fica **local** por enquanto, e isso é uma limitação conhecida, não
  # um descuido: com três pessoas no time, o `terraform.tfstate` no disco de
  # quem aplicou é a única fonte de verdade, e duas aplicações simultâneas se
  # sobrescrevem sem aviso.
  #
  # A correção é o backend S3 abaixo, que precisa de um bucket já existente —
  # e criá-lo com este mesmo Terraform seria o ovo antes da galinha. Do
  # Terraform 1.10 em diante o bloqueio é nativo do S3 (`use_lockfile`), sem
  # precisar de tabela no DynamoDB como antigamente.
  #
  # backend "s3" {
  #   bucket       = "mapface-tfstate"
  #   key          = "poc/terraform.tfstate"
  #   region       = "us-east-1"
  #   encrypt      = true
  #   use_lockfile = true
  # }
}
