"""Latência do canal de telemetria no ambiente publicado (parecer do TC2, F01).

Abre uma sessão **sintética e identificada**, manda payloads no ritmo do
navegador (1 Hz) e mede, para cada um:

- **RTT**: do `send` à chegada do `score` correspondente, no relógio deste
  processo. O pareamento é pelo carimbo `t0`, que o backend devolve intacto —
  não pela ordem de chegada;
- **processamento**: o `processamento_ms` que o backend devolve, medido do
  payload em memória até a resposta sair (fórmula, classificador, INSERT);
- **rede + fila**: RTT − processamento. É a única subtração feita aqui, e ela
  não soma nada ao RTT: o processamento já está *dentro* dele.

Percentil por posto mais próximo, sem interpolação — o mesmo de
`app.routers.telemetria.percentil` —, para o p95 ser uma medição que existiu.

**A sessão é identificável no banco.** Cada cliente cria uma conta própria com
o nome ``Medição sintética de latência``, e-mail ``medicao-sintetica-…`` e
assunto ``medicao-sintetica-latencia``. Quem consultar o banco depois separa
estas sessões das de alunos sem ambiguidade. A senha é gerada aqui e descartada:
ninguém precisa entrar nessas contas de novo.

Os payloads são **fixos e plausíveis** (olhos abertos, rosto de frente). Não
representam um aluno; servem para medir o canal, não o índice.

Uso, com o venv do backend::

    backend/.venv/Scripts/python.exe mapface-evidencias/medir_latencia.py \
        --duracao 120 --saida mapface-evidencias/latencia-1cliente.json

    # carga: N alunos simultâneos, cada um com conta e sessão próprias
    ... --clientes 5 --saida mapface-evidencias/latencia-5clientes.json
"""
import argparse
import asyncio
import json
import math
import secrets
import statistics
import sys
import time
from datetime import datetime, timezone
from typing import List, Optional

import httpx
import websockets

URL_PADRAO = "https://d2qm0t6ecgabb2.cloudfront.net"
NOME_DA_CONTA = "Medição sintética de latência"
# Espelha backend/app/consentimento.py. A conta sintética precisa aceitar o termo para abrir sessão.
VERSAO_DO_TERMO = "1.2"
ASSUNTO = "medicao-sintetica-latencia"

PAYLOAD = {
    "ear": 0.30,
    "yaw": 2.0,
    "mar": 0.10,
    "rosto_detectado": True,
    "incerteza": None,
    "ear_esq": 0.30,
    "ear_dir": 0.30,
    "pitch": -4.0,
    "roll": 1.0,
}


def percentil(valores: List[float], p: float) -> Optional[float]:
    if not valores:
        return None
    ordenados = sorted(valores)
    posicao = max(1, math.ceil(p / 100 * len(ordenados)))
    return ordenados[posicao - 1]


def resumo(valores: List[float]) -> dict:
    if not valores:
        return {"n": 0}
    return {
        "n": len(valores),
        "p50": round(percentil(valores, 50), 2),
        "p95": round(percentil(valores, 95), 2),
        "max": round(max(valores), 2),
        "media": round(statistics.fmean(valores), 2),
    }


def _url_ws(base: str) -> str:
    if base.startswith("https://"):
        return "wss://" + base[len("https://"):] + "/telemetria"
    return "ws://" + base[len("http://"):] + "/telemetria"


async def _abrir_conta_e_sessao(http: httpx.AsyncClient, indice: int) -> tuple:
    email = f"medicao-sintetica-{secrets.token_hex(4)}-{indice}@example.com"
    senha = secrets.token_urlsafe(18)
    r = await http.post("/auth/registro", json={
        "nome": NOME_DA_CONTA, "email": email, "senha": senha,
        "aceitou_termo": True, "declarou_maioridade": True, "versao_termo": VERSAO_DO_TERMO,
    })
    r.raise_for_status()
    r = await http.post("/auth/login", json={"email": email, "senha": senha})
    r.raise_for_status()
    token = r.json()["access_token"]
    cabecalho = {"Authorization": f"Bearer {token}"}
    r = await http.post("/sessoes", headers=cabecalho, json={"metodo": "livre", "assunto": ASSUNTO})
    r.raise_for_status()
    return email, token, cabecalho, r.json()["id"]


