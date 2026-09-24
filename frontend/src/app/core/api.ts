/**
 * Endereços do backend, derivados de onde a própria página está.
 *
 * **Por que não são constantes fixas.** O bundle do Angular é estático: uma URL
 * escrita aqui é compilada para dentro do `main.js` e não há variável de
 * ambiente que a mude depois. Manter `http://localhost:8000` significaria que o
 * mesmo build **não** serve para desenvolvimento e para a nuvem — seria preciso
 * recompilar por ambiente, e um deploy feito com o build errado falharia só na
 * primeira chamada, no navegador do usuário.
 *
 * **Como fica na nuvem.** O CloudFront serve o site e encaminha `/auth`,
 * `/sessoes`, `/metodos` e `/telemetria` para o backend. O navegador enxerga
 * **uma origem só**, e disso saem três coisas de graça: não há CORS (mesma
 * origem não é requisição cross-origin), não há conteúdo misto (o WebSocket
 * herda o `https` e vira `wss`), e não há configuração para errar.
 *
 * **A exceção é o `ng serve`**, que responde na 4200 e não sabe nada da API; ali
 * o backend está ao lado, na 8000. É a única origem de duas pontas que sobra, e
 * é a razão de o CORS continuar existindo no backend com esse valor padrão.
 */

/** Porta do servidor de desenvolvimento do Angular (`ng serve`). */
export const PORTA_DO_DEV_SERVER = '4200';

/** Porta do `uvicorn` no desenvolvimento local. */
export const PORTA_DO_BACKEND_LOCAL = '8000';

/**
 * Base da API a partir do endereço da página.
 *
 * Recebe o `Location` em vez de ler o global para poder ser exercitada com
 * endereços que o teste não tem como visitar — a página do Karma responde numa
 * porta só, e o caso que interessa é justamente o de portas diferentes.
 */
export function baseDaApi(endereco: Pick<Location, 'protocol' | 'hostname' | 'port' | 'origin'>): string {
  if (endereco.port === PORTA_DO_DEV_SERVER) {
    return `${endereco.protocol}//${endereco.hostname}:${PORTA_DO_BACKEND_LOCAL}`;
  }

  return endereco.origin;
}

/**
 * Base do canal de telemetria a partir da base da API.
 *
 * `http` vira `ws` e `https` vira `wss` pela mesma troca, que é o ponto: uma
 * página em HTTPS falando `ws://` é conteúdo misto, e o navegador bloqueia sem
 * pedir permissão e sem mensagem que explique. Derivar em vez de configurar
 * torna esse erro impossível de cometer.
 */
export function baseDoWebSocket(baseHttp: string): string {
  return baseHttp.replace(/^http/, 'ws');
}

/** Base da API REST do backend FastAPI. */
export const API_URL = baseDaApi(window.location);
