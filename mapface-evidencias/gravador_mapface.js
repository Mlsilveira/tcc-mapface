/*
 * Gravador de sessão do MapFace — cole no Console do Chrome (F12 → Console)
 * ANTES de clicar em "Iniciar sessão". Não recarregue a página depois de colar:
 * o recarregamento apaga o gravador.
 *
 * O que ele grava (tudo fica só no seu navegador até você baixar):
 *   - cada payload de telemetria enviado (os mesmos 9 números que o backend
 *     já recebe; o TOKEN DA PRIMEIRA MENSAGEM NÃO É GRAVADO);
 *   - cada resposta do servidor (score, calibrando, fadiga, motivos,
 *     incerteza, sonolência, processamento_ms) e o tempo de ida e volta até ela;
 *   - o build que está respondendo (lido de /health ao colar e ao baixar);
 *   - aberturas, quedas e reautenticações do WebSocket;
 *   - eventos online/offline do navegador e troca de aba (visibilidade);
 *   - o FPS exibido na tela, uma vez por segundo;
 *   - marcações manuais feitas pelo teclado (abaixo).
 *
 * Marcações (tecla simples, sem Alt; clique antes na página do MapFace):
 *   B  bocejo (aperte no início do bocejo)
 *   F  fala — aperte ao começar e de novo ao parar
 *   S  sorriso / riso
 *   C  comer ou beber
 *   M  marca livre (sem texto: anote no papel o que foi)
 *   1 a 9  início de uma condição da sessão adversa (1 = primeira condição...)
 * Nenhuma tecla abre caixa de diálogo: uma caixa aberta pausa a página e a
 * captura junto.
 * Teclas digitadas dentro de um campo de texto são ignoradas. Sem Alt de
 * propósito: no Chrome para Windows, Alt+F abre o menu do navegador.
 *
 * Comandos no console:
 *   __mapface.resumo()   mostra contagens rápidas
 *   __mapface.baixar()   baixa o JSON da sessão (faça isso NA TELA DO RELATÓRIO,
 *                        sem recarregar)
 */
(() => {
  if (window.__mapface) {
    console.warn('[gravador] já está instalado nesta página.');
    return;
  }

  const agora = () => performance.timeOrigin + performance.now();

  const R = {
    versao: 1,
    instalado_em: new Date().toISOString(),
    ambiente: {
      url: location.origin,
      user_agent: navigator.userAgent,
      nucleos_cpu: navigator.hardwareConcurrency ?? null,
      memoria_gb: navigator.deviceMemory ?? null,
      tela: `${screen.width}x${screen.height}@${devicePixelRatio}`,
    },
    enviados: [],   // {t, i_conexao, ...payload}
    recebidos: [],  // {t, i_conexao, rtt_ms, i_envio, ...mensagem}
    conexoes: [],   // {t, i_conexao, evento, codigo?}
    rede: [],       // {t, evento}
    build: [],      // {t, momento, build}
    fps: [],        // {t, fps}
    marcas: [],     // {t, tipo, texto?}
  };
  window.__mapface = R;

  let nConexoes = 0;
  const envioOriginal = WebSocket.prototype.send;

  WebSocket.prototype.send = function (dados) {
    if (!this.__mf) {
      this.__mf = { i: nConexoes++, pendentes: [] };
      const ws = this;
      R.conexoes.push({ t: agora(), i_conexao: ws.__mf.i, evento: 'aberta' });
      ws.addEventListener('message', (ev) => {
        const t = agora();
        let msg;
        try { msg = JSON.parse(ev.data); } catch { return; }
        const p = ws.__mf.pendentes.shift();
        R.recebidos.push({
          t,
          i_conexao: ws.__mf.i,
          rtt_ms: p ? Math.round((t - p.t) * 10) / 10 : null,
          i_envio: p && p.i_envio !== undefined ? p.i_envio : null,
          ...msg,
        });
        if (msg.tipo === 'autenticado') {
          R.conexoes.push({ t, i_conexao: ws.__mf.i, evento: 'autenticada' });
        }
        if (msg.tipo === 'erro') {
          R.conexoes.push({ t, i_conexao: ws.__mf.i, evento: 'erro:' + msg.motivo });
        }
      });
      ws.addEventListener('close', (ev) => {
        R.conexoes.push({ t: agora(), i_conexao: ws.__mf.i, evento: 'fechada', codigo: ev.code });
      });
    }

    let obj = null;
    try { obj = JSON.parse(dados); } catch { /* não é JSON: ignora */ }
    const t = agora();
    if (obj && typeof obj === 'object' && 'token' in obj) {
      // A primeira mensagem carrega a credencial. Só o fato fica registrado.
      this.__mf.pendentes.push({ t });
    } else if (obj && typeof obj === 'object') {
      R.enviados.push({ t, i_conexao: this.__mf.i, ...obj });
      this.__mf.pendentes.push({ t, i_envio: R.enviados.length - 1 });
    }
    return envioOriginal.call(this, dados);
  };

  const lerBuild = (momento) =>
    fetch('/health', { cache: 'no-store' })
      .then((r) => r.json())
      .then((j) => { R.build.push({ t: agora(), momento, build: j.build ?? null }); return j.build; })
      .catch(() => { R.build.push({ t: agora(), momento, build: null }); return null; });
  lerBuild('instalacao').then((b) => console.log(`[gravador] build no ar: ${b ?? 'não informado'}`));

  addEventListener('online', () => R.rede.push({ t: agora(), evento: 'online' }));
  addEventListener('offline', () => R.rede.push({ t: agora(), evento: 'offline' }));
  document.addEventListener('visibilitychange', () =>
    R.rede.push({ t: agora(), evento: 'aba-' + document.visibilityState }));

  setInterval(() => {
    const el = document.querySelector('[data-teste="fps"]');
    if (!el) return;
    const n = parseFloat(el.textContent);
    if (Number.isFinite(n)) R.fps.push({ t: agora(), fps: n });
  }, 1000);

  const teclas = { b: 'bocejo', f: 'fala', s: 'sorriso', c: 'comer-beber', m: 'livre' };
  for (let n = 1; n <= 9; n++) teclas[String(n)] = 'condicao';
  addEventListener('keydown', (ev) => {
    if (ev.altKey || ev.ctrlKey || ev.metaKey || ev.repeat) return;
    const alvo = ev.target;
    if (alvo && (alvo.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(alvo.tagName))) return;
    const tipo = teclas[ev.key.toLowerCase()];
    if (!tipo) return;
    ev.preventDefault();
    const marca = { t: agora(), tipo };
    if (tipo === 'condicao') marca.numero = Number(ev.key);
    R.marcas.push(marca);
    console.log(`[gravador] marca "${tipo}${marca.numero ? ' ' + marca.numero : ''}" às ${new Date(marca.t).toLocaleTimeString()}`);
  });

  R.resumo = () => {
    const tab = {
      payloads_enviados: R.enviados.length,
      respostas: R.recebidos.length,
      conexoes: nConexoes,
      quedas: R.conexoes.filter((c) => c.evento === 'fechada').length,
      amostras_fps: R.fps.length,
      marcas: R.marcas.length,
    };
    console.table(tab);
    return tab;
  };

  R.baixar = async () => {
    await lerBuild('download');
    R.pagina_no_download = location.pathname;
    const { resumo, baixar, ...dados } = R;
    const blob = new Blob([JSON.stringify(dados)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `mapface-sessao-${new Date().toISOString().replace(/[:.]/g, '-')}.json`;
    a.click();
  };

  console.log('[gravador] instalado. Agora inicie a sessão. Tecla B marca bocejo.');
})();
