from datetime import datetime
from typing import Annotated, Dict, Iterable, List, Optional

from pydantic import (
    AfterValidator,
    BaseModel,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)

from app import blocos, criterios, metodos, recomendacoes
from app.models import LogEngajamento, SessaoEstudo
from app.relatorio import RelatorioDaSessao, ResumoDaSessao
from app.tempo import como_utc

# bcrypt não aceita segredos acima de 72 bytes. O limite é em bytes, não em
# caracteres: acentos ocupam 2 bytes em UTF-8.
LIMITE_SENHA_BYTES = 72


def _dentro_do_limite_do_bcrypt(senha: str) -> str:
    if len(senha.encode("utf-8")) > LIMITE_SENHA_BYTES:
        raise ValueError(f"a senha não pode passar de {LIMITE_SENHA_BYTES} bytes")
    return senha


Senha = Annotated[str, Field(min_length=8), AfterValidator(_dentro_do_limite_do_bcrypt)]


#: Teto de tamanho do nome do aluno, em **caracteres**.
#:
#: Mesma natureza de `LIMITE_ASSUNTO_CARACTERES` — limite de produto, medido em
#: caracteres porque é o que a pessoa vê enquanto digita — com uma urgência que
#: o assunto não tem: `nome` é o único texto livre de um endpoint **público**.
#: `POST /auth/registro` não pede token, e um campo sem teto do outro lado
#: significa que qualquer pessoa na internet escolhe quantos bytes a instância
#: (uma só) vai bufferizar, gravar no banco e depois repetir em **toda** resposta
#: que traga o aluno. Não era hipótese: a auditoria mandou 200 mil caracteres e
#: recebeu 201, com os 200 mil persistidos.
#:
#: 120, e não um número apertado, porque nome de pessoa não é vocabulário que se
#: possa derivar como os códigos logo abaixo: nome civil brasileiro com os
#: sobrenomes das duas famílias passa de 60 caracteres sem esforço, e um teto
#: curto demais recusaria gente real na tela de cadastro — o pior defeito
#: possível num campo de identidade, porque a pessoa não tem como contornar. É o
#: mesmo 120 do assunto pelo mesmo motivo: os dois são rótulos que a interface
#: desenha em uma linha, ao lado de outra coisa.
LIMITE_NOME_CARACTERES = 120


def _teto_de_vocabulario(valores: Iterable[str]) -> int:
    """O teto de um campo cujo conjunto de valores válidos o servidor conhece.

    `metodo`, `tipo` e `origem` não são texto livre: os valores aceitos estão em
    `app/metodos.py` e `app/blocos.py`, e o maior de todos tem 10 caracteres
    (`timeboxing`). O teto sai daí em vez de ser escolhido, e a diferença é que
    ele acompanha o catálogo sozinho — no dia em que um método de código mais
    longo entrar, ninguém precisa lembrar de vir aqui ajustar um número.

    **O dobro do maior código, e não o próprio.** O 422 de código desconhecido é
    uma ajuda: ele repete o que chegou e aponta `GET /metodos`. Apertado no valor
    exato, um erro de digitação com um caractere a mais (`"pomodoroo"`, ou
    `"timeboxing "` com o espaço que o campo colou) deixaria de chegar naquela
    mensagem e receberia `String should have at most 10 characters`, que não
    ajuda ninguém a consertar nada. O dobro dá espaço para todo engano plausível
    e continua sendo teto: um valor duas vezes mais longo que o maior código
    válido não é engano, é sondagem.
    """
    return 2 * max(len(valor) for valor in valores)


#: Teto do código de método aceito em `POST /sessoes` — ver `_teto_de_vocabulario`.
LIMITE_CODIGO_DE_METODO = _teto_de_vocabulario(metodos.METODOS)

#: Tetos do tipo e da origem aceitos em `POST /sessoes/{id}/blocos`, pela mesma
#: regra e pelo mesmo motivo: os dois vocabulários estão em `app/blocos.py`.
LIMITE_TIPO_DE_BLOCO = _teto_de_vocabulario(blocos.TIPOS)
LIMITE_ORIGEM_DE_BLOCO = _teto_de_vocabulario(blocos.ORIGENS)


