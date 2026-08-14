import { Injectable, InjectionToken, NgZone, OnDestroy, inject, signal } from '@angular/core';
import { FaceLandmarker, FilesetResolver } from '@mediapipe/tasks-vision';

import { MetricasFaciais, calcularMetricas } from './metricas';

/** Binários WASM, copiados de `node_modules/@mediapipe/tasks-vision/wasm` pelo build. */
export const CAMINHO_DO_WASM = 'assets/mediapipe/wasm';

/** Modelo Face Mesh. Não vem no pacote npm — ver README. */
export const CAMINHO_DO_MODELO = 'assets/mediapipe/face_landmarker.task';

/**
 * De quanto em quanto tempo as métricas sobem para a interface.
 *
 * A captura roda na taxa do vídeo (~30 FPS), mas publicar a cada quadro
 * dispararia change detection 30 vezes por segundo à toa. 4 Hz é suficiente
 * para o aluno perceber o número mudando, e mantém o custo de CD longe da meta
 * de CPU ≤ 25% da ticket 16.
 */
export const INTERVALO_DE_PUBLICACAO_MS = 250;

/**
 * O mínimo que o serviço precisa de um detector facial. Existe para que os
 * testes possam substituir o MediaPipe sem carregar WASM nem o modelo de 3 MB.
 */
export interface DetectorFacial {
  detectForVideo(video: HTMLVideoElement, instanteMs: number): {
    faceLandmarks?: ReadonlyArray<ReadonlyArray<{ x: number; y: number }>>;
    facialTransformationMatrixes?: ReadonlyArray<{
      rows: number;
      columns: number;
      data: ArrayLike<number>;
    }>;
  };
  close(): void;
}

export type CriadorDeDetector = () => Promise<DetectorFacial>;

async function criarDetectorDoMediaPipe(): Promise<DetectorFacial> {
  const arquivos = await FilesetResolver.forVisionTasks(CAMINHO_DO_WASM);

  const opcoes = {
    baseOptions: { modelAssetPath: CAMINHO_DO_MODELO },
    runningMode: 'VIDEO' as const,
    numFaces: 1,
    // Sem isso o resultado vem sem `facialTransformationMatrixes`, e não há
    // como calcular Head Pose.
    outputFacialTransformationMatrixes: true,
  };

  try {
    return (await FaceLandmarker.createFromOptions(arquivos, {
      ...opcoes,
      baseOptions: { ...opcoes.baseOptions, delegate: 'GPU' },
    })) as unknown as DetectorFacial;
  } catch {
    // Nem toda máquina de estudante tem WebGL disponível para o delegate de
    // GPU. Cair para CPU é mais lento, mas a alternativa seria a sessão
    // simplesmente não começar.
    return (await FaceLandmarker.createFromOptions(arquivos, {
      ...opcoes,
      baseOptions: { ...opcoes.baseOptions, delegate: 'CPU' },
    })) as unknown as DetectorFacial;
  }
}

export const CRIADOR_DE_DETECTOR = new InjectionToken<CriadorDeDetector>('CriadorDeDetector', {
  providedIn: 'root',
  factory: () => criarDetectorDoMediaPipe,
});

/**
 * Agenda o próximo quadro a processar.
 *
 * Usa `requestAnimationFrame`, e não `requestVideoFrameCallback`. O rVFC seria
 * o encaixe teoricamente perfeito — acorda uma vez por quadro do vídeo, não por
 * repintura da tela — mas há navegadores e contextos em que ele simplesmente
 * não dispara para um `<video>` que está tocando normalmente. Quando isso
 * acontece o loop nunca acorda, e a captura fica em 0 FPS **sem erro nenhum**:
 * a falha mais cara de diagnosticar que existe.
 *
 * O ganho que o rVFC daria — não reprocessar o mesmo quadro num monitor de
 * 120 Hz com webcam de 30 — é recuperado comparando `currentTime` do vídeo em
 * `processarQuadro`.
 */
export type AgendadorDeQuadros = (video: HTMLVideoElement, passo: () => void) => void;

export const AGENDADOR_DE_QUADROS = new InjectionToken<AgendadorDeQuadros>('AgendadorDeQuadros', {
  providedIn: 'root',
  factory: (): AgendadorDeQuadros => (_video, passo) => {
    requestAnimationFrame(passo);
  },
});

/** Fonte de tempo. Injetável para que o teste de FPS não dependa do relógio real. */
export const RELOGIO = new InjectionToken<() => number>('Relogio', {
  providedIn: 'root',
  factory: () => () => performance.now(),
});

/**
 * Ponte entre a webcam e o cálculo de métricas.
 *
 * Só esta classe conhece o `@mediapipe/tasks-vision`. A aritmética vive em
 * `metricas.ts`, sem fornecedor; trocar de biblioteca de visão computacional
 * mexe aqui e em mais nada.
 */
@Injectable({ providedIn: 'root' })
export class LandmarksService implements OnDestroy {
  private readonly zone = inject(NgZone);
  private readonly criarDetector = inject(CRIADOR_DE_DETECTOR);
  private readonly agendarQuadro = inject(AGENDADOR_DE_QUADROS);
  private readonly agora = inject(RELOGIO);

