"""Reinício do backend no meio de uma sessão, no ambiente publicado (parecer, F06).

Abre uma sessão sintética **identificada**, manda telemetria a 1 Hz como o
navegador, espera a calibração terminar e então força um novo deploy do serviço
no ECS (`update-service --force-new-deployment`). A task troca embaixo da sessão
aberta, e o script registra o que o aluno viveria:

- quando o canal caiu, com que código, e quanto tempo ficou sem score;
- quantas tentativas de reconexão foram precisas, com o **mesmo backoff do
  frontend** (1 s, dobrando até 30 s; `telemetria.service.ts`);
- se a sessão continuou a mesma depois da troca (mesmo `id`, sem 409);
- se a calibração recomeçou (`calibrando` volta a `true`): a linha de base vive
  na memória do processo, e um processo novo não a tem;
- o relatório final da sessão, com a lacuna que a troca deixou.

Payloads não são enviados enquanto o canal está fora, como no navegador: o
frontend descarta a janela em vez de acumular.

Uso, com o venv do backend e credenciais da AWS que possam atualizar o serviço::

    backend/.venv/Scripts/python.exe mapface-evidencias/teste_reinicio.py \
        --saida mapface-evidencias/evidencias/teste-reinicio-publicado.json
"""
import argparse
import asyncio
import json
import secrets
import sys
import time
from datetime import datetime, timezone

import httpx
import websockets

URL_PADRAO = "https://d2qm0t6ecgabb2.cloudfront.net"
NOME_DA_CONTA = "Teste sintético de reinício"
ASSUNTO = "teste-sintetico-reinicio"
VERSAO_DO_TERMO = "1.2"
PAYLOAD = {"ear": 0.30, "yaw": 2.0, "mar": 0.10, "rosto_detectado": True, "incerteza": None,
           "ear_esq": 0.30, "ear_dir": 0.30, "pitch": -4.0, "roll": 1.0}
DELAY_INICIAL_S, DELAY_MAXIMO_S = 1.0, 30.0


def agora_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class Diario:
    def __init__(self):
        self.inicio = time.monotonic()
        self.eventos = []

    def __call__(self, tipo: str, **dados):
        evento = {"t_s": round(time.monotonic() - self.inicio, 2), "utc": agora_iso(), "evento": tipo, **dados}
        self.eventos.append(evento)
        print(f"{evento['t_s']:8.2f}s  {tipo}  {dados if dados else ''}", flush=True)


def forcar_deploy(cluster: str, servico: str, regiao: str) -> dict:
    import boto3

    ecs = boto3.client("ecs", region_name=regiao)
    resposta = ecs.update_service(cluster=cluster, service=servico, forceNewDeployment=True)
    return {"deployment": resposta["service"]["deployments"][0]["id"]}