#: Quantos caracteres de um texto recebido sobrevivem até a resposta de erro.
#:
#: **Por que um teto de campo não basta.** O 422 do pydantic carrega, no campo
#: `input`, o valor recebido **inteiro**. Pôr `max_length` no `nome` e parar por
#: aí trocaria "200 KB aceitos e gravados" por "200 KB devolvidos na mensagem de
#: erro": a recusa passaria a custar mais banda que a aceitação, e quem manda o
#: lixo continuaria pagando o mesmo de sempre. É a amplificação por reflexão da
#: auditoria, entrando pela porta do validador em vez da porta da mensagem
#: escrita à mão.
#:
#: **De onde sai o número.** 320 é o maior endereço de e-mail que o RFC 5321
#: admite (64 de parte local, `@`, 255 de domínio), e e-mail é o campo de texto
#: mais longo que esta API pode legitimamente receber — todos os tetos declarados
#: acima ficam bem abaixo dele. Ou seja: nenhum valor que algum dia fosse aceito
#: passa pela tesoura, e o corte só alcança o que já estava condenado.
LIMITE_DE_ECO_CARACTERES = 320


def _recortado_para_o_erro(valor: object) -> object:
    """Texto longo demais, cortado no tamanho em que a recusa ainda é a mesma.

    Deixa **um caractere a mais** que `LIMITE_DE_ECO_CARACTERES`, e não o
    tamanho exato: é o que mantém reprovado o que estava reprovado. Cortar para
    dentro do limite de um campo transformaria entrada inválida em válida, que é
    o jeito mais bobo possível de abrir um buraco enquanto se fecha outro.

    Devolve o que não for texto sem tocar — número, nulo, lista, objeto
    aninhado. Quem decide o que cada campo aceita continua sendo o campo.
    """
    if isinstance(valor, str) and len(valor) > LIMITE_DE_ECO_CARACTERES:
        return valor[: LIMITE_DE_ECO_CARACTERES + 1]
    return valor


class CorpoRecebido(BaseModel):
    """Corpo de request com os textos absurdos cortados antes da validação.

    **Isto não é validação.** Nada aqui aceita ou recusa nada: quem recusa
    continua sendo o `max_length` de cada campo, aplicado a um valor que já está
    comprovadamente acima de qualquer teto desta API. O que muda é só o tamanho
    da resposta de erro, que deixa de ser proporcional ao que o cliente mandou e
    passa a ser constante.

    **Por que aqui e não num handler de `RequestValidationError`.** O handler
    seria mais abrangente — pegaria todo campo de todo modelo de uma vez, sem
    ninguém ter que lembrar de herdar desta classe. Foi descartado por dois
    motivos. Ele mora na montagem da aplicação, em `app/main.py`, que nesta
    rodada tem outro dono; e, mais de fundo, ele mudaria a forma de **toda**
    resposta 422 da API, inclusive as que hoje ajudam o cliente a se corrigir.
    Isto aqui é local, mede-se pela definição dos campos e não esconde nada de
    quem está depurando: sobram 321 caracteres na mensagem, um a mais que o
    maior valor legítimo que esta API poderia receber.
    """

    @model_validator(mode="before")
    @classmethod
    def _cortar_textos_absurdos(cls, dados: object) -> object:
        # Só o corpo JSON de objeto passa por aqui. Construção em código com
        # argumentos nomeados chega como dicionário igual; qualquer outra coisa
        # (um modelo já pronto, por exemplo) segue intacta.
        if not isinstance(dados, dict):
            return dados

        return {chave: _recortado_para_o_erro(valor) for chave, valor in dados.items()}


