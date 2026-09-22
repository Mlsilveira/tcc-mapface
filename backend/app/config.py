"""Configuração lida do ambiente, e o que a aplicação recusa antes de subir.

Este módulo faz duas coisas que parecem uma só: lê os valores (`Settings`) e
**julga** se a combinação deles pode ir para o ar (`verificar_configuracao`). A
segunda roda no import, o que significa que uma configuração insegura não vira
um erro no primeiro request — vira um processo que não sobe. Ver §1.4 e §1.5 do
plano de produção.
"""
from contextlib import contextmanager
from typing import FrozenSet, Iterator, List, Optional

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

#: A chave que está no `.env.example` e, portanto, em todo clone do repositório.
#: Quem a tem assina um JWT válido de qualquer aluno. É literal aqui de propósito:
#: o valor precisa ser comparável em tempo de execução, e não só legível por um
#: humano num parágrafo de README.
CHAVE_DE_EXEMPLO = "troque-esta-chave-por-um-valor-aleatorio-e-secreto"

DESENVOLVIMENTO = "desenvolvimento"
TESTE = "teste"
PRODUCAO = "producao"

#: Os ambientes que a aplicação reconhece. A lista é fechada porque o julgamento
#: abaixo depende dela: com ambiente livre, `AMBIENTE=prod` (um typo plausível)
#: não seria "produção" para efeito de verificação e passaria batido justamente
#: onde a verificação importa.
AMBIENTES_CONHECIDOS: FrozenSet[str] = frozenset({DESENVOLVIMENTO, TESTE, PRODUCAO})

#: Onde a chave de exemplo ainda é aceita — **junto** com a condição de banco
#: local do item 3 de `verificar_configuracao`, nunca sozinha. `teste` está aqui
#: porque a suíte roda sem `.env` nenhum, em máquina de CI que não tem segredo a
#: oferecer, e exigir um segredo para rodar teste só ensinaria a inventar um e
#: versioná-lo.
AMBIENTES_SEM_SEGREDO: FrozenSet[str] = frozenset({DESENVOLVIMENTO, TESTE})

#: Prefixo da URL de um banco que mora num arquivo da própria máquina. É o que
#: separa "alguém clonou o repositório" de "isto é uma instalação de verdade":
#: um SQLite local não tem usuário além de quem está sentado na frente dele.
PREFIXO_SQLITE = "sqlite"

#: Os algoritmos de assinatura que este projeto pode usar. Só a família HMAC,
#: porque o segredo é simétrico (`SECRET_KEY`): pedir `RS256` aqui seria pedir
#: para a `jose` tratar uma senha como chave privada RSA, e o erro apareceria no
#: primeiro login e não no boot. `none` — o algoritmo que desliga a verificação
#: de assinatura — é recusado por consequência de a lista ser fechada, que é o
#: motivo de ela ser uma lista e não uma validação de formato.
ALGORITMOS_CONHECIDOS: FrozenSet[str] = frozenset({"HS256", "HS384", "HS512"})

#: O curinga de CORS. Recusado, não ignorado — ver `verificar_configuracao`.
CURINGA = "*"

#: O único esquema de origem aceito em produção. Ver o item 6 de
#: `verificar_configuracao`.
ESQUEMA_SEGURO = "https://"


class ConfiguracaoInsegura(RuntimeError):
    """A aplicação foi configurada de um jeito que não pode ir para o ar.

    Exceção própria, e não `ValueError` dentro de um validador do pydantic,
    porque as duas leituras são diferentes na hora em que isso acontece: o
    pydantic empacota o erro num `ValidationError` com o relatório de campos, e
    quem está olhando os logs de uma task que não sobe precisa de uma frase que
    diga o que fazer. A mensagem desta exceção é a única coisa que essa pessoa
    vai ler.
    """


