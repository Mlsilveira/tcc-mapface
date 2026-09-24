output "bucket" {
  description = "Nome do bucket. É o destino do `aws s3 sync` do build do Angular."
  value       = aws_s3_bucket.site.bucket
}

output "endereco_do_site" {
  description = "URL pública do site, em HTTPS. É o endereço que abre a aplicação."
  value       = "https://${aws_cloudfront_distribution.site.domain_name}"
}

output "id_da_distribuicao" {
  description = "Id da distribuição. Necessário para invalidar o cache depois de cada deploy."
  value       = aws_cloudfront_distribution.site.id
}
