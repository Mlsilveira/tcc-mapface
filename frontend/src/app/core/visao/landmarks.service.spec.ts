import { TestBed, discardPeriodicTasks, fakeAsync, tick } from '@angular/core/testing';

import {
  AGENDADOR_DE_QUADROS,
  AgendadorDeQuadros,
  CRIADOR_DE_DETECTOR,
  DetectorFacial,
  INTERVALO_DE_PUBLICACAO_MS,
  LandmarksService,
  RELOGIO,
} from './landmarks.service';
import { INDICES_BOCA, INDICES_OLHO_DIREITO, INDICES_OLHO_ESQUERDO } from './metricas';

/** Matriz identidade 4x4 em column-major, com o rosto a 30 unidades da câmera. */
const MATRIZ_NEUTRA = {
  rows: 4,
  columns: 4,
  data: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 30, 1],
};

function malhaComRosto(): Array<{ x: number; y: number }> {
  const pontos = Array.from({ length: 478 }, () => ({ x: 0, y: 0 }));

  for (const indices of [INDICES_OLHO_DIREITO, INDICES_OLHO_ESQUERDO]) {
    const [p1, p2, p3, p4, p5, p6] = indices;
    pontos[p1] = { x: -0.05, y: 0 };
    pontos[p2] = { x: -0.025, y: -0.015 };
    pontos[p3] = { x: 0.025, y: -0.015 };
    pontos[p4] = { x: 0.05, y: 0 };
    pontos[p5] = { x: 0.025, y: 0.015 };
    pontos[p6] = { x: -0.025, y: 0.015 };
  }

  pontos[INDICES_BOCA.cantoEsquerdo] = { x: -0.06, y: 0.2 };
  pontos[INDICES_BOCA.cantoDireito] = { x: 0.06, y: 0.2 };
  pontos[INDICES_BOCA.labioSuperior] = { x: 0, y: 0.19 };
  pontos[INDICES_BOCA.labioInferior] = { x: 0, y: 0.21 };

  return pontos;
}