#: Teto de tamanho do assunto declarado pelo aluno, em **caracteres**.
#:
#: O precedente no projeto é `LIMITE_SENHA_BYTES`, e a unidade muda de propósito:
#: lá o limite é técnico (o bcrypt trunca acima de 72 bytes) e por isso se mede
#: em bytes; aqui não há limite técnico nenhum — o `VARCHAR` do SQLite aceitaria
#: um capítulo inteiro. O limite é de produto, e produto se mede em caracteres,
#: porque é o que o aluno vê digitando.
#:
#: **Por que existe um teto.** `assunto` é o primeiro campo de conteúdo autoral
#: do banco, num sistema cujo eixo é privacidade: nada o lê, nada o indexa, nada
#: o analisa, e é isso que precisa continuar verdadeiro. Campo curto é rótulo —
#: "Cálculo II, integrais por partes" —, e rótulo o aluno reconhece no
#: histórico. Campo longo convida a diário, e diário num banco que ninguém
#: prometeu proteger como diário é uma promessa quebrada que ninguém chegou a
#: fazer em voz alta. 120 caracteres cabem um título de matéria com o recorte do
#: dia e não cabem um desabafo.
LIMITE_ASSUNTO_CARACTERES = 120

#: Teto da meta de blocos declarada pelo aluno.
#:
#: Uma sessão aqui é **um ciclo** (a pausa longa encerra a sessão), e o ciclo
#: mais longo do catálogo é o Pomodoro, com 4 blocos de foco. Doze é três ciclos
#: — folga de sobra para qualquer método que venha a entrar, e ainda assim um
#: número. Sem teto, `meta_de_blocos` seria um inteiro livre vindo do cliente que
#: o relatório depois leria em voz alta: "você planejou 900000 blocos, foram
#: executados 3".
META_MAXIMA_DE_BLOCOS = 12


def _assunto_util(valor: Optional[str]) -> Optional[str]:
    """Espaço em branco não é assunto declarado.

    Um campo que o aluno deixou com três espaços tem que virar `None`, e não uma
    string em branco: o relatório da sessão sem assunto mostra traço, e "  " não
    é traço nem é assunto — é um terceiro estado que nenhuma tela sabe desenhar.
    """
    if valor is None:
        return None

    limpo = valor.strip()
    return limpo or None


Assunto = Annotated[str, Field(max_length=LIMITE_ASSUNTO_CARACTERES)]


class AlunoRegistro(CorpoRecebido):
    """O cadastro, que é o **único** corpo desta API aberto a quem não tem token.

    Herda de `CorpoRecebido` por isso: aqui o tamanho da entrada é escolhido por
    um desconhecido, e os três campos precisam ter teto e ter resposta de erro de
    tamanho constante. `senha` já tinha o dele desde sempre
    (`LIMITE_SENHA_BYTES`); `nome` não tinha nenhum.
    """

    nome: str = Field(min_length=1, max_length=LIMITE_NOME_CARACTERES)
    email: EmailStr
    senha: Senha


class AlunoLogin(BaseModel):
    email: EmailStr
    senha: str


class AlunoPublico(BaseModel):
    id: int
    nome: str
    email: EmailStr

    model_config = {"from_attributes": True}


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


def _nome_do_metodo(codigo: Optional[str]) -> Optional[str]:
    """O nome legível de um método, ou `None` quando não há método.

    `None` aqui é o que a interface desenha como traço — sessão anterior ao
    recurso, que nunca declarou nada. Não confundir com `"livre"`, que tem nome
    próprio ("Sem método") porque foi uma escolha.

    Código fora do catálogo devolve o próprio código, no mesmo espírito de
    `recomendacoes.nome_do_alerta`: um rótulo sem tradução na tela é um bug
    visível, e um campo silenciosamente apagado é um bug invisível.
    """
    if codigo is None:
        return None

    metodo = metodos.buscar(codigo)
    return metodo.nome if metodo is not None else codigo


