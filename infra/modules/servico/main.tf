/**
 * O backend rodando: ECS Fargate atrás de um ALB (ticket 15).
 *
 * **Por que existe um balanceador para uma única task.** O CloudFront precisa
 * de um endereço **estável** na origem, e uma task Fargate não tem: o IP muda a
 * cada deploy, a cada reinício, a cada falha de health check. O ALB é o menor
 * componente da AWS que oferece nome fixo com health check — e é, de longe, o
 * item mais caro desta infraestrutura, ~43% da conta.
 *
 * **Por que o ALB fala HTTP, e isso não é um furo.** O TLS termina no
 * CloudFront; daqui para dentro o tráfego é interno da AWS. Colocar HTTPS no
 * balanceador exigiria um certificado, e o ACM **não emite certificado para
 * nome de ALB** — seria preciso registrar e validar um domínio próprio só para
 * cifrar um salto interno. O que fecha o buraco é o security group abaixo: o
 * ALB só aceita conexão da lista de prefixos do próprio CloudFront, então não
 * há como alguém chegar nele por fora e conversar em texto claro.
 *
 * **Uma réplica, e isso é decisão de produto, não economia.** A baseline
 * calibrada de cada aluno vive na memória do processo
 * (`analista.RegistroDeAnalistas`). Com duas tasks e sem sessão pegajosa, o
 * mesmo aluno reconectando cairia na outra e recalibraria do zero — perdendo os
 * 60 segundos iniciais no meio da sessão de estudo. Enquanto a baseline não for
 * para o banco, `desired_count = 1`.
 *
 * **Ordem de criação.** Um serviço ECS apontando para um repositório ECR vazio
 * entra em ciclo permanente de falha de deploy. A imagem precisa existir
 * **antes** do primeiro apply deste módulo — ver o README da infraestrutura.
 */

data "aws_region" "atual" {}

# A lista de prefixos que a AWS publica e mantém com as faixas de saída do
# CloudFront. Usá-la é o que transforma "o ALB é público" em "o ALB só atende
# quem vem pela distribuição" — sem ninguém ter que manter IP na mão.
data "aws_ec2_managed_prefix_list" "cloudfront" {
  name = "com.amazonaws.global.cloudfront.origin-facing"
}

# --- Segredo da aplicação --------------------------------------------------

resource "aws_secretsmanager_secret" "chave" {
  name        = "${var.nome}-secret-key"
  description = "SECRET_KEY de assinatura dos JWT do MapFace"

  # Sem isto, um `destroy` seguido de `apply` no mesmo dia falha: a AWS mantém
  # o nome reservado por 7 a 30 dias depois da remoção. Numa PoC que é montada
  # e desmontada para demonstração, isso seria um tiro no pé semanal.
  recovery_window_in_days = 0
}

/**
 * A chave é gerada aqui, e o custo disso está escrito:
 *
 * `random_password` grava o valor **em texto claro no arquivo de estado**. Para
 * a senha do banco esse custo foi evitado (`manage_master_user_password` faz a
 * AWS gerar e guardar sozinha), mas para um segredo de aplicação a AWS não
 * oferece equivalente — alguém precisa gerar.
 *
 * O que sobra é escolher onde o valor aparece. As alternativas eram: pedir que
 * uma pessoa rode `put-secret-value` na mão depois do apply, o que devolve o
 * passo manual que a ticket 14 existe para eliminar; ou passar a chave como
 * variável do Terraform, o que a coloca no estado do mesmo jeito **e** no
 * histórico do shell.
 *
 * Mitigações em vigor: o estado é local e ignorado pelo Git, e `ignore_changes`
 * impede que um `apply` de rotina troque a chave — o que deslogaria todo mundo
 * e invalidaria as sessões em andamento. Para rotacionar de verdade:
 * `aws secretsmanager put-secret-value` e um novo deploy do serviço.
 */
resource "random_password" "chave" {
  length  = 64
  special = false
}

resource "aws_secretsmanager_secret_version" "chave" {
  secret_id     = aws_secretsmanager_secret.chave.id
  secret_string = random_password.chave.result

  lifecycle {
    ignore_changes = [secret_string]
  }
}

# --- Rede do serviço -------------------------------------------------------

