"""Como o relatório lê a sessão segundo o método declarado (ticket 17, E02-S02).

Como `app/blocos.py`, `app/metodos.py` e `app/presenca.py`, este módulo não
conhece HTTP, banco nem UI: recebe blocos e série e devolve critérios e frases.

**O defeito que ele existe para corrigir.** Até aqui a sessão inteira virava uma
média só. Para quem usa Pomodoro isso inverte o resultado: os cinco minutos em
que o aluno está corretamente longe da tela entram na conta e a derrubam, e o
sistema penaliza exatamente o comportamento que o método prescreve. A correção é
uma linha de código e o resto deste módulo é o cuidado em torno dela — **os
pontos das pausas não entram na média dos blocos de foco**.

**Por que todas as frases nascem aqui.** A trava de tom deste projeto só existe
porque `app/recomendacoes.py` concentra cada frase que o aluno lê sobre si
mesmo, num arquivo só, onde um teste parametrizado consegue varrê-las todas. Uma
frase de critério escrita no template Angular não seria varrida por teste nenhum
— a trava morreria no mesmo commit em que o recurso nasce, e ninguém veria. Por
isso o backend entrega texto pronto, como já faz com `Recomendacao`.

**Por que contagem, e nunca razão.** A alternativa descartada é curta de
escrever e difícil de desfazer: `"aderência: 62%"`. Repare que ela **passaria**
pela trava de tom — não afirma estado interno nenhum, é aritmética sobre
carimbos de tempo. A régua que ela atravessa é a outra, a que a ticket 12
enunciou: *oferecer a linha do tempo é útil; desenhar uma seta para cima em cima
dela seria afirmar mais do que o dado sustenta*. Um quociente entre o declarado e
o executado é uma nota de obediência com outro nome, e um relatório de
autopercepção que vira boletim deixa de ser lido — ou, pior, passa a ser
obedecido. Daí `Cadencia` carregar durações e contagens, e **nenhum quociente**:
quem quiser o percentual precisa acrescentar campo e justificar no PR, que é
exatamente a conversa que a ausência dele existe para forçar.

**Por que um bloco curto se abstém de ter média.** O projeto já tem a disciplina
do `media = None` (ver `relatorio.ResumoDaSessao`), mas ela nunca foi exercitada
com n pequeno. Num bloco de 12 minutos um ponto espúrio é 1 em 720 e vira o
carimbo daquele bloco; numa sessão de duas horas ele sumia em 7.200. Abaixo de
`MEDIDA_MINIMA_S` de medida o bloco diz "curto demais para uma média" em vez de
publicar um número que a amostra não sustenta.

**Um bloco continua não sendo afirmação de presença.** Este módulo não reconcilia
as duas leituras nem escolhe entre elas: põe a duração declarada ao lado da
duração com captura e deixa a discrepância à vista, que é o idioma da casa
(`presenca.duracao_total` ao lado de `presenca.duracao_presente`).
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Sequence, Tuple

from app import blocos, metodos, presenca, relatorio

#: Quanto tempo de **medida** um bloco precisa ter para receber uma média.
#:
#: Sessenta segundos, que com a série em resolução de 1 Hz são os 60 pontos
#: medidos da story. Não é um limite estatístico derivado: é a menor janela em
#: que a média ainda descreve comportamento e não ruído de piscada — a mesma
#: ordem de grandeza que `sumarizacao.JANELA_DE_RESUMO` adotou para colapsar a
#: série, e pelo mesmo motivo.
MEDIDA_MINIMA_S = 60

#: Meia-largura da faixa de cadência, como fração da duração prescrita.
#:
#: Vinte por cento porque a transição é humana: quem termina o parágrafo antes
#: de apertar o botão estoura o Pomodoro em um ou dois minutos, e uma faixa mais
#: estreita transformaria essa banalidade em desvio. Note que a fração é usada
#: para **desenhar a faixa**, e nunca para produzir um quociente que saia daqui:
#: o que atravessa a fronteira é a contagem de blocos dentro dela.
TOLERANCIA_DE_CADENCIA = 0.2

#: O bloco teve alguma medida, mas pouca demais para sustentar uma média.
MOTIVO_CURTO_DEMAIS = "curto-demais"

#: O bloco teve captura o tempo todo e nenhuma leitura confiável — a incerteza
#: da ticket 10 do começo ao fim. Diagnóstico diferente do anterior, e a frase
#: precisa distingui-los: "não deu para medir" e "curto demais" mandam o aluno
#: mexer em coisas diferentes (a luz do quarto, ou a duração do bloco).
MOTIVO_SEM_MEDIDA = "sem-medida"

#: Nenhum ponto chegou dentro do bloco. É o bloco declarado e não executado — o
#: aluno apertou "pausa" e não voltou — e também o bloco de uma sessão cuja
#: captura nunca subiu.
MOTIVO_SEM_CAPTURA = "sem-captura"

#: A frase que o aluno lê no lugar da média. Fechada, como
#: `recomendacoes.NOMES_DE_ALERTA`: motivo sem frase seria um bloco mudo, e
#: bloco mudo no relatório é falha silenciosa.
FRASES_SEM_MEDIA: Dict[str, str] = {
    MOTIVO_CURTO_DEMAIS: "Curto demais para uma média.",
    MOTIVO_SEM_MEDIDA: "Não deu para medir este bloco.",
    MOTIVO_SEM_CAPTURA: "Nenhuma leitura chegou neste bloco.",
}

#: Nome legível de cada tipo de bloco, no molde de `recomendacoes.NOMES_DE_ALERTA`.
#:
#: Traduzir aqui, e não no navegador, mantém uma única versão do vocabulário: a
#: tela recebe o nome pronto e não precisa saber que `"foco"` existe. Um tipo
#: novo sem tradução aparece cru na tela, que é um bug visível — melhor que o
#: bloco sumir do relatório, que é um bug invisível.
NOMES_DE_TIPO: Dict[str, str] = {
    blocos.TIPO_FOCO: "Foco",
    blocos.TIPO_PAUSA: "Pausa",
}

#: A mesma coisa dita de um jeito que aceita vários blocos de uma vez ("blocos 2
#: e 5: não deu para medir"). Duas tabelas, e não uma com conjugação calculada:
#: gramática derivada em tempo de execução é o caminho mais curto para uma frase
#: torta na tela do aluno.
ROTULOS_SEM_MEDIA: Dict[str, str] = {
    MOTIVO_CURTO_DEMAIS: "curto demais para uma média",
    MOTIVO_SEM_MEDIDA: "não deu para medir",
    MOTIVO_SEM_CAPTURA: "nenhuma leitura chegou",
}


@dataclass(frozen=True)
class BlocoAvaliado:
    """Um bloco declarado com o que a série diz sobre ele.

    As três durações não são redundantes e nenhuma substitui a outra:
    `duracao_s` é o que o aluno declarou ao apertar o botão, e
    `duracao_com_captura_s` é quanto tempo houve evidência de captura lá dentro.
    A diferença entre elas é informação — "25 min declarados · 11 min com
    captura" —, não inconsistência a esconder.

    **Não existe aqui um campo de rótulo dominante**, e a ausência é
    deliberada. `DetectorDeFadiga._intervalos` atribui a duração entre duas
    amostras ao estado da **primeira**: uma parada de captura de 30 a 59 s logo
    depois de uma piscada computa o intervalo inteiro como pálpebra fechada.
    Diluído em duas horas isso some; dentro de um bloco de 12 minutos, um campo
    chamado `alerta_dominante` transformaria esse artefato no nome daquele
    bloco. Os alertas saem em **contagem de registros**, que é o que eles são.
    """

    indice: int
    tipo: str
    tipo_nome: str
    inicio: datetime
    fim: Optional[datetime]
    duracao_s: float
    duracao_com_captura_s: float
    pontos_medidos: int
    pontos_incertos: int
    media: Optional[float]

    #: `None` quando há média. Quando não há, um de `FRASES_SEM_MEDIA` — o
    #: código para a máquina, a frase pronta para a pessoa, no molde de
    #: `AlertaPublico`.
    motivo_sem_media: Optional[str]
    observacao: Optional[str]

    alertas_de_fadiga: Dict[str, int]


@dataclass(frozen=True)
class Cadencia:
    """O declarado ao lado do executado, em durações e contagens.

    **Nenhum campo aqui é razão normalizada, e essa é a regra estrutural desta
    story.** O que atravessa é `duracao_alvo_s` (o que o método prescreve),
    `duracoes_observadas_s` (o que aconteceu), `blocos_na_faixa`,
    `blocos_de_foco` e `meta_de_blocos` — nunca o quociente entre eles.

    O motivo está no docstring do módulo, e a consequência prática é esta: um
    campo novo do tipo `float` chamado `aderencia` passaria em silêncio por
    todos os testes de texto que o projeto tem, porque não afirma estado interno
    nenhum. Teste de string é conselho; teste de tipo é regra, e é por isso que
    `test_criterios.py` varre estes campos em vez de varrer estas frases.
    """

    duracao_alvo_s: int
    duracoes_observadas_s: Tuple[float, ...]
    blocos_na_faixa: int
    blocos_de_foco: int
    meta_de_blocos: Optional[int]


@dataclass(frozen=True)
class Criterio:
    """Uma leitura da sessão segundo o método, com a evidência que a sustenta.

    Mesma forma de `recomendacoes.Recomendacao`, e de propósito: as duas são
    frases que o aluno lê sobre a própria sessão, e uma forma só é o que permite
    à tela renderizá-las do mesmo jeito e ao teste de tom varrê-las juntas.
    `detalhe` existe pela razão que `Recomendacao.motivo` existe — leitura sem o
    dado que a originou é opinião.
    """

    codigo: str
    titulo: str
    texto: str
    detalhe: str


@dataclass(frozen=True)
class Avaliacao:
    """A sessão inteira lida segundo o método declarado.

    `media_de_foco` é a correção que a ticket 17 existe para fazer: ela sai só
    dos pontos recortados pelos blocos de **foco**, e por isso uma pausa
    corretamente executada deixou de derrubá-la. Ela convive com
    `ResumoDaSessao.media` sem substituí-la — a da sessão continua congelada em
    `resumo_sessao` (ticket 13) e continua sendo o número que o aluno viu
    ontem; esta é a leitura do método, e só existe onde há método.
    """

    metodo: Optional[metodos.MetodoDeEstudo]
    blocos: Tuple[BlocoAvaliado, ...]
    blocos_de_foco: int
    blocos_de_pausa: int
    duracao_de_foco_s: float
    duracao_de_pausa_s: float
    media_de_foco: Optional[float]
    cadencia: Optional[Cadencia]
    criterios: Tuple[Criterio, ...]


def _instante_do(ponto) -> datetime:
    return ponto.horario_registro


def avaliar(
    codigo_do_metodo: Optional[str],
    blocos_declarados: Sequence[blocos.BlocoLido],
    serie: Sequence,
    meta_de_blocos: Optional[int] = None,
    resolucao_da_serie_s: int = 1,
) -> Optional["Avaliacao"]:
    """A leitura da sessão pelo método, ou `None` se não houve método declarado.

    O `None` é a AC-17-11 inteira, e ele nasce **aqui** e não na tela: sessão com
    `metodo IS NULL` é anterior ao recurso, e uma seção de método vazia diria ao
    aluno que ele escolheu não usar método — que é `"livre"`, uma coisa
    diferente. Deixar a decisão para o template obrigaria cada tela a repeti-la,
    e a primeira que esquecesse inventaria a escolha.

    `resolucao_da_serie_s` é quantos segundos cada ponto da série representa.
    Vale 1 na sessão do dia e 60 depois que `sumarizacao.aplicar_retencao`
    colapsa a série em médias por minuto. Sem esse parâmetro, todo bloco de uma
    sessão de ontem cairia na abstenção por n pequeno e o relatório diria "curto
    demais para uma média" sobre um bloco de meia hora — uma frase falsa
    produzida por uma faxina de banco, que é a espécie de defeito que a ticket 13
    inteira foi construída para impedir.
    """
    if codigo_do_metodo is None:
        return None

    metodo = metodos.buscar(codigo_do_metodo)
    ordenados = sorted(blocos_declarados, key=lambda bloco: bloco.indice)
    avaliados = tuple(
        _avaliar_bloco(bloco, serie, resolucao_da_serie_s) for bloco in ordenados
    )

    de_foco = [a for a in avaliados if a.tipo == blocos.TIPO_FOCO]
    de_pausa = [a for a in avaliados if a.tipo == blocos.TIPO_PAUSA]

    cadencia = _cadencia(metodo, de_foco, meta_de_blocos)
    media_de_foco = _media_dos_blocos_de_foco(
        ordenados, serie, resolucao_da_serie_s
    )

    return Avaliacao(
        metodo=metodo,
        blocos=avaliados,
        blocos_de_foco=len(de_foco),
        blocos_de_pausa=len(de_pausa),
        duracao_de_foco_s=sum(a.duracao_s for a in de_foco),
        duracao_de_pausa_s=sum(a.duracao_s for a in de_pausa),
        media_de_foco=media_de_foco,
        cadencia=cadencia,
        criterios=_criterios(metodo, avaliados, de_foco, de_pausa, cadencia, meta_de_blocos),
    )


def _avaliar_bloco(
    bloco: blocos.BlocoLido, serie: Sequence, resolucao_da_serie_s: int
) -> BlocoAvaliado:
    """Um bloco com os indicadores da fatia de série que cai dentro dele.

    O recorte é `blocos.recortar`, que já é semiaberto e já tem teste de que dois
    blocos consecutivos particionam a série sem duplicar nem perder ponto.
    Refazer o recorte aqui criaria uma segunda opinião sobre a borda, e o ponto
    da transição passaria a ser contado duas vezes numa sessão de quatro blocos.
    """
    dentro = blocos.recortar(bloco, serie, _instante_do)
    indicadores = relatorio.resumir_serie(dentro)
    media, motivo = _media_ou_motivo(indicadores, resolucao_da_serie_s)

    return BlocoAvaliado(
        indice=bloco.indice,
        tipo=bloco.tipo,
        tipo_nome=NOMES_DE_TIPO.get(bloco.tipo, bloco.tipo),
        inicio=bloco.inicio,
        fim=bloco.fim,
        duracao_s=blocos.duracao(bloco).total_seconds(),
        duracao_com_captura_s=presenca.duracao_presente(
            bloco.inicio, bloco.fim, (ponto.horario_registro for ponto in dentro)
        ).total_seconds(),
        pontos_medidos=indicadores.pontos_medidos,
        pontos_incertos=indicadores.pontos_incertos,
        media=media,
        motivo_sem_media=motivo,
        observacao=FRASES_SEM_MEDIA[motivo] if motivo is not None else None,
        alertas_de_fadiga=dict(indicadores.alertas_de_fadiga),
    )


def _media_ou_motivo(
    indicadores: "relatorio.IndicadoresDaSerie", resolucao_da_serie_s: int
) -> Tuple[Optional[float], Optional[str]]:
    """A média do trecho, ou o motivo de ela não existir.

    A ordem das perguntas importa, e é o que separa E1 de E7: um bloco sem
    nenhuma medida e com pontos incertos não é "curto demais", é "não deu para
    medir". Os dois têm `media = None` e mandam o aluno mexer em coisas
    diferentes, e colapsá-los num motivo só devolveria ao relatório a ambiguidade
    que a ticket 10 comprou o direito de não ter.
    """
    medida_s = indicadores.pontos_medidos * resolucao_da_serie_s

    if medida_s >= MEDIDA_MINIMA_S:
        return indicadores.media, None
    if indicadores.pontos_medidos == 0 and indicadores.pontos_incertos == 0:
        return None, MOTIVO_SEM_CAPTURA
    if indicadores.pontos_medidos == 0:
        return None, MOTIVO_SEM_MEDIDA
    return None, MOTIVO_CURTO_DEMAIS


def _media_dos_blocos_de_foco(
    ordenados: Sequence[blocos.BlocoLido], serie: Sequence, resolucao_da_serie_s: int
) -> Optional[float]:
    """A média do IEE **sem os pontos das pausas**.

    É a linha que a ticket 17 inteira existe para escrever. Note que ela junta os
    pontos crus de todos os blocos de foco e tira uma média só, em vez de tirar a
    média das médias dos blocos: média de médias não é média, e um bloco de 31
    minutos pesaria o mesmo que um de 12 — o mesmo erro que a ticket 13 recusou
    ao congelar os indicadores em `resumo_sessao`.
    """
    pontos: List = []
    for bloco in ordenados:
        if bloco.tipo == blocos.TIPO_FOCO:
            pontos.extend(blocos.recortar(bloco, serie, _instante_do))

    media, _ = _media_ou_motivo(relatorio.resumir_serie(pontos), resolucao_da_serie_s)
    return media


def _faixa_de_cadencia(duracao_alvo_s: int) -> Tuple[float, float]:
    """Os dois extremos da faixa, em segundos."""
    folga = TOLERANCIA_DE_CADENCIA * duracao_alvo_s
    return duracao_alvo_s - folga, duracao_alvo_s + folga


def _cadencia(
    metodo: Optional[metodos.MetodoDeEstudo],
    de_foco: Sequence[BlocoAvaliado],
    meta_de_blocos: Optional[int],
) -> Optional[Cadencia]:
    """A comparação entre a duração prescrita e as observadas.

    `None` quando o método não prescreve duração de bloco (Flow, Timeboxing e
    "Sem método", todos com `foco_s` nulo) ou quando não houve bloco de foco
    nenhum. Nos dois casos não há alvo contra o qual comparar, e inventar um —
    "vamos supor 25 minutos" — faria o relatório cobrar do aluno um plano que
    ele não declarou.
    """
    if metodo is None or metodo.foco_s is None or not de_foco:
        return None

    piso, teto = _faixa_de_cadencia(metodo.foco_s)
    duracoes = tuple(bloco.duracao_s for bloco in de_foco)

    return Cadencia(
        duracao_alvo_s=metodo.foco_s,
        duracoes_observadas_s=duracoes,
        # Bloco declarado e não executado tem duração zero e **não** entra na
        # faixa: contá-lo diria que o aluno conduziu um bloco que não houve.
        blocos_na_faixa=sum(1 for d in duracoes if d > 0 and piso <= d <= teto),
        blocos_de_foco=len(de_foco),
        meta_de_blocos=meta_de_blocos,
    )


def _criterios(
    metodo: Optional[metodos.MetodoDeEstudo],
    avaliados: Sequence[BlocoAvaliado],
    de_foco: Sequence[BlocoAvaliado],
    de_pausa: Sequence[BlocoAvaliado],
    cadencia: Optional[Cadencia],
    meta_de_blocos: Optional[int],
) -> Tuple[Criterio, ...]:
    """As frases que o relatório publica sobre o método executado.

    Curtas e poucas, pela mesma razão que `recomendacoes.recomendar` é curto: um
    relatório com oito leituras não tem nenhuma. Cada uma delas descreve o que
    aconteceu e nada mais — não há aqui nenhuma frase que diga se foi bom.
    """
    lista: List[Criterio] = []

    if not avaliados:
        lista.append(
            Criterio(
                codigo="sem-blocos",
                titulo="Nenhum bloco foi registrado",
                texto=(
                    "Esta sessão declarou um método e nenhuma transição entre foco e pausa "
                    "chegou até aqui. Sem as transições não há estrutura para descrever — "
                    "o índice e as durações acima continuam valendo para a sessão inteira."
                ),
                detalhe=f"Método declarado: {_nome(metodo)}.",
            )
        )
        return tuple(lista)

    if cadencia is not None:
        lista.append(_criterio_de_cadencia(metodo, cadencia))

    continuidade = _criterio_de_continuidade(de_foco)
    if continuidade is not None:
        lista.append(continuidade)

    if meta_de_blocos is not None:
        lista.append(
            Criterio(
                codigo="meta",
                titulo="O que você planejou e o que conduziu",
                texto=(
                    f"Você abriu a sessão planejando {_por_extenso(meta_de_blocos)} "
                    f"{_plural(meta_de_blocos, 'bloco', 'blocos')} de foco e conduziu "
                    f"{_por_extenso(len(de_foco))}."
                ),
                detalhe=f"{len(de_foco)} de {meta_de_blocos} blocos de foco declarados.",
            )
        )

    if de_pausa:
        minutos = _minutos(sum(bloco.duracao_s for bloco in de_pausa))
        lista.append(
            Criterio(
                codigo="pausas",
                titulo="As pausas ficam fora da média",
                texto=(
                    f"Você declarou {_por_extenso(len(de_pausa), feminino=True)} "
                    f"{_plural(len(de_pausa), 'pausa', 'pausas')}, somando {minutos}. "
                    "Esse tempo não entra na média dos blocos de foco: o que o método manda "
                    "fazer não pode pesar contra quem o fez."
                ),
                detalhe=f"{minutos} declarados em pausa.",
            )
        )

    sem_media = [bloco for bloco in avaliados if bloco.media is None]
    if sem_media:
        lista.append(_criterio_de_medida(sem_media))

    return tuple(lista)


def _criterio_de_cadencia(
    metodo: Optional[metodos.MetodoDeEstudo], cadencia: Cadencia
) -> Criterio:
    """A AC-17-10 escrita por extenso: contagem, nunca razão.

    A frase diz quantos blocos ficaram na faixa e quais são os limites dela. Ela
    **não** diz "você seguiu" nem publica quociente: o aluno lê quatro números
    que pode conferir no relógio e decide sozinho o que eles significam.
    """
    piso, teto = _faixa_de_cadencia(cadencia.duracao_alvo_s)
    faixa = f"entre {_minutos_inteiros(piso)} e {_minutos_inteiros(teto)} minutos"
    na_faixa = cadencia.blocos_na_faixa
    total = cadencia.blocos_de_foco

    fora = total - na_faixa

    if fora == 0:
        texto = (
            f"{_por_extenso(total).capitalize()} "
            f"{_plural(total, 'bloco', 'blocos')} de foco "
            f"{_plural(total, 'ficou', 'ficaram')} {faixa}, que é a duração de bloco "
            f"do {_nome(metodo)}."
        )
    else:
        texto = (
            f"{_por_extenso(na_faixa).capitalize()} "
            f"{_plural(total, 'do', 'dos')} {_por_extenso(total)} "
            f"{_plural(total, 'bloco', 'blocos')} de foco "
            f"{_plural(na_faixa, 'ficou', 'ficaram')} {faixa} — a duração de bloco do "
            f"{_nome(metodo)}. "
            f"{_plural(fora, 'O outro ficou', f'Os outros {_por_extenso(fora)} ficaram')} "
            "fora dessa faixa."
        )

    observadas = ", ".join(_minutos(d) for d in cadencia.duracoes_observadas_s)
    return Criterio(
        codigo="cadencia",
        titulo="A duração dos seus blocos de foco",
        texto=texto,
        detalhe=f"Blocos de foco: {observadas}.",
    )


def _criterio_de_continuidade(de_foco: Sequence[BlocoAvaliado]) -> Optional[Criterio]:
    """O índice do primeiro bloco de foco ao lado do último.

    Existe só a partir de **dois** blocos de foco com média. Com um bloco só não
    há o que comparar, e comparar o bloco consigo mesmo produziria uma frase
    verdadeira e vazia. A frase põe os dois números lado a lado e para por aí: a
    diferença entre eles pode ser cansaço, pode ser o material da segunda metade,
    pode ser a luz da tarde — e este sistema não distingue os três.
    """
    com_media = [bloco for bloco in de_foco if bloco.media is not None]
    if len(com_media) < 2:
        return None

    primeiro, ultimo = com_media[0], com_media[-1]
    return Criterio(
        codigo="continuidade",
        titulo="Do primeiro bloco ao último",
        texto=(
            f"O índice médio foi {primeiro.media:.0f} no bloco {primeiro.indice} e "
            f"{ultimo.media:.0f} no bloco {ultimo.indice}. O que mudou entre um e outro "
            "pode estar no material, no ambiente ou no corpo — o sistema mede os três do "
            "mesmo jeito e não os distingue."
        ),
        detalhe=(
            f"Bloco {primeiro.indice}: {primeiro.media:.0f}. "
            f"Bloco {ultimo.indice}: {ultimo.media:.0f}."
        ),
    )


def _criterio_de_medida(sem_media: Sequence[BlocoAvaliado]) -> Criterio:
    """Por que alguns blocos aparecem com traço no lugar do índice.

    Sem esta frase o traço vira mistério, e mistério no relatório é lido como
    defeito do aluno. Os motivos vêm agrupados porque uma sessão pode ter os três
    ao mesmo tempo e uma linha por bloco viraria uma lista mais longa que o
    relatório.
    """
    partes = []
    for motivo in (MOTIVO_CURTO_DEMAIS, MOTIVO_SEM_MEDIDA, MOTIVO_SEM_CAPTURA):
        indices = [bloco.indice for bloco in sem_media if bloco.motivo_sem_media == motivo]
        if indices:
            partes.append(
                f"{_plural(len(indices), 'Bloco', 'Blocos')} {_lista(indices)}: "
                f"{ROTULOS_SEM_MEDIA[motivo]}."
            )

    return Criterio(
        codigo="medida",
        titulo="Onde o índice não pôde ser calculado",
        texto=(
            "Um traço no lugar do índice é a recusa de publicar um número que a medida não "
            "sustenta — e nunca um índice zero, que diria uma coisa bem diferente sobre "
            "aquele trecho da sessão."
        ),
        detalhe=" ".join(partes),
    )


def _lista(indices: Sequence[int]) -> str:
    """`1`, `1 e 2`, `1, 2 e 5` — a enumeração como se escreve, não como se itera."""
    rotulos = [str(indice) for indice in indices]
    if len(rotulos) == 1:
        return rotulos[0]
    return f"{', '.join(rotulos[:-1])} e {rotulos[-1]}"


def _nome(metodo: Optional[metodos.MetodoDeEstudo]) -> str:
    """O nome legível do método, ou uma expressão neutra se ele não está no catálogo.

    Sessão gravada por uma versão com um método a mais abre com "o método
    declarado" em vez de estourar — mesma escolha de `metodos.buscar`.
    """
    return metodo.nome if metodo is not None else "método declarado"


#: Números por extenso até a meta máxima de blocos. O relatório fala em frases,
#: e "2 dos 4 blocos" no meio de um parágrafo lê-se como planilha. Fechado no 12
#: porque `schemas.META_MAXIMA_DE_BLOCOS` é 12 — acima disso o código cai no
#: algarismo, que é feio e honesto, em vez de inventar "quatorze".
POR_EXTENSO_MASCULINO = (
    "nenhum", "um", "dois", "três", "quatro", "cinco", "seis",
    "sete", "oito", "nove", "dez", "onze", "doze",
)

POR_EXTENSO_FEMININO = (
    "nenhuma", "uma", "duas", "três", "quatro", "cinco", "seis",
    "sete", "oito", "nove", "dez", "onze", "doze",
)


def _por_extenso(quantidade: int, feminino: bool = False) -> str:
    tabela = POR_EXTENSO_FEMININO if feminino else POR_EXTENSO_MASCULINO
    if 0 <= quantidade < len(tabela):
        return tabela[quantidade]
    return str(quantidade)


def _plural(quantidade: int, singular: str, plural: str) -> str:
    return singular if quantidade == 1 else plural


def _minutos_inteiros(segundos: float) -> int:
    """Minutos arredondados, e não truncados como em `recomendacoes._minutos`.

    A diferença tem motivo: aqui o número é conferido pelo aluno contra a faixa
    que a frase ao lado anuncia. Um bloco de 29 min 40 s truncado viraria
    "29 min" numa frase que fala em "entre 20 e 30 minutos" — a conta bateria
    errado no papel dele e o erro seria nosso.
    """
    return int(round(segundos / 60))


def _minutos(segundos: float) -> str:
    return f"{_minutos_inteiros(segundos)} min"
