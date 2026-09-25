/**
 * Hospedagem do Angular compilado: bucket privado atrás do CloudFront.
 *
 * **O CloudFront não é enfeite — sem ele o produto não funciona.** O navegador
 * só libera `getUserMedia` em contexto seguro, e o endpoint de site estático do
 * S3 serve **apenas HTTP**. Publicar o Angular direto no S3 entregaria uma
 * aplicação que carrega, faz login, deixa iniciar a sessão de estudo e falha na
 * única coisa que ela existe para fazer: acender a webcam. O README do projeto
 * já registra isso para o ambiente local ("localhost funciona, mas um IP na
 * rede local, não"); em produção a consequência é a mesma.
 *
 * O bucket fica **fechado**, sem ACL pública e sem website endpoint. Quem lê é
 * o CloudFront, por Origin Access Control, e o bucket policy só aceita
 * requisição vinda desta distribuição — não de qualquer distribuição da conta,
 * nem de qualquer conta da AWS.
 *
 * **Consequência para a ticket 15:** com o site em HTTPS, o WebSocket tem que
 * ser `wss://`. Página segura falando com `ws://` é conteúdo misto, e o
 * navegador bloqueia sem perguntar. O backend no ECS vai precisar de TLS —
 * na prática, um ALB com certificado do ACM. Isso não é construído aqui, mas é
 * consequência direta desta decisão e precisa estar no caminho da 15.
 */

resource "aws_s3_bucket" "site" {
  # Nome de bucket é global na AWS inteira: dois times com o mesmo prefixo
  # colidiriam. O sufixo do id da conta resolve sem obrigar ninguém a inventar
  # nome único na mão.
  bucket        = "${var.nome}-site-${data.aws_caller_identity.atual.account_id}"
  force_destroy = true

  tags = { Name = "${var.nome}-site" }
}

data "aws_caller_identity" "atual" {}

