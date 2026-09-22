"""A configuração que a aplicação recusa, e as origens que o CORS aceita (§1.4, §1.5).

Estes testes existem porque os defeitos que eles travam são **invisíveis em
desenvolvimento**: com a chave de exemplo tudo funciona, e com o CORS cravado em
`localhost:4200` tudo funciona — na máquina de quem escreveu. O primeiro sintoma
de qualquer um dos dois aparece depois de publicado, e o da `SECRET_KEY` não
aparece nunca, porque uma credencial forjável não produz erro.

`TestAmbienteDeclarado` trava um defeito de outra natureza, e pior: a
verificação **existia e falhava aberta**. Sem `AMBIENTE` declarado, com a chave
de exemplo e com `DATABASE_URL` apontando para um PostgreSQL, a aplicação subia
— porque o default do campo era `desenvolvimento` e desenvolvimento é isento de
segredo. A guarda desenhada contra o esquecimento tinha um esquecimento como
caminho de contorno.
"""
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import (
    CHAVE_DE_EXEMPLO,
    DESENVOLVIMENTO,
    PRODUCAO,
    TESTE,
    ConfiguracaoInsegura,
    Settings,
    verificar_configuracao,
)

#: Uma chave qualquer que não é a do repositório. O conteúdo é irrelevante — o
#: que a verificação julga é a igualdade com `CHAVE_DE_EXEMPLO`.
CHAVE_PROPRIA = "5f2b0c9d4e1a7836bb90c1d2e3f4a5b6"

ORIGEM_DO_FRONTEND = "https://mapface.exemplo.br"
ORIGEM_DE_FORA = "https://site-de-terceiro.exemplo.com"

#: Um banco que não é um arquivo da máquina de quem clonou. Não precisa existir:
#: a verificação lê a URL, não conecta.
BANCO_DE_VERDADE = "postgresql+psycopg://mapface@10.0.0.10:5432/mapface"

EMAIL_DA_TURMA = "ana@exemplo.br"


def _configuracao(**valores) -> Settings:
    """Uma `Settings` com valores explícitos, imune ao `.env` da máquina.

    Argumentos de construção vencem variáveis de ambiente e `.env` no
    pydantic-settings, então estes testes afirmam a mesma coisa na máquina do
    desenvolvedor (que tem `.env`) e na CI (que não tem).

    Os defaults preenchidos aqui são os que **passam em produção** — chave
    própria, origem em HTTPS, lista de e-mails preenchida. Cada teste varia um
    eixo e afirma sobre ele; sem esta base, um teste sobre a chave secreta
    passaria a falhar por causa do CORS, e a mensagem acusaria a regra errada.
    """
    valores.setdefault("secret_key", CHAVE_PROPRIA)
    valores.setdefault("origens_permitidas", ORIGEM_DO_FRONTEND)
    valores.setdefault("emails_autorizados", EMAIL_DA_TURMA)
    return Settings(**valores)


def _boot_em_subprocesso(**ambiente) -> subprocess.CompletedProcess:
    """Importa `app.main` num processo de verdade, com o ambiente declarado aqui.

    O processo do pytest já importou `app.config` com a configuração dele, e o
    que está sob teste é o boot inteiro — inclusive o fato de a verificação
    estar **ligada** no caminho do import. `env` substitui o ambiente por
    completo: só o que esta função declara chega lá dentro.
    """
    raiz_do_backend = Path(__file__).resolve().parents[1]
    return subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=str(raiz_do_backend),
        env={"PATH": "/usr/bin:/bin", **ambiente},
        capture_output=True,
        text=True,
    )


