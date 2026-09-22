"""Teto de tamanho do corpo do request, aplicado antes de bufferizar qualquer coisa.

Como `app/presenca.py` e `app/metodos.py`, este módulo não conhece banco; ao
contrário deles, conhece HTTP — é a única coisa que ele faz.

**Qual buraco isto fecha.** Um `max_length` de campo só age depois que o corpo
inteiro já entrou: o servidor lê os bytes todos, o pydantic olha, e só então
recusa. Numa instância só — que é o que vai ao ar — "recusado depois de
carregado" e "aceito" custam a mesma memória. `POST /auth/registro` com dezenas
de megabytes de `nome` era exatamente isso: a recusa que os tetos de campo agora
produzem ainda seria paga em RAM por quem hospeda, e não por quem manda.

**O que exatamente é recusado.** Um `Content-Length` declarado acima do teto,
com **413**, sem ler um byte do corpo e sem tocar na aplicação. O cabeçalho é
uma declaração do cliente, e recusar pela declaração é o único jeito de recusar
*antes* do custo — conferir contando os bytes que chegam já seria tê-los
recebido.

**O que não é recusado, e por que fica assim.** Um request sem `Content-Length`,
em `Transfer-Encoding: chunked`, passa direto. Duas alternativas foram
descartadas:

1. *Contar os bytes conforme chegam.* Exige embrulhar o canal `receive` e
   abortar no meio de um corpo que a aplicação já começou a ler — em ASGI isso
   significa ou devolver um corpo truncado (a aplicação veria JSON cortado e
   responderia 422, uma mentira sobre o que aconteceu) ou derrubar a conexão sem
   resposta. Troca um defeito claro por um comportamento difícil de explicar.
2. *Recusar `chunked` com 411.* Fecharia o buraco em três linhas, e quebraria a
   produção: o ALB converte requests HTTP/2 do navegador para HTTP/1.1 na perna
   até a aplicação, e pode reemitir o corpo em chunks. A regra recusaria
   tráfego legítimo por uma escolha do balanceador que ninguém controla daqui.

Todo cliente desta API — o Angular via `fetch`, o `httpx` da suíte, `curl`
com `--data` — declara `Content-Length` em corpo JSON. A brecha exige um cliente
feito de propósito, e é onde uma regra de WAF entra (ver abaixo).

Para quem cuida da infraestrutura
---------------------------------

**A recomendação é que o teto fique no código, como está aqui, e o ALB seja
complemento — não substituto.** Três razões:

1. **O ALB não tem essa regra para dar.** Um Application Load Balancer limita
   tamanho de cabeçalho e número de headers; ele **não** tem um limite
   configurável de tamanho de corpo para HTTP. Quem tem é o AWS WAF, e aí já é
   outro recurso, com outro custo e outro dono. "Deixar para o ALB" não é uma
   decisão que possa ser executada.
2. **O teto precisa existir onde a aplicação roda**, e ela roda em mais de um
   lugar: no `docker-compose` da máquina de quem desenvolve, na instância do
   teste com usuários e no notebook ligado ao projetor na defesa. Só o primeiro
   desses tem balanceador na frente. Proteção que mora na borda protege o que
   está atrás *daquela* borda.
3. **É uma linha de código e nenhum custo de operação.** Onde a diferença de
   preço entre as duas opções é essa, a que não depende de ninguém lembrar de
   configurar ganha.

O que **vale** pedir à infraestrutura, por cima disto:

- Uma regra de WAF `SizeRestrictions_BODY` na frente do ALB, que recusa o corpo
  grande antes de ele chegar a gastar banda e CPU da instância — e que, ao
  contrário deste middleware, também alcança o caso `chunked` descrito acima.
- `client_max_body_size` equivalente em qualquer proxy que venha a ser posto na
  frente (nginx, CloudFront), alinhado com `LIMITE_DE_CORPO_BYTES`.

Nenhum dos dois é pré-requisito para publicar: sem eles, o teto daqui já vale.
"""
import json
from typing import Awaitable, Callable, MutableMapping, Optional

from fastapi import status