resource "aws_s3_bucket_public_access_block" "site" {
  bucket = aws_s3_bucket.site.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "site" {
  bucket = aws_s3_bucket.site.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "site" {
  bucket = aws_s3_bucket.site.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "site" {
  bucket = aws_s3_bucket.site.id

  # O build do Angular sobrescreve os mesmos caminhos a cada deploy. Versionar
  # é o que permite voltar um deploy ruim sem reconstruir nada.
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_cloudfront_origin_access_control" "site" {
  name                              = "${var.nome}-site"
  description                       = "Acesso do CloudFront ao bucket do site, sem expor o bucket"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

data "aws_cloudfront_cache_policy" "otimizado" {
  name = "Managed-CachingOptimized"
}

# A API não pode ser cacheada: cada resposta depende do aluno autenticado, e um
# relatório servido do cache seria o de outra pessoa.
data "aws_cloudfront_cache_policy" "sem_cache" {
  name = "Managed-CachingDisabled"
}

# Encaminha tudo o que o navegador mandou — inclusive `Authorization`, sem o
# qual nenhuma rota protegida funciona, e os cabeçalhos de upgrade, sem os quais
# o WebSocket nunca estabelece. O `ExceptHostHeader` é obrigatório aqui: o ALB
# precisa receber o host dele, não o do CloudFront.
data "aws_cloudfront_origin_request_policy" "tudo_menos_host" {
  name = "Managed-AllViewerExceptHostHeader"
}

resource "aws_cloudfront_distribution" "site" {
  enabled             = true
  comment             = var.nome
  default_root_object = "index.html"

  # `PriceClass_All` porque é a única classe que inclui a América do Sul, e os
  # alunos estão no Brasil. As classes mais baratas não deixam de funcionar —
  # roteiam para a borda incluída mais próxima —, mas fazem cada requisição
  # atravessar o oceano. No volume de uma PoC a diferença de preço é nula.
  price_class = "PriceClass_All"

  origin {
    origin_id                = "s3-site"
    domain_name              = aws_s3_bucket.site.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.site.id
  }

  # O backend entra como **segundo origin da mesma distribuição**, e é isso que
  # faz site e API compartilharem domínio. Ver `var.dominio_do_backend`.
  dynamic "origin" {
    for_each = var.dominio_do_backend == null ? [] : [var.dominio_do_backend]

    content {
      origin_id   = "alb-backend"
      domain_name = origin.value

      custom_origin_config {
        origin_protocol_policy = "http-only"
        http_port              = 80
        https_port             = 443
        # O TLS termina aqui, no CloudFront. Daqui para dentro é rede da AWS, e
        # o security group do ALB só aceita a lista de prefixos do CloudFront.
        origin_ssl_protocols = ["TLSv1.2"]

        # O WebSocket de telemetria fica aberto pela sessão inteira. O padrão de
        # 30 s derrubaria a conexão de quem estuda a cada meio minuto, e o
        # cliente reconectaria perdendo a baseline em memória.
        origin_read_timeout      = 60
        origin_keepalive_timeout = 60
      }
    }
  }

  default_cache_behavior {
    target_origin_id = "s3-site"
    # Redirecionar e não apenas permitir: quem digitar `http://` chega no
    # mesmo lugar, em contexto seguro, e a webcam funciona.
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD", "OPTIONS"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true
    cache_policy_id        = data.aws_cloudfront_cache_policy.otimizado.id
  }

  dynamic "ordered_cache_behavior" {
    for_each = var.dominio_do_backend == null ? [] : var.caminhos_da_api

    content {
      path_pattern     = ordered_cache_behavior.value
      target_origin_id = "alb-backend"

      # Redirecionar, e não apenas permitir: uma chamada em `http://` seria
      # respondida em texto claro, com o token dentro.
      viewer_protocol_policy = "redirect-to-https"

      # Todos os métodos: o `OPTIONS` do preflight, o `POST` do login e o `GET`
      # com upgrade que abre o WebSocket.
      allowed_methods = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
      cached_methods  = ["GET", "HEAD"]

      cache_policy_id          = data.aws_cloudfront_cache_policy.sem_cache.id
      origin_request_policy_id = data.aws_cloudfront_origin_request_policy.tudo_menos_host.id

      # Comprimir uma resposta de API a 1 Hz custa CPU e não economiza nada: os
      # payloads do score têm dezenas de bytes.
      compress = false
    }
  }

  # O Angular é uma SPA: `/home` e `/relatorio/7` não são objetos no bucket, e o
  # S3 responde 403 para eles. Sem estas duas regras, recarregar a página em
  # qualquer rota que não a raiz devolveria erro — e recarregar no meio de uma
  # sessão é caminho previsto, que o `ngOnInit` da tela já trata.
  #
  # 403 e não só 404 porque o bucket está fechado: objeto inexistente em bucket
  # sem permissão de listagem volta como "acesso negado", não como "não existe".
  custom_error_response {
    error_code            = 403
    response_code         = 200
    response_page_path    = "/index.html"
    error_caching_min_ttl = 0
  }

  custom_error_response {
    error_code            = 404
    response_code         = 200
    response_page_path    = "/index.html"
    error_caching_min_ttl = 0
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    # Certificado do próprio domínio `*.cloudfront.net`. Um domínio próprio
    # exigiria certificado no ACM da us-east-1 e validação por DNS — trabalho da
    # ticket 15, se o time quiser um endereço apresentável para a banca.
    cloudfront_default_certificate = true
  }

  tags = { Name = "${var.nome}-site" }
}

data "aws_iam_policy_document" "site" {
  statement {
    sid       = "LeituraSomenteDestaDistribuicao"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.site.arn}/*"]

    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }

    # Sem esta condição o policy liberaria o bucket para **qualquer**
    # distribuição do CloudFront, de qualquer conta da AWS — o serviço inteiro é
    # o principal. É a diferença entre "o CloudFront lê" e "esta distribuição lê".
    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.site.arn]
    }
  }
}

resource "aws_s3_bucket_policy" "site" {
  bucket = aws_s3_bucket.site.id
  policy = data.aws_iam_policy_document.site.json

  # O bloqueio de policy pública precisa estar de pé **antes** deste policy
  # entrar, senão há uma janela em que o bucket aceita policy sem restrição.
  depends_on = [aws_s3_bucket_public_access_block.site]
}
