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

variable "abrir_para_a_vpc" {
  description = <<-TEXTO
    Libera a porta 5432 para toda a faixa da VPC.

    Fica `true` enquanto não existe serviço: sem nenhuma regra, um banco
    recém-criado é inalcançável até por quem foi criá-lo, e o diagnóstico disso
    custa caro. Quando a ticket 15 entra, a raiz passa `false` e cria no lugar
    uma regra que referencia **o security group da task** — aí só o backend
    entra, e não qualquer coisa que venha a existir na VPC.
  TEXTO
  type        = bool
  default     = true
}

variable "protecao_contra_remocao" {
  description = "Impede que o `destroy` apague o banco."
  type        = bool
}
