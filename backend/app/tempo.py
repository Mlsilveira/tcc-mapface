"""Helpers de tempo.

Todo instante gravado no banco é UTC. O SQLite (usado na PoC) devolve datetimes
sem fuso, enquanto o PostgreSQL (alvo da ticket 14) devolve com fuso — `como_utc`
normaliza os dois casos para que comparações e serialização não dependam do
banco embaixo.
"""
from datetime import datetime, timezone


def agora_utc() -> datetime:
    return datetime.now(timezone.utc)


def como_utc(valor: datetime) -> datetime:
    if valor.tzinfo is None:
        return valor.replace(tzinfo=timezone.utc)
    return valor.astimezone(timezone.utc)