class SessaoPublica(BaseModel):
    """A sessão como a tela a consome — inclusive a tela que conduz o método.

    `metodo` e `metodo_nome` viajam juntos pelo mesmo motivo que em
    `AlertaPublico`: o código serve à máquina (é ele que o cliente compara com o
    catálogo para saber quantos minutos tem o bloco) e o nome serve à pessoa.

    `meta_de_blocos` entra porque o cronômetro precisa dela para escrever "bloco
    2 de 4" depois de um reload, quando o cliente já perdeu o que o aluno
    declarou na tela inicial. Sem isso, a única alternativa seria o cliente
    guardar a meta por conta própria — e aí passariam a existir duas verdades
    sobre um número que o aluno declarou uma vez só.
    """

    id: int
    id_aluno: int
    inicio: datetime
    fim: Optional[datetime] = None

    metodo: Optional[str] = None
    metodo_nome: Optional[str] = None
    assunto: Optional[str] = None
    meta_de_blocos: Optional[int] = None

    model_config = {"from_attributes": True}

    @field_validator("inicio", "fim")
    @classmethod
    def _explicitar_utc(cls, valor: Optional[datetime]) -> Optional[datetime]:
        # Sem fuso explícito, o navegador interpretaria o instante como hora
        # local e o horário da sessão apareceria deslocado na interface.
        return como_utc(valor) if valor is not None else None

    @model_validator(mode="after")
    def _traduzir_o_metodo(self) -> "SessaoPublica":
        # Derivado, nunca recebido: o nome do método é do catálogo, e deixá-lo
        # entrar pelo construtor abriria a porta para duas respostas diferentes
        # sobre o mesmo código na mesma tela.
        self.metodo_nome = _nome_do_metodo(self.metodo)
        return self


def _utc(valor: Optional[datetime]) -> Optional[datetime]:
    """O mesmo cuidado de `SessaoPublica`, reaproveitado pelos DTOs novos.

    Sem fuso explícito o navegador lê o instante como hora local, e a curva
    inteira do relatório aparece deslocada — de propósito nenhum, só por causa
    de um `tzinfo` ausente que o SQLite não devolve.
    """
    return como_utc(valor) if valor is not None else None


class PontoDaSerie(BaseModel):
    """Um ponto da curva do IEE, como o gráfico do relatório o consome.

    `score = null` é a incerteza da ticket 10 e **precisa** atravessar como
    nulo: é ele que faz a linha quebrar em vez de ligar os dois lados do buraco
    como se nada tivesse acontecido no meio. Converter para zero aqui desfaria a
    ticket 10 sem tocar em nenhuma linha dela.
    """

    instante: datetime
    score: Optional[float] = None
    alerta: Optional[str] = None

    @field_validator("instante")
    @classmethod
    def _explicitar_utc(cls, valor: datetime) -> datetime:
        return como_utc(valor)

    @classmethod
    def de(cls, log: LogEngajamento) -> "PontoDaSerie":
        return cls(instante=log.horario_registro, score=log.score, alerta=log.alerta)


class AlertaPublico(BaseModel):
    """Um alerta agregado, com código para a máquina e nome para a pessoa.

    Os dois viajam juntos porque servem a leitores diferentes: a tela usa o nome,
    e o código é o que permite ao frontend agrupar, ordenar ou destacar sem ter
    que casar strings traduzidas.
    """

    codigo: str
    nome: str
    ocorrencias: int

    @classmethod
    def lista(cls, contagem: Dict[str, int]) -> List["AlertaPublico"]:
        """Do mais frequente para o menos; empate em ordem alfabética.

        Ordem estável importa: sem ela a mesma sessão renderizaria os alertas em
        ordens diferentes a cada carregamento da página.
        """
        itens = sorted(contagem.items(), key=lambda par: (-par[1], par[0]))
        return [
            cls(codigo=codigo, nome=recomendacoes.nome_do_alerta(codigo), ocorrencias=quantas)
            for codigo, quantas in itens
        ]


class RecomendacaoPublica(BaseModel):
    codigo: str
    titulo: str
    texto: str
    motivo: str

    @classmethod
    def de(cls, sugestao: recomendacoes.Recomendacao) -> "RecomendacaoPublica":
        return cls(
            codigo=sugestao.codigo,
            titulo=sugestao.titulo,
            texto=sugestao.texto,
            motivo=sugestao.motivo,
        )


