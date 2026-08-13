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

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
