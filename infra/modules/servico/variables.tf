variable "nome" {
  description = "Prefixo dos nomes dos recursos."
  type        = string
}

variable "id_da_vpc" {
  description = "VPC onde o serviço e o balanceador vivem."
  type        = string
}

variable "subredes_publicas" {
  description = "Sub-redes do balanceador e da task. Precisam de rota para a internet."
  type        = list(string)

  validation {
    condition     = length(var.subredes_publicas) >= 2
    error_message = "O ALB exige pelo menos duas sub-redes, em zonas diferentes."
  }
}

variable "url_do_repositorio" {
  description = "Repositório ECR de onde a imagem é baixada."
  type        = string
}

variable "tag_da_imagem" {
  description = "Tag da imagem a rodar."
  type        = string
  default     = "latest"
}

variable "endereco_do_banco" {
  description = "Host do RDS."
  type        = string
}

variable "porta_do_banco" {
  description = "Porta do RDS."
  type        = number
  default     = 5432
}

variable "nome_do_banco" {
  description = "Banco dentro da instância."
  type        = string
  default     = "mapface"
}

variable "usuario_do_banco" {
  description = "Usuário do banco."
  type        = string
  default     = "mapface"
}

variable "arn_do_segredo_do_banco" {
  description = "Segredo do Secrets Manager com a senha que a AWS gerou para o RDS."
  type        = string
}

variable "porta" {
  description = "Porta em que o uvicorn escuta dentro do contêiner."
  type        = number
  default     = 8000
}

variable "cpu" {
  description = "Unidades de CPU da task. 256 = 0,25 vCPU."
  type        = number
  default     = 256
}

variable "memoria" {
  description = "Memória da task, em MiB. O par válido de 256 CPU começa em 512."
  type        = number
  default     = 512
}

variable "replicas" {
  description = <<-TEXTO
    Quantas tasks rodam.

    **Um, e mudar isto quebra a calibração.** A baseline de cada aluno vive na
    memória do processo (`analista.RegistroDeAnalistas`); com duas tasks e sem
    sessão pegajosa, o mesmo aluno reconectando cai na outra e recalibra do
    zero — perdendo 60 segundos no meio da sessão de estudo. A variável existe
    para poder ir a **zero** e parar de pagar Fargate sem destruir o resto.
  TEXTO
  type        = number
  default     = 1

  validation {
    condition     = var.replicas <= 1
    error_message = "Mais de uma réplica quebra a calibração por sessão; ver a nota desta variável."
  }
}

variable "retencao_de_log_dias" {
  description = "Dias de retenção do log da task no CloudWatch."
  type        = number
  default     = 7
}
