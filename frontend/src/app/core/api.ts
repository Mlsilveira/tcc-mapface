import { environment } from '../../environments/environment';

/**
 * Base da API REST do backend FastAPI.
 *
 * A barra final é removida porque o valor deixou de ser um literal escrito por
 * quem programa e passou a vir de uma variável de ambiente preenchida na hora
 * de publicar. `https://api.exemplo.com/` é uma digitação plausível, e sem esta
 * limpeza ela viraria `https://api.exemplo.com//auth/login` — que alguns
 * servidores aceitam, outros devolvem 404, e nenhum explica.
 */
export const API_URL = environment.apiUrl.replace(/\/+$/, '');

/**
 * Traduz a base HTTP da API na base WebSocket correspondente.
 *
 * **A decisão: o endereço do WebSocket é derivado da API, e não configurado à
 * parte.** O custo dessa escolha é real — ela amarra os dois ao mesmo host, e
 * se um dia a infra puser a telemetria atrás de outro domínio isto aqui deixa
 * de servir. Três razões para aceitar esse custo:
 *
 * 1. Não é o caso desta aplicação. `/telemetria` é um router da mesma app
 *    FastAPI (`backend/app/main.py` faz `include_router(telemetria.router)`),
 *    servido pelo mesmo processo, na mesma porta. Hosts diferentes não é uma
 *    possibilidade que este deploy tenha: é uma que ele teria que passar a ter.
 * 2. A troca de esquema é justamente o que se esquece. `http`→`ws` em
 *    desenvolvimento e `https`→`wss` em produção: com dois valores
 *    independentes, publicar com `ws://` sob um site `https://` é um erro de
 *    uma letra que o navegador só denuncia em tempo de execução, e só no canal
 *    de telemetria — o resto do site funciona. Derivando, o erro não existe.
 * 3. Duas variáveis de ambiente é o dobro de coisas para quem publica acertar,
 *    e quem publica não é quem escreveu este código.
 *
 * Se a separação vier a ser necessária, o conserto é acrescentar uma chave
 * opcional ao `environment` e usar `API_URL` como padrão — uma linha, e com a
 * troca acima declarada em vez de descoberta.
 */
export function baseDeWebSocket(base: string): string {
  // `^http` cobre os dois esquemas de uma vez: `http://` vira `ws://` e
  // `https://` vira `wss://`, sem um `if` que alguém possa escrever ao
  // contrário.
  return base.replace(/^http/, 'ws');
}