class CriterioPublico(BaseModel):
    """Uma leitura da sessão pelo método, já escrita (ticket 17, AC-17-9).

    Mesma forma de `RecomendacaoPublica`, e a igualdade é o ponto: as duas são
    frases que o aluno lê sobre si, e as duas nascem no backend. Uma frase de
    critério escrita no template Angular sairia do alcance do teste de tom que
    varre `app/recomendacoes.py` e `app/criterios.py` — a trava morreria no
    mesmo commit em que o recurso nasce, e ninguém veria.
    """

    codigo: str
    titulo: str
    texto: str
    detalhe: str

    @classmethod
    def de(cls, criterio: criterios.Criterio) -> "CriterioPublico":
        return cls(
            codigo=criterio.codigo,
            titulo=criterio.titulo,
            texto=criterio.texto,
            detalhe=criterio.detalhe,
        )


class CadenciaPublica(BaseModel):
    """O declarado ao lado do executado — em durações e contagens (AC-17-10).

    **Nenhum campo aqui é razão normalizada.** Não há quociente entre o
    observado e o declarado, e não há de propósito: `"aderência: 62%"`
    atravessaria em silêncio todos os testes de texto deste projeto, porque não
    afirma estado interno nenhum. Quem quiser o percentual precisa acrescentar
    campo e justificar no PR — o docstring de `criterios.Cadencia` tem o porquê,
    e `test_criterios.py` tem a trava.
    """

    duracao_alvo_s: int
    duracoes_observadas_s: List[float]
    blocos_na_faixa: int
    blocos_de_foco: int
    meta_de_blocos: Optional[int] = None

    @classmethod
    def de(cls, cadencia: criterios.Cadencia) -> "CadenciaPublica":
        return cls(
            duracao_alvo_s=cadencia.duracao_alvo_s,
            duracoes_observadas_s=list(cadencia.duracoes_observadas_s),
            blocos_na_faixa=cadencia.blocos_na_faixa,
            blocos_de_foco=cadencia.blocos_de_foco,
            meta_de_blocos=cadencia.meta_de_blocos,
        )


class BlocoAvaliadoPublico(BaseModel):
    """Um bloco declarado com o que a série diz sobre ele.

    As duas durações viajam juntas pelo mesmo motivo que `duracao_total_s` e
    `duracao_presente_s`: "25 min declarados · 11 min com captura" informa o
    aluno de um jeito que nenhuma das duas sozinha informaria.

    `observacao` é a frase pronta para o bloco sem média, e `media` continua
    `null` — nunca zero. Os dois viajam porque a tela precisa dizer **por que**
    não há número, e "curto demais" e "não deu para medir" mandam o aluno mexer
    em coisas diferentes.

    **Não traz a lista de alertas do bloco**, e a ausência é decisão. O detector
    de fadiga atribui a duração entre duas amostras ao estado da primeira, então
    uma lacuna de captura de 30 a 59 s logo depois de uma piscada fabrica um
    registro de pálpebra fechada. Num bloco de 12 minutos, uma lista de alertas
    por bloco convidaria o aluno a ler aquele artefato como o rótulo do bloco.
    Os alertas continuam sendo publicados na sessão inteira, onde a contagem tem
    denominador à vista.
    """

    indice: int
    tipo: str
    tipo_nome: str
    inicio: datetime
    fim: Optional[datetime] = None

    duracao_s: float
    duracao_com_captura_s: float

    media: Optional[float] = None
    pontos_medidos: int
    pontos_incertos: int
    observacao: Optional[str] = None

    @field_validator("inicio", "fim")
    @classmethod
    def _explicitar_utc(cls, valor: Optional[datetime]) -> Optional[datetime]:
        return _utc(valor)

    @classmethod
    def de(cls, bloco: criterios.BlocoAvaliado) -> "BlocoAvaliadoPublico":
        return cls(
            indice=bloco.indice,
            tipo=bloco.tipo,
            tipo_nome=bloco.tipo_nome,
            inicio=bloco.inicio,
            fim=bloco.fim,
            duracao_s=bloco.duracao_s,
            duracao_com_captura_s=bloco.duracao_com_captura_s,
            media=bloco.media,
            pontos_medidos=bloco.pontos_medidos,
            pontos_incertos=bloco.pontos_incertos,
            observacao=bloco.observacao,
        )


