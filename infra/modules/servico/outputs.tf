output "dominio_do_balanceador" {
  description = "Nome DNS do ALB. É o que entra como segundo origin do CloudFront."
  value       = aws_lb.backend.dns_name
}

output "id_do_security_group_da_task" {
  description = "Security group da task, para o banco autorizar só ela."
  value       = aws_security_group.task.id
}

output "nome_do_cluster" {
  description = "Cluster ECS, para o `aws ecs update-service` do deploy."
  value       = aws_ecs_cluster.este.name
}

output "nome_do_servico" {
  description = "Serviço ECS, para forçar um novo deploy depois do `docker push`."
  value       = aws_ecs_service.backend.name
}

output "grupo_de_log" {
  description = "Grupo do CloudWatch onde a task escreve, para o `aws logs tail`."
  value       = aws_cloudwatch_log_group.backend.name
}

output "arn_do_segredo_da_chave" {
  description = "Segredo com a SECRET_KEY, para rotacionar fora do Terraform."
  value       = aws_secretsmanager_secret.chave.arn
}
