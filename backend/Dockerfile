# Imagem do backend FastAPI (ticket 15).
#
# `slim` e não `alpine`: o Alpine usa musl, e as rodas binárias do PyPI são
# compiladas para glibc. Com ele, `psycopg[binary]`, `bcrypt` e `cryptography`
# voltariam a ser compilados na hora — imagem maior no fim, build muito mais
# longo, e um compilador dentro da imagem final.
#
# A versão é a mesma do desenvolvimento (3.11), de propósito: a PoC não tem
# ambiente de homologação onde uma diferença de versão apareceria antes da
# banca.
FROM python:3.11-slim

# PYTHONDONTWRITEBYTECODE: o `.pyc` de um contêiner morre com ele.
# PYTHONUNBUFFERED: sem isto o stdout fica em buffer e o log da task aparece em
# blocos atrasados no CloudWatch — inclusive o traceback de um boot que falhou,
# que é justamente quando se precisa dele na hora.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# As dependências entram antes do código: elas mudam raramente, o código muda a
# cada commit, e o Docker reaproveita a camada enquanto o arquivo não mudar. Sem
# essa separação, cada build reinstalaria tudo.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Usuário sem privilégio. Um processo que não precisa de root não deve rodar
# como root — e este não precisa: ele abre uma porta alta e não escreve em
# disco, já que o estado todo vive no RDS.
RUN useradd --create-home --uid 10001 mapface
USER mapface

EXPOSE 8000

# `--proxy-headers` porque há dois saltos na frente: CloudFront e ALB. Sem ele,
# o uvicorn acha que todo request vem do IP do balanceador e em HTTP — e é isso
# que vai parar no log.
#
# Um worker só, e isso é decisão, não preguiça: a baseline calibrada de cada
# aluno vive na memória do processo (`analista.RegistroDeAnalistas`). Com dois
# workers, o mesmo aluno reconectando cairia no outro e recalibraria do zero.
# Enquanto a baseline não for para o banco, o backend é um processo só — e o
# `desired_count` do serviço ECS tem que ser 1 pela mesma razão.
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "1", \
     "--proxy-headers", \
     "--forwarded-allow-ips", "*"]