class RelatorioPublico(BaseModel):
    """O relatório de autopercepção de uma sessão (tickets 11 e 17).

    As durações viajam em **segundos**, e não formatadas: formatar é decisão de
    apresentação, e o navegador é quem sabe a largura da tela e o idioma do
    aluno. O backend entrega o número.

    Os campos de método são todos vazios quando a sessão não declarou nenhum
    (AC-17-11), e a tela desenha traço. `metodo = null` com `blocos = []` e
    `criterios = []` é "esta sessão é anterior ao recurso"; `metodo = "livre"`
    é "o aluno escolheu estudar sem método". Colapsar os dois na renderização
    desfaria a distinção que o modelo custou a preservar.
    """

    id_sessao: int
    inicio: datetime
    fim: Optional[datetime] = None
    parcial: bool = False

    duracao_total_s: float
    duracao_presente_s: float

    media: Optional[float] = None
    pico: Optional[float] = None
    vale: Optional[float] = None

    pontos_medidos: int
    pontos_incertos: int
    pontos_zerados: int

    alertas_de_fadiga: List[AlertaPublico] = []
    motivos_de_incerteza: List[AlertaPublico] = []
    recomendacoes: List[RecomendacaoPublica] = []
    serie: List[PontoDaSerie] = []

    metodo: Optional[str] = None
    metodo_nome: Optional[str] = None
    assunto: Optional[str] = None

    #: A média do IEE **sem os pontos das pausas** — a correção da ticket 17.
    #: Convive com `media` sem substituí-la: aquela é a da sessão inteira e vem
    #: congelada de `resumo_sessao`; esta é a leitura do método, e só existe
    #: onde há método.
    media_de_foco: Optional[float] = None
    duracao_de_foco_s: float = 0.0
    duracao_de_pausa_s: float = 0.0

    blocos: List[BlocoAvaliadoPublico] = []
    criterios: List[CriterioPublico] = []
    cadencia: Optional[CadenciaPublica] = None

    @field_validator("inicio", "fim")
    @classmethod
    def _explicitar_utc(cls, valor: Optional[datetime]) -> Optional[datetime]:
        return _utc(valor)

    @classmethod
    def de(cls, relatorio: RelatorioDaSessao) -> "RelatorioPublico":
        resumo = relatorio.resumo
        avaliacao = relatorio.avaliacao
        return cls(
            id_sessao=relatorio.sessao.id,
            inicio=relatorio.sessao.inicio,
            fim=relatorio.sessao.fim,
            parcial=relatorio.parcial,
            duracao_total_s=resumo.duracao_total.total_seconds(),
            duracao_presente_s=resumo.duracao_presente.total_seconds(),
            media=resumo.media,
            pico=resumo.pico,
            vale=resumo.vale,
            pontos_medidos=resumo.pontos_medidos,
            pontos_incertos=resumo.pontos_incertos,
            pontos_zerados=resumo.pontos_zerados,
            alertas_de_fadiga=AlertaPublico.lista(resumo.alertas_de_fadiga),
            motivos_de_incerteza=AlertaPublico.lista(resumo.motivos_de_incerteza),
            recomendacoes=[RecomendacaoPublica.de(r) for r in relatorio.recomendacoes],
            serie=[PontoDaSerie.de(ponto) for ponto in relatorio.serie],
            # A sessão sem método não ganha nem o código nem o nome: o traço na
            # tela é a ausência dos dois, e não um rótulo dizendo "nenhum".
            metodo=relatorio.sessao.metodo,
            metodo_nome=_nome_do_metodo(relatorio.sessao.metodo),
            assunto=relatorio.sessao.assunto,
            media_de_foco=avaliacao.media_de_foco if avaliacao else None,
            duracao_de_foco_s=avaliacao.duracao_de_foco_s if avaliacao else 0.0,
            duracao_de_pausa_s=avaliacao.duracao_de_pausa_s if avaliacao else 0.0,
            blocos=(
                [BlocoAvaliadoPublico.de(bloco) for bloco in avaliacao.blocos]
                if avaliacao
                else []
            ),
            criterios=(
                [CriterioPublico.de(criterio) for criterio in avaliacao.criterios]
                if avaliacao
                else []
            ),
            cadencia=(
                CadenciaPublica.de(avaliacao.cadencia)
                if avaliacao and avaliacao.cadencia is not None
                else None
            ),
        )