resource "aws_security_group" "alb" {
  name        = "${var.nome}-alb"
  description = "Balanceador: aceita apenas o CloudFront"
  vpc_id      = var.id_da_vpc

  tags = { Name = "${var.nome}-alb" }
}

resource "aws_vpc_security_group_ingress_rule" "alb_do_cloudfront" {
  security_group_id = aws_security_group.alb.id
  description       = "HTTP vindo da lista de prefixos do CloudFront"

  prefix_list_id = data.aws_ec2_managed_prefix_list.cloudfront.id
  ip_protocol    = "tcp"
  from_port      = 80
  to_port        = 80
}

resource "aws_vpc_security_group_egress_rule" "alb_para_a_task" {
  security_group_id = aws_security_group.alb.id
  description       = "Encaminhamento para a task"

  referenced_security_group_id = aws_security_group.task.id
  ip_protocol                  = "tcp"
  from_port                    = var.porta
  to_port                      = var.porta
}

resource "aws_security_group" "task" {
  name        = "${var.nome}-task"
  description = "Task do backend: aceita apenas o balanceador"
  vpc_id      = var.id_da_vpc

  tags = { Name = "${var.nome}-task" }
}

resource "aws_vpc_security_group_ingress_rule" "task_do_alb" {
  security_group_id = aws_security_group.task.id
  description       = "Trafego da aplicacao vindo do balanceador"

  referenced_security_group_id = aws_security_group.alb.id
  ip_protocol                  = "tcp"
  from_port                    = var.porta
  to_port                      = var.porta
}

# Saída aberta porque a task precisa alcançar quatro serviços da AWS pela
# internet — ECR para baixar a imagem, Secrets Manager para ler a chave,
# CloudWatch para escrever log, e o RDS. Fechar isso exigiria VPC endpoints,
# que custam por hora cada um e resolveriam um risco que não existe: a task
# não aceita conexão de fora, e o que ela busca são serviços da própria AWS.
resource "aws_vpc_security_group_egress_rule" "task_para_fora" {
  security_group_id = aws_security_group.task.id
  description       = "Saida para ECR, Secrets Manager, CloudWatch e RDS"

  cidr_ipv4   = "0.0.0.0/0"
  ip_protocol = "-1"
}

# --- Balanceador -----------------------------------------------------------

resource "aws_lb" "backend" {
  name               = "${var.nome}-alb"
  load_balancer_type = "application"
  internal           = false
  subnets            = var.subredes_publicas
  security_groups    = [aws_security_group.alb.id]

  tags = { Name = "${var.nome}-alb" }
}