#: Maior corpo aceito, em bytes.
#:
#: **De onde sai.** O maior corpo legítimo desta API é o cadastro: `nome` (120
#: caracteres), `email` (320 no pior caso do RFC 5321), `senha` (72 bytes) e a
#: pontuação do JSON em volta — menos de 1 KB somando com folga. O segundo maior
#: é `POST /sessoes`, com um código de método, um assunto de 120 e um inteiro.
#: Nada mais nesta API tem corpo: a telemetria, que é o único fluxo de volume,
#: viaja por WebSocket e não passa por aqui.
#:
#: 64 KB é, portanto, umas sessenta vezes o maior request honesto que existe. A
#: folga é de propósito. O trabalho deste número **não** é validar tamanho de
#: campo — isso é de `app/schemas.py`, que sabe o que cada campo significa e
#: devolve 422 dizendo qual campo e por quê. O trabalho dele é impedir que a
#: memória da instância seja escolhida por um desconhecido, e para isso a
#: diferença entre 1 KB e 64 KB é nenhuma. Um teto justo, por outro lado, viraria
#: um segundo validador escondido: no dia em que um campo crescesse, a falha
#: apareceria como um 413 sem nome de campo, no lugar errado, e custaria uma
#: tarde para alguém entender.
LIMITE_DE_CORPO_BYTES = 64 * 1024

#: Resposta do 413. Diz o teto porque o cliente legítimo que bater nele precisa
#: saber de quanto ele é; não diz quanto veio, para não repetir de volta um
#: número que o próprio cliente declarou.
MENSAGEM_DE_CORPO_GRANDE = (
    f"Corpo do request grande demais: o limite é de {LIMITE_DE_CORPO_BYTES} bytes."
)

Escopo = MutableMapping[str, object]
Receber = Callable[[], Awaitable[MutableMapping[str, object]]]
Enviar = Callable[[MutableMapping[str, object]], Awaitable[None]]


class LimiteDeCorpo:
    """Middleware ASGI que recusa `Content-Length` acima do teto, com 413.

    **ASGI puro, e não `BaseHTTPMiddleware`.** A classe do Starlette é mais
    curta de escrever e só enxerga requests HTTP — o que aqui seria uma
    armadilha silenciosa, porque a telemetria deste projeto é um WebSocket de
    vida longa e um middleware que não entende `scope["type"]` é exatamente como
    se quebra um. Aqui o desvio do WebSocket é a primeira linha do método, à
    vista, com teste que o prova. Além disso `BaseHTTPMiddleware` embrulha o
    corpo num par de tasks para poder inspecioná-lo, que é precisamente o custo
    que este middleware existe para não pagar.

    **Responde sem drenar o corpo, de propósito.** Ler os bytes que se acabou de
    declarar grandes demais desfaria o middleware. A conexão HTTP/1.1 morre
    depois da resposta, e é o desfecho certo: quem mandou 50 MB não tem direito
    a reaproveitar a conexão.
    """

    def __init__(self, app, limite_bytes: int = LIMITE_DE_CORPO_BYTES) -> None:
        # `limite_bytes` é parâmetro, e não leitura direta da constante, para
        # que o teste possa provar a regra com números pequenos em vez de
        # empurrar 64 KB por um cliente de teste a cada asserção.
        self.app = app
        self.limite_bytes = limite_bytes

    async def __call__(self, scope: Escopo, receive: Receber, send: Enviar) -> None:
        if scope.get("type") != "http" or not self._passou_do_teto(scope):
            await self.app(scope, receive, send)
            return

        await self._recusar(send)

    def _passou_do_teto(self, scope: Escopo) -> bool:
        declarado = self._content_length(scope)
        return declarado is not None and declarado > self.limite_bytes

    @staticmethod
    def _content_length(scope: Escopo) -> Optional[int]:
        """O `Content-Length` declarado, ou `None` quando não dá para saber.

        `None` cobre dois casos que terminam igual — o cabeçalho ausente e o
        cabeçalho ilegível (`"abacaxi"`) — e nos dois o request segue em
        frente. Não é leniência: um `Content-Length` malformado é erro
        de protocolo, e quem tem autoridade para respondê-lo é o servidor HTTP,
        não um middleware da aplicação. Adivinhar aqui produziria um 413 para o
        que é, na verdade, um 400.
        """
        for nome, valor in scope.get("headers", []):
            if nome.lower() != b"content-length":
                continue
            try:
                return int(valor)
            except ValueError:
                return None
        return None

    @staticmethod
    async def _recusar(send: Enviar) -> None:
        corpo = json.dumps({"detail": MENSAGEM_DE_CORPO_GRANDE}).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(corpo)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": corpo})
