/**
 * Registro das imagens Docker do FastAPI (ECR).
 *
 * Um repositório só. A PoC publica um serviço — o backend — e criar repositório
 * por ambiente multiplicaria imagem idêntica sem nada a ganhar: a mesma imagem
 * serve a PoC e a demonstração, mudando só as variáveis de ambiente do serviço.
 */

resource "aws_ecr_repository" "backend" {
  name = "${var.nome}-backend"

  # Tag mutável de propósito. O fluxo da ticket 15 é `docker push ...:latest`
  # seguido de novo deploy no ECS; com tag imutável, cada deploy exigiria
  # inventar uma tag nova, e o passo manual voltaria pela porta dos fundos.
  # Quando houver pipeline carimbando o sha do commit, vale trocar para IMMUTABLE.
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    # Varredura de vulnerabilidade a cada push. É gratuita no modo básico e a
    # imagem do FastAPI carrega o sistema operacional inteiro junto.
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  # A imagem é reconstruível a partir do Dockerfile: destruir o repositório com
  # imagens dentro não perde nada que não se refaça com um `docker build`.
  force_delete = true

  tags = { Name = "${var.nome}-backend" }
}

resource "aws_ecr_lifecycle_policy" "backend" {
  repository = aws_ecr_repository.backend.name

  # Sem isto o repositório acumula uma imagem por deploy, para sempre, e o
  # armazenamento é cobrado por GB — numa imagem Python de algumas centenas de
  # MB, cada deploy custa. Dez imagens cobrem qualquer rollback plausível de uma
  # PoC.
  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Mantem apenas as 10 imagens mais recentes"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 10
        }
        action = { type = "expire" }
      },
    ]
  })
}