resource "aws_lb_target_group" "backend" {
  name     = "${var.nome}-backend"
  port     = var.porta
  protocol = "HTTP"
  vpc_id   = var.id_da_vpc

  # `ip` e não `instance`: no modo `awsvpc` a task tem ENI própria, e é o IP
  # dela que o balanceador registra. Com `instance` o target group esperaria
  # uma EC2, que não existe aqui.
  target_type = "ip"

  health_check {
    path                = "/health"
    matcher             = "200"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  # A telemetria é um WebSocket de vida longa. O padrão de 300 s derrubaria a
  # conexão de quem estuda, e o cliente reconectaria a cada cinco minutos —
  # perdendo a baseline em memória a cada vez.
  deregistration_delay = 30

  stickiness {
    type    = "lb_cookie"
    enabled = false
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.backend.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.backend.arn
  }
}

# --- Permissões ------------------------------------------------------------

data "aws_iam_policy_document" "assume_ecs" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

# Quem baixa a imagem, lê os segredos e abre o log. É o agente do ECS que a
# assume, **antes** de o contêiner existir — por isso ela é separada da role da
# própria aplicação.
resource "aws_iam_role" "execucao" {
  name               = "${var.nome}-execucao"
  assume_role_policy = data.aws_iam_policy_document.assume_ecs.json
}

resource "aws_iam_role_policy_attachment" "execucao_padrao" {
  role       = aws_iam_role.execucao.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "ler_segredos" {
  statement {
    actions = ["secretsmanager:GetSecretValue"]
    # Apenas estes dois segredos, e não `*`: a política gerenciada acima já dá
    # o resto do que o agente precisa, e uma permissão de leitura irrestrita no
    # Secrets Manager é exatamente o tipo de coisa que ninguém revisa depois.
    resources = compact([aws_secretsmanager_secret.chave.arn, var.arn_do_segredo_do_banco])
  }
}

resource "aws_iam_role_policy" "execucao_segredos" {
  name   = "ler-segredos"
  role   = aws_iam_role.execucao.id
  policy = data.aws_iam_policy_document.ler_segredos.json
}

# A role da **aplicação**. Fica vazia de propósito: o MapFace não chama nenhuma
# API da AWS em tempo de execução — ele fala com o banco e mais nada. Existir
# vazia é melhor que não existir: quando alguém precisar de S3 ou SES, o lugar
# de conceder já está criado e separado do agente do ECS.
resource "aws_iam_role" "task" {
  name               = "${var.nome}-task"
  assume_role_policy = data.aws_iam_policy_document.assume_ecs.json
}

# --- Log -------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "backend" {
  name              = "/ecs/${var.nome}"
  retention_in_days = var.retencao_de_log_dias

  tags = { Name = "${var.nome}-backend" }
}

# --- ECS -------------------------------------------------------------------

resource "aws_ecs_cluster" "este" {
  name = var.nome

  setting {
    name  = "containerInsights"
    value = "disabled"
  }

  tags = { Name = var.nome }
}

resource "aws_ecs_task_definition" "backend" {
  family                   = "${var.nome}-backend"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.cpu
  memory                   = var.memoria
  execution_role_arn       = aws_iam_role.execucao.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([
    {
      name      = "backend"
      image     = "${var.url_do_repositorio}:${var.tag_da_imagem}"
      essential = true

      portMappings = [{ containerPort = var.porta, protocol = "tcp" }]

      # As peças do banco viajam separadas da senha, de propósito. Ver a nota
      # em `backend/app/config.py`: o ECS injeta segredo numa variável, não no
      # meio de uma URL, e montar a URL fora do processo colocaria a senha em
      # texto claro no estado ou no log.
      environment = [
        { name = "DATABASE_HOST", value = var.endereco_do_banco },
        { name = "DATABASE_PORT", value = tostring(var.porta_do_banco) },
        { name = "DATABASE_NAME", value = var.nome_do_banco },
        { name = "DATABASE_USER", value = var.usuario_do_banco },
        # Vazia: o CloudFront serve o site e encaminha a API, então navegador e
        # API compartilham origem — e mesma origem não passa por CORS.
        { name = "ORIGENS_PERMITIDAS", value = "" },
      ]

      secrets = [
        { name = "SECRET_KEY", valueFrom = aws_secretsmanager_secret.chave.arn },
        # `:password::` extrai uma chave do JSON que o RDS guarda. Sem isso, a
        # variável receberia o documento inteiro, e a aplicação tentaria usar
        # `{"username":...}` como senha.
        { name = "DATABASE_PASSWORD", valueFrom = "${var.arn_do_segredo_do_banco}:password::" },
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.backend.name
          "awslogs-region"        = data.aws_region.atual.region
          "awslogs-stream-prefix" = "backend"
        }
      }
    }
  ])

  tags = { Name = "${var.nome}-backend" }
}

resource "aws_ecs_service" "backend" {
  name            = "${var.nome}-backend"
  cluster         = aws_ecs_cluster.este.id
  task_definition = aws_ecs_task_definition.backend.arn
  desired_count   = var.replicas
  launch_type     = "FARGATE"

  network_configuration {
    subnets = var.subredes_publicas
    # IP público porque não há NAT Gateway: é assim que a task alcança o ECR e
    # o Secrets Manager. Ela continua inalcançável de fora — quem decide isso é
    # o security group, não o endereço.
    assign_public_ip = true
    security_groups  = [aws_security_group.task.id]
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.backend.arn
    container_name   = "backend"
    container_port   = var.porta
  }

  # O ALB leva ~30 s para considerar a task saudável; sem esta carência o ECS a
  # mataria por health check antes de ela terminar de subir — e a subida inclui
  # carregar 4,5 MB de modelo de sonolência.
  health_check_grace_period_seconds = 120

  # Com uma réplica, o rolling update sobe a nova antes de derrubar a velha, e
  # existem dois processos por alguns segundos. É por isso que a migração de
  # boot tem cadeado consultivo — ver `app/database.py`.
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200

  depends_on = [aws_lb_listener.http]

  tags = { Name = "${var.nome}-backend" }
}
