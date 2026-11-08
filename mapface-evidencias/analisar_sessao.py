"""Analisa o JSON baixado pelo gravador_mapface.js e gera um relatório em Markdown.

Uso:
    python analisar_sessao.py mapface-sessao-XXXX.json [--rotulo "Sessão real 1"]
                              [--bocejos-video bocejos.csv] [-o saida.md]

`--bocejos-video` é opcional: um CSV com uma coluna `inicio` no formato mm:ss
(tempo desde o início da gravação de vídeo local), para quem preferir anotar os
bocejos assistindo ao vídeo em vez de usar a tecla B. Junto vai `--offset-video`,
em segundos: quanto o vídeo começou DEPOIS do primeiro payload (negativo se
começou antes).

Só usa a biblioteca padrão do Python.
"""
import argparse
import csv
import json
import math
import statistics
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

# Espelham backend/app/analista.py (commit c7b6739). Se mudarem lá, mudar aqui.
LIMIAR_MAR_BOCEJO = 0.30
DURACAO_MINIMA_BOCEJO_S = 2.0

# Janela para casar uma marca de bocejo com uma detecção: a marca é feita no
# começo do bocejo e o detector só dispara depois de ~2–3 s de boca aberta,
# mais o atraso de quem aperta a tecla.
CASAMENTO_ANTES_S = 5.0
CASAMENTO_DEPOIS_S = 10.0

# Vão entre payloads acima disto conta como lacuna de dados (o normal é 1 s).
LACUNA_S = 2.5

# Pontos que cada bocejo soma ao fator de fadiga no backend.
PONTOS_POR_BOCEJO = 8


def hora(t_ms: float) -> str:
    return datetime.fromtimestamp(t_ms / 1000, tz=timezone.utc).astimezone().strftime("%H:%M:%S")


def mmss(segundos: float) -> str:
    s = int(round(segundos))
    return f"{s // 60:02d}:{s % 60:02d}"


def percentil(valores, p):
    """Nearest-rank, sem interpolar: o mesmo método de medir_latencia.py e do
    log do backend, para os números do grupo serem comparáveis."""
    if not valores:
        return None
    v = sorted(valores)
    return v[max(1, math.ceil(p / 100 * len(v))) - 1]


def fmt(x, casas=1, sufixo=""):
    return "—" if x is None else f"{x:.{casas}f}{sufixo}"


def pct(parte, todo):
    return "—" if not todo else f"{100 * parte / todo:.1f}%"


def deteccoes_de_bocejo(enviados):
    """Reaplica a regra do backend à série de MAR enviada.

    O backend atribui a duração entre duas amostras ao estado da primeira, soma
    enquanto a boca está aberta e conta um bocejo quando a soma cruza 2 s. Na
    prática, a 1 Hz, isso exige três payloads seguidos com MAR > 0,30.
    Devolve o instante (ms) em que cada bocejo foi contado.
    """
    eventos, acumulado = [], 0.0
    for a, b in zip(enviados, enviados[1:]):
        mar = a.get("mar")
        aberta = isinstance(mar, (int, float)) and mar > LIMIAR_MAR_BOCEJO
        dur = (b["t"] - a["t"]) / 1000
        if aberta:
            antes = acumulado
            acumulado += dur
            if antes < DURACAO_MINIMA_BOCEJO_S <= acumulado:
                eventos.append(b["t"])
        else:
            acumulado = 0.0
    return eventos


def casar(marcas, deteccoes):
    """Casamento guloso 1-para-1 dentro da janela [-ANTES, +DEPOIS] da marca."""
    livres = sorted(deteccoes)
    pares, perdidas = [], []
    for m in sorted(marcas):
        candidatas = [d for d in livres if -CASAMENTO_ANTES_S <= (d - m) / 1000 <= CASAMENTO_DEPOIS_S]
        if candidatas:
            d = min(candidatas, key=lambda d: abs(d - m))
            livres.remove(d)
            pares.append((m, d))
        else:
            perdidas.append(m)
    return pares, perdidas, livres