class SessaoNoHistorico(BaseModel):
    """Uma linha da lista de sessões passadas (ticket 12).

    Traz o suficiente para o aluno escolher qual abrir — quando foi, quanto
    durou, como ficou o índice e se houve alerta — e nada além disso. A série
    inteira de cada sessão no payload da lista transformaria a tela de histórico
    no download de todo o histórico.
    """

    id: int
    inicio: datetime
    fim: Optional[datetime] = None
    parcial: bool = False
    duracao_presente_s: float
    media: Optional[float] = None
    pontos_medidos: int
    alertas: int

    #: `None` nas sessões anteriores ao recurso, e a lista desenha traço. É a
    #: mesma disciplina de `media = None`: o histórico diz "não há informação",
    #: nunca "Sem método" — que seria inventar uma escolha que ninguém fez.
    metodo: Optional[str] = None
    metodo_nome: Optional[str] = None
    assunto: Optional[str] = None

    @field_validator("inicio", "fim")
    @classmethod
    def _explicitar_utc(cls, valor: Optional[datetime]) -> Optional[datetime]:
        return _utc(valor)

    @classmethod
    def de(cls, sessao: SessaoEstudo, resumo: ResumoDaSessao, parcial: bool) -> "SessaoNoHistorico":
        return cls(
            id=sessao.id,
            inicio=sessao.inicio,
            fim=sessao.fim,
            parcial=parcial,
            duracao_presente_s=resumo.duracao_presente.total_seconds(),
            media=resumo.media,
            pontos_medidos=resumo.pontos_medidos,
            alertas=sum(resumo.alertas_de_fadiga.values()),
            metodo=sessao.metodo,
            metodo_nome=_nome_do_metodo(sessao.metodo),
            assunto=sessao.assunto,
        )


class NovaSessao(CorpoRecebido):
    """O que o aluno declara na tela inicial, antes de começar.

    **`pausa_maxima_s` não está aqui, e a ausência é a decisão.** O cliente manda
    o *código* do método; o número de segundos é resolvido no servidor, a partir
    de `app/metodos.py`. Se ele viesse no corpo do request, "sessão que nunca
    encerra" seria um campo de request — e o teto absoluto de 20 min viraria uma
    sugestão que qualquer curl ignora.

    Os três campos são opcionais e o corpo inteiro também: `POST /sessoes` sem
    corpo continua abrindo uma sessão sem contexto, que é o que as telas
    anteriores a este recurso fazem e o que uma sessão sem método é.
    """

    #: Código do catálogo. Validado contra ele em `sessoes.iniciar`, e não aqui,
    #: para que exista **um** lugar que decide o que é método válido. Repetir a
    #: lista num `Literal` daria um 422 mais bonito e uma segunda fonte de
    #: verdade que envelheceria sozinha.
    #:
    #: O `max_length` não é uma segunda validação do catálogo — é o teto que
    #: separa "erro de digitação, que merece a mensagem boa" de "carga", e ele
    #: sai do próprio catálogo (`_teto_de_vocabulario`) para não virar um número
    #: solto que ninguém sabe revisar.
    metodo: Optional[str] = Field(
        default=None,
        max_length=LIMITE_CODIGO_DE_METODO,
        description="Código de um método de `GET /metodos`. Nulo abre sessão sem método.",
    )

    assunto: Optional[Assunto] = Field(
        default=None,
        description=f"Rótulo curto do que vai ser estudado (até {LIMITE_ASSUNTO_CARACTERES}).",
    )

    meta_de_blocos: Optional[int] = Field(
        default=None, ge=1, le=META_MAXIMA_DE_BLOCOS
    )

    @field_validator("assunto", mode="before")
    @classmethod
    def _limpar_o_assunto(cls, valor: Optional[str]) -> Optional[str]:
        # Antes da validação de tamanho, de propósito: espaço no fim não pode
        # consumir o orçamento de caracteres de quem escreveu um assunto legítimo.
        return _assunto_util(valor)


