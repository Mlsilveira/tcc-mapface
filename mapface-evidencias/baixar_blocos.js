/**
 * Baixa os blocos de uma sessão para o ml/sensibilidade_iee.py.
 *
 * O gravador só enxerga o WebSocket, e as bordas dos blocos passam por REST.
 * Cole no console do navegador, logado na conta que fez a sessão.
 *
 * Sem argumento pega a sessão encerrada mais recente. Para outra:
 *   baixarBlocos(123)
 *
 * Salva só o que a análise usa (índice, tipo, início, fim e média de cada bloco).
 * O token é lido para autenticar e não vai para o arquivo. Rode logo depois de
 * encerrar: passadas 24 h a média do relatório já vem das médias por minuto.
 */
window.baixarBlocos = async (idPedido) => {
  const base = location.port === '4200' ? `${location.protocol}//${location.hostname}:8000` : '';
  const cabecalhos = { Authorization: `Bearer ${localStorage.getItem('iee_access_token')}` };

  const pedir = async (caminho) => {
    const resposta = await fetch(base + caminho, { headers: cabecalhos });
    if (!resposta.ok) throw new Error(`${caminho} respondeu ${resposta.status}`);
    return resposta.json();
  };

  const historico = await pedir('/sessoes/historico');
  console.table(historico.map(({ id, inicio, metodo }) => ({ id, inicio, metodo })));
  const id = idPedido ?? historico[0]?.id;
  if (id === undefined) throw new Error('Esta conta não tem sessão encerrada.');

  const relatorio = await pedir(`/sessoes/${id}/relatorio`);
  const blocos = relatorio.blocos.map(({ indice, tipo, inicio, fim, media }) => ({
    indice, tipo, inicio, fim, media,
  }));

  const arquivo = new Blob([JSON.stringify({ id_sessao: id, blocos }, null, 2)], {
    type: 'application/json',
  });
  const link = document.createElement('a');
  link.href = URL.createObjectURL(arquivo);
  link.download = `blocos-sessao-${id}.json`;
  link.click();
  URL.revokeObjectURL(link.href);
  console.log(`[baixar_blocos] sessão ${id}: ${blocos.length} blocos salvos.`);
};

baixarBlocos();