def analisar(dados, rotulo, bocejos_video=None, nomes_condicoes=None):
    env = sorted(dados.get("enviados", []), key=lambda x: x["t"])
    rec = sorted(dados.get("recebidos", []), key=lambda x: x["t"])
    con = dados.get("conexoes", [])
    rede = dados.get("rede", [])
    fps = [f["fps"] for f in dados.get("fps", [])]
    marcas = dados.get("marcas", [])
    amb = dados.get("ambiente", {})

    if not env:
        return f"# {rotulo}\n\nNenhum payload gravado. O gravador foi colado antes de iniciar a sessão?\n"

    t0, t1 = env[0]["t"], env[-1]["t"]
    rel = lambda t: (t - t0) / 1000  # noqa: E731
    dur = rel(t1)
    out = []
    w = out.append

    w(f"# {rotulo}\n")
    w(f"- Gravação: {hora(t0)} → {hora(t1)} (duração {mmss(dur)}, horário local)")
    w(f"- Navegador: `{amb.get('user_agent', '—')}`")
    w(f"- CPU lógicas: {amb.get('nucleos_cpu', '—')} · memória declarada: {amb.get('memoria_gb', '—')} GB · tela: {amb.get('tela', '—')}")
    w(f"- Origem: {amb.get('url', '—')}")
    builds = sorted({b.get('build') for b in dados.get('build', []) if b.get('build')})
    w(f"- Build (/health): {', '.join(f'`{b}`' for b in builds) if builds else 'não lido'}"
      + (" — **mudou durante a gravação**" if len(builds) > 1 else ""))
    if dados.get("pagina_no_download"):
        w(f"- Página no download: `{dados['pagina_no_download']}`")
    w("")

    # Captura
    w("## Captura no cliente\n")
    if fps:
        w(f"- FPS exibido na tela: média {statistics.mean(fps):.1f}, mediana {statistics.median(fps):.1f}, "
          f"p5 {fmt(percentil(fps, 5))}, mínimo {min(fps):.0f}, máximo {max(fps):.0f} ({len(fps)} leituras de 1 s)")
        abaixo = sum(1 for f in fps if f < 15)
        w(f"- Segundos abaixo de 15 FPS: {abaixo} ({pct(abaixo, len(fps))})")
    else:
        w("- FPS: nenhuma leitura (o elemento de FPS não estava na tela?)")
    w("- CPU: anotar à mão pelo Performance monitor (ver roteiro).\n")

    # Cobertura
    w("## Cobertura da medição\n")
    # Categorias exclusivas, na ordem em que o servidor decide o score: com
    # incerteza o ponto fica sem valor, haja rosto ou não (no escuro, sair da
    # frente da câmera vira baixa-luz); só sem incerteza a ausência de rosto
    # vira zero.
    inc = Counter(e.get("incerteza") for e in env if e.get("incerteza"))
    n_inc = sum(inc.values())
    inc_sem_rosto = sum(1 for e in env if e.get("incerteza") and not e.get("rosto_detectado"))
    confiaveis = sum(1 for e in env if e.get("rosto_detectado") and not e.get("incerteza"))
    sem_rosto = sum(1 for e in env if not e.get("rosto_detectado") and not e.get("incerteza"))
    lacunas = [(a["t"], (b["t"] - a["t"]) / 1000) for a, b in zip(env, env[1:]) if (b["t"] - a["t"]) / 1000 > LACUNA_S]
    perdidos = sum(round(g) - 1 for _, g in lacunas)
    esperados = len(env) + perdidos
    w("| Situação | Segundos | % do esperado |")
    w("| --- | ---: | ---: |")
    w(f"| Payloads esperados (1 por segundo de gravação) | {esperados} | 100% |")
    w(f"| Enviados com rosto e captura confiável | {confiaveis} | {pct(confiaveis, esperados)} |")
    w(f"| Enviados com incerteza (sem valor de índice) | {n_inc} | {pct(n_inc, esperados)} |")
    w(f"| Enviados sem rosto e sem incerteza (índice zero) | {sem_rosto} | {pct(sem_rosto, esperados)} |")
    w(f"| Não enviados (lacuna de conexão/aba) | {perdidos} | {pct(perdidos, esperados)} |")
    if inc:
        w("\nMotivos de incerteza: " + ", ".join(f"{k} = {v} s" for k, v in inc.most_common()))
    if inc_sem_rosto:
        w(f"\nDos {n_inc} s com incerteza, {inc_sem_rosto} também não tinham rosto: o servidor os grava como incertos, não como ausência.")
    w("")

    # Canal
    w("## Canal WebSocket (ida e volta medida no navegador)\n")
    rtts = [r["rtt_ms"] for r in rec if r.get("tipo") == "score" and isinstance(r.get("rtt_ms"), (int, float))]
    pares = [(r["rtt_ms"], r["processamento_ms"]) for r in rec
             if r.get("tipo") == "score" and isinstance(r.get("rtt_ms"), (int, float))
             and isinstance(r.get("processamento_ms"), (int, float))]
    if rtts:
        w("| Medida | p50 (ms) | p95 (ms) | Máx. (ms) | Média (ms) |")
        w("| --- | ---: | ---: | ---: | ---: |")
        def linha(nome, v):
            w(f"| {nome} | {fmt(percentil(v, 50))} | {fmt(percentil(v, 95))} | {max(v):.1f} | {statistics.mean(v):.1f} |")
        linha("RTT (navegador)", rtts)
        if pares:
            linha("Processamento (backend)", [p for _, p in pares])
            linha("Rede + fila (RTT − processamento)", [r - p for r, p in pares])
        w("")
        w(f"- {len(rtts)} respostas de score. O RTT já inclui o processamento; rede = RTT − processamento, sem somar nada duas vezes.")
        w(f"- Meta WebSocket ≤ 200 ms: {sum(1 for r in rtts if r <= 200)} de {len(rtts)} respostas")
        if pares:
            w(f"- Meta RNF06 backend ≤ 100 ms: {sum(1 for _, p in pares if p <= 100)} de {len(pares)} respostas")
        else:
            w("- `processamento_ms` ausente nas respostas: o build no ar é anterior a 09b5208?")
        w("- O RTT inclui o tempo até o navegador processar a mensagem; com a aba em segundo plano ele infla.")
    erros = Counter(r.get("motivo") for r in rec if r.get("tipo") == "erro")
    if erros:
        w("- Erros recebidos: " + ", ".join(f"{k} × {v}" for k, v in erros.items()))
    sem_resposta = len(env) - sum(1 for r in rec if r.get("i_envio") is not None)
    w(f"- Payloads sem resposta registrada: {sem_resposta}\n")

    # Conexões, quedas, rede
    w("## Eventos de conexão e rede\n")
    eventos = [(c["t"], f"WS #{c['i_conexao']} {c['evento']}" + (f" (código {c['codigo']})" if "codigo" in c else "")) for c in con]
    eventos += [(r["t"], f"navegador {r['evento']}") for r in rede]
    if eventos:
        w("| Instante | Desde o início | Evento |")
        w("| --- | ---: | --- |")
        for t, e in sorted(eventos):
            w(f"| {hora(t)} | {mmss(rel(t)) if t >= t0 else '-' + mmss(-rel(t))} | {e} |")
    if lacunas:
        w("\nLacunas na série (vão > %.1f s entre payloads):\n" % LACUNA_S)
        for t, g in lacunas:
            w(f"- {hora(t)} (em {mmss(rel(t))}): {g:.1f} s sem dados")
    w("")

    # Calibração
    w("## Calibração\n")
    scores = [r for r in rec if r.get("tipo") == "score"]
    fim_calib, recal = None, []
    anterior = None
    for r in scores:
        c = bool(r.get("calibrando"))
        if anterior is True and not c and fim_calib is None:
            fim_calib = r["t"]
        if anterior is False and c:
            recal.append(r["t"])
        anterior = c
    w(f"- Calibração inicial concluída em: {mmss(rel(fim_calib)) if fim_calib else 'não concluiu nesta gravação'}")
    if recal:
        w("- **Voltou a calibrar** (baseline perdida) em: " + ", ".join(f"{hora(t)} ({mmss(rel(t))})" for t in recal))
    else:
        w("- Não houve volta à calibração depois da inicial.")
    w("")

    # Índice e fadiga
    w("## O que o servidor devolveu\n")
    medidos = [r["score"] for r in scores if isinstance(r.get("score"), (int, float))]
    nulos = sum(1 for r in scores if r.get("score") is None)
    if medidos:
        w(f"- IEE médio sobre pontos com valor: {statistics.mean(medidos):.1f} ({len(medidos)} pontos; "
          f"{nulos} pontos nulos por incerteza; cobertura {pct(len(medidos), len(scores))})")
    motivos = Counter(m for r in scores for m in (r.get("motivos_fadiga") or []))
    if motivos:
        w("- Segundos com cada motivo de fadiga ativo: " + ", ".join(f"{k} = {v}" for k, v in motivos.most_common()))
    son = [r["sonolencia"] for r in scores if isinstance(r.get("sonolencia"), (int, float))]
    if son:
        w(f"- Leitura de sonolência: média {statistics.mean(son):.3f} em {len(son)} segundos com valor")
    w("")

    # Bocejos
    w("## Bocejos: marcados × detectados\n")
    # A verdade é o servidor: cada bocejo contado soma 8 pontos ao fator de
    # fadiga (Tabela da seção 5.6.4). A reaplicação local da regra fica só como
    # reserva para gravações sem resposta do servidor, porque ela erra no caso
    # limite de 2 s: a contagem depende do intervalo exato entre payloads.
    dets, anterior = [], None
    for r in scores:
        f = r.get("fadiga")
        if isinstance(f, (int, float)) and isinstance(anterior, (int, float)):
            if round(f - anterior) == PONTOS_POR_BOCEJO and "bocejos" in (r.get("motivos_fadiga") or []):
                dets.append(r["t"])
        anterior = f
    fonte_det = "servidor (fadiga +8 com motivo bocejos)"
    if not scores:
        dets, fonte_det = deteccoes_de_bocejo(env), "regra reaplicada no script"
    marc_b = [m["t"] for m in marcas if m["tipo"] == "bocejo"]
    origem = "tecla B"
    if bocejos_video:
        marc_b = [t0 + s * 1000 for s in bocejos_video]
        origem = "vídeo local"
    mares = [e["mar"] for e in env if isinstance(e.get("mar"), (int, float)) and e.get("rosto_detectado")]
    if mares:
        w(f"- MAR com rosto: mediana {statistics.median(mares):.3f}, p99 {fmt(percentil(mares, 99), 3)}, máximo {max(mares):.3f}")
    w(f"- Regra do backend: MAR médio do segundo > {LIMIAR_MAR_BOCEJO} por ≥ {DURACAO_MINIMA_BOCEJO_S:.0f} s. Com 1 leitura por segundo, um bocejo de exatamente 2 leituras fica no limite e pode não contar.")
    w(f"- Detecções lidas de: {fonte_det}")
    w(f"- Bocejos marcados ({origem}): {len(marc_b)} · detecções do sistema: {len(dets)}\n")
    if marc_b or dets:
        pares, perdidas, sobras = casar(marc_b, dets)
        w(f"**Detectados: {len(pares)} de {len(marc_b)}** · não detectados: {len(perdidas)} · "
          f"detecções sem bocejo marcado: {len(sobras)}\n")
        conf = [(m["t"], m["tipo"]) for m in marcas if m["tipo"] in ("fala", "sorriso", "comer-beber", "livre")]
        linhas = [(m, "marcado", f"detectado {((d - m) / 1000):+.0f} s") for m, d in pares]
        linhas += [(m, "marcado", "**não detectado**") for m in perdidas]
        for d in sobras:
            perto = [tp for t, tp in conf if -15 <= (d - t) / 1000 <= 15]
            linhas.append((d, "detecção sem marca", "perto de: " + ", ".join(perto) if perto else "sem marca próxima"))
        w("| Desde o início | Origem | Resultado |")
        w("| ---: | --- | --- |")
        for t, o, r in sorted(linhas):
            w(f"| {mmss(rel(t))} | {o} | {r} |")
        w("")
    outras = Counter(m["tipo"] for m in marcas if m["tipo"] not in ("bocejo", "condicao"))
    if outras:
        w("Outras marcas: " + ", ".join(f"{k} × {v}" for k, v in outras.items()))
        for m in [m for m in marcas if m["tipo"] == "livre"]:
            w(f"- marca livre em {mmss(rel(m['t']))}" + (f": {m['texto']}" if m.get("texto") else ""))
        w("")

    por_condicao(w, env, scores, marcas, nomes_condicoes, rel, t1)
    return "\n".join(out) + "\n"


