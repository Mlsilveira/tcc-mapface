import { TestBed, discardPeriodicTasks, fakeAsync, tick } from '@angular/core/testing';

import { MetricasFaciais } from '../visao/metricas';
import {
  CRIADOR_DE_CANAL,
  CanalDeTelemetria,
  DELAY_INICIAL_DE_RECONEXAO_MS,
  INTERVALO_DE_ENVIO_MS,
  TelemetriaService,
} from './telemetria.service';

const TOKEN = 'jwt-de-teste';

function leitura(ear: number, yaw = 0): MetricasFaciais {
  return { ear, mar: 0.05, cabeca: { yaw, pitch: 0, roll: 0 } };
}

class CanalFalso implements CanalDeTelemetria {
  static abertos: CanalFalso[] = [];

  readonly enviados: string[] = [];
  fechadoPeloCliente = false;

  onopen: (() => void) | null = null;
  onmessage: ((evento: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;

  constructor(readonly url: string) {
    CanalFalso.abertos.push(this);
  }

  send(dados: string): void {
    this.enviados.push(dados);
  }

  close(): void {
    this.fechadoPeloCliente = true;
  }

  /** O servidor aceitou a conexão. */
  abrir(): void {
    this.onopen?.();
  }

  receber(mensagem: unknown): void {
    this.onmessage?.({ data: JSON.stringify(mensagem) });
  }

  /** A conexão caiu sem o cliente pedir. */
  cair(): void {
    this.onclose?.();
  }

  get payloads(): Array<Record<string, unknown>> {
    return this.enviados.map((bruto) => JSON.parse(bruto) as Record<string, unknown>);
  }
}

describe('TelemetriaService', () => {
  let service: TelemetriaService;
  let metricasAtuais: MetricasFaciais | null;

  function canal(indice = 0): CanalFalso {
    return CanalFalso.abertos[indice];
  }

  /** Conecta, abre e conclui o handshake de autenticação. */
  function conectarEAutenticar(): CanalFalso {
    service.iniciar(TOKEN, () => metricasAtuais);
    canal().abrir();
    canal().receber({ tipo: 'autenticado' });
    return canal();
  }

  beforeEach(() => {
    CanalFalso.abertos = [];
    metricasAtuais = leitura(0.3);

    TestBed.configureTestingModule({
      providers: [{ provide: CRIADOR_DE_CANAL, useValue: (url: string) => new CanalFalso(url) }],
    });

    service = TestBed.inject(TelemetriaService);
  });

  it('manda o token como primeira mensagem, e nada antes disso', fakeAsync(() => {
    // Token em query string vazaria para log de servidor e proxy; a primeira
    // mensagem é o único lugar limpo num WebSocket de navegador.
    service.iniciar(TOKEN, () => metricasAtuais);
    canal().abrir();

    expect(canal().payloads).toEqual([{ token: TOKEN }]);

    service.parar();
    discardPeriodicTasks();
  }));

  it('não envia telemetria enquanto o servidor não confirmar a autenticação', fakeAsync(() => {
    service.iniciar(TOKEN, () => metricasAtuais);
    canal().abrir();

    tick(INTERVALO_DE_ENVIO_MS * 2);

    expect(canal().payloads.length).toBe(1);
    expect(canal().payloads[0]['token']).toBe(TOKEN);

    service.parar();
    discardPeriodicTasks();
  }));

  it('envia um payload agregado por segundo depois de autenticado', fakeAsync(() => {
    conectarEAutenticar();

    tick(INTERVALO_DE_ENVIO_MS);

    const telemetria = canal().payloads.slice(1);
    expect(telemetria.length).toBe(1);
    expect(telemetria[0]['ear']).toBeCloseTo(0.3, 6);
    expect(telemetria[0]['rosto_detectado']).toBeTrue();

    service.parar();
    discardPeriodicTasks();
  }));

  it('resume a janela em vez de mandar só o último quadro', fakeAsync(() => {
    conectarEAutenticar();

    // Metade da janela com olho aberto, metade semicerrado: o payload tem que
    // refletir a janela, não o instante do disparo.
    metricasAtuais = leitura(0.4);
    tick(INTERVALO_DE_ENVIO_MS / 2);
    metricasAtuais = leitura(0.2);
    tick(INTERVALO_DE_ENVIO_MS / 2);

    const ultimo = canal().payloads.at(-1)!;
    expect(ultimo['ear'] as number).toBeGreaterThan(0.2);
    expect(ultimo['ear'] as number).toBeLessThan(0.4);

    service.parar();
    discardPeriodicTasks();
  }));

  it('não deixa uma janela contaminar a seguinte', fakeAsync(() => {
    conectarEAutenticar();

    metricasAtuais = leitura(0.4);
    tick(INTERVALO_DE_ENVIO_MS);

    metricasAtuais = leitura(0.1);
    tick(INTERVALO_DE_ENVIO_MS);

    // Se o buffer não fosse limpo, a segunda janela viria puxada para cima
    // pelas amostras da primeira.
    expect(canal().payloads.at(-1)!['ear'] as number).toBeCloseTo(0.1, 6);

    service.parar();
    discardPeriodicTasks();
  }));

  it('reporta ausência de rosto quando a janela inteira ficou sem detecção', fakeAsync(() => {
    conectarEAutenticar();

    metricasAtuais = null;
    tick(INTERVALO_DE_ENVIO_MS);

    expect(canal().payloads.at(-1)!['rosto_detectado']).toBeFalse();

    service.parar();
    discardPeriodicTasks();
  }));

  it('expõe o score devolvido pelo servidor', fakeAsync(() => {
    const aberto = conectarEAutenticar();

    aberto.receber({ tipo: 'score', score: 82.5 });

    expect(service.score()).toBeCloseTo(82.5, 6);

    service.parar();
    discardPeriodicTasks();
  }));

  it('reconecta sozinho quando a conexão cai', fakeAsync(() => {
    // Critério da ticket 6: uma instabilidade momentânea de rede não pode
    // interromper a sessão de estudo inteira.
    conectarEAutenticar();
    expect(service.conectado()).toBeTrue();

    canal().cair();
    expect(service.conectado()).toBeFalse();

    tick(DELAY_INICIAL_DE_RECONEXAO_MS);

    expect(CanalFalso.abertos.length).toBe(2);

    service.parar();
    discardPeriodicTasks();
  }));

  it('reautentica ao reconectar', fakeAsync(() => {
    // Uma conexão nova é uma conexão anônima: sem repetir o handshake, o
    // servidor recusaria toda a telemetria seguinte.
    conectarEAutenticar();
    canal().cair();
    tick(DELAY_INICIAL_DE_RECONEXAO_MS);

    canal(1).abrir();

    expect(canal(1).payloads).toEqual([{ token: TOKEN }]);

    service.parar();
    discardPeriodicTasks();
  }));

  it('espera cada vez mais entre tentativas de reconexão', fakeAsync(() => {
    // Servidor fora do ar não pode ser martelado a cada segundo por todos os
    // alunos com sessão aberta.
    conectarEAutenticar();

    canal().cair();
    tick(DELAY_INICIAL_DE_RECONEXAO_MS);
    expect(CanalFalso.abertos.length).toBe(2);

    canal(1).cair();
    tick(DELAY_INICIAL_DE_RECONEXAO_MS);
    // Ainda não: a segunda espera é maior que a primeira.
    expect(CanalFalso.abertos.length).toBe(2);

    tick(DELAY_INICIAL_DE_RECONEXAO_MS);
    expect(CanalFalso.abertos.length).toBe(3);

    service.parar();
    discardPeriodicTasks();
  }));

  it('não reconecta depois que a sessão foi encerrada', fakeAsync(() => {
    // Senão o logout deixaria um laço de reconexão rodando para sempre em
    // segundo plano, tentando falar de uma sessão que não existe mais.
    conectarEAutenticar();

    service.parar();
    canal().cair();
    tick(DELAY_INICIAL_DE_RECONEXAO_MS * 10);

    expect(CanalFalso.abertos.length).toBe(1);
    discardPeriodicTasks();
  }));

  it('para de enviar telemetria depois de encerrada', fakeAsync(() => {
    conectarEAutenticar();
    const enviadosAteParar = canal().payloads.length;

    service.parar();
    tick(INTERVALO_DE_ENVIO_MS * 3);

    expect(canal().payloads.length).toBe(enviadosAteParar);
    expect(service.score()).toBeNull();
    discardPeriodicTasks();
  }));

  it('fecha o canal ao encerrar', fakeAsync(() => {
    conectarEAutenticar();

    service.parar();

    expect(canal().fechadoPeloCliente).toBeTrue();
    discardPeriodicTasks();
  }));

  it('nunca envia landmarks — só ear, yaw, pitch e presença de rosto', fakeAsync(() => {
    // A fronteira de privacidade, afirmada no ponto exato onde os dados saem
    // do navegador.
    conectarEAutenticar();
    tick(INTERVALO_DE_ENVIO_MS * 2);

    for (const payload of canal().payloads.slice(1)) {
      expect(Object.keys(payload).sort()).toEqual(['ear', 'pitch', 'rosto_detectado', 'yaw']);
    }

    service.parar();
    discardPeriodicTasks();
  }));
});
