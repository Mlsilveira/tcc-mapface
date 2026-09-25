from datetime import datetime
from typing import Dict, Optional

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from app.blocos import ORIGEM_METODO
from app.tempo import agora_utc

#: Como uma sessão chegou ao fim. `None` enquanto ela está em andamento.
#:
#: Existe para o relatório (AC-11-4): sessão derrubada por queda de conexão ou
#: por fechamento do navegador é encerrada pela varredura de inatividade, não
#: pelo aluno, e o relatório dela é **parcial**. Sem esta coluna a distinção
#: teria que ser adivinhada comparando `fim` com `ultima_atividade`, que hoje
#: coincidem no caso automático por acidente de implementação — um acidente que
#: a primeira mudança na varredura desfaria em silêncio.
ENCERRAMENTO_MANUAL = "manual"
ENCERRAMENTO_POR_INATIVIDADE = "inatividade"


class Aluno(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    nome: str
    email: str = Field(index=True, unique=True)
    senha_hash: str


class SessaoEstudo(SQLModel, table=True):
    """Uma sessão de estudo monitorada, do "iniciar" ao "encerrar".

    `ultima_atividade` não está no schema do spec (id, id_aluno, inicio, fim):
    é uma coluna operacional. Ela **decidia** o encerramento automático até os
    métodos de estudo entrarem; hoje quem decide é `ultima_presenca`, e o motivo
    está no docstring dela.

    O contexto (método, assunto) não é coluna inventada: a seção 7.3 do texto em
    ABNT já descrevia a tabela de sessões como registrando "o início, o fim e o
    **contexto (disciplina/matéria)** de cada ciclo de estudo monitorado". O
    `spec-poc-iee.md` reduziu o schema a `(id, id_aluno, inicio, fim)` sem
    registrar a redução como decisão; estas colunas restauram o que já estava
    prometido.
    """

    __tablename__ = "sessao_estudo"

    id: Optional[int] = Field(default=None, primary_key=True)
    id_aluno: int = Field(foreign_key="aluno.id", index=True)
    inicio: datetime = Field(default_factory=agora_utc)
    fim: Optional[datetime] = Field(default=None)

    #: Último sinal de que a **aba** está aberta (heartbeat do navegador).
    #:
    #: Deixou de ter leitor no ciclo de vida, e isso é deliberado: o heartbeat
    #: bate sozinho com a aba aberta, com ou sem aluno na cadeira, então ele
    #: nunca foi evidência sobre a pessoa. A coluna fica porque a migração deste
    #: projeto acrescenta e afrouxa, nunca remove — e porque o histórico gravado
    #: nela continua sendo verdade sobre o que ela de fato media. Quem procura o
    #: relógio da sessão quer `ultima_presenca`.
    ultima_atividade: datetime = Field(default_factory=agora_utc)

    #: `ENCERRAMENTO_MANUAL`, `ENCERRAMENTO_POR_INATIVIDADE`, ou `None` enquanto
    #: em andamento. Sessões gravadas antes da ticket 11 ficam com `None` mesmo
    #: encerradas — a migração acrescenta coluna, nunca inventa valor para linha
    #: antiga (ver `database._acrescentar_colunas_faltantes`). O relatório trata
    #: esse `None` como "não dá para saber", que é a verdade sobre elas.
    encerramento: Optional[str] = Field(default=None)

    #: Código do método declarado pelo aluno — **snapshot textual, não chave
    #: estrangeira**. O catálogo mora em `app/metodos.py` e pode ser
    #: reparametrizado; o relatório de uma sessão antiga não pode mudar junto.
    #:
    #: `None` e `"livre"` significam coisas diferentes e não podem ser
    #: colapsados: `None` é "esta sessão é anterior ao recurso", `"livre"` é "o
    #: aluno escolheu estudar sem método". Colapsar os dois faria a migração
    #: inventar uma escolha que ninguém fez — o mesmo erro que `encerramento`
    #: evita ao deixar sessão antiga sem valor em vez de chutar "manual".
    metodo: Optional[str] = Field(default=None)

    #: O que o aluno disse que ia estudar. Primeiro campo de conteúdo autoral do
    #: banco: nada o lê, nada o indexa, nada o analisa. Ele existe para o aluno
    #: reconhecer a própria sessão no histórico, e é isso.
    assunto: Optional[str] = Field(default=None)

    #: Quantos blocos o aluno disse que pretendia fazer. Opcional de propósito:
    #: `None` é "não declarou", e o relatório não tem denominador nenhum a
    #: exibir. Declarado, vira "você planejou 4, foram executados 3" — dois
    #: números lado a lado, nunca a divisão entre eles.
    meta_de_blocos: Optional[int] = Field(default=None)

    #: A pausa máxima do método, em segundos, congelada na abertura da sessão.
    #:
    #: Resolvida **pelo servidor** a partir do catálogo: o cliente manda o
    #: código do método, nunca o número. Se este valor viesse do cliente,
    #: "sessão que nunca encerra" seria um campo de request.
    #:
    #: `None` numa sessão aberta antes do recurso faz o limite cair no valor
    #: legado — que não é invenção, é a regra anterior aplicada a dado anterior.
    pausa_maxima_s: Optional[int] = Field(default=None)

    #: Última vez que houve **rosto na câmera** — o relógio real da sessão.
    #:
    #: Escrito pelo canal de telemetria quando `rosto_detectado` é verdadeiro —
    #: e **só** isso. Incerteza de captura não desqualifica a presença: luz
    #: baixa e reflexo no óculos estragam a medida do EAR sem tirar ninguém da
    #: frente da webcam, e tratar "não medi" como "não estava lá" desfaria a
    #: ticket 10 por uma porta lateral.
    #:
    #: É o que separa "o aluno está aqui" de "a aba está aberta": durante uma
    #: pausa o navegador continua mandando payload (com `rosto_detectado:
    #: false`), então qualquer coisa que conte payload conta cadeira vazia como
    #: estudo.
    #:
    #: `None` significa que nenhuma presença foi observada ainda, e isso é a
    #: verdade, não um buraco — sessão cuja webcam foi negada morre contada a
    #: partir de `inicio`, que é o comportamento desejado.
    ultima_presenca: Optional[datetime] = Field(default=None)


class BlocoEstudo(SQLModel, table=True):
    """Um trecho declarado da sessão: um bloco de foco ou uma pausa.

    **Por que tabela própria, e não as duas alternativas óbvias.**

    *Derivar os blocos na leitura é impossível, e a impossibilidade é
    silenciosa.* Passadas 24 h, `sumarizacao.aplicar_retencao` colapsa a série
    em médias por minuto, e `score = 0.0` já é ambíguo entre "rosto ausente" e
    "presente com fadiga máxima". Blocos derivados existiriam por 24 h e depois
    mudariam sozinhos — relatório que muda sozinho é o pior bug do catálogo
    deste projeto, e é o que a ticket 13 inteira existe para impedir.

    *Guardar um JSON em `resumo_sessao` também não serve*, porque aquela linha
    só é escrita no encerramento: uma sessão derrubada por queda de conexão
    fecharia com os blocos reconstruídos a partir de nada. É o caso AC-11-4, que
    o projeto trata com cuidado em todo o resto do código e que não tem por que
    ser tratado com menos aqui.

    Tabela nova, escrita em tempo real na transição, é barata — poucas linhas
    por sessão, contra um ponto por segundo de `log_engajamento` — e tem
    precedente testado: `test_migracao.py::test_cria_a_tabela_de_resumo_da_ticket_13`.

    **O que um bloco afirma, e a armadilha de fazê-lo afirmar demais.** Um bloco
    é o *plano executado*: o que o método mandou e o aluno aceitou, declarado na
    transição e fechado na transição seguinte. Ele **não** é afirmação de
    presença. Fazer "bloco de foco" significar "o aluno estava ali focado"
    obrigaria a reconciliar com a série toda vez, e erraria. Os dois ficam lado
    a lado, que é o idioma da casa:

        "Bloco 3 (foco): 25 min planejados · 11 min com captura · IEE médio 54"

    A discrepância é informação para o aluno, não inconsistência a esconder.

    **Nada aqui vem de `log_engajamento`**, e essa é a razão de a decisão 9 (a
    fronteira de privacidade não se move) sobreviver a este recurso inteiro:
    tudo que os blocos precisam saber são carimbos de tempo de cliques
    declarados. A regra de negócio mora em `app/blocos.py`, que não conhece
    banco; esta classe é só onde ela encosta no SQLite.
    """

    __tablename__ = "bloco_estudo"

    id: Optional[int] = Field(default=None, primary_key=True)

    #: Indexado pelo mesmo motivo que `log_engajamento.id_sessao`: todo leitor
    #: quer "os blocos desta sessão", em ordem, e nenhum quer "todos os blocos".
    id_sessao: int = Field(foreign_key="sessao_estudo.id", index=True)

    #: A numeração que o aluno lê ("bloco 3"), a partir de 1. Vale para a sessão
    #: inteira, e não por tipo, porque é a ordem cronológica que o relatório
    #: narra: foco 1, pausa 2, foco 3.
    indice: int

    #: `blocos.TIPO_FOCO` ou `blocos.TIPO_PAUSA`. Snapshot textual pelo mesmo
    #: motivo que `metodo`: vocabulário fechado mora em Python neste projeto, e
    #: uma FK para uma tabela de dois valores seria cerimônia sem benefício.
    tipo: str

    inicio: datetime = Field(default_factory=agora_utc)

    #: `None` enquanto o bloco é o que está em andamento. Numa sessão já
    #: encerrada, `None` aqui é **dado corrompido**: `sessoes.encerrar` e
    #: `sessoes.encerrar_inativas` fecham o bloco aberto com o mesmo `fim` da
    #: sessão justamente para que isso não exista. É o tipo de inconsistência
    #: que não estoura em lugar nenhum e aparece três semanas depois como um
    #: gráfico torto.
    fim: Optional[datetime] = Field(default=None)

    #: `blocos.ORIGEM_METODO` quando o cronômetro chegou ao fim e o aluno seguiu
    #: o plano; `blocos.ORIGEM_ALUNO` quando ele antecipou ou adiou a transição.
    #: Só o cliente sabe qual foi — é ele que tem o cronômetro na tela —, então
    #: o valor é declarado, não derivado.
    origem: str = Field(default=ORIGEM_METODO)


class LogEngajamento(SQLModel, table=True):
    """Um registro de score de engajamento dentro de uma sessão (ticket 6).

    Não existe — e não pode passar a existir — nenhuma coluna de imagem, vídeo
    ou landmark bruto aqui. Os landmarks são calculados e descartados no
    navegador; o que chega ao banco é o score derivado deles. Há um teste que
    trava a lista de colunas exatamente para forçar essa conversa quando alguém
    quiser adicionar campo novo.

    `fadiga` e `alerta` são as colunas que o spec chama de `flag_fadiga` e
    `alerta_gerado`. Entraram na ticket 10, e não na 8, porque quem precisa
    delas gravadas é o relatório da ticket 11: o fator `F` já era calculado e
    devolvido ao navegador desde a 8, mas morria na conexão.
    """

    __tablename__ = "log_engajamento"

    id: Optional[int] = Field(default=None, primary_key=True)
    id_sessao: int = Field(foreign_key="sessao_estudo.id", index=True)

    #: Indexado por exigência da ticket 13. A série é sempre lida em ordem
    #: cronológica e recortada por sessão; sem índice, cada relatório custa uma
    #: varredura da tabela inteira, que é a que mais cresce no sistema (um ponto
    #: por segundo de estudo, por aluno).
    horario_registro: datetime = Field(default_factory=agora_utc, index=True)

    #: `None` quando a captura foi descartada por incerteza (ticket 10). Não é o
    #: mesmo que zero: zero é "o aluno não estava lá", `None` é "não dá para
    #: afirmar nada sobre este segundo". Gravar um número inventado aqui seria
    #: exatamente o score enganoso que a ticket 10 existe para evitar.
    score: Optional[float] = Field(default=None)

    #: Quanto o fator de fadiga descontou deste ponto, em pontos do IEE.
    fadiga: float = Field(default=0.0)

    #: Rótulo curto do que houve de anormal: o motivo da incerteza quando
    #: `score is None`, ou o motivo dominante da fadiga quando há score. Os dois
    #: casos nunca se confundem porque `score` os separa.
    alerta: Optional[str] = Field(default=None)

    #: Probabilidade de sonolência lida pelo classificador treinado no UTA-RLDD,
    #: entre 0 e 1, ou `None` — sem modelo carregado, durante os 60 segundos de
    #: calibração, ou quando a janela de 10s ainda não fechou.
    #:
    #: **Continua não havendo nada de imagem aqui.** O que entra é um número
    #: derivado das mesmas métricas que já trafegavam; nenhum landmark, nenhum
    #: quadro. É também uma coluna **paralela** a `fadiga`, e não substituta: o
    #: fator que desconta do IEE segue vindo das regras, e esta é a segunda
    #: opinião, registrada para o relatório poder mostrar as duas e para a
    #: orientação poder decidir, com dado na mão, se uma vira a outra.
    sonolencia: Optional[float] = Field(default=None)


class ResumoSessao(SQLModel, table=True):
    """Os indicadores de uma sessão, congelados no encerramento (ticket 13).

    Existe por causa da retenção. Os pontos granulares de `log_engajamento` são
    colapsados em médias por minuto depois da janela de retenção, e média de
    médias não é média: recalcular os indicadores sobre a série já colapsada
    daria números *parecidos* com os originais, e parecido é a pior categoria de
    errado num relatório que o aluno vai comparar com o da semana passada.

    Então o resumo é calculado uma vez, sobre a série completa, no instante em
    que a sessão termina — e é ele que o relatório lê dali em diante. A série
    colapsada serve ao gráfico, que é sobre forma; o resumo serve aos números,
    que são sobre valor.

    Não há coluna de imagem aqui pelo mesmo motivo que não há em
    `LogEngajamento`: o que se guarda é derivado de métricas derivadas, nunca do
    quadro de vídeo.
    """

    __tablename__ = "resumo_sessao"

    id_sessao: Optional[int] = Field(
        default=None, primary_key=True, foreign_key="sessao_estudo.id"
    )

    #: `None` quando não houve nenhuma medida — sessão que mal começou, ou
    #: sessão inteira em incerteza de captura. Zero diria "o aluno estava aqui e
    #: desengajado", que é outra afirmação e que estes dados não sustentam.
    media: Optional[float] = Field(default=None)
    pico: Optional[float] = Field(default=None)
    vale: Optional[float] = Field(default=None)

    pontos_medidos: int = Field(default=0)
    pontos_incertos: int = Field(default=0)
    pontos_zerados: int = Field(default=0)

    #: Segundos, não `timedelta`: SQLite não tem tipo de intervalo, e gravar
    #: número evita depender de como cada banco serializa duração.
    duracao_presente_s: float = Field(default=0.0)

    alertas_de_fadiga: Dict[str, int] = Field(default_factory=dict, sa_column=Column(JSON))
    motivos_de_incerteza: Dict[str, int] = Field(default_factory=dict, sa_column=Column(JSON))

    #: Se os pontos por segundo desta sessão já foram trocados por médias por
    #: minuto. É o que torna a varredura de retenção idempotente: sem a marca,
    #: descobrir "esta série já foi colapsada?" exigiria adivinhar pelo formato
    #: dos dados, e uma sessão que de fato só teve um ponto por minuto seria
    #: colapsada de novo a cada passagem.
    granular_descartado: bool = Field(default=False)