class TransicaoDeBloco(CorpoRecebido):
    """A declaração de que a sessão entrou em foco ou em pausa.

    **É declaração, não observação.** O cliente conduz o método com o cronômetro
    na tela, então ele *sabe* a hora da transição; o servidor não teria como
    derivá-la da série sem confundir queda de Wi-Fi com pausa (ver o docstring de
    `app/blocos.py`). O instante é o da chegada do request, e não um campo do
    corpo: carimbo de tempo vindo do cliente é relógio de navegador
    desregulado — ou, no caso ruim, escolhido.

    Os dois campos são vocabulário fechado de `app/blocos.py`, e quem decide o
    que vale continua sendo `blocos.validar_declaracao` — os tetos aqui só
    impedem que um valor de quilobytes chegue até lá para ser repetido de volta.
    """

    tipo: str = Field(
        max_length=LIMITE_TIPO_DE_BLOCO, description="`foco` ou `pausa`."
    )

    origem: str = Field(
        default=blocos.ORIGEM_METODO,
        max_length=LIMITE_ORIGEM_DE_BLOCO,
        description="`metodo` quando o cronômetro zerou; `aluno` quando ele antecipou ou adiou.",
    )


class BlocoPublico(BaseModel):
    """Um bloco declarado, como a tela e o relatório o consomem.

    Não traz duração calculada. As durações do relatório saem de segundos, como
    todas as outras (`RelatorioPublico` explica por quê), e derivá-la aqui
    criaria um número que o cliente teria de conferir contra `inicio` e `fim` —
    dois caminhos para o mesmo fato, que é como eles passam a divergir.
    """

    id: int
    id_sessao: int
    indice: int
    tipo: str
    inicio: datetime
    fim: Optional[datetime] = None
    origem: str

    model_config = {"from_attributes": True}

    @field_validator("inicio", "fim")
    @classmethod
    def _explicitar_utc(cls, valor: Optional[datetime]) -> Optional[datetime]:
        return _utc(valor)


class MetodoPublico(BaseModel):
    """Um método do catálogo, para o cliente renderizar a escolha e conduzir.

    Vai o **nome legível** junto do código, no molde de `AlertaPublico`: sem
    isso a tela inicial teria que carregar uma tabela de tradução própria, e o
    dia em que alguém acrescentasse um método ao catálogo ele apareceria na tela
    como `52-17`.

    `foco_s`, `ciclos_ate_pausa_longa` e `pausa_longa_s` viajam porque é o
    cliente que conduz o método — é o cronômetro dele que precisa saber quanto
    dura um bloco. `pausa_s` vai junto por transparência: é o número que o
    servidor vai usar para decidir quando a sessão morre por ausência, e
    escondê-lo do aluno não o tornaria mais seguro (o servidor o resolve
    sozinho, aconteça o que acontecer no cliente).

    `foco_s` nulo é método que **não prescreve** duração de bloco — Flow e
    Timeboxing. Nulo, e não zero, para que a tela não desenhe um cronômetro
    regressivo a partir de zero.
    """

    codigo: str
    nome: str
    foco_s: Optional[int] = None
    pausa_s: int
    ciclos_ate_pausa_longa: Optional[int] = None
    pausa_longa_s: Optional[int] = None

    @classmethod
    def de(cls, metodo: metodos.MetodoDeEstudo) -> "MetodoPublico":
        return cls(
            codigo=metodo.codigo,
            nome=metodo.nome,
            foco_s=metodo.foco_s,
            pausa_s=metodo.pausa_s,
            ciclos_ate_pausa_longa=metodo.ciclos_ate_pausa_longa,
            pausa_longa_s=metodo.pausa_longa_s,
        )

    @classmethod
    def catalogo(cls) -> List["MetodoPublico"]:
        """O catálogo inteiro, na ordem em que está declarado em `app/metodos.py`.

        A ordem do dicionário é a ordem da tela, e ela não é acidental: os
        métodos com cadência prescrita vêm primeiro e "Sem método" fica por
        último, que é onde uma opção de escape pertence. Ordenar por nome aqui
        jogaria "Sem método" para o meio da lista.
        """
        return [cls.de(metodo) for metodo in metodos.METODOS.values()]
