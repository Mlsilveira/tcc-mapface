"""Log da aplicação — o que ele registra e, sobretudo, o que ele recusa (§2.3).

Até aqui `grep -rn "logging" app/` não devolvia uma linha. Enquanto tudo roda na
máquina do desenvolvedor isso passa: o traceback do uvicorn aparece no terminal
que está aberto ali do lado. Fora dela não há terminal nenhum — há um contêiner
cujo stdout alguém lê depois, e uma apresentação em que a pergunta "o que
aconteceu?" precisa de resposta em segundos.

**Por que JSON, e não uma linha legível.** O destino do stdout de um contêiner é
um agregador (CloudWatch, no caso previsto), e lá a diferença entre uma linha de
texto e um objeto é a diferença entre `grep` e consulta por campo: "todas as
sessões encerradas por ausência da última hora" é uma pergunta trivial se
`id_sessao` é um campo, e um exercício de expressão regular se é substring de
uma frase. A alternativa descartada foi um formato humano com `%(asctime)s` —
mais confortável de ler no terminal, e é exatamente no terminal que ele menos
faz falta, porque lá o volume é pequeno.

**Por que um logger próprio e não `logging.basicConfig`.** `basicConfig` mexe no
logger raiz, que é território do uvicorn: ele chama `dictConfig` ao subir e
qualquer coisa que a aplicação tenha configurado antes vira efeito colateral
difícil de explicar (linha duplicada, formato de um vencendo o do outro). Uma
árvore `mapface.*` com handler próprio convive com o que o servidor fizer.

A propagação para o raiz fica **ligada** de propósito. Desligá-la seria o
isolamento completo, e custaria a captura por ferramentas que escutam no raiz —
o `caplog` do pytest é a que os testes desta seção usam para afirmar o que **não**
sai no log. Como o raiz não ganha handler nosso, propagar não duplica nada.

**O que nunca entra numa linha de log.** O eixo do TCC é privacidade, e log é o
lugar clássico onde um dado pessoal escapa por conveniência de depuração:

- **Conteúdo de aluno.** `assunto` e `meta` são texto autoral. Um log de
  encerramento com o assunto dentro seria confortável ("sessão de Cálculo II
  encerrada") e transformaria o agregador num arquivo do que cada pessoa estuda.
- **E-mail.** O sistema já identifica por id numérico em quase tudo; o log segue
  a mesma moeda. Id é suficiente para investigar (dá para chegar ao aluno pelo
  banco, com motivo) e insuficiente para vazar por leitura casual.
- **Senha em URL de banco.** `DATABASE_URL` de produção carrega credencial, e a
  linha de boot é justamente onde ela apareceria — ver `banco_sem_segredo`.

Nada disso é preferência de estilo: é a diferença entre "nenhuma imagem sai do
seu computador" ser verdade sobre o sistema inteiro ou só sobre a webcam.
"""
import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Optional

#: Raiz da árvore de loggers da aplicação. Todo logger daqui nasce abaixo dela,
#: para que um único `setLevel` alcance o sistema inteiro sem alcançar o uvicorn.
RAIZ = "mapface"

#: Nome da chave em `extra=` que carrega os campos estruturados da linha.
#: Existe porque `extra` despeja as chaves direto no `LogRecord`, onde elas
#: colidem com atributos reservados (`name`, `message`, `args`): um campo nosso
#: chamado `module` derrubaria o próprio log. Aninhar sob um nome só isola.
CONTEXTO = "contexto"


class FormatadorJson(logging.Formatter):
    """Uma linha, um objeto JSON.

    Os quatro campos fixos (`instante`, `nivel`, `origem`, `mensagem`) estão em
    toda linha; o resto vem do `contexto` de quem registrou. Chave de contexto
    que colida com campo fixo perde — o cabeçalho da linha não é negociável, e
    sobrescrevê-lo produziria um log em que `nivel` significa coisas diferentes
    em linhas diferentes.

    `default=str` no `json.dumps` cobre `datetime` e `timedelta`, que aparecem
    naturalmente no contexto deste projeto. A alternativa — exigir que quem
    registra converta antes — só garantiria que um dia alguém esqueceria e
    perderia a linha inteira para um `TypeError` dentro do logger.
    """

    def format(self, record: logging.LogRecord) -> str:
        linha: Dict[str, Any] = {
            "instante": datetime.fromtimestamp(
                record.created, timezone.utc
            ).isoformat(),
            "nivel": record.levelname,
            "origem": record.name,
            "mensagem": record.getMessage(),
        }

        contexto = getattr(record, CONTEXTO, None)
        if isinstance(contexto, dict):
            for chave, valor in contexto.items():
                if chave not in linha:
                    linha[chave] = valor

        if record.exc_info:
            linha["excecao"] = self.formatException(record.exc_info)

        return json.dumps(linha, ensure_ascii=False, default=str)


def configurar_logs(nivel: str = "INFO") -> None:
    """Instala o handler JSON na árvore `mapface`.

    Idempotente por construção: os handlers anteriores são descartados antes de
    o novo entrar. Sem isso, cada chamada acrescentaria uma saída e a mesma
    linha sairia duas, três, quatro vezes — o que acontece de fato nos testes,
    onde o módulo é importado e reconfigurado mais de uma vez no mesmo processo.

    Escreve em `stdout`, não em `stderr`: num contêiner os dois vão para o mesmo
    lugar, e `stdout` é onde o agregador espera encontrar o fluxo normal. Erro
    não é exceção a isso — o nível já está na linha, e separar por descritor
    faria a ordem entre uma falha e o que a precedeu depender do buffer.
    """
    raiz = logging.getLogger(RAIZ)
    for anterior in list(raiz.handlers):
        raiz.removeHandler(anterior)

    manipulador = logging.StreamHandler(sys.stdout)
    manipulador.setFormatter(FormatadorJson())
    raiz.addHandler(manipulador)
    raiz.setLevel(nivel.upper())


def obter_logger(nome: str) -> logging.Logger:
    """Logger de um módulo, sempre abaixo da raiz `mapface`."""
    return logging.getLogger("{}.{}".format(RAIZ, nome))


def registrar(
    logger: logging.Logger,
    nivel: int,
    mensagem: str,
    contexto: Optional[Dict[str, Any]] = None,
    exc_info: bool = False,
) -> None:
    """Emite uma linha com campos estruturados, sem repetir o `extra={...}`.

    Existe para que o nome `CONTEXTO` apareça num lugar só. Espalhado pelos
    módulos, bastaria alguém escrever `extra={"id_sessao": 1}` direto — o que
    funciona, até o dia em que o campo se chamar `message` e o log morrer.
    """
    logger.log(nivel, mensagem, extra={CONTEXTO: contexto or {}}, exc_info=exc_info)


def banco_sem_segredo(url: str) -> str:
    """A URL do banco como ela pode aparecer num log: sem a senha.

    `DATABASE_URL` de produção é `postgresql://usuario:senha@host/base`. Ela
    precisa aparecer no boot — saber contra qual banco a aplicação subiu é
    metade das investigações — e a senha, não.

    Delegado ao SQLAlchemy em vez de uma expressão regular própria: ele já
    entende as formas que uma URL de conexão assume (senha com `@`, com `:`,
    percent-encoded), e cada uma delas é uma chance de a regex deixar passar. Se
    a URL não for sequer analisável, o retorno é um marcador — devolver a
    original "porque não deu para limpar" seria vazar exatamente no caso em que
    menos se sabe o que ela contém.
    """
    try:
        from sqlalchemy.engine import make_url

        return make_url(url).render_as_string(hide_password=True)
    except Exception:
        return "<url de banco ilegível>"
