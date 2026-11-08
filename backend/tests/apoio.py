"""O aceite que todo cadastro de teste precisa enviar."""
from app.consentimento import VERSAO_TERMO

ACEITE_DO_TERMO = {
    "aceitou_termo": True,
    "declarou_maioridade": True,
    "versao_termo": VERSAO_TERMO,
}