class TestAmbienteDeclarado:
    """A verificação distingue "não declarado" de "declarado como desenvolvimento".

    O critério escolhido não é exigir `AMBIENTE` sempre — isso quebraria
    `git clone && uvicorn` sem `.env` e obrigaria a suíte a declarar ambiente
    para rodar, e verificação que atrapalha o trabalho diário é verificação que
    alguém desliga. Exige-se declaração **onde a ausência dela é perigosa**:
    quando o banco não é um SQLite local.
    """

    def test_ambiente_nao_declarado_com_banco_de_verdade_recusa_subir(self):
        """O furo, na forma exata em que foi reproduzido.

        Quem esquece `AMBIENTE` na task definition é o mesmo perfil de quem
        esquece a `SECRET_KEY` — e, antes desta regra, esquecer a primeira dava
        isenção automática da segunda.
        """
        with pytest.raises(ConfiguracaoInsegura) as erro:
            verificar_configuracao(_configuracao(database_url=BANCO_DE_VERDADE))

        assert "AMBIENTE" in str(erro.value)

    def test_clone_novo_sem_env_nenhum_sobe(self):
        """`git clone && uvicorn`: nada declarado, SQLite local, chave de exemplo.

        É a contrapartida obrigatória do teste acima, e o que impede a correção
        de virar um campo minado no setup local.
        """
        config = _configuracao(
            secret_key=CHAVE_DE_EXEMPLO,
            database_url="sqlite:///./app.db",
            origens_permitidas="http://localhost:4200",
            emails_autorizados="",
        )

        verificar_configuracao(config)

        assert config.ambiente_declarado is None
        assert config.ambiente == DESENVOLVIMENTO

    def test_banco_de_verdade_com_ambiente_declarado_sobe(self):
        """Declarar é o bastante: a regra pede a declaração, não um valor dela."""
        verificar_configuracao(
            _configuracao(ambiente_declarado=PRODUCAO, database_url=BANCO_DE_VERDADE)
        )

    def test_chave_de_exemplo_com_banco_de_verdade_recusa_mesmo_em_desenvolvimento(self):
        """O que sai de copiar o `.env.example` e trocar só a `DATABASE_URL`.

        A isenção de segredo é de desenvolvimento **e** banco local, nunca de um
        dos dois sozinho. A frase que esta regra torna verdadeira é curta: a
        chave que está no repositório só protege um arquivo na máquina de quem
        clonou.
        """
        with pytest.raises(ConfiguracaoInsegura) as erro:
            verificar_configuracao(
                _configuracao(
                    ambiente_declarado=DESENVOLVIMENTO,
                    secret_key=CHAVE_DE_EXEMPLO,
                    database_url=BANCO_DE_VERDADE,
                )
            )

        assert "SECRET_KEY" in str(erro.value)

    def test_sqlite_de_outro_formato_ainda_e_banco_local(self):
        # `sqlite://` (em memória) e `sqlite+pysqlite:///arquivo` são os dois
        # outros jeitos de escrever a mesma coisa, e nenhum deles é uma
        # instalação de verdade.
        assert _configuracao(database_url="sqlite://").banco_e_local()
        assert _configuracao(database_url="sqlite+pysqlite:///./app.db").banco_e_local()
        assert not _configuracao(database_url=BANCO_DE_VERDADE).banco_e_local()

    def test_o_boot_de_verdade_morre_sem_ambiente_declarado(self):
        """Num processo real, sem `AMBIENTE` e com banco de verdade, não sobe.

        Este é o teste que falha contra o código anterior à correção: lá, este
        mesmo processo subia em silêncio, com a chave de exemplo, porque o
        default do campo era `desenvolvimento`. A `SECRET_KEY` própria está aqui
        de propósito — sem ela, a recusa poderia vir da regra da chave e este
        teste passaria sem provar nada sobre o `AMBIENTE`.
        """
        resultado = _boot_em_subprocesso(
            DATABASE_URL=BANCO_DE_VERDADE,
            SECRET_KEY=CHAVE_PROPRIA,
            ORIGENS_PERMITIDAS=ORIGEM_DO_FRONTEND,
            EMAILS_AUTORIZADOS=EMAIL_DA_TURMA,
        )

        assert resultado.returncode != 0
        assert "AMBIENTE" in resultado.stderr
        assert "ConfiguracaoInsegura" in resultado.stderr


