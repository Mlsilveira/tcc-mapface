variable "nome" {
  description = "Prefixo dos nomes dos recursos."
  type        = string
}

variable "id_da_vpc" {
  description = "VPC onde o banco vive."
  type        = string
}

variable "subredes_privadas" {
  description = "Sub-redes do grupo do RDS. A AWS exige pelo menos duas, em AZs diferentes."
  type        = list(string)

  validation {
    condition     = length(var.subredes_privadas) >= 2
    error_message = "O grupo de sub-redes do RDS precisa de pelo menos duas sub-redes, em zonas diferentes."
  }
}

variable "cidr_da_vpc" {
  description = "Faixa da VPC, usada na regra de entrada da porta 5432."
  type        = string
}

variable "versao_do_postgres" {
  description = "Família de versão do PostgreSQL."
  type        = string
}

variable "classe_da_instancia" {
  description = "Classe da instância RDS."
  type        = string
}

variable "armazenamento_gb" {
  description = "Armazenamento inicial, em GB."
  type        = number
}

variable "retencao_de_backup_dias" {
  description = "Dias de retenção do backup automático."
  type        = number
}

variable "protecao_contra_remocao" {
  description = "Impede que o `destroy` apague o banco."
  type        = bool
}
