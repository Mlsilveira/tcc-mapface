variable "nome" {
  description = "Prefixo dos nomes dos recursos."
  type        = string
}

variable "dominio_do_backend" {
  description = <<-TEXTO
    Nome DNS do balanceador do backend, ou `null` para servir só o site.

    **Quando preenchido, é o que faz o produto existir.** A API passa a ser
    servida pelo mesmo domínio do site, e disso saem três coisas de uma vez:
    o CORS desaparece, porque mesma origem não é requisição cross-origin; o
    WebSocket herda o `https` e vira `wss`, sem conteúdo misto; e o frontend
    deixa de ter qualquer URL de ambiente para configurar, porque
    `core/api.ts` deriva tudo de `window.location`.

    A alternativa — um domínio para o site e outro para a API — esbarra no ACM,
    que **não emite certificado para nome de ALB**. Ela exigiria registrar e
    validar um domínio próprio, e traria CORS e configuração de build de volta.

    `null` mantém o comportamento da ticket 14: só o site, o que é útil para
    subir a infraestrutura antes de existir imagem no ECR.
  TEXTO
  type        = string
  default     = null
}

variable "caminhos_da_api" {
  description = <<-TEXTO
    Os padrões de caminho que vão para o backend em vez do bucket.

    Lista explícita, e não um curinga: o que **não** estiver aqui é servido
    pelo S3, que é o comportamento certo para tudo o mais. Um `/*` apontando
    para o backend faria o CloudFront pedir o `index.html` ao FastAPI.
  TEXTO
  type        = list(string)
  default     = ["/auth/*", "/sessoes", "/sessoes/*", "/metodos", "/telemetria", "/health"]
}
