import { PORTA_DO_BACKEND_LOCAL, PORTA_DO_DEV_SERVER, baseDaApi, baseDoWebSocket } from './api';

function endereco(url: string) {
  const { protocol, hostname, port, origin } = new URL(url);
  return { protocol, hostname, port, origin };
}

describe('baseDaApi', () => {
  it('aponta para a mesma origem quando o site é servido pelo CloudFront', () => {
    expect(baseDaApi(endereco('https://d111.cloudfront.net/home'))).toBe('https://d111.cloudfront.net');
  });

  it('desvia para a porta do uvicorn quando a página vem do ng serve', () => {
    expect(baseDaApi(endereco(`http://localhost:${PORTA_DO_DEV_SERVER}/home`))).toBe(
      `http://localhost:${PORTA_DO_BACKEND_LOCAL}`,
    );
  });

  it('não desvia em nenhuma outra porta', () => {
    // O Karma responde na 9876, e é por aqui que os demais testes passam: eles
    // esperam a API na própria origem da página de teste.
    expect(baseDaApi(endereco('http://localhost:9876/context.html'))).toBe('http://localhost:9876');
  });
});

describe('baseDoWebSocket', () => {
  it('acompanha o HTTPS do site', () => {
    // Página segura falando `ws://` é conteúdo misto: o navegador bloqueia sem
    // avisar, e a sessão de estudo ficaria sem telemetria e sem erro visível.
    expect(baseDoWebSocket('https://d111.cloudfront.net')).toBe('wss://d111.cloudfront.net');
  });

  it('continua em texto claro no desenvolvimento local', () => {
    expect(baseDoWebSocket('http://localhost:8000')).toBe('ws://localhost:8000');
  });
});
