"""Hash de senha e emissão/leitura do JWT.

**O problema que a renovação existe para resolver.** Até os métodos de estudo
entrarem, `access_token_expire_minutes` era um teto absoluto disfarçado de
detalhe: o token vivia 30 minutos, não havia renovação em lugar nenhum, e
portanto **nenhuma sessão de estudo passava de meia hora**. Um ciclo Pomodoro
completo (4 blocos + pausas ≈ 2 h) era impossível — e não por causa do
Pomodoro. As sessões gravadas em `app.db` durante o desenvolvimento têm 1 a 3
minutos, o que escondeu o limite por meses.

**A solução: janela deslizante com teto absoluto carimbado no token.** Um
endpoint só (`POST /auth/renovar`), um tipo de token só. O token desliza
enquanto o aluno usa o sistema; `iat` guarda o início da *sessão de credencial*
e é propagado a cada renovação, de modo que o teto é contado do login e não do
último uso.

Defesa em uma linha: *o token renova enquanto o aluno usa o sistema, mas
nenhuma credencial vive mais que o teto depois do login, e renovar exige um
token ainda válido.*

**As quatro alternativas descartadas, e por quê** — isto é material de defesa,
não anotação de conveniência:

1. **Simplesmente aumentar `ACCESS_TOKEN_EXPIRE_MINUTES`.** Troca o problema de
   lugar: para cobrir uma tarde de estudo o valor teria de ir a 4–6 horas, e aí
   um token roubado vale 4–6 horas *sem nenhum uso legítimo no meio*. O número
   passaria a ser dimensionado pelo caso mais longo em vez do risco — e o que se
   quer é o contrário: janela curta de exposição, vida longa só enquanto há
   atividade.
2. **Sliding puro, sem teto.** É a implementação ingênua e a mais comum: cada
   request empurra o `exp`. Produz credencial **eterna** — basta um request a
   cada 29 minutos, e o heartbeat de 60 s faz isso sozinho, com a aba aberta e
   ninguém na frente dela. O teto no `iat` é exatamente o que separa "desliza"
   de "nunca expira".
3. **Dois tokens (access + refresh).** É a resposta canônica, e aqui pagaria
   caro por benefício que não se materializa: exige armazenar/revogar o refresh
   no servidor (senão é só um token longo com outro nome), duplica o caminho de
   erro no cliente e dobra a superfície de teste. O ganho real do par é poder
   **revogar** — e revogação depende de estado no servidor, que este projeto não
   tem e cuja introdução é decisão de outra ordem. Sem revogação, dois tokens são
   um token com cerimônia.
4. **Renovar pela presença física** (a câmera vê o aluno → estende a
   credencial). Frase bonita e propriedade de segurança ruim: uma foto colada no
   monitor renovaria indefinidamente — e o atacante nem precisa da foto, porque
   ele controla o cliente e manda `{"rosto_detectado": true}`. Além disso poria
   `criar_token_acesso` no caminho mais quente do sistema (1 Hz por aluno) e
   mataria o seam de teste que mantém `sessoes.py` e `analista.py` sem HTTP.
   **Presença estende a sessão; um mecanismo de auth estende a credencial** — e
   os dois compõem sem se conhecerem, porque a presença mantém a sessão, a
   sessão mantém o heartbeat, e o heartbeat carrega a renovação.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from jose import JWTError, jwt

from app.config import settings
from app.schemas import LIMITE_SENHA_BYTES
from app.tempo import agora_utc


def hash_senha(senha: str) -> str:
    return bcrypt.hashpw(senha.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verificar_senha(senha: str, senha_hash: str) -> bool:
    senha_bytes = senha.encode("utf-8")
    # O registro rejeita senhas acima do limite, então nenhum hash armazenado
    # pode corresponder a uma. Sem esta guarda o bcrypt levanta ValueError e o
    # login vira 500 em vez de 401.
    if len(senha_bytes) > LIMITE_SENHA_BYTES:
        return False
    return bcrypt.checkpw(senha_bytes, senha_hash.encode("utf-8"))


def teto_de_credencial() -> timedelta:
    """Quanto tempo depois do login nenhuma renovação mais é concedida."""
    return timedelta(hours=settings.teto_de_credencial_horas)


def criar_token_acesso(email: str, inicio_da_sessao: Optional[datetime] = None) -> str:
    """Emite um token, carimbando quando a **sessão de credencial** começou.

    `inicio_da_sessao` é o que separa este desenho de um sliding puro. No login
    ele é omitido e vale "agora"; na renovação ele vem do token anterior, de modo
    que o teto continue sendo contado do login. Se cada renovação recarimbasse o
    início, o teto nunca seria alcançado e a credencial seria eterna — que é
    justamente a falha da alternativa 2 do docstring do módulo.

    O claim usado é o `iat` registrado, e isto é deliberado apesar de ele passar
    a não significar mais "instante em que *este* token foi emitido": é o claim
    que qualquer ferramenta de inspeção de JWT já sabe ler, e o projeto não
    valida `iat` contra relógio em lugar nenhum. O equivalente exato em OIDC
    seria `auth_time`; inventar um claim próprio custaria um vocabulário novo
    para ganhar precisão que ninguém aqui consome.
    """
    agora = agora_utc()
    inicio = inicio_da_sessao or agora
    expira_em = agora + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {"sub": email, "iat": inicio, "exp": expira_em}
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def _decodificar(token: str) -> Optional[dict]:
    """O payload completo, ou `None` se o token for inválido ou estiver expirado.

    Separado de `decodificar_token` porque a renovação precisa de `iat` e `exp`,
    e expor o dicionário cru para quem só quer saber quem é o aluno convidaria
    cada chamador a ler claims por conta própria.
    """
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except JWTError:
        return None


def decodificar_token(token: str) -> Optional[str]:
    """Retorna o e-mail (subject) do token, ou None se inválido/expirado."""
    payload = _decodificar(token)
    if payload is None:
        return None
    return payload.get("sub")


def expiracao_do_token(token: str) -> Optional[datetime]:
    """O instante em que o token deixa de valer, para quem precisa reavaliá-lo.

    Existe por causa do WebSocket de telemetria, que autentica **uma vez** e
    depois fica horas aberto. Um canal autenticado que nunca reavalia a
    credencial é imune a expiração e a logout; enquanto a sessão morria em 30
    minutos isso era invisível, porque o heartbeat tomava 401 e o cliente
    desmontava tudo. Com a renovação, deixa de ser invisível.

    Devolve `None` quando o token é inválido **ou** quando não traz `exp`.
    Quem reavalia precisa tratar os dois como "não dá para afirmar que ainda
    vale" — a mesma disciplina de `None` significar ausência de medida, e não
    zero, que o resto do projeto segue.
    """
    payload = _decodificar(token)
    if payload is None:
        return None

    exp = payload.get("exp")
    if not isinstance(exp, (int, float)) or isinstance(exp, bool):
        return None
    return datetime.fromtimestamp(exp, tz=timezone.utc)


def _inicio_da_sessao_de(payload: dict) -> datetime:
    """Quando a sessão de credencial deste token começou.

    Token sem `iat` só pode ter sido emitido pela versão anterior a este
    mecanismo. Ele **não** é tratado como "início agora" — isso daria ao token
    legado um teto maior que o de quem acabou de logar. O início é reconstruído
    de `exp - access_token_expire_minutes`, que é exato e não um chute: o único
    emissor é `criar_token_acesso`, e ele sempre usou essa janela. Sem `exp`
    utilizável sobra "agora", que só acontece com token que este sistema não
    emitiu.
    """
    iat = payload.get("iat")
    if isinstance(iat, (int, float)) and not isinstance(iat, bool):
        return datetime.fromtimestamp(iat, tz=timezone.utc)

    exp = payload.get("exp")
    if isinstance(exp, (int, float)) and not isinstance(exp, bool):
        expira_em = datetime.fromtimestamp(exp, tz=timezone.utc)
        return expira_em - timedelta(minutes=settings.access_token_expire_minutes)

    return agora_utc()


def renovar_token(token: str) -> Optional[str]:
    """Troca um token **ainda válido** por outro, preservando `iat`.

    Devolve `None` — e o endpoint responde 401 — em dois casos, que são as duas
    propriedades que sustentam o desenho:

    - **Token expirado não ressuscita.** Renovação exige credencial viva. Aceitar
      um token vencido faria de qualquer token roubado uma credencial permanente,
      que é exatamente o que o `exp` curto existe para impedir, e transformaria o
      access token num refresh token sem nenhuma das garantias de um.
    - **Passado o teto, não há mais renovação.** `agora - iat > teto_de_credencial`
      encerra a linhagem. O aluno faz login de novo; é o preço de uma frase que
      se pode afirmar sem ressalva sobre a vida máxima de uma credencial.

    Repare que não há estado no servidor: o teto viaja dentro do próprio token.
    Isso mantém a autenticação stateless (não há tabela de sessão, não há
    revogação) — o que é uma limitação declarada, não um descuido: revogar exige
    estado, e introduzir estado de sessão é decisão de outra ordem que esta
    função não tem autoridade para tomar sozinha.
    """
    payload = _decodificar(token)
    if payload is None:
        return None

    email = payload.get("sub")
    if not isinstance(email, str) or not email:
        return None

    inicio = _inicio_da_sessao_de(payload)
    if agora_utc() - inicio > teto_de_credencial():
        return None

    return criar_token_acesso(email, inicio_da_sessao=inicio)
