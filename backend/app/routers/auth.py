from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from app import conta
from app.database import get_session
from app.deps import get_aluno_atual, oauth2_scheme
from app.models import Aluno
from app.schemas import (
    AceiteDoTermo,
    AlunoLogin,
    AlunoPublico,
    AlunoRegistro,
    CorrecaoDePerfil,
    ExclusaoDeConta,
    PerfilCorrigido,
    Token,
)
from app.security import (
    criar_token_acesso,
    hash_senha,
    reemitir_para_email,
    renovar_token,
    verificar_senha,
)

router = APIRouter(prefix="/auth", tags=["autenticação"])


@router.post("/registro", response_model=AlunoPublico, status_code=status.HTTP_201_CREATED)
def registrar(dados: AlunoRegistro, session: Session = Depends(get_session)) -> Aluno:
    email_existente = session.exec(select(Aluno).where(Aluno.email == dados.email)).first()
    if email_existente is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="E-mail já cadastrado"
        )

    aluno = Aluno(
        nome=dados.nome,
        email=dados.email,
        senha_hash=hash_senha(dados.senha),
        objetivo_estudo=dados.objetivo,
    )
    conta.registrar_aceite(aluno)
    session.add(aluno)
    session.commit()
    session.refresh(aluno)
    return aluno


@router.post("/login", response_model=Token)
def login(dados: AlunoLogin, session: Session = Depends(get_session)) -> Token:
    aluno = session.exec(select(Aluno).where(Aluno.email == dados.email)).first()
    if aluno is None or not verificar_senha(dados.senha, aluno.senha_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="E-mail ou senha inválidos"
        )

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
    """Os dados da conta e o estado do consentimento."""
    return aluno_atual


@router.patch("/me", response_model=PerfilCorrigido)
def corrigir_perfil(
    dados: CorrecaoDePerfil,
    aluno_atual: Aluno = Depends(get_aluno_atual),
    token: str = Depends(oauth2_scheme),
    session: Session = Depends(get_session),
) -> PerfilCorrigido:
    novo_token = None
    email_mudou = dados.email is not None and dados.email != aluno_atual.email

    if email_mudou:
        em_uso = session.exec(select(Aluno).where(Aluno.email == dados.email)).first()
        if em_uso is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="E-mail já cadastrado"
            )
        aluno_atual.email = dados.email
        novo_token = reemitir_para_email(token, dados.email)

    if dados.nome is not None:
        aluno_atual.nome = dados.nome

    if dados.objetivo is not None:
        aluno_atual.objetivo_estudo = dados.objetivo

    session.add(aluno_atual)
    session.commit()
    session.refresh(aluno_atual)
    return PerfilCorrigido.model_validate(aluno_atual).model_copy(
        update={"access_token": novo_token}
    )


@router.post("/consentimento", response_model=AlunoPublico)
def aceitar_termo(
    _: AceiteDoTermo,
    aluno_atual: Aluno = Depends(get_aluno_atual),
    session: Session = Depends(get_session),
) -> Aluno:
    """Aceite de conta anterior ao termo, ou novo aceite depois de revogar."""
    return conta.aceitar(session, aluno_atual)


@router.delete("/consentimento", response_model=AlunoPublico)
def revogar_consentimento(
    aluno_atual: Aluno = Depends(get_aluno_atual),
    session: Session = Depends(get_session),
) -> Aluno:
    """Revogação (LGPD, art. 8º, § 5º): impede novas sessões e não apaga nada."""
    return conta.revogar(session, aluno_atual)


@router.delete("/conta", status_code=status.HTTP_204_NO_CONTENT)
def excluir_conta(
    dados: ExclusaoDeConta,
    aluno_atual: Aluno = Depends(get_aluno_atual),
    session: Session = Depends(get_session),
) -> None:
    """Apaga a conta e todos os dados dela (LGPD, art. 18, VI).

    Pede a senha porque é irreversível e o token fica no navegador: quem achar
    a aba aberta não pode apagar a conta de ninguém. Senha errada é **403**, e
    não 401, porque o interceptor do frontend lê 401 como credencial vencida e
    derrubaria a sessão de quem só digitou errado.
    """
    if not verificar_senha(dados.senha, aluno_atual.senha_hash):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Senha incorreta")

    conta.excluir(session, aluno_atual)
