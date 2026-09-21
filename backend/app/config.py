"""Configuração lida do ambiente, e o que a aplicação recusa antes de subir.

Este módulo faz duas coisas que parecem uma só: lê os valores (`Settings`) e
**julga** se a combinação deles pode ir para o ar (`verificar_configuracao`). A
segunda roda no import, o que significa que uma configuração insegura não vira
um erro no primeiro request — vira um processo que não sobe. Ver §1.4 e §1.5 do
plano de produção.
"""
from typing import FrozenSet, List

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

#: Onde a chave de exemplo ainda é aceita. `teste` está aqui porque a suíte roda
#: sem `.env` nenhum, em máquina de CI que não tem segredo a oferecer — e exigir
#: um segredo para rodar teste só ensinaria a inventar um e versioná-lo.
AMBIENTES_SEM_SEGREDO: FrozenSet[str] = frozenset({DESENVOLVIMENTO, TESTE})

#: O curinga de CORS. Recusado, não ignorado — ver `verificar_configuracao`.
CURINGA = "*"


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

    # Qual dos ambientes conhecidos está rodando. O default é desenvolvimento
    # porque é o único que não pode exigir declaração: é o estado de quem acabou
    # de clonar o repositório e da suíte de testes.
    #
    # Inverter (default `producao`, dev declarado) foi considerado e descartado:
    # seria mais seguro por construção e quebraria os 383 testes e o primeiro
    # `uvicorn` de qualquer pessoa nova. A segurança aqui vem da verificação
    # explícita, não de um default hostil.
    ambiente: str = DESENVOLVIMENTO

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

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

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

    As três recusas, e o que cada uma protege:

    1. **Ambiente desconhecido.** `AMBIENTE=prod` não é produção para o item 2 e
       passaria pela verificação sem ser verificado. Fechar a lista transforma o
       typo num erro em vez de num buraco.
    2. **Chave de exemplo fora de desenvolvimento/teste.** O item que dá nome a
       tudo isto.
    3. **Curinga no CORS.** `allow_origins=["*"]` com `allow_credentials=True` é
       recusado pelos próprios navegadores, então configurar assim produz um
       sintoma ("nada funciona em produção") a uma distância enorme da causa. E
       se um dia as credenciais saírem do meio, o curinga abre a API para
       qualquer página da internet. Recusar aqui custa uma linha e economiza a
       tarde inteira de depuração.
    """
    if config.ambiente not in AMBIENTES_CONHECIDOS:
        conhecidos = ", ".join(sorted(AMBIENTES_CONHECIDOS))
        raise ConfiguracaoInsegura(
            "AMBIENTE={} não é um ambiente conhecido. Use um de: {}.".format(
                config.ambiente, conhecidos
            )
        )

    if config.secret_key == CHAVE_DE_EXEMPLO and config.ambiente not in AMBIENTES_SEM_SEGREDO:
        raise ConfiguracaoInsegura(
            "SECRET_KEY ainda é a chave de exemplo do repositório e AMBIENTE={}. "
            "Qualquer pessoa com acesso ao código assinaria um token válido de "
            "qualquer aluno. Gere uma chave aleatória — por exemplo "
            '`python -c "import secrets; print(secrets.token_urlsafe(64))"` — e '
            "publique-a como SECRET_KEY.".format(config.ambiente)
        )

    if CURINGA in config.origens_de_cors():
        raise ConfiguracaoInsegura(
            "ORIGENS_PERMITIDAS contém '{}'. A API responde com credenciais, e o "
            "curinga nessa combinação é recusado pelo próprio navegador. Liste as "
            "origens uma a uma, separadas por vírgula.".format(CURINGA)
        )


settings = Settings()
verificar_configuracao(settings)