async def medir_um_cliente(base: str, indice: int, duracao_s: float, intervalo_s: float) -> dict:
    async with httpx.AsyncClient(base_url=base, timeout=30) as http:
        email, token, cabecalho, id_sessao = await _abrir_conta_e_sessao(http, indice)
        enviados = {}
        rtt, processamento, rede = [], [], []
        erros, sem_par = [], 0

        try:
            async with websockets.connect(_url_ws(base), open_timeout=30) as ws:
                await ws.send(json.dumps({"token": token}))
                autenticacao = json.loads(await ws.recv())
                if autenticacao.get("tipo") != "autenticado":
                    raise RuntimeError(f"canal recusou a credencial: {autenticacao}")

                async def ouvir():
                    nonlocal sem_par
                    async for bruto in ws:
                        chegada = time.perf_counter() * 1000
                        msg = json.loads(bruto)
                        if msg.get("tipo") != "score":
                            erros.append(msg)
                            continue
                        envio = enviados.pop(msg.get("t0"), None)
                        if envio is None:
                            sem_par += 1
                            continue
                        ida_e_volta = chegada - envio
                        rtt.append(ida_e_volta)
                        proc = msg.get("processamento_ms")
                        if isinstance(proc, (int, float)):
                            processamento.append(proc)
                            rede.append(ida_e_volta - proc)

                ouvinte = asyncio.create_task(ouvir())
                fim = time.perf_counter() + duracao_s
                proximo = time.perf_counter()
                while time.perf_counter() < fim:
                    t0 = round(time.perf_counter() * 1000, 3)
                    enviados[t0] = t0
                    await ws.send(json.dumps({**PAYLOAD, "t0": t0}))
                    proximo += intervalo_s
                    await asyncio.sleep(max(0.0, proximo - time.perf_counter()))
                # As últimas respostas ainda estão a caminho.
                await asyncio.sleep(3)
                ouvinte.cancel()
        finally:
            await http.post(f"/sessoes/{id_sessao}/encerrar", headers=cabecalho)

    return {
        "cliente": indice,
        "conta": email,
        "id_sessao": id_sessao,
        "enviados": len(rtt) + len(enviados) + sem_par,
        "sem_resposta": len(enviados),
        "respostas_sem_par": sem_par,
        "erros_do_canal": erros,
        "rtt_ms": rtt,
        "processamento_ms": processamento,
        "rede_e_fila_ms": rede,
    }


async def principal(args) -> dict:
    async with httpx.AsyncClient(base_url=args.url, timeout=30) as http:
        saude = (await http.get("/health")).json()

    inicio = datetime.now(timezone.utc)
    clientes = await asyncio.gather(
        *[medir_um_cliente(args.url, i, args.duracao, 1 / args.hz) for i in range(args.clientes)]
    )
    fim = datetime.now(timezone.utc)

    def juntar(campo):
        return [v for c in clientes for v in c[campo]]

    return {
        "url": args.url,
        "build": saude.get("build"),
        "inicio_utc": inicio.isoformat(timespec="seconds"),
        "fim_utc": fim.isoformat(timespec="seconds"),
        "clientes_simultaneos": args.clientes,
        "frequencia_hz": args.hz,
        "duracao_s": args.duracao,
        "percentil": "posto mais próximo, sem interpolação",
        "resumo": {
            "rtt_ms": resumo(juntar("rtt_ms")),
            "processamento_ms": resumo(juntar("processamento_ms")),
            "rede_e_fila_ms": resumo(juntar("rede_e_fila_ms")),
        },
        "perdas": {
            "sem_resposta": sum(c["sem_resposta"] for c in clientes),
            "erros_do_canal": sum(len(c["erros_do_canal"]) for c in clientes),
        },
        "clientes": clientes,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default=URL_PADRAO)
    parser.add_argument("--duracao", type=float, default=120, help="segundos de canal aberto por cliente")
    parser.add_argument("--hz", type=float, default=1.0, help="payloads por segundo (o navegador manda 1)")
    parser.add_argument("--clientes", type=int, default=1, help="alunos simultâneos, cada um com conta própria")
    parser.add_argument("--saida", help="arquivo JSON com o resumo e as medições cruas")
    args = parser.parse_args()

    resultado = asyncio.run(principal(args))

    print(f"build {resultado['build']}  |  {resultado['clientes_simultaneos']} cliente(s)  |  "
          f"{resultado['inicio_utc']} a {resultado['fim_utc']}")
    for nome, r in resultado["resumo"].items():
        if r["n"]:
            print(f"  {nome:18} n={r['n']:<5} p50={r['p50']:>8.2f}  p95={r['p95']:>8.2f}  max={r['max']:>8.2f}")
    print(f"  perdas: {resultado['perdas']}")

    if args.saida:
        with open(args.saida, "w", encoding="utf-8") as f:
            json.dump(resultado, f, ensure_ascii=False, indent=2)
        print(f"  gravado em {args.saida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
