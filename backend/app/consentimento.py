"""A regra do consentimento: quando o aceite do termo está valendo.

Como `app/presenca.py` e `app/blocos.py`, este módulo não conhece HTTP nem banco.
Quem grava o aceite e a revogação é `app/conta.py`; quem recusa a sessão é o
router. Aqui fica só a pergunta que os dois fazem.

**O projeto adota o consentimento como base legal** (LGPD, art. 11, I). O artigo
admite outras hipóteses, e esta é a escolhida para uma ferramenta de uso
voluntário. Daí a consequência operacional: sem aceite vigente não há sessão,
porque não há outra base que autorize o tratamento das métricas faciais.

**A versão faz parte do aceite.** O termo promete um novo aceite quando mudar, e
isso só é verdade se aceitar a versão anterior deixar de valer sozinho, sem
depender de alguém lembrar de zerar uma coluna.

**Maioridade é autodeclarada, e não há data de nascimento.** Guardar a data só
para conferir uma conta seria coletar um dado a mais para provar que se coleta
pouco. A declaração é parte do aceite: conta sem ela não nasce.
"""
from datetime import datetime
from typing import Optional

#: Versão do termo em vigor. O texto mora em `frontend/src/app/core/consentimento/termo.ts`,
#: que precisa declarar este mesmo número.
VERSAO_TERMO = "1.2"


def vigente(
    termo_versao: Optional[str],
    termo_aceito_em: Optional[datetime],
    consentimento_revogado_em: Optional[datetime],
) -> bool:
    """Se o titular aceitou a versão atual do termo e não revogou depois."""
    return (
        termo_versao == VERSAO_TERMO
        and termo_aceito_em is not None
        and consentimento_revogado_em is None
    )