class TestChaveDeExemplo:
    """§1.5 — a aplicação recusa subir com a chave que está no repositório."""

    def test_chave_de_exemplo_em_producao_recusa_subir(self):
        with pytest.raises(ConfiguracaoInsegura) as erro:
            verificar_configuracao(
                _configuracao(ambiente_declarado=PRODUCAO, secret_key=CHAVE_DE_EXEMPLO)
            )

        # A mensagem é o único texto que quem publicou vai ler antes de decidir
        # o que fazer: ela precisa nomear a variável a corrigir.
        assert "SECRET_KEY" in str(erro.value)

    @pytest.mark.parametrize("ambiente", [DESENVOLVIMENTO, TESTE])
    def test_chave_de_exemplo_e_aceita_onde_nao_ha_segredo(self, ambiente):
        """Clone novo roda, e a suíte roda em CI, sem ninguém publicar segredo.

        É a contrapartida obrigatória do teste acima: uma verificação que também
        quebrasse `git clone && uvicorn` seria desligada por quem a encontrasse
        pela frente, e aí não protegeria mais nada.
        """
        verificar_configuracao(
            _configuracao(ambiente_declarado=ambiente, secret_key=CHAVE_DE_EXEMPLO)
        )

    def test_chave_propria_em_producao_e_aceita(self):
        verificar_configuracao(_configuracao(ambiente_declarado=PRODUCAO))

    def test_ambiente_desconhecido_recusa_subir(self):
        """`AMBIENTE=prod` é um typo plausível, e o efeito dele seria silencioso.

        Com a lista de ambientes aberta, `prod` não seria `producao` e a chave de
        exemplo passaria — a verificação estaria ligada e não verificando nada.
        """
        with pytest.raises(ConfiguracaoInsegura) as erro:
            verificar_configuracao(_configuracao(ambiente_declarado="prod"))

        assert "prod" in str(erro.value)

    def test_o_boot_de_verdade_morre_com_a_chave_de_exemplo(self):
        """Importar `app.main` num processo real falha, e falha com mensagem.

        Os testes acima chamam a verificação à mão. Este verifica a única coisa
        que importa na prática: que a verificação **está ligada no caminho do
        boot**. Alguém poderia deixar `verificar_configuracao` perfeita e nunca
        chamá-la, e todos os outros testes desta classe continuariam verdes.
        """
        resultado = _boot_em_subprocesso(
            AMBIENTE=PRODUCAO,
            SECRET_KEY=CHAVE_DE_EXEMPLO,
            # Um banco que não toca o disco: o import não deve chegar a conectar,
            # e se um dia chegar, este teste não deixa lixo para trás.
            DATABASE_URL="sqlite://",
            ORIGENS_PERMITIDAS=ORIGEM_DO_FRONTEND,
            EMAILS_AUTORIZADOS=EMAIL_DA_TURMA,
        )

        assert resultado.returncode != 0
        assert "SECRET_KEY" in resultado.stderr
        assert "ConfiguracaoInsegura" in resultado.stderr


class TestAlgoritmoDeAssinatura:
    """`ALGORITHM` vem do ambiente, e agora é olhado antes de ser usado."""

    def test_algoritmo_fora_da_lista_recusa_subir(self):
        """Um valor torto virava exceção no primeiro login, não no boot."""
        with pytest.raises(ConfiguracaoInsegura) as erro:
            verificar_configuracao(_configuracao(algorithm="HS257"))

        assert "ALGORITHM" in str(erro.value)

    def test_algoritmo_none_recusa_subir(self):
        """`none` é o algoritmo que desliga a verificação de assinatura.

        É o caso que justifica a lista ser fechada em vez de um teste de
        formato: `none` tem formato impecável.
        """
        with pytest.raises(ConfiguracaoInsegura):
            verificar_configuracao(_configuracao(algorithm="none"))

    @pytest.mark.parametrize("algoritmo", ["HS256", "HS384", "HS512"])
    def test_a_familia_hmac_inteira_e_aceita(self, algoritmo):
        # São os três que combinam com um segredo simétrico. Aceitar menos que
        # isso obrigaria a mexer no código para trocar o tamanho do digest.
        verificar_configuracao(_configuracao(algorithm=algoritmo))