def por_condicao(w, env, scores, marcas, nomes, rel, t_fim):
    """Cobertura entre marcas de condição (teclas 1 a 9), para a sessão adversa.

    Cada trecho vai de uma marca até a seguinte (ou até o último payload). Os
    segundos sem payload dentro do trecho contam como "não enviado".
    """
    conds = sorted((m for m in marcas if m["tipo"] == "condicao"), key=lambda m: m["t"])
    if not conds:
        return
    w("## Cobertura por condição (teclas 1 a 9)\n")
    w("| Condição | Início | Duração (s) | Confiável (%) | Incerta (%) | Sem rosto (%) | Não enviado (%) | Motivo de incerteza dominante | Calibrando no trecho? |")
    w("| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |")
    limites = [m["t"] for m in conds[1:]] + [t_fim + 1000]
    for m, fim in zip(conds, limites):
        n = m.get("numero")
        nome = nomes[n - 1] if nomes and n and n <= len(nomes) else f"Condição {n}"
        trecho = [e for e in env if m["t"] <= e["t"] < fim]
        dur = max(1, round((fim - m["t"]) / 1000), len(trecho))
        inc = [e for e in trecho if e.get("incerteza")]
        sem = [e for e in trecho if not e.get("incerteza") and not e.get("rosto_detectado")]
        conf = len(trecho) - len(inc) - len(sem)
        nao = max(0, dur - len(trecho))
        motivo = Counter(e["incerteza"] for e in inc).most_common(1)
        recal = any(r.get("calibrando") for r in scores if m["t"] <= r["t"] < fim)
        w(f"| {n} — {nome} | {mmss(rel(m['t']))} | {dur} | {pct(conf, dur)} | {pct(len(inc), dur)} | "
          f"{pct(len(sem), dur)} | {pct(nao, dur)} | {motivo[0][0] + f' ({motivo[0][1]} s)' if motivo else '—'} | "
          f"{'sim' if recal else 'não'} |")
    w("")
    w("Percentuais sobre a duração do trecho; uma tecla de condição apertada duas vezes abre dois trechos.")


def ler_csv_video(caminho, offset):
    segs = []
    with open(caminho, newline="", encoding="utf-8") as f:
        for linha in csv.DictReader(f):
            mm, ss = linha["inicio"].strip().split(":")
            segs.append(int(mm) * 60 + float(ss) - offset)
    return segs


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("json")
    ap.add_argument("--rotulo", default="Sessão MapFace")
    ap.add_argument("--bocejos-video")
    ap.add_argument("--offset-video", type=float, default=0.0)
    ap.add_argument("-o", "--saida")
    ap.add_argument("--condicoes", help='nomes das condições na ordem das teclas, separados por vírgula')
    a = ap.parse_args()
    dados = json.loads(Path(a.json).read_text(encoding="utf-8"))
    video = ler_csv_video(a.bocejos_video, a.offset_video) if a.bocejos_video else None
    nomes = [c.strip() for c in a.condicoes.split(",")] if a.condicoes else None
    md = analisar(dados, a.rotulo, video, nomes)
    if a.saida:
        Path(a.saida).write_text(md, encoding="utf-8")
        print(f"Relatório salvo em {a.saida}")
    else:
        print(md)


if __name__ == "__main__":
    main()
