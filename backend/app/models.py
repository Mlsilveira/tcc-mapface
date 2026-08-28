from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel

from app.tempo import agora_utc


class Aluno(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    nome: str
    email: str = Field(index=True, unique=True)
    senha_hash: str


class SessaoEstudo(SQLModel, table=True):
    """Uma sessão de estudo monitorada, do "iniciar" ao "encerrar".

    `ultima_atividade` não está no schema do spec (id, id_aluno, inicio, fim):
    é uma coluna operacional, necessária para detectar inatividade prolongada e
    encerrar a sessão automaticamente. A partir da ticket 6 ela passa a ser
    atualizada também pelos payloads de telemetria.
    """

    __tablename__ = "sessao_estudo"

    id: Optional[int] = Field(default=None, primary_key=True)
    id_aluno: int = Field(foreign_key="aluno.id", index=True)
    inicio: datetime = Field(default_factory=agora_utc)
    fim: Optional[datetime] = Field(default=None)
    ultima_atividade: datetime = Field(default_factory=agora_utc)

    #: Se os logs granulares desta sessão já foram colapsados em médias.
    #:
    #: É um marcador explícito, e não uma inferência a partir das linhas, porque
    #: uma sessão de uma única leitura é indistinguível de uma já sumarizada se
    #: a pergunta for "existe linha com `n_leituras` igual a 1?". Sem ele, a
    #: varredura reexaminaria essas sessões para sempre.
    resumida: bool = Field(default=False)


class LogEngajamento(SQLModel, table=True):
    """Um registro de score de engajamento dentro de uma sessão (ticket 6).

    Não existe — e não pode passar a existir — nenhuma coluna de imagem, vídeo
    ou landmark bruto aqui. Os landmarks são calculados e descartados no
    navegador; o que chega ao banco é o score derivado deles. Há um teste que
    trava a lista de colunas exatamente para forçar essa conversa quando alguém
    quiser adicionar campo novo.

    As colunas de fadiga entraram depois da ticket 8: o fator já era calculado e
    devolvido ao navegador, mas não era gravado — e o relatório da ticket 11
    precisa dos "alertas de fadiga registrados", que só existem se alguém os
    tiver registrado.

    **`flag_fadiga` e `fator_fadiga` convivem de propósito.** O spec previa só o
    booleano, e ele é o que responde "houve fadiga nesta sessão?" numa consulta
    direta. Mas um booleano não distingue um bocejo isolado de meia hora de
    pálpebra pesada, e é essa diferença que vira indicador-chave no relatório.
    O flag é sempre `fator_fadiga > 0`; há um teste que trava essa relação.
    """

    __tablename__ = "log_engajamento"

    id: Optional[int] = Field(default=None, primary_key=True)
    id_sessao: int = Field(foreign_key="sessao_estudo.id")

    #: Indexado porque toda leitura da série é ordenada ou filtrada por ele — o
    #: relatório, o gráfico e a sumarização. É a indexação temporal que a ticket
    #: 13 pede.
    horario_registro: datetime = Field(default_factory=agora_utc, index=True)
    score: float

    #: Quantas leituras esta linha representa.
    #:
    #: Vale 1 enquanto a linha é granular. Depois da sumarização da ticket 13,
    #: uma linha passa a representar uma janela inteira e os valores viram
    #: médias dela. Guardar o peso aqui, em vez de criar uma tabela separada de
    #: resumos, mantém **uma série só**: o relatório continua lendo de um lugar,
    #: e a única diferença é que a média passa a ser ponderada. Duas tabelas
    #: obrigariam todo leitor a saber qual das duas consultar, e a decidir o que
    #: fazer quando as duas tivessem linhas da mesma sessão.
    n_leituras: int = Field(default=1)

    #: Houve penalidade de fadiga neste instante.
    flag_fadiga: bool = Field(default=False)

    #: Quanto a fadiga descontou do score, em pontos da escala de 0 a 100.
    fator_fadiga: float = Field(default=0.0)

    #: Motivos separados por vírgula (`palpebras-pesadas`, `bocejos`, ...), ou
    #: `None` quando não houve alerta. Coluna de texto e não booleana porque a
    #: ticket 10 grava aqui a "Incerteza de Captura" pelo mesmo canal — o spec
    #: chamou de `alerta_gerado`, no singular, mas o campo sempre foi o lugar de
    #: registrar *o que* o sistema quis dizer ao aluno naquele segundo.
    alerta_gerado: Optional[str] = Field(default=None)

    #: Desvio do yaw em relação à pose neutra do aluno, em graus, com sinal.
    #: É o desvio, e não o yaw absoluto: a mesma normalização que o IEE usa, e a
    #: única forma de a série significar a mesma coisa entre alunos que sentam
    #: de jeitos diferentes. `None` quando não havia rosto.
    direcao_olhar: Optional[float] = Field(default=None)

    #: Se dá para confiar nesta leitura (ticket 10).
    #:
    #: `False` quando a captura estava instável — detecção piscando ou EAR
    #: saltando muito além do fisiológico. O `score` continua gravado, porque a
    #: fórmula é bem definida sobre os números que chegaram; o que esta coluna
    #: diz é que **aqueles números não descrevem o aluno**.
    #:
    #: É o critério "o alerta não é registrado como score corrompido": em vez de
    #: inventar um score, ou de gravar um buraco que apagaria o instante da
    #: série, a leitura fica registrada e marcada. O relatório exclui as não
    #: confiáveis dos indicadores, então uma câmera ruim vira "a captura falhou
    #: em 30% da sessão" em vez de "você esteve disperso em 30% da sessão" —
    #: que é exatamente a conclusão errada que a ticket existe para evitar.
    captura_confiavel: bool = Field(default=True)

    #: EAR e MAR brutos da janela, como o navegador os mediu. `None` sem rosto.
    #:
    #: Existem para **calibração**, não para o score — que já é derivado deles.
    #: Sem guardá-los não há como responder "o limiar de bocejo está certo?"
    #: depois da sessão: foi exatamente o que faltou para diagnosticar os 58
    #: alertas de bocejo da sessão de 28/08. A Sprint 11 prevê recalibrar esses
    #: limiares com dados reais, e estes são os dados.
    #:
    #: São números derivados de landmarks, como todo o resto que trafega — a
    #: fronteira de privacidade não se move por causa deles.
    ear: Optional[float] = Field(default=None)
    mar: Optional[float] = Field(default=None)
