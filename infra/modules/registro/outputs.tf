output "url_do_repositorio" {
  description = "Endereço do repositório. É o destino do `docker push`."
  value       = aws_ecr_repository.backend.repository_url
}

output "nome_do_repositorio" {
  description = "Nome do repositório, para o `aws ecr` e para a task definition da ticket 15."
  value       = aws_ecr_repository.backend.name
}
