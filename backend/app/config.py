from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuração da aplicação, lida de variáveis de ambiente / .env.

    Ticket 3 (Cadastro e login) usa SQLite por padrão para manter o escopo
    restrito à autenticação. A troca para PostgreSQL (previsto no plano de
    sprints / ticket 14 de infraestrutura) é apenas uma mudança de
    DATABASE_URL — o SQLModel já é compatível com ambos.
    """

    database_url: str = "sqlite:///./app.db"
    secret_key: str = "troque-esta-chave-por-um-valor-aleatorio-e-secreto"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

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


settings = Settings()
