"""Critérios de aceitação das metas de desempenho (Tabelas 9 e 10 do TCC).

As metas vêm do pré-projeto, que não dizia em qual estatística cada uma seria
julgada. Os critérios abaixo foram fixados em 17/11/2026, depois das medições
de 08/11/2026, sem mudar o valor de nenhuma meta. A regra é olhar a cauda, e
não o caso típico: tempo no percentil 95 e taxa de quadros no percentil 5. A
mediana continua sendo informada, mas não decide.

Uso:
    python metas.py evidencias/sessao-real-1.json
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional

CRITERIOS_FIXADOS_EM = "2026-11-17"


def percentil(valores: Iterable[float], p: float) -> Optional[float]:
    """Posto mais próximo, sem interpolação: o mesmo método de medir_latencia.py,
    analisar_sessao.py e do log do backend."""
    v = sorted(valores)
    if not v:
        return None
    return v[max(1, math.ceil(p / 100 * len(v))) - 1]


@dataclass(frozen=True)
class Meta:
    codigo: str
    indicador: str
    limite: float
    unidade: str
    estatistica: float  # percentil que decide
    sentido: str  # "max": o valor tem de ficar <= limite; "min": >= limite

    def julgar(self, valores: List[float]) -> Dict[str, object]:
        if not valores:
            return {"meta": self.codigo, "n": 0, "valor": None, "atendida": None}
        valor = percentil(valores, self.estatistica)
        ok = valor <= self.limite if self.sentido == "max" else valor >= self.limite
        dentro = sum(1 for x in valores if (x <= self.limite if self.sentido == "max" else x >= self.limite))
        return {
            "meta": self.codigo,
            "n": len(valores),
            "valor": valor,
            "mediana": percentil(valores, 50),
            "proporcao_dentro": dentro / len(valores),
            "atendida": ok,
        }


METAS = {
    "fps": Meta("fps", "Taxa de quadros da captura", 15, "FPS", 5, "min"),
    "websocket": Meta("websocket", "Latência do WebSocket (ida e volta)", 200, "ms", 95, "max"),
    "backend": Meta("backend", "Tempo de resposta do backend", 100, "ms", 95, "max"),
    "ciclo": Meta("ciclo", "Ciclo de feedback (trecho rede e backend)", 1000, "ms", 95, "max"),
}


def series_da_sessao(gravacao: dict) -> Dict[str, List[float]]:
    """Extrai as séries de uma gravação do gravador_mapface.js."""
    scores = [r for r in gravacao.get("recebidos", []) if r.get("tipo") == "score"]
    rtt = [r["rtt_ms"] for r in scores if r.get("rtt_ms") is not None]
    proc = [r["processamento_ms"] for r in scores if r.get("processamento_ms") is not None]
    fps = [f["fps"] for f in gravacao.get("fps", []) if f.get("fps") is not None]
    return {"fps": fps, "websocket": rtt, "backend": proc, "ciclo": rtt}


def avaliar(gravacao: dict) -> Dict[str, Dict[str, object]]:
    series = series_da_sessao(gravacao)
    return {codigo: meta.julgar(series[codigo]) for codigo, meta in METAS.items()}


def main(argv: Optional[List[str]] = None) -> int:
    a = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    a.add_argument("gravacao", type=Path)
    args = a.parse_args(argv)
    resultado = avaliar(json.loads(args.gravacao.read_text(encoding="utf-8")))
    print(f"Critérios fixados em {CRITERIOS_FIXADOS_EM}")
    for codigo, r in resultado.items():
        m = METAS[codigo]
        lado = "<=" if m.sentido == "max" else ">="
        situacao = {True: "ATENDIDA", False: "NÃO ATENDIDA", None: "SEM DADOS"}[r["atendida"]]
        valor = "-" if r["valor"] is None else f"{r['valor']:.1f}"
        print(f"{m.indicador}: p{m.estatistica:g} = {valor} {m.unidade} (meta {lado} {m.limite:g}) -> {situacao}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
