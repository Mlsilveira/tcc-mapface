import { API_URL, baseDeWebSocket } from './api';

describe('endereços da API', () => {
  it('troca http por ws', () => {
    expect(baseDeWebSocket('http://localhost:8000')).toBe('ws://localhost:8000');
  });

  // O caso que o plano aponta como o que se esquece. Ele só apareceria em
  // produção, num canal só, com o resto do site funcionando — então é aqui que
  // ele precisa aparecer.
  it('troca https por wss', () => {
    expect(baseDeWebSocket('https://api.exemplo.com')).toBe('wss://api.exemplo.com');
  });

  it('não mexe no host nem no caminho', () => {
    expect(baseDeWebSocket('https://exemplo.com/api')).toBe('wss://exemplo.com/api');
  });

  it('não confunde um host que começa com http', () => {
    // `^` na expressão: sem ele, `https://http.exemplo.com` viraria
    // `wss://ws.exemplo.com` — um host que não existe.
    expect(baseDeWebSocket('https://http.exemplo.com')).toBe('wss://http.exemplo.com');
  });

  it('não deixa barra final sobrar na base da API', () => {
    expect(API_URL.endsWith('/')).toBeFalse();
  });
});
