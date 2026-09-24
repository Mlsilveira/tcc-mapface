output "endereco_do_site" {
  description = "URL da aplicação, em HTTPS. É o endereço que abre o MapFace."
  value       = module.site.endereco_do_site
}

output "bucket_do_site" {
  description = "Destino do `aws s3 sync` com o build do Angular."
  value       = module.site.bucket
}

output "id_da_distribuicao" {
  description = "Distribuição do CloudFront, para invalidar o cache depois do deploy."
  value       = module.site.id_da_distribuicao
}

output "repositorio_do_backend" {
  description = "Destino do `docker push` da imagem do FastAPI."
  value       = module.registro.url_do_repositorio
}

output "database_url_sem_senha" {
  description = <<-TEXTO
    `DATABASE_URL` montada, **sem a senha**, para conferência.

    A senha vive no Secrets Manager e entra só no contêiner, em tempo de
    execução. Esta saída existe para o time ver que host, porta, banco e usuário
    batem — não para ser copiada para um `.env`.
  TEXTO
  value       = "postgresql+psycopg2://${module.banco.usuario}:SENHA@${module.banco.endereco}:${module.banco.porta}/${module.banco.nome_do_banco}"
}

output "arn_do_segredo_da_senha" {
  description = "Segredo com a senha do banco, para a task definition da ticket 15."
  value       = module.banco.arn_do_segredo_da_senha
}

output "subredes_publicas" {
  description = "Onde o serviço ECS da ticket 15 vai rodar."
  value       = module.rede.subredes_publicas
}

output "id_do_security_group_do_banco" {
  description = "Security group do banco, para a ticket 15 restringir o acesso ao grupo da task."
  value       = module.banco.id_do_security_group
}
