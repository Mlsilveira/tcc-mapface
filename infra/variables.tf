variable "projeto" {
  description = "Prefixo de todos os nomes de recurso. Troque para subir um segundo ambiente na mesma conta."
  type        = string
  default     = "mapface"

  validation {
    # Vira nome de bucket S3, que é global e só aceita minúsculas, dígitos e
    # hífen. Falhar aqui é melhor que falhar no meio do apply, com metade da
    # infraestrutura de pé.
    condition     = can(regex("^[a-z0-9][a-z0-9-]{1,30}[a-z0-9]$", var.projeto))
    error_message = "O prefixo precisa ter de 3 a 32 caracteres, só minúsculas, dígitos e hífen, começando e terminando com letra ou dígito."
  }
}

variable "ambiente" {
  description = "Ambiente lógico. Entra nos nomes e nas tags."
  type        = string
  default     = "poc"
}

variable "regiao" {
  description = "Região da AWS."
  type        = string
  default     = "us-east-1"
}

variable "cidr_da_vpc" {
  description = "Faixa da VPC. /16 dá espaço de sobra para as quatro sub-redes."
  type        = string
  default     = "10.20.0.0/16"
}

variable "versao_do_postgres" {
  description = "Família de versão do PostgreSQL. Só a maior: a AWS escolhe a menor mais recente."
  type        = string
  default     = "17"
}

variable "classe_do_banco" {
  description = "Classe da instância RDS. `db.t4g.micro` é a elegível ao nível gratuito."
  type        = string
  default     = "db.t4g.micro"
}

variable "armazenamento_do_banco_gb" {
  description = "Armazenamento inicial do RDS, em GB. O mínimo do gp3 para PostgreSQL é 20."
  type        = number
  default     = 20

  validation {
    condition     = var.armazenamento_do_banco_gb >= 20
    error_message = "O gp3 no PostgreSQL não aceita menos de 20 GB."
  }
}

variable "retencao_de_backup_dias" {
  description = "Dias de retenção do backup automático do RDS. Zero desliga os backups."
  type        = number
  default     = 7
}

variable "protecao_contra_remocao" {
  description = <<-TEXTO
    Impede `terraform destroy` de apagar o banco.

    Fica `false` por padrão **de propósito**: numa PoC que é montada e desmontada
    para demonstração, um banco que se recusa a morrer deixa custo rodando e
    obriga a ir no console apagar na mão — exatamente o passo manual que a
    ticket 14 existe para eliminar. Ligue antes de qualquer coisa que valha
    guardar.
  TEXTO
  type        = bool
  default     = false
}

variable "tags_extras" {
  description = "Tags adicionais aplicadas a tudo que aceita tag."
  type        = map(string)
  default     = {}
}