describe('LandmarksService', () => {
  let service: LandmarksService;
  let detectForVideo: jasmine.Spy;
  let fechar: jasmine.Spy;
  let video: HTMLVideoElement;

  /** Callback do próximo quadro, guardado para o teste disparar quando quiser. */
  let proximoQuadro: (() => void) | null;

  /** Relógio controlado pelo teste: sem ele o FPS dependeria do tempo real. */
  let instante: number;

  /** Dispara `quantidade` repinturas, avançando relógio e vídeo em `avancoMs`. */
  function rodarQuadros(quantidade: number, avancoMs = 10): void {
    for (let i = 0; i < quantidade; i += 1) {
      instante += avancoMs;
      (video as { currentTime: number }).currentTime += avancoMs / 1000;
      dispararRepintura();
    }
  }

  /**
   * Dispara uma repintura sem avançar o vídeo — o caso do monitor de 120 Hz com
   * webcam de 30 FPS, em que a mesma imagem chega várias vezes.
   */
  function dispararRepintura(): void {
    const quadro = proximoQuadro;
    proximoQuadro = null;
    quadro?.();
  }

  function resultadoComRosto() {
    return { faceLandmarks: [malhaComRosto()], facialTransformationMatrixes: [MATRIZ_NEUTRA] };
  }

  function resultadoSemRosto() {
    return { faceLandmarks: [], facialTransformationMatrixes: [] };
  }

  beforeEach(() => {
    instante = 1000;
    proximoQuadro = null;

    detectForVideo = jasmine.createSpy('detectForVideo').and.callFake(resultadoComRosto);
    fechar = jasmine.createSpy('close');

    const detector: DetectorFacial = {
      detectForVideo,
      close: fechar,
    } as unknown as DetectorFacial;

    const agendador: AgendadorDeQuadros = (_video, passo) => {
      proximoQuadro = passo;
    };

    TestBed.configureTestingModule({
      providers: [
        { provide: CRIADOR_DE_DETECTOR, useValue: () => Promise.resolve(detector) },
        { provide: AGENDADOR_DE_QUADROS, useValue: agendador },
        { provide: RELOGIO, useValue: () => instante },
      ],
    });

    service = TestBed.inject(LandmarksService);

    // Um <video> de verdade não tem dimensão nem dados em teste; o serviço só lê
    // estas três propriedades antes de repassar o elemento ao detector.
    video = {
      readyState: 4,
      videoWidth: 640,
      videoHeight: 480,
      currentTime: 0,
    } as unknown as HTMLVideoElement;
  });

  it('começa parado e sem leitura nenhuma', () => {
    expect(service.ativo).toBeFalse();
    expect(service.metricas()).toBeNull();
    expect(service.fps()).toBe(0);
  });

  it('processa quadros depois de iniciar', fakeAsync(() => {
    service.iniciar(video);
    tick();

    rodarQuadros(3);

    expect(service.ativo).toBeTrue();
    expect(detectForVideo).toHaveBeenCalledTimes(3);

    service.parar();
    discardPeriodicTasks();
  }));

  it('publica as métricas do último quadro na cadência de publicação', fakeAsync(() => {
    service.iniciar(video);
    tick();

    rodarQuadros(4);
    // Antes da publicação, a interface ainda não viu nada.
    expect(service.metricas()).toBeNull();

    tick(INTERVALO_DE_PUBLICACAO_MS);

    const leitura = service.metricas();
    expect(leitura).not.toBeNull();
    expect(leitura!.ear).toBeGreaterThan(0);
    expect(leitura!.mar).toBeGreaterThan(0);
    expect(leitura!.cabeca.yaw).toBeCloseTo(0, 6);

    service.parar();
    discardPeriodicTasks();
  }));

  it('leva a proporção do vídeo para dentro do cálculo das métricas', fakeAsync(() => {
    // O MediaPipe normaliza x pela largura e y pela altura, separadamente, então
    // o cálculo só fecha se o aspecto do quadro chegar até ele.
    //
    // Os valores esperados vêm da geometria da malha, não do código: os pontos
    // verticais do olho distam 0,03 e os cantos distam 0,1 em x, logo
    // EAR = (0,03 + 0,03) / (2 × 0,1 × aspecto) = 0,3 / aspecto.
    service.iniciar(video);
    tick();
    rodarQuadros(1);
    tick(INTERVALO_DE_PUBLICACAO_MS);

    // 640/480 = 4/3  →  0,3 / (4/3) = 0,225
    expect(service.metricas()!.ear).toBeCloseTo(0.225, 6);

    service.parar();
    discardPeriodicTasks();
  }));

  it('acompanha a proporção quando o vídeo é vertical', fakeAsync(() => {
    // Mesmo rosto, quadro em retrato: o EAR tem que mudar junto, senão a métrica
    // carregaria a resolução da webcam embutida.
    (video as { videoWidth: number; videoHeight: number }).videoWidth = 480;
    (video as { videoWidth: number; videoHeight: number }).videoHeight = 640;

    service.iniciar(video);
    tick();
    rodarQuadros(1);
    tick(INTERVALO_DE_PUBLICACAO_MS);

    // 480/640 = 0,75  →  0,3 / 0,75 = 0,4
    expect(service.metricas()!.ear).toBeCloseTo(0.4, 6);

    service.parar();
    discardPeriodicTasks();
  }));

  it('calcula o FPS a partir dos quadros processados no intervalo', fakeAsync(() => {
    service.iniciar(video);
    tick();

    // 5 quadros espaçados de 50 ms = 250 ms de captura a 20 FPS.
    rodarQuadros(5, 50);
    tick(INTERVALO_DE_PUBLICACAO_MS);

    expect(service.fps()).toBe(20);

    service.parar();
    discardPeriodicTasks();
  }));

  it('reporta FPS abaixo do piso quando a captura está lenta', fakeAsync(() => {
    // O piso de 15 FPS é critério da ticket 5; o serviço precisa medir de forma
    // que a interface consiga acusar a queda.
    service.iniciar(video);
    tick();

    rodarQuadros(2, 125);
    tick(INTERVALO_DE_PUBLICACAO_MS);

    expect(service.fps()).toBeLessThan(15);

    service.parar();
    discardPeriodicTasks();
  }));

  it('zera as métricas quando o rosto sai do quadro', fakeAsync(() => {
    service.iniciar(video);
    tick();

    rodarQuadros(2);
    tick(INTERVALO_DE_PUBLICACAO_MS);
    expect(service.metricas()).not.toBeNull();

    detectForVideo.and.callFake(resultadoSemRosto);
    rodarQuadros(2);
    tick(INTERVALO_DE_PUBLICACAO_MS);

    expect(service.metricas()).toBeNull();

    service.parar();
    discardPeriodicTasks();
  }));

  it('conta como quadro processado mesmo sem rosto detectado', fakeAsync(() => {
    // Senão o FPS despencaria quando o aluno saísse da frente da câmera, e a
    // interface acusaria captura lenta onde só falta rosto.
    detectForVideo.and.callFake(resultadoSemRosto);
    service.iniciar(video);
    tick();

    rodarQuadros(5, 50);
    tick(INTERVALO_DE_PUBLICACAO_MS);

    expect(service.fps()).toBe(20);

    service.parar();
    discardPeriodicTasks();
  }));

  it('não reprocessa o mesmo quadro do vídeo em repinturas repetidas', fakeAsync(() => {
    // Num monitor de 120 Hz com webcam de 30 FPS, três em cada quatro
    // repinturas trazem a mesma imagem. Reprocessá-las gastaria CPU à toa e
    // inflaria o FPS medido com trabalho repetido.
    service.iniciar(video);
    tick();

    rodarQuadros(1);
    dispararRepintura();
    dispararRepintura();

    expect(detectForVideo).toHaveBeenCalledTimes(1);

    service.parar();
    discardPeriodicTasks();
  }));

  it('conta apenas quadros novos no FPS', fakeAsync(() => {
    service.iniciar(video);
    tick();

    // 5 quadros reais em 250 ms, intercalados com repinturas repetidas.
    for (let i = 0; i < 5; i += 1) {
      rodarQuadros(1, 50);
      dispararRepintura();
      dispararRepintura();
    }
    tick(INTERVALO_DE_PUBLICACAO_MS);

    expect(service.fps()).toBe(20);

    service.parar();
    discardPeriodicTasks();
  }));

  it('ignora quadros enquanto o vídeo ainda não tem dados', fakeAsync(() => {
    (video as { readyState: number }).readyState = 0;
    service.iniciar(video);
    tick();

    rodarQuadros(3);

    expect(detectForVideo).not.toHaveBeenCalled();

    service.parar();
    discardPeriodicTasks();
  }));

  it('sobrevive a um quadro que faz o detector estourar', fakeAsync(() => {
    service.iniciar(video);
    tick();

    detectForVideo.and.throwError('quadro corrompido');
    rodarQuadros(1);

    detectForVideo.and.callFake(resultadoComRosto);
    rodarQuadros(2);
    tick(INTERVALO_DE_PUBLICACAO_MS);

    expect(service.ativo).toBeTrue();
    expect(service.metricas()).not.toBeNull();

    service.parar();
    discardPeriodicTasks();
  }));

  it('não processa mais nada depois de parar', fakeAsync(() => {
    service.iniciar(video);
    tick();
    rodarQuadros(2);

    service.parar();
    const chamadasAteParar = detectForVideo.calls.count();
    rodarQuadros(3);

    expect(detectForVideo).toHaveBeenCalledTimes(chamadasAteParar);
    expect(service.ativo).toBeFalse();
    discardPeriodicTasks();
  }));

  it('limpa a leitura e o FPS ao parar', fakeAsync(() => {
    service.iniciar(video);
    tick();
    rodarQuadros(3, 50);
    tick(INTERVALO_DE_PUBLICACAO_MS);

    service.parar();

    expect(service.metricas()).toBeNull();
    expect(service.fps()).toBe(0);
    discardPeriodicTasks();
  }));

  it('para de publicar depois de parar', fakeAsync(() => {
    service.iniciar(video);
    tick();
    rodarQuadros(3);

    service.parar();
    tick(INTERVALO_DE_PUBLICACAO_MS * 3);

    expect(service.metricas()).toBeNull();
    discardPeriodicTasks();
  }));

  it('iniciar duas vezes não abre um segundo loop', fakeAsync(() => {
    service.iniciar(video);
    tick();
    service.iniciar(video);
    tick();

    rodarQuadros(1);

    expect(detectForVideo).toHaveBeenCalledTimes(1);

    service.parar();
    discardPeriodicTasks();
  }));

  it('reaproveita o detector já carregado entre sessões', fakeAsync(() => {
    const criar = jasmine
      .createSpy('criarDetector')
      .and.resolveTo({ detectForVideo, close: fechar } as unknown as DetectorFacial);

    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      providers: [
        { provide: CRIADOR_DE_DETECTOR, useValue: criar },
        { provide: AGENDADOR_DE_QUADROS, useValue: (_v: unknown, passo: () => void) => (proximoQuadro = passo) },
        { provide: RELOGIO, useValue: () => instante },
      ],
    });
    const outro = TestBed.inject(LandmarksService);

    outro.iniciar(video);
    tick();
    outro.parar();
    outro.iniciar(video);
    tick();

    // Carregar o modelo custa segundos e megabytes; refazer isso a cada sessão
    // seria uma espera desnecessária para o aluno.
    expect(criar).toHaveBeenCalledTimes(1);

    outro.parar();
    discardPeriodicTasks();
  }));

  it('fecha o detector ao ser destruído', fakeAsync(() => {
    service.iniciar(video);
    tick();

    service.ngOnDestroy();

    expect(fechar).toHaveBeenCalled();
    expect(service.ativo).toBeFalse();
    discardPeriodicTasks();
  }));
});
