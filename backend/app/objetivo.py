"""O objetivo de estudo declarado pelo aluno (RF04) e o que ele muda na recomendação (RF17).

São três valores fechados porque cada um leva a uma regra diferente da Tabela 6
do TCC. Um objetivo livre, digitado, não teria regra para disparar.

`None` é estado legítimo: contas criadas antes do campo existir não têm o que
informar, e o relatório delas simplesmente não recebe a recomendação por
objetivo. Inventar um padrão diria ao aluno algo que ele nunca declarou.
"""

from typing import Dict, Literal, Optional

Objetivo = Literal["prova", "vestibular", "pessoal"]

OBJETIVOS: Dict[str, str] = {
    "prova": "Prova específica",
    "vestibular": "Vestibular",
    "pessoal": "Estudo pessoal",
}


def nome(codigo: Optional[str]) -> Optional[str]:
    """O nome legível do objetivo, ou `None` quando não há objetivo declarado."""
    if codigo is None:
        return None
    return OBJETIVOS.get(codigo, codigo)
