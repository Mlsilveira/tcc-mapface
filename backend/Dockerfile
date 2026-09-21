# Imagem do backend do MapFace.
#
# NÃO VALIDADA: a máquina em que este arquivo foi escrito não tem Docker, então
# ele nunca foi construído nem executado. O que está aqui é raciocínio, não
# observação — quem tiver um Docker por perto deve rodar as duas linhas da
# seção "Imagem do backend" do README antes de confiar em qualquer coisa deste
# arquivo.
#
# ---------------------------------------------------------------------------
#
# **Por que 3.9, sendo que 3.9 é antigo.** O `README.md` declara "Python 3.9+"
# como pré-requisito, e `sqlmodel==0.0.34` está pinado justamente por ser o
# último que ainda roda nessa versão (0.0.35+ exige 3.10). Uma imagem em 3.12
# construiria e rodaria igual — e, no primeiro trecho de sintaxe de 3.10 que
# alguém escrevesse, o piso do README viraria mentira sem ninguém notar, porque
# nada mais executaria 3.9. Construir no piso é o que torna o piso verificável.
#
# O preço está dito por inteiro: o 3.9 chegou ao fim do suporte upstream, e esta
# imagem não recebe mais correção de segurança do interpretador. Para a janela
# de uso deste projeto — duas ocasiões, um grupo conhecido — é troca aceitável;
# se ela deixar de ser, o caminho é subir o piso no README, soltar o pin do
# sqlmodel e revalidar o par com o pydantic (ver `requirements.txt`), **nesta
# ordem**, e não trocar esta linha sozinha.
FROM python:3.9-slim-bookworm

# `PYTHONDONTWRITEBYTECODE`: o `.pyc` não sobrevive ao contêiner e só engorda a
# camada. `PYTHONUNBUFFERED`: sem ele o stdout do Python fica em buffer quando
# não é um terminal, e é exatamente o caso aqui — o log do boot só apareceria
# no painel depois de encher o buffer, ou seja, justamente quando ninguém mais
# precisa dele.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# O `requirements.txt` entra **sozinho**, antes do código. É o que faz a camada
# de dependências ser reaproveitada: mudar uma linha de `app/` não reinstala o
# pydantic. Copiar tudo de uma vez inverteria isso e transformaria cada build
# numa instalação completa.
#
# `--no-cache-dir` porque o cache do pip nunca mais é lido dentro da imagem —
# ficaria só ocupando espaço na camada.
#
# Este é o `pip install` num ambiente limpo de que fala o commit 222d332: foi
# nele que se descobriu que `sqlmodel` e `pydantic` precisavam ser pinados como
# par. Um venv de desenvolvimento com meses de idade não reproduz este passo.
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Só `app/`. Os testes ficam de fora de propósito: eles não são executados aqui
# (a verificação acontece no desenvolvimento, contra os dois bancos), e a imagem
# de produção não tem por que carregar `tests/`, `.venv/` ou o `app.db` de
# alguém. O `.dockerignore` ao lado garante o resto.
COPY app/ ./app/

# Usuário sem privilégio. O processo não escreve em disco — o banco é externo —,
# então nada aqui precisa ser gravável, e um `chown` do diretório seria conceder
# permissão que o serviço não usa.
#
# Efeito colateral desejado: com `DATABASE_URL` apontando para o SQLite padrão,
# a aplicação tentaria criar `./app.db` num diretório que este usuário não pode
# escrever, e morreria no boot. Falhar assim é melhor que subir em produção
# gravando num arquivo que some junto com o contêiner.
RUN useradd --create-home --shell /usr/sbin/nologin mapface
USER mapface

EXPOSE 8000

# `--host 0.0.0.0` porque o padrão do uvicorn é `127.0.0.1`, que dentro de um
# contêiner significa "ninguém de fora alcança" — e o sintoma é uma porta
# publicada que não responde, sem erro em lugar nenhum.
#
# Sem `--reload`: além do custo, é o modo em que o uvicorn devolve stack trace
# ao cliente.
#
# Sem `--workers`: mais de um processo é o mesmo problema que mais de uma
# réplica, e `app/analista.py` guarda a calibração de cada aluno em memória de
# processo. Dois workers fariam o aluno recalibrar a cada requisição que caísse
# no outro. Não é economia, é requisito de correção — quem for dimensionar a
# infra precisa saber que subir para dois quebra a medição em silêncio.
#
# Sem HEALTHCHECK: quem sonda esta aplicação é o orquestrador, e ele precisa
# distinguir `/vivo` (reinicie a task) de `/pronto` (tire da rotação). Um
# `HEALTHCHECK` no Dockerfile só sabe dizer "saudável" ou "doente", e escolher
# um dos dois aqui esconderia a distinção de quem vai escrever o Terraform.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