class Settings(BaseSettings):
    """Configuração da aplicação, lida de variáveis de ambiente / .env.

    Os defaults são os de **desenvolvimento**: o objetivo é que `git clone` +
    `uvicorn` funcione sem nenhum arquivo de configuração, e que a suíte rode
    numa máquina limpa. Todo valor que precisa ser diferente em produção é, por
    isso, um valor que alguém tem que declarar — e `verificar_configuracao`
    existe para que esquecer de declarar seja barulhento em vez de silencioso.
    """

    # Qual dos ambientes conhecidos está rodando, **como declarado** — `None`
    # quando ninguém declarou nada. A distinção entre "não declarado" e
    # "declarado como desenvolvimento" é o conserto de um furo real: enquanto
    # este campo tinha default `desenvolvimento`, quem esquecesse `AMBIENTE` na
    # task definition caía automaticamente na lista de isentos de segredo
    # (`AMBIENTES_SEM_SEGREDO`) — e é exatamente o mesmo perfil de quem esquece
    # a `SECRET_KEY`. A guarda desenhada contra o esquecimento tinha um
    # esquecimento como caminho de contorno.
    #
    # Quem quer o valor para usar (log, decisão de política) lê `ambiente`, que
    # devolve `desenvolvimento` quando não há declaração. Quem quer saber se
    # **houve** declaração lê este campo — e é só a verificação que quer isso.
    ambiente_declarado: Optional[str] = Field(
        default=None, validation_alias=AliasChoices("AMBIENTE")
    )

    database_url: str = "sqlite:///./app.db"
    secret_key: str = CHAVE_DE_EXEMPLO
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    # Origens que o navegador pode usar para chamar esta API, separadas por
    # vírgula. Era `["http://localhost:4200"]` cravado em `app/main.py`, o que
    # significa que em produção o navegador recusaria toda chamada.
    #
    # **Texto, e não `List[str]`.** O pydantic-settings lê campo de tipo
    # composto do ambiente como **JSON**: `ORIGENS_PERMITIDAS=https://a,https://b`
    # não viraria duas origens, viraria um erro de parse antes de qualquer
    # validador nosso rodar, e quem escreve o `.env` teria que saber que aquela
    # linha específica precisa de colchetes e aspas. Uma string dividida por
    # `origens_de_cors` é a forma que sobrevive a um `.env` escrito à mão.
    origens_permitidas: str = "http://localhost:4200"

    # Nível mínimo das linhas que a aplicação escreve. Existe para a ocasião em
    # que algo está errado no ambiente publicado e não dá para reproduzir na
    # máquina: `NIVEL_DE_LOG=DEBUG` e subir de novo é mais rápido que adivinhar.
    nivel_de_log: str = "INFO"

    # Quem pode se cadastrar, separado por vírgula. **Vazio significa aberto**,
    # que é o que mantém `git clone && uvicorn` utilizável e a suíte rodando sem
    # configurar nada — e é também por isso que `verificar_configuracao` recusa
    # subir com esta lista vazia em produção. Ver `emails_autorizados` e o item
    # 7 da verificação.
    #
    # Lista de e-mails, e não código de convite: ver o docstring de
    # `app.routers.auth.registrar`, onde a escolha é justificada contra a
    # alternativa.
    emails_autorizados: str = ""

    # Quantas tentativas de autenticação um mesmo e-mail pode gastar dentro da
    # janela abaixo antes de levar 429. Dez porque é folgado para quem erra a
    # senha de verdade — três, quatro erros seguidos é o que acontece com gente
    # apressada — e apertado para quem está varrendo: 10 tentativas a cada 5
    # minutos são 2.880 por dia contra **uma** conta, número que não chega perto
    # de um dicionário. O contador é zerado por login bem-sucedido, de modo que
    # o aluno legítimo nunca o acumula.
    tentativas_de_autenticacao: int = 10
    janela_de_tentativas_minutos: int = 5

    # Quantas requisições de login/registro podem estar **em voo ao mesmo
    # tempo**. Existe por causa da CPU do bcrypt (cost 12, ~300 ms) e do
    # threadpool de 40 threads em que os endpoints síncronos do FastAPI rodam:
    # sem teto, algumas dezenas de chamadas simultâneas ocupam as threads,
    # `/pronto` — que é síncrono e divide o mesmo pool — fica na fila e estoura
    # o timeout da sonda, e o orquestrador recicla uma task que estava sã,
    # derrubando a sessão de estudo de todo mundo junto.
    #
    # Oito é o maior número que ainda deixa a conta confortável: 8 das 40
    # threads ocupadas, 32 livres para sonda e telemetria, e ~2,4 s de trabalho
    # de bcrypt enfileirado no pior caso de uma task de 0,25 vCPU. É folgado
    # para uma turma que entra ao longo de um ou dois minutos (cada login ocupa
    # sua vaga por pouco mais de um segundo) e é um teto duro para quem
    # dispara em rajada.
    autenticacoes_simultaneas: int = 8

    # Maior vão entre dois pontos consecutivos da série que ainda é atribuível a
    # **perda de captura** — reconexão do WebSocket, aba em segundo plano,
    # máquina suspensa — e não a fim de sessão. É o que `app.presenca` usa para
    # costurar a duração presente.
    #
    # Este valor **decidia** o encerramento automático da sessão até os métodos
    # de estudo entrarem, e o nome antigo dizia isso. Hoje quem decide é
    # `sessao_estudo.ultima_presenca`, com o limite do método
    # (`app.metodos.limite_de_ausencia`). Renomear em vez de duplicar porque o
    # nome vira mentira no instante em que ele deixa de decidir a morte da
    # sessão — e nome mentiroso é pior que constante órfã.
    #
    # O alias antigo fica: um `.env` escrito antes desta mudança continua
    # funcionando sem ninguém precisar saber que houve mudança.
    vao_maximo_da_serie_minutos: int = Field(
        default=10,
        validation_alias=AliasChoices(
            "VAO_MAXIMO_DA_SERIE_MINUTOS", "SESSAO_INATIVIDADE_MINUTOS"
        ),
    )

    # Tempo máximo de vida de uma **credencial**, contado do login e carimbado
    # no próprio token (`iat`), não do último uso. A janela de 30 minutos acima
    # desliza por renovação enquanto o aluno usa o sistema; este é o teto que a
    # deslizada não atravessa.
    #
    # Doze horas porque é a menor duração que cobre o caso legítimo sem cobrir o
    # caso perigoso: **um dia de estudo cabe** — manhã, almoço, tarde, incluindo
    # quem estuda em blocos espalhados desde cedo — e **um fim de semana
    # esquecido não**. Uma aba deixada aberta numa máquina compartilhada na
    # sexta à noite não continua autenticada na segunda.
    #
    # Sem este teto a janela deslizante vira credencial eterna: bastaria um
    # request a cada 29 minutos, e o heartbeat de 60 s faz exatamente isso
    # sozinho. Com ele, o pior caso é limitado e dizível em uma frase.
    teto_de_credencial_horas: int = 12

    # `populate_by_name` existe por causa do `validation_alias` de
    # `ambiente_declarado`: sem ele, o campo só poderia ser preenchido pelo nome
    # da variável de ambiente, e os testes que constroem uma `Settings` à mão
    # teriam de escrever `AMBIENTE=` como argumento — que é o nome do ambiente,
    # não o do campo.
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", populate_by_name=True
    )

    @property
    def ambiente(self) -> str:
        """O ambiente em vigor: o declarado, ou desenvolvimento quando não há.

        Propriedade, e não campo com default, porque o default apagava a
        informação de que ninguém declarou nada — e é justamente essa
        informação que `verificar_configuracao` precisa para distinguir "estou
        em desenvolvimento" de "esqueci de dizer onde estou". Quem só quer o
        valor continua lendo `settings.ambiente` como antes.
        """
        if self.ambiente_declarado is None:
            return DESENVOLVIMENTO
        return self.ambiente_declarado

    def banco_e_local(self) -> bool:
        """O banco é um arquivo SQLite desta máquina?

        É o sinal que esta configuração usa para reconhecer uma instalação de
        verdade sem depender de ninguém declarar que ela é de verdade: um
        PostgreSQL tem endereço, credencial e outras pessoas do outro lado;
        `sqlite:///./app.db` é um arquivo ao lado do código de quem clonou.
        """
        return self.database_url.strip().lower().startswith(PREFIXO_SQLITE)

    def origens_de_cors(self) -> List[str]:
        """As origens declaradas, uma a uma, sem espaços e sem vazias.

        Descartar as vazias não é zelo estético: `"https://a,"` — uma vírgula
        sobrando no fim da linha do `.env`, que é o erro de digitação mais
        provável aqui — produziria a origem `""`, e uma origem vazia na lista do
        CORS é uma entrada que nunca casa com nada e que ninguém consegue ver
        olhando o arquivo.
        """
        return [
            origem.strip() for origem in self.origens_permitidas.split(",") if origem.strip()
        ]

    def emails_autorizados_a_registrar(self) -> FrozenSet[str]:
        """Os e-mails da lista, normalizados. Vazio significa **registro aberto**.

        Normalizar para minúsculas é o que faz a lista casar com o que a pessoa
        digita: `Ana.Souza@exemplo.com` e `ana.souza@exemplo.com` são a mesma
        caixa postal em todo provedor que esta turma usa, e uma lista que
        recusasse a primeira produziria um "não estou autorizado" incompreensível
        para quem está com o próprio e-mail na mão. O rigor do RFC — que permite
        parte local sensível a maiúsculas — perderia aqui para a realidade, e o
        custo de errar é alguém não conseguir se cadastrar.
        """
        return frozenset(
            email.strip().lower() for email in self.emails_autorizados.split(",") if email.strip()
        )