async def principal(args) -> dict:
    diario = Diario()
    async with httpx.AsyncClient(base_url=args.url, timeout=60) as http:
        build_antes = (await http.get("/health")).json().get("build")
        email = f"teste-sintetico-reinicio-{secrets.token_hex(4)}@example.com"
        senha = secrets.token_urlsafe(18)
        (await http.post("/auth/registro", json={
            "nome": NOME_DA_CONTA, "email": email, "senha": senha,
            "aceitou_termo": True, "declarou_maioridade": True, "versao_termo": VERSAO_DO_TERMO,
        })).raise_for_status()
        token = (await http.post("/auth/login", json={"email": email, "senha": senha})).json()["access_token"]
        cabecalho = {"Authorization": f"Bearer {token}"}
        r = await http.post("/sessoes", headers=cabecalho, json={"metodo": "livre", "assunto": ASSUNTO})
        r.raise_for_status()
        id_sessao = r.json()["id"]
        diario("sessao-aberta", id_sessao=id_sessao, conta=email, build=build_antes)

        url_ws = args.url.replace("https://", "wss://").replace("http://", "ws://") + "/telemetria"
        estado = {"deploy_disparado_em": None, "ultimo_score": None, "calibrando": None,
                  "conexoes": 0, "scores": 0, "fim": None, "maior_lacuna_s": 0.0}
        delay = DELAY_INICIAL_S

        def acabou() -> bool:
            agora = time.monotonic()
            return (estado["fim"] is not None and agora >= estado["fim"]) or agora - diario.inicio > args.limite

        while not acabou():
            try:
                async with websockets.connect(url_ws, open_timeout=15) as ws:
                    estado["conexoes"] += 1
                    await ws.send(json.dumps({"token": token}))
                    resposta = json.loads(await ws.recv())
                    if resposta.get("tipo") != "autenticado":
                        diario("canal-recusado", resposta=resposta)
                        break
                    delay = DELAY_INICIAL_S
                    diario("canal-autenticado", conexao=estado["conexoes"])

                    async def ouvir():
                        async for bruto in ws:
                            msg = json.loads(bruto)
                            if msg.get("tipo") != "score":
                                diario("mensagem", msg=msg)
                                continue
                            agora = time.monotonic()
                            if estado["ultimo_score"] is not None:
                                lacuna = agora - estado["ultimo_score"]
                                if lacuna > 2.5:
                                    diario("lacuna-sem-score", segundos=round(lacuna, 1))
                                estado["maior_lacuna_s"] = max(estado["maior_lacuna_s"], lacuna)
                            estado["ultimo_score"] = agora
                            estado["scores"] += 1
                            if msg.get("calibrando") != estado["calibrando"]:
                                diario("calibrando", valor=msg.get("calibrando"), score=msg.get("score"))
                                estado["calibrando"] = msg.get("calibrando")
                                # Calibrou depois da troca: a sessão voltou ao normal.
                                if (msg.get("calibrando") is False and estado["deploy_disparado_em"]
                                        and estado["fim"] is None):
                                    estado["fim"] = time.monotonic() + args.depois

                    ouvinte = asyncio.create_task(ouvir())
                    while not ouvinte.done():
                        if acabou():
                            break
                        if (estado["deploy_disparado_em"] is None and estado["calibrando"] is False
                                and time.monotonic() - diario.inicio >= args.reinicio_em):
                            dados = await asyncio.to_thread(forcar_deploy, args.cluster, args.servico, args.regiao)
                            estado["deploy_disparado_em"] = time.monotonic()
                            diario("deploy-forcado", **dados)
                        await ws.send(json.dumps({**PAYLOAD, "t0": round(time.perf_counter() * 1000, 3)}))
                        await asyncio.sleep(1)
                    ouvinte.cancel()
                    if acabou():
                        break
                    diario("canal-caiu", codigo=ws.close_code, motivo=ws.close_reason)
            except (websockets.ConnectionClosed, OSError, asyncio.TimeoutError,
                    websockets.InvalidStatus, websockets.InvalidHandshake) as erro:
                diario("canal-caiu", erro=f"{type(erro).__name__}: {erro}"[:160])
            if acabou():
                break
            diario("reconectar-em", segundos=delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, DELAY_MAXIMO_S)

        ativa = (await http.get("/sessoes/ativa", headers=cabecalho)).json()
        diario("sessao-ativa-depois", id=(ativa or {}).get("id"))
        r = await http.post(f"/sessoes/{id_sessao}/encerrar", headers=cabecalho)
        diario("sessao-encerrada", http=r.status_code)
        relatorio = (await http.get(f"/sessoes/{id_sessao}/relatorio", headers=cabecalho)).json()
        build_depois = (await http.get("/health")).json().get("build")

    return {
        "url": args.url, "build_antes": build_antes, "build_depois": build_depois,
        "id_sessao": id_sessao, "conta": email, "assunto": ASSUNTO,
        "conexoes": estado["conexoes"], "scores": estado["scores"],
        "maior_lacuna_sem_score_s": round(estado["maior_lacuna_s"], 1),
        "eventos": diario.eventos, "relatorio": relatorio,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default=URL_PADRAO)
    parser.add_argument("--reinicio-em", type=float, default=90, help="segundos de sessão antes do deploy (depois da calibração)")
    parser.add_argument("--depois", type=float, default=90, help="segundos de sessão depois de recalibrar")
    parser.add_argument("--limite", type=float, default=900, help="teto de duração do teste, em segundos")
    parser.add_argument("--cluster", default="mapface-poc")
    parser.add_argument("--servico", default="mapface-poc-backend")
    parser.add_argument("--regiao", default="us-east-1")
    parser.add_argument("--saida")
    args = parser.parse_args()

    resultado = asyncio.run(principal(args))
    print(f"\nconexões: {resultado['conexoes']}  scores: {resultado['scores']}  "
          f"maior lacuna sem score: {resultado['maior_lacuna_sem_score_s']} s")
    if args.saida:
        with open(args.saida, "w", encoding="utf-8") as f:
            json.dump(resultado, f, ensure_ascii=False, indent=2)
        print(f"gravado em {args.saida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
