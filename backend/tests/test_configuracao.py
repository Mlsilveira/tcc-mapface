"""A configuração que a aplicação recusa, e as origens que o CORS aceita (§1.4, §1.5).

Estes testes existem porque os dois defeitos que eles travam são **invisíveis em
desenvolvimento**: com a chave de exemplo tudo funciona, e com o CORS cravado em
`localhost:4200` tudo funciona — na máquina de quem escreveu. O primeiro sintoma
de qualquer um dos dois aparece depois de publicado, e o da `SECRET_KEY` não
aparece nunca, porque uma credencial forjável não produz erro.
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


def _configuracao(**valores) -> Settings:
    """Uma `Settings` com valores explícitos, imune ao `.env` da máquina.

    Argumentos de construção vencem variáveis de ambiente e `.env` no
    pydantic-settings, então estes testes afirmam a mesma coisa na máquina do
    desenvolvedor (que tem `.env`) e na CI (que não tem).
    """
    valores.setdefault("secret_key", CHAVE_PROPRIA)
    return Settings(**valores)


class TestChaveDeExemplo:
    """§1.5 — a aplicação recusa subir com a chave que está no repositório."""

    def test_chave_de_exemplo_em_producao_recusa_subir(self):
        with pytest.raises(ConfiguracaoInsegura) as erro:
            verificar_configuracao(
                _configuracao(ambiente=PRODUCAO, secret_key=CHAVE_DE_EXEMPLO)
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
            _configuracao(ambiente=ambiente, secret_key=CHAVE_DE_EXEMPLO)
        )

    def test_chave_propria_em_producao_e_aceita(self):
        verificar_configuracao(_configuracao(ambiente=PRODUCAO))

    def test_ambiente_desconhecido_recusa_subir(self):
        """`AMBIENTE=prod` é um typo plausível, e o efeito dele seria silencioso.

        Com a lista de ambientes aberta, `prod` não seria `producao` e a chave de
        exemplo passaria — a verificação estaria ligada e não verificando nada.
        """
        with pytest.raises(ConfiguracaoInsegura) as erro:
            verificar_configuracao(_configuracao(ambiente="prod"))

        assert "prod" in str(erro.value)

    def test_o_boot_de_verdade_morre_com_a_chave_de_exemplo(self):
        """Importar `app.main` num processo real falha, e falha com mensagem.

        Os testes acima chamam a verificação à mão. Este verifica a única coisa
        que importa na prática: que a verificação **está ligada no caminho do
        boot**. Alguém poderia deixar `verificar_configuracao` perfeita e nunca
        chamá-la, e todos os outros testes desta classe continuariam verdes.

        Roda em subprocesso porque é o boot inteiro que está sob teste, e porque
        o processo do pytest já importou `app.config` com a configuração dele.
        """
        ambiente = {
            "PATH": "/usr/bin:/bin",
            "AMBIENTE": PRODUCAO,
            "SECRET_KEY": CHAVE_DE_EXEMPLO,
            # Um banco que não toca o disco: o import não deve chegar a conectar,
            # e se um dia chegar, este teste não deixa lixo para trás.
            "DATABASE_URL": "sqlite://",
        }
        raiz_do_backend = Path(__file__).resolve().parents[1]

        resultado = subprocess.run(
            [sys.executable, "-c", "import app.main"],
            cwd=str(raiz_do_backend),
            env=ambiente,
            capture_output=True,
            text=True,
        )

        assert resultado.returncode != 0
        assert "SECRET_KEY" in resultado.stderr
        assert "ConfiguracaoInsegura" in resultado.stderr


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
                _configuracao(ambiente=PRODUCAO, origens_permitidas="*")
            )

        assert "ORIGENS_PERMITIDAS" in str(erro.value)

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
