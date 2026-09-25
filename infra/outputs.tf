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
  value       = "postgresql+psycopg://${module.banco.usuario}:SENHA@${module.banco.endereco}:${module.banco.porta}/${module.banco.nome_do_banco}"
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

# --- Ticket 15 -------------------------------------------------------------

output "cluster_do_backend" {
  description = "Cluster ECS, para o `aws ecs update-service` depois do `docker push`."
  value       = try(module.servico[0].nome_do_cluster, null)
}

output "servico_do_backend" {
  description = "Serviço ECS, para forçar um novo deploy."
  value       = try(module.servico[0].nome_do_servico, null)
}

output "grupo_de_log_do_backend" {
  description = "Grupo do CloudWatch da task, para o `aws logs tail`."
  value       = try(module.servico[0].grupo_de_log, null)
}

output "arn_do_segredo_da_chave" {
  description = <<-TEXTO
    Segredo com a `SECRET_KEY` da aplicação.

    Para rotacionar: `aws secretsmanager put-secret-value` neste ARN e um novo
    deploy do serviço. Trocar a chave **desloga todo mundo** — os tokens em
    circulação deixam de validar —, então não é operação de rotina.
  TEXTO
  value       = try(module.servico[0].arn_do_segredo_da_chave, null)
}

output "dominio_do_balanceador" {
  description = <<-TEXTO
    Nome DNS do ALB.

    Existe para diagnóstico, **não para uso**: ele só aceita conexão vinda da
    lista de prefixos do CloudFront, então acessá-lo direto do seu navegador dá
    timeout. O endereço da aplicação é `endereco_do_site`.
  TEXTO
  value       = try(module.servico[0].dominio_do_balanceador, null)
}
