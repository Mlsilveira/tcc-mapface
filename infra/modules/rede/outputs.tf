output "id_da_vpc" {
  description = "Id da VPC."
  value       = aws_vpc.esta.id
}

output "subredes_publicas" {
  description = "Sub-redes com rota para a internet. É onde o serviço ECS da ticket 15 vai rodar."
  value       = aws_subnet.publica[*].id
}

output "subredes_privadas" {
  description = "Sub-redes sem rota de saída. É onde o banco vive."
  value       = aws_subnet.privada[*].id
}
