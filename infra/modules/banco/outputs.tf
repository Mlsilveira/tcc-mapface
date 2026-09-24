output "endereco" {
  description = "Host do banco, resolvível de dentro da VPC."
  value       = aws_db_instance.banco.address
}

output "porta" {
  description = "Porta do PostgreSQL."
  value       = aws_db_instance.banco.port
}

output "nome_do_banco" {
  description = "Banco criado dentro da instância."
  value       = aws_db_instance.banco.db_name
}

output "usuario" {
  description = "Usuário mestre."
  value       = aws_db_instance.banco.username
}

output "arn_do_segredo_da_senha" {
  description = <<-TEXTO
    ARN do segredo no Secrets Manager onde a AWS guarda a senha do banco.

    É isto que a task do ECS vai ler na ticket 15, via `secrets` na task
    definition — a senha vai do Secrets Manager direto para a variável de
    ambiente do contêiner, sem passar por ninguém no meio.
  TEXTO
  value       = try(aws_db_instance.banco.master_user_secret[0].secret_arn, null)
}

output "id_do_security_group" {
  description = "Security group do banco. A ticket 15 troca a regra de CIDR por referência ao grupo da task."
  value       = aws_security_group.banco.id
}
