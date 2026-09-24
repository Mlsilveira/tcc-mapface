/**
 * Rede mínima para a PoC.
 *
 * **Uma VPC própria, e não a default da conta.** A história de usuário 34 pede
 * um ambiente "reproduzível e portátil entre contas", e a VPC default não
 * atende nenhuma das duas coisas: ela não existe em toda conta — quem apagou a
 * sua, ou usa uma região onde ela nunca foi criada, fica sem —, e as faixas de
 * endereço dela variam, então o mesmo código gera redes diferentes em contas
 * diferentes.
 *
 * **Sem NAT Gateway.** Ele custa por hora mais do que todo o resto desta
 * infraestrutura junto, e nada aqui precisa dele: o RDS não fala com a
 * internet, e o ECS da ticket 15 roda em sub-rede pública com IP público, que
 * alcança o ECR pelo mesmo caminho. Se algum dia houver tarefa em sub-rede
 * privada precisando de saída, o NAT entra aqui — como decisão consciente, com
 * o custo na mesa.
 */

data "aws_availability_zones" "disponiveis" {
  state = "available"
}

locals {
  # Duas AZs porque o grupo de sub-redes do RDS exige no mínimo duas, mesmo
  # numa instância Single-AZ. É requisito da AWS, não escolha de arquitetura.
  azs = slice(data.aws_availability_zones.disponiveis.names, 0, 2)
}

resource "aws_vpc" "esta" {
  cidr_block = var.cidr_da_vpc

  # Os dois são exigidos pelo RDS para resolver o endpoint por nome de dentro
  # da VPC. Sem eles a aplicação só alcançaria o banco por IP, que muda.
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = { Name = var.nome }
}

resource "aws_internet_gateway" "esta" {
  vpc_id = aws_vpc.esta.id

  tags = { Name = var.nome }
}

resource "aws_subnet" "publica" {
  count = length(local.azs)

  vpc_id                  = aws_vpc.esta.id
  availability_zone       = local.azs[count.index]
  cidr_block              = cidrsubnet(var.cidr_da_vpc, 8, count.index)
  map_public_ip_on_launch = true

  tags = { Name = "${var.nome}-publica-${count.index + 1}" }
}

resource "aws_subnet" "privada" {
  count = length(local.azs)

  vpc_id            = aws_vpc.esta.id
  availability_zone = local.azs[count.index]
  # Deslocadas em 10 para as faixas pública e privada ficarem legíveis num
  # `describe`: .0 e .1 públicas, .10 e .11 privadas.
  cidr_block = cidrsubnet(var.cidr_da_vpc, 8, count.index + 10)

  tags = { Name = "${var.nome}-privada-${count.index + 1}" }
}

resource "aws_route_table" "publica" {
  vpc_id = aws_vpc.esta.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.esta.id
  }

  tags = { Name = "${var.nome}-publica" }
}

resource "aws_route_table_association" "publica" {
  count = length(aws_subnet.publica)

  subnet_id      = aws_subnet.publica[count.index].id
  route_table_id = aws_route_table.publica.id
}

# As sub-redes privadas ficam com a tabela default da VPC, que só tem a rota
# local. É o isolamento que se quer do banco: sem rota para o gateway, não há
# caminho de saída nem de entrada pela internet, independentemente de security
# group. Duas camadas dizendo a mesma coisa, que é como isolamento se faz.
