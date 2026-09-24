/**
 * RDS PostgreSQL, criptografado em repouso.
 *
 * **A senha nunca passa pelo Terraform.** `manage_master_user_password` faz a
 * AWS gerar e guardar a credencial no Secrets Manager; o Terraform só recebe o
 * ARN do segredo. A alternativa comum — `random_password` alimentando o campo
 * `password` — grava a senha **em texto claro no arquivo de estado**, e o
 * estado é um arquivo que se comita por engano, se manda por chat, se copia
 * para o Drive. Marcar a variável como `sensitive` esconde a senha do log do
 * `apply` e não muda nada disso.
 *
 * **Criptografia em repouso.** `storage_encrypted = true` é literalmente o
 * critério da ticket e a história de usuário 32: o RDS cifra volume, snapshots,
 * backups automáticos e réplicas com **AES-256**, usando a chave gerenciada
 * `aws/rds`. Uma chave própria no KMS daria rotação e política de acesso
 * separadas, e custa um dólar por mês por chave — escolha consciente de não
 * fazer numa PoC, e uma linha para mudar quando deixar de ser.
 *
 * O banco é **inalcançável pela internet**: sub-rede sem rota de saída,
 * `publicly_accessible = false`, e security group que só aceita a porta 5432
 * vinda de dentro da própria VPC.
 */

resource "aws_db_subnet_group" "banco" {
  name       = "${var.nome}-banco"
  subnet_ids = var.subredes_privadas

  tags = { Name = "${var.nome}-banco" }
}

resource "aws_security_group" "banco" {
  name        = "${var.nome}-banco"
  description = "Acesso ao PostgreSQL, somente de dentro da VPC"
  vpc_id      = var.id_da_vpc

  tags = { Name = "${var.nome}-banco" }
}

resource "aws_vpc_security_group_ingress_rule" "postgres" {
  security_group_id = aws_security_group.banco.id
  description       = "PostgreSQL a partir da propria VPC"

  # A faixa da VPC, e não `0.0.0.0/0`: o banco não está na internet, e mesmo
  # que estivesse, a regra não o exporia. Quando o serviço ECS existir, o certo
  # é trocar isto por `referenced_security_group_id` apontando para o grupo da
  # task — aí só o backend entra, nem o resto da VPC.
  cidr_ipv4   = var.cidr_da_vpc
  ip_protocol = "tcp"
  from_port   = 5432
  to_port     = 5432
}

resource "aws_db_instance" "banco" {
  identifier = "${var.nome}-banco"

  engine         = "postgres"
  engine_version = var.versao_do_postgres
  instance_class = var.classe_da_instancia

  # `postgres` é nome de banco reservado no PostgreSQL; `db_name` precisa ser
  # outro, senão a criação falha.
  db_name  = "mapface"
  username = "mapface"

  # Sem `password`: quem gera e guarda é a AWS. Ver a nota no topo.
  manage_master_user_password = true

  allocated_storage = var.armazenamento_gb
  storage_type      = "gp3"
  storage_encrypted = true

  db_subnet_group_name   = aws_db_subnet_group.banco.name
  vpc_security_group_ids = [aws_security_group.banco.id]
  publicly_accessible    = false

  backup_retention_period = var.retencao_de_backup_dias
  deletion_protection     = var.protecao_contra_remocao

  # Numa PoC que é montada e desmontada, exigir snapshot final faria todo
  # `destroy` deixar um snapshot cobrado para trás — e desmontar é operação
  # rotineira aqui, não excepcional.
  skip_final_snapshot = true

  # Correção de segurança dentro da mesma versão maior entra sozinha, na janela
  # de manutenção. A versão maior continua presa em `engine_version`.
  auto_minor_version_upgrade = true

  # Single-AZ. Alta disponibilidade dobra o custo e o plano de sprints trata a
  # meta de 99,9% como validação de carga na ticket 16, não como topologia.
  multi_az = false

  tags = { Name = "${var.nome}-banco" }
}