  private detector: DetectorFacial | null = null;
  private video: HTMLVideoElement | null = null;
  private processando = false;
  private publicador: ReturnType<typeof setInterval> | null = null;

  private metricasDoUltimoQuadro: MetricasFaciais | null = null;
  private quadrosDesdeAPublicacao = 0;
  private instanteDaUltimaPublicacao = 0;
  private ultimoInstanteEnviado = -1;
  private ultimoTempoDeVideo = -1;

  private readonly metricasSignal = signal<MetricasFaciais | null>(null);
  private readonly fpsSignal = signal(0);

  /** Última leitura de EAR/MAR/Head Pose, ou `null` quando não há rosto no quadro. */
  readonly metricas = this.metricasSignal.asReadonly();

  /** Quadros processados por segundo. A ticket 5 exige pelo menos 15. */
  readonly fps = this.fpsSignal.asReadonly();

  /** Já está processando quadros? */
  get ativo(): boolean {
    return this.processando;
  }

  /**
   * Começa a extrair landmarks do vídeo. Idempotente.
   *
   * O detector é criado uma vez e reaproveitado entre sessões: carregá-lo custa
   * alguns megabytes e alguns segundos.
   */
  async iniciar(video: HTMLVideoElement): Promise<void> {
    if (this.processando) {
      return;
    }

    this.detector ??= await this.criarDetector();

    this.video = video;
    this.processando = true;
    this.quadrosDesdeAPublicacao = 0;
    this.instanteDaUltimaPublicacao = this.agora();

    // O loop fica fora da zona do Angular para não disparar change detection a
    // cada quadro; a volta para dentro acontece só na publicação.
    this.zone.runOutsideAngular(() => this.agendarQuadro(video, () => this.passo()));

    this.publicador = setInterval(() => this.publicar(), INTERVALO_DE_PUBLICACAO_MS);
  }

  /** Para o processamento. Não desliga a webcam — isso é do `CameraService`. Idempotente. */
  parar(): void {
    this.processando = false;

    if (this.publicador !== null) {
      clearInterval(this.publicador);
      this.publicador = null;
    }

    this.video = null;
    this.metricasDoUltimoQuadro = null;
    this.ultimoInstanteEnviado = -1;
    this.ultimoTempoDeVideo = -1;
    this.quadrosDesdeAPublicacao = 0;

    this.metricasSignal.set(null);
    this.fpsSignal.set(0);
  }

  private passo(): void {
    if (!this.processando) {
      return;
    }

    this.processarQuadro();

    const video = this.video;
    if (this.processando && video !== null) {
      this.agendarQuadro(video, () => this.passo());
    }
  }

  private processarQuadro(): void {
    const video = this.video;
    const detector = this.detector;

    // `HAVE_CURRENT_DATA`: antes disso não há pixel nenhum para analisar, e
    // `videoWidth`/`videoHeight` ainda valem 0.
    if (video === null || detector === null || video.readyState < 2) {
      return;
    }

    // O `requestAnimationFrame` acompanha a tela, não a webcam: num monitor de
    // 120 Hz com câmera de 30 FPS, três em cada quatro chamadas trazem o mesmo
    // quadro. Reprocessá-lo seria CPU jogada fora — e inflaria o FPS medido com
    // trabalho repetido.
    if (video.currentTime === this.ultimoTempoDeVideo) {
      return;
    }
    this.ultimoTempoDeVideo = video.currentTime;

    // `detectForVideo` exige instantes estritamente crescentes; repetir um
    // timestamp faz o MediaPipe descartar o quadro.
    const instante = this.agora();
    if (instante <= this.ultimoInstanteEnviado) {
      return;
    }
    this.ultimoInstanteEnviado = instante;

    let resultado;
    try {
      resultado = detector.detectForVideo(video, instante);
    } catch {
      // Um quadro problemático não pode derrubar a sessão inteira.
      return;
    }

    this.quadrosDesdeAPublicacao += 1;

    const malha = resultado.faceLandmarks?.[0];
    const matriz = resultado.facialTransformationMatrixes?.[0];

    if (malha === undefined || matriz === undefined) {
      // Rosto fora do quadro. A ticket 7 zera o IEE aqui via P(t) = 0.
      this.metricasDoUltimoQuadro = null;
      return;
    }

    this.metricasDoUltimoQuadro = calcularMetricas(
      malha,
      matriz,
      video.videoWidth / video.videoHeight,
    );
  }

  private publicar(): void {
    const agora = this.agora();
    const segundos = (agora - this.instanteDaUltimaPublicacao) / 1000;
    const fps = segundos > 0 ? this.quadrosDesdeAPublicacao / segundos : 0;

    this.quadrosDesdeAPublicacao = 0;
    this.instanteDaUltimaPublicacao = agora;

    const metricas = this.metricasDoUltimoQuadro;

    this.zone.run(() => {
      this.fpsSignal.set(Math.round(fps));
      this.metricasSignal.set(metricas);
    });
  }

  ngOnDestroy(): void {
    this.parar();
    this.detector?.close();
    this.detector = null;
  }
}