class TestOrigensDeCors:
    """§1.4 — as origens vêm de configuração, e o curinga é recusado."""

    def test_uma_lista_separada_por_virgula_vira_uma_origem_por_item(self):
        # Esperado calculado à mão: três itens, espaços em volta removidos, e a
        # vírgula final (o erro de digitação mais provável num .env) descartada.
        config = _configuracao(
            origens_permitidas=(
                "https://a.exemplo.br, https://b.exemplo.br ,https://c.exemplo.br,"
            )
        )

        assert config.origens_de_cors() == [
            "https://a.exemplo.br",
            "https://b.exemplo.br",
            "https://c.exemplo.br",
        ]

    def test_curinga_recusa_subir(self):
        """`*` com credenciais é recusado pelo navegador — e aqui, mais cedo."""
        with pytest.raises(ConfiguracaoInsegura) as erro:
            verificar_configuracao(
                _configuracao(ambiente_declarado=PRODUCAO, origens_permitidas="*")
            )

        assert "ORIGENS_PERMITIDAS" in str(erro.value)

    def test_origem_sem_https_em_producao_recusa_subir(self):
        """Sem HTTPS o navegador não entrega a webcam, e sem webcam não há IEE.

        A recusa é a mesma ideia do curinga: a alternativa era a aplicação subir
        inteira e o aluno ver "permissão de câmera negada" numa tela que não tem
        como explicar que a causa está numa variável de ambiente.
        """
        with pytest.raises(ConfiguracaoInsegura) as erro:
            verificar_configuracao(
                _configuracao(
                    ambiente_declarado=PRODUCAO,
                    origens_permitidas="http://mapface.exemplo.br",
                )
            )

        assert "HTTPS" in str(erro.value)

    def test_origem_sem_https_fora_de_producao_e_aceita(self):
        # `http://localhost:4200` é o frontend em desenvolvimento, e o navegador
        # trata localhost como contexto seguro justamente para isto funcionar.
        verificar_configuracao(
            _configuracao(
                ambiente_declarado=DESENVOLVIMENTO,
                origens_permitidas="http://localhost:4200",
            )
        )

    def test_aceita_a_origem_declarada(self, monkeypatch):
        """Uma origem que está na configuração recebe permissão na sondagem."""
        cliente = self._cliente_com_origens(monkeypatch, ORIGEM_DO_FRONTEND)

        resposta = cliente.options(
            "/vivo",
            headers={
                "Origin": ORIGEM_DO_FRONTEND,
                "Access-Control-Request-Method": "GET",
            },
        )

        assert resposta.status_code == 200
        assert resposta.headers["access-control-allow-origin"] == ORIGEM_DO_FRONTEND
        assert resposta.headers["access-control-allow-credentials"] == "true"

    def test_recusa_a_origem_que_nao_foi_declarada(self, monkeypatch):
        """E uma que não está, não — senão configurar origens não serviria a nada.

        A sondagem (`OPTIONS` com `Access-Control-Request-Method`) é o momento em
        que o navegador pergunta antes de mandar a chamada de verdade; é ali que
        o CORS decide, e por isso é ali que o teste observa.
        """
        cliente = self._cliente_com_origens(monkeypatch, ORIGEM_DO_FRONTEND)

        resposta = cliente.options(
            "/vivo",
            headers={
                "Origin": ORIGEM_DE_FORA,
                "Access-Control-Request-Method": "GET",
            },
        )

        assert resposta.status_code == 400
        assert "access-control-allow-origin" not in resposta.headers

    def test_chamada_simples_de_origem_nao_declarada_sai_sem_permissao(
        self, monkeypatch
    ):
        """Numa chamada sem sondagem, o veto é a **ausência** do cabeçalho.

        O servidor responde normalmente — o navegador é quem joga a resposta
        fora por não encontrar `Access-Control-Allow-Origin`. Vale afirmar
        separadamente porque é fácil ler o 200 acima como "passou".
        """
        cliente = self._cliente_com_origens(monkeypatch, ORIGEM_DO_FRONTEND)

        resposta = cliente.get("/vivo", headers={"Origin": ORIGEM_DE_FORA})

        assert resposta.status_code == 200
        assert "access-control-allow-origin" not in resposta.headers

    @staticmethod
    def _cliente_com_origens(monkeypatch, origens: str) -> TestClient:
        """Uma aplicação montada do zero com as origens deste teste.

        `criar_app` existe por causa disto: as origens são lidas na montagem, e
        sem uma fábrica o único CORS testável seria o do processo do pytest.
        """
        monkeypatch.setattr(main.settings, "origens_permitidas", origens)
        return TestClient(main.criar_app())


class TestListaDeAutorizados:
    """Quem pode se cadastrar é configuração, e em produção é obrigatória."""

    def test_lista_vazia_em_producao_recusa_subir(self):
        """Lista vazia é cadastro aberto, e este sistema liga a webcam de quem entra.

        É a mesma variável esquecida do `AMBIENTE`: o default permissivo existe
        para o clone novo funcionar, e sem esta regra ele viraria o modo de
        produção por distração.
        """
        with pytest.raises(ConfiguracaoInsegura) as erro:
            verificar_configuracao(
                _configuracao(ambiente_declarado=PRODUCAO, emails_autorizados="")
            )

        assert "EMAILS_AUTORIZADOS" in str(erro.value)

    def test_lista_vazia_fora_de_producao_e_aceita(self):
        verificar_configuracao(
            _configuracao(ambiente_declarado=DESENVOLVIMENTO, emails_autorizados="")
        )

    def test_a_lista_e_normalizada_e_tolera_espacos_e_maiusculas(self):
        # Esperado à mão: três endereços, minúsculos, sem espaços, e o item
        # vazio da vírgula sobrando descartado.
        config = _configuracao(
            emails_autorizados=" Ana@Exemplo.BR, bruno@exemplo.br ,CARLA@exemplo.br,"
        )

        assert config.emails_autorizados_a_registrar() == frozenset(
            {"ana@exemplo.br", "bruno@exemplo.br", "carla@exemplo.br"}
        )

    def test_lista_vazia_e_um_conjunto_vazio(self):
        # E não `{""}`, que autorizaria um e-mail impossível e, pior, faria a
        # lista parecer preenchida para quem só testasse `if autorizados`.
        assert _configuracao(emails_autorizados="   ").emails_autorizados_a_registrar() == frozenset()