def verificar_configuracao(config: Settings) -> None:
    """Recusa subir quando a configuração é insegura — falha fechada.

    **Por que uma verificação e não um parágrafo no README.** O README já pedia
    para trocar a `SECRET_KEY`. Pedir é um controle que depende de alguém ler,
    lembrar e executar no dia do deploy; e a consequência de esquecer não é um
    erro visível, é uma aplicação que funciona perfeitamente enquanto qualquer
    pessoa com acesso ao repositório assina um JWT de qualquer aluno. Defeito
    que não se manifesta é defeito que não se corrige.

    **Por que no import e não no primeiro request.** Uma verificação tardia
    deixa o processo subir, o orquestrador marcar a task como saudável e o erro
    aparecer para o primeiro aluno que tentar entrar. No import, o contêiner
    morre no boot com a mensagem no log — que é o lugar onde quem publicou está
    olhando naquele exato minuto.

    **O furo que os itens 2 e 3 fecham, e por que o conserto tem esta forma.**
    A primeira versão desta função condicionava a recusa a
    `ambiente not in AMBIENTES_SEM_SEGREDO`, e `ambiente` tinha default
    `desenvolvimento`. Resultado: quem **não declarava** `AMBIENTE` entrava na
    lista de isentos sem escolher entrar nela — a mesma distração que deixa a
    `SECRET_KEY` de exemplo para trás desligava a guarda que existe por causa
    dela. Foi reproduzido: sem `AMBIENTE`, com a chave de exemplo e com
    `DATABASE_URL` apontando para um PostgreSQL, a aplicação subia.

    Das duas saídas possíveis, a escolhida **não** foi exigir `AMBIENTE`
    declarado em toda situação. Exigir sempre quebraria `git clone && uvicorn`
    sem `.env` e obrigaria a suíte a declarar ambiente para rodar — e uma
    verificação que atrapalha o trabalho diário é uma verificação que alguém
    comenta numa tarde ruim, o que a deixa pior do que não existir. O que se
    exige é declaração **onde a ausência dela é perigosa**: quando o banco não é
    um SQLite local. Um PostgreSQL tem endereço, credencial e gente do outro
    lado; um arquivo `app.db` é de quem clonou o repositório. O critério não
    depende de ninguém lembrar de nada — ele lê a única variável que, nesse
    cenário, a pessoa não tem como esquecer, porque sem ela a aplicação não
    encontra dado nenhum.

    Nenhuma destas recusas protege contra **decisão**: quem declarar
    `AMBIENTE=desenvolvimento` num endereço público está escolhendo, e o
    trabalho desta função é impedir esquecimento, não vetar escolha.

    As recusas, e o que cada uma protege:

    1. **Ambiente desconhecido.** `AMBIENTE=prod` não é produção para os itens
       seguintes e passaria pela verificação sem ser verificado. Fechar a lista
       transforma o typo num erro em vez de num buraco.
    2. **Ambiente não declarado com banco que não é SQLite local.** O furo
       descrito acima. A mensagem pede a declaração em vez de adivinhar o
       ambiente: adivinhar "isto deve ser produção" acertaria hoje e seria uma
       regra que ninguém consegue prever amanhã.
    3. **Chave de exemplo com banco que não é SQLite local.** O item 4 sozinho
       deixava passar `AMBIENTE=desenvolvimento` + RDS + chave de exemplo, que é
       o que sai de copiar o `.env.example` para uma task definition e trocar só
       a `DATABASE_URL`. A frase que este item torna verdadeira é curta: *a
       chave que está no repositório só protege um arquivo na máquina de quem
       clonou*.
    4. **Chave de exemplo fora de desenvolvimento/teste.** O item que dá nome a
       tudo isto.
    5. **Algoritmo de assinatura fora da lista.** `ALGORITHM` vinha do ambiente
       sem ser olhado: um valor torto não era recusado no boot, virava exceção
       no primeiro login — ou, pior, `none`, que faria a `jose` aceitar token
       sem assinatura nenhuma.
    6. **Curinga no CORS, e `http://` em produção.** `allow_origins=["*"]` com
       `allow_credentials=True` é recusado pelos próprios navegadores, então
       configurar assim produz um sintoma ("nada funciona em produção") a uma
       distância enorme da causa. E `http://` em produção é, pela lógica deste
       projeto, configuração impossível: o navegador só entrega a webcam a um
       contexto seguro, e sem webcam não há IEE — a origem em texto claro
       renderia uma tela de permissão negada sem explicação.
    7. **Registro aberto em produção.** `EMAILS_AUTORIZADOS` vazio significa
       "qualquer um se cadastra", que é o certo em desenvolvimento e é a mesma
       variável esquecida do item 2 quando o endereço é público. Em produção a
       lista é obrigatória — e quem realmente quiser cadastro aberto pode dizer
       isso declarando outro ambiente, que é uma decisão e não um descuido.
    """
    declarado = config.ambiente_declarado
    if declarado is not None and declarado not in AMBIENTES_CONHECIDOS:
        conhecidos = ", ".join(sorted(AMBIENTES_CONHECIDOS))
        raise ConfiguracaoInsegura(
            "AMBIENTE={} não é um ambiente conhecido. Use um de: {}.".format(
                declarado, conhecidos
            )
        )

    if declarado is None and not config.banco_e_local():
        conhecidos = ", ".join(sorted(AMBIENTES_CONHECIDOS))
        raise ConfiguracaoInsegura(
            "AMBIENTE não foi declarado e DATABASE_URL não aponta para um SQLite "
            "local. Sem declaração a aplicação assumiria desenvolvimento, que é "
            "onde a chave de exemplo e o cadastro aberto são tolerados — e um "
            "banco de verdade não é lugar para nenhum dos dois. Declare "
            "AMBIENTE com um de: {}.".format(conhecidos)
        )

    if config.secret_key == CHAVE_DE_EXEMPLO and not config.banco_e_local():
        raise ConfiguracaoInsegura(
            "SECRET_KEY ainda é a chave de exemplo do repositório e DATABASE_URL "
            "não aponta para um SQLite local. Essa chave está publicada no "
            "código: quem a tem assina um token válido de qualquer aluno. Gere "
            'uma chave aleatória — por exemplo `python -c "import secrets; '
            'print(secrets.token_urlsafe(64))"` — e publique-a como SECRET_KEY.'
        )

    if config.secret_key == CHAVE_DE_EXEMPLO and config.ambiente not in AMBIENTES_SEM_SEGREDO:
        raise ConfiguracaoInsegura(
            "SECRET_KEY ainda é a chave de exemplo do repositório e AMBIENTE={}. "
            "Qualquer pessoa com acesso ao código assinaria um token válido de "
            "qualquer aluno. Gere uma chave aleatória — por exemplo "
            '`python -c "import secrets; print(secrets.token_urlsafe(64))"` — e '
            "publique-a como SECRET_KEY.".format(config.ambiente)
        )

    if config.algorithm not in ALGORITMOS_CONHECIDOS:
        conhecidos = ", ".join(sorted(ALGORITMOS_CONHECIDOS))
        raise ConfiguracaoInsegura(
            "ALGORITHM={} não é um algoritmo aceito. O segredo desta aplicação é "
            "simétrico, então só a família HMAC serve. Use um de: {}.".format(
                config.algorithm, conhecidos
            )
        )

    if CURINGA in config.origens_de_cors():
        raise ConfiguracaoInsegura(
            "ORIGENS_PERMITIDAS contém '{}'. A API responde com credenciais, e o "
            "curinga nessa combinação é recusado pelo próprio navegador. Liste as "
            "origens uma a uma, separadas por vírgula.".format(CURINGA)
        )

    if config.ambiente == PRODUCAO:
        inseguras = [
            origem
            for origem in config.origens_de_cors()
            if not origem.lower().startswith(ESQUEMA_SEGURO)
        ]
        if inseguras:
            raise ConfiguracaoInsegura(
                "ORIGENS_PERMITIDAS tem origem sem HTTPS em produção: {}. O "
                "navegador só entrega a webcam a um contexto seguro, e sem "
                "webcam não há IEE — a aplicação abriria e mediria nada. Use "
                "{}.".format(", ".join(inseguras), ESQUEMA_SEGURO)
            )

    if config.ambiente == PRODUCAO and not config.emails_autorizados_a_registrar():
        raise ConfiguracaoInsegura(
            "EMAILS_AUTORIZADOS está vazio e AMBIENTE=producao. Lista vazia "
            "significa cadastro aberto a qualquer pessoa da internet, e este "
            "sistema liga a webcam de quem entra. Liste os e-mails do estudo, "
            "separados por vírgula."
        )


settings = Settings()
verificar_configuracao(settings)


@contextmanager
def configuracao_temporaria(**valores) -> Iterator[Settings]:
    """Troca os valores do `settings` do processo durante um bloco, e devolve.

    Existe para os testes que precisam observar o comportamento de um endpoint
    sob outra configuração — a lista de e-mails autorizados, o limite de
    tentativas — sem subir um processo novo para cada caso. Fica aqui, e não no
    `conftest.py`, porque quem sabe quais atributos existem é este módulo; um
    `monkeypatch.setattr` espalhado pelos testes erraria o nome em silêncio no
    dia em que um campo fosse renomeado.

    Restaura no `finally` inclusive quando o bloco levanta: um teste que falha
    não pode deixar a configuração do processo diferente para o teste seguinte,
    porque o sintoma apareceria no teste errado.
    """
    anteriores = {nome: getattr(settings, nome) for nome in valores}
    for nome, valor in valores.items():
        setattr(settings, nome, valor)
    try:
        yield settings
    finally:
        for nome, valor in anteriores.items():
            setattr(settings, nome, valor)
