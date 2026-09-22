"""A porta da frente: quem entra, quantas vezes pode tentar e quanto custa.

Os dois endpoints anônimos deste módulo são os únicos do sistema que qualquer
pessoa da internet alcança sem credencial, e os dois pagam um bcrypt cost 12
(~300 ms de CPU) por chamada. É por isso que `app/contencao.py` aparece aqui e em
nenhum outro router: o que se protege não é só a conta do aluno, é a capacidade
da única instância que serve a turma inteira.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from app import contencao
from app.config import settings
from app.database import get_session
from app.deps import get_aluno_atual, oauth2_scheme
from app.models import Aluno
from app.schemas import AlunoLogin, AlunoPublico, AlunoRegistro, Token
from app.security import (
    criar_token_acesso,
    hash_inalcancavel,
    hash_senha,
    renovar_token,
    verificar_senha,
)

router = APIRouter(prefix="/auth", tags=["autenticação"])

#: O que quem não está na lista lê. Não diz se a lista existe nem quem está
#: nela: a frase serve para a pessoa certa entender o que houve (falar com quem
#: conduz o estudo) sem virar um relatório para quem está do lado de fora.
CADASTRO_RESTRITO = (
    "Cadastro restrito aos participantes do estudo. "
    "Fale com quem conduz a pesquisa para ter seu e-mail incluído."
)

MUITAS_TENTATIVAS = "Muitas tentativas seguidas. Espere alguns minutos e tente de novo."

PORTA_OCUPADA = (
    "Há autenticações demais acontecendo agora. Tente de novo em alguns segundos."
)


def _recusar_por_tentativas() -> HTTPException:
    """429 com `Retry-After` em segundos — o cabeçalho que o cliente sabe ler.

    O valor é a janela inteira, e não o tempo exato que falta para a tentativa
    mais antiga expirar. Calcular o exato exigiria devolver o instante da
    primeira tentativa até aqui, e o número mais preciso diria a quem está
    varrendo exatamente quando voltar — o arredondamento para cima é a resposta
    correta para os dois públicos.
    """
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=MUITAS_TENTATIVAS,
        headers={"Retry-After": str(settings.janela_de_tentativas_minutos * 60)},
    )


def _recusar_por_ocupacao() -> HTTPException:
    """429 de fila cheia — segundos, não minutos: as vagas giram em ~1 s."""
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=PORTA_OCUPADA,
        headers={"Retry-After": "2"},
    )


@router.post("/registro", response_model=AlunoPublico, status_code=status.HTTP_201_CREATED)
def registrar(dados: AlunoRegistro, session: Session = Depends(get_session)) -> Aluno:
    """Cria a conta de quem está autorizado a participar do estudo.

    **Por que uma lista de e-mails e não um código de convite.** As duas fecham
    o cadastro; a lista é a que combina com o cenário real, que é uma turma
    conhecida, de tamanho conhecido, com os e-mails conhecidos antes do dia.

    O código de convite tem um defeito que não aparece no desenho e aparece no
    uso: ele é **um** segredo compartilhado por todos. Basta alguém encaminhar a
    mensagem do grupo e ele é tão público quanto a URL; tirar o acesso de uma
    pessoa obriga a trocar o código de todo mundo, inclusive de quem está no
    meio de uma sessão. Ele também exigiria um campo novo na tela de cadastro —
    e o frontend não muda por causa disto, o que aqui não é economia, é uma
    frente a menos para errar na semana da defesa.

    A lista nomeia a população real: entra quem foi convidado, sai quem desistiu
    (um item a menos), e o que está em vigor é legível na configuração da task
    em vez de estar na memória de quem distribuiu o código. O preço é precisar
    dos e-mails com antecedência — que é exatamente o que este estudo tem.

    **Vazio significa aberto**, e isso é deliberado: `git clone && uvicorn` e a
    suíte continuam cadastrando sem configurar nada. Para que o vazio não vire o
    modo de produção por esquecimento — que é a falha que originou tudo isto —,
    `verificar_configuracao` recusa subir com a lista vazia em `AMBIENTE=producao`.

    Os e-mails da turma numa variável de ambiente são dado pessoal, e ficam no
    mesmo lugar onde já está a senha do banco, com o mesmo controle de acesso.
    Vale dizer em voz alta porque é uma troca, não um detalhe: fechar o cadastro
    custa guardar uma lista de nomes em algum lugar.

    **A ordem das três recusas não é acidental.** O 403 vem antes de qualquer
    consulta ao banco, então quem está fora da lista não consegue distinguir um
    e-mail cadastrado de um livre — o 409 abaixo é um oráculo de existência, e
    esta ordem o deixa visível apenas para quem já está na lista e, portanto, já
    conhece a turma. Com a lista vazia (desenvolvimento) o oráculo volta, e ali
    ele não custa nada porque não há ninguém real cadastrado. Uniformizar o 409
    — responder 201 sem criar nada — foi descartado: seria mentir para o aluno
    que digitou o próprio e-mail duas vezes, que é o caso comum de longe, para
    esconder um fato de quem já está autorizado a conhecê-lo.
    """
    email = dados.email.strip().lower()

    autorizados = settings.emails_autorizados_a_registrar()
    if autorizados and email not in autorizados:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=CADASTRO_RESTRITO)

    if not contencao.tentativas.cobrar("registro:{}".format(email)):
        raise _recusar_por_tentativas()

    with contencao.vaga_de_autenticacao() as vaga:
        if not vaga:
            raise _recusar_por_ocupacao()

        email_existente = session.exec(select(Aluno).where(Aluno.email == dados.email)).first()
        if email_existente is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="E-mail já cadastrado"
            )

        aluno = Aluno(nome=dados.nome, email=dados.email, senha_hash=hash_senha(dados.senha))
        session.add(aluno)
        session.commit()
        session.refresh(aluno)
        return aluno


@router.post("/login", response_model=Token)
def login(dados: AlunoLogin, session: Session = Depends(get_session)) -> Token:
    """Troca e-mail e senha por um token — com tempo e contagem iguais para todos.

    **Duas defesas, contra dois ataques diferentes.** O contador por e-mail
    limita a adivinhação de senha, que é um ataque paciente: mil tentativas
    espalhadas pelo dia não derrubam nada e mesmo assim entram. O teto de
    trabalho em voo limita o esgotamento de CPU, que é um ataque instantâneo:
    são os ~300 ms de bcrypt por chamada, num threadpool que `/pronto` divide
    com esta rota. O porquê de cada um está em `app.contencao`.

    **O contador é zerado no acerto.** O limite existe contra quem *não*
    consegue entrar; quem acertou a senha provou não ser o caso, e sem isso o
    aluno que erra algumas vezes de manhã levaria 429 à tarde, no meio de uma
    sessão de estudo.

    **A verificação da senha acontece mesmo quando o e-mail não existe.** Antes,
    e-mail desconhecido voltava na hora e e-mail conhecido custava os 300 ms do
    bcrypt: a diferença é medível com o cronômetro do próprio navegador e
    responde "esta pessoa usa o sistema?" a qualquer um. É o oráculo de
    existência que as rotas de sessão evitam com o 404 uniforme, e que faltava
    justamente na porta da frente. `hash_inalcancavel` é o hash que o caminho
    sem aluno verifica para gastar o mesmo tempo.

    A comparação é feita **antes** do `if` de propósito. Escrever
    `if aluno is None or not verificar_senha(...)` faria o Python curto-circuitar
    e pular o bcrypt exatamente no caso que precisa pagá-lo — o defeito voltaria
    inteiro, com o código parecendo correto.
    """
    chave = "login:{}".format(dados.email.strip().lower())
    if not contencao.tentativas.cobrar(chave):
        raise _recusar_por_tentativas()

    with contencao.vaga_de_autenticacao() as vaga:
        if not vaga:
            raise _recusar_por_ocupacao()

        aluno = session.exec(select(Aluno).where(Aluno.email == dados.email)).first()
        referencia = aluno.senha_hash if aluno is not None else hash_inalcancavel()
        senha_confere = verificar_senha(dados.senha, referencia)

        if aluno is None or not senha_confere:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="E-mail ou senha inválidos"
            )

        contencao.tentativas.perdoar(chave)
        token = criar_token_acesso(aluno.email)
        return Token(access_token=token)


@router.post("/renovar", response_model=Token)
def renovar(
    aluno_atual: Aluno = Depends(get_aluno_atual),
    token: str = Depends(oauth2_scheme),
) -> Token:
    """Devolve um token novo em troca de um ainda válido (janela deslizante).

    Um endpoint só e um tipo de token só. O par access+refresh, que seria a
    resposta canônica, foi descartado porque o ganho dele é poder **revogar**, e
    revogação exige estado no servidor que este projeto não tem — sem isso,
    dois tokens são um token com cerimônia. O raciocínio inteiro, com as quatro
    alternativas, está no docstring de `app.security`.

    `get_aluno_atual` está aqui por dois motivos, e o segundo não é redundante
    com `renovar_token`: ele garante que **token expirado não ressuscita** (401
    antes de qualquer coisa) e que o aluno ainda existe no banco — um token
    perfeitamente assinado de uma conta removida não deve render credencial
    nova.

    O 401 devolvido daqui significa outra coisa que o 401 de `/auth/me`: não é
    "sua credencial não vale", é "sua credencial vale mas chegou ao teto de
    tempo desde o login". Para o cliente o desfecho é o mesmo — voltar à tela de
    login —, e por isso não ganha um código próprio.

    **Esta rota não entra no limite de tentativas**, e é a decisão mais
    importante deste módulo para a estabilidade do estudo. Ela é chamada em
    laço pelo cliente de cada aluno enquanto a sessão está aberta; qualquer
    contagem compartilhada entre alunos — por IP, por exemplo, que atrás de um
    balanceador é o mesmo IP para a turma inteira — transformaria o limite numa
    interrupção coletiva no meio da apresentação. E ela já é cara de atacar por
    outro motivo: exige um token válido, e não paga bcrypt.
    """
    novo_token = renovar_token(token)
    if novo_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credencial expirada: faça login novamente",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return Token(access_token=novo_token)


@router.get("/me", response_model=AlunoPublico)
def perfil(aluno_atual: Aluno = Depends(get_aluno_atual)) -> Aluno:
    """Endpoint de exemplo protegido — usado para provar que a autenticação bloqueia acesso sem token."""
    return aluno_atual
