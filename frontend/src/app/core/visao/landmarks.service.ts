import { Injectable, InjectionToken, NgZone, OnDestroy, inject, signal } from '@angular/core';
import { FaceLandmarker, FilesetResolver } from '@mediapipe/tasks-vision';

import { MetricasFaciais, calcularMetricas } from './metricas';
import { MotivoDeIncerteza, avaliarCaptura } from './qualidade';

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
 * Lado do quadrado em que o quadro é reamostrado para medir luminância.
 *
 * A medição é uma média do quadro inteiro, então resolução não acrescenta nada:
 * 24×24 são 576 pixels em vez de 300 mil, e o resultado é o mesmo número. O
 * custo importa porque isso roda a 4 Hz durante a sessão toda, contra a meta de
 * CPU ≤ 25% da ticket 16.
 */
export const LADO_DA_AMOSTRA_DE_LUZ = 24;

/**
 * Mede a luminância média do quadro atual, de 0 a 1 (ticket 10).
 *
 * Injetável porque é a única parte da medição de qualidade que toca pixels — e
 * portanto a única que um teste não consegue exercitar com um `<video>` dublado.
 * A aritmética do veredito fica em `qualidade.ts`, testável sem nada disso.
 */
export type MedidorDeLuminancia = (video: HTMLVideoElement) => number;

function criarMedidorDeLuminancia(): MedidorDeLuminancia {
  // Um canvas só, reaproveitado entre quadros: alocar 4 por segundo daria ao
  // GC trabalho constante durante uma sessão de uma hora.
  const canvas = document.createElement('canvas');
  canvas.width = LADO_DA_AMOSTRA_DE_LUZ;
  canvas.height = LADO_DA_AMOSTRA_DE_LUZ;

  // `willReadFrequently` evita que o navegador mantenha o canvas na GPU, de
  // onde cada `getImageData` custaria um round-trip.
  const contexto = canvas.getContext('2d', { willReadFrequently: true });

  return (video) => {
    if (contexto === null || video.videoWidth === 0) {
      // Sem contexto 2D não há como medir. Devolver 1 (claro) é o palpite
      // seguro: a falta de medição não pode virar um alerta de "está escuro".
      return 1;
    }

    contexto.drawImage(video, 0, 0, canvas.width, canvas.height);
    const { data } = contexto.getImageData(0, 0, canvas.width, canvas.height);

    let soma = 0;
    for (let i = 0; i < data.length; i += 4) {
      // Luma da Rec. 601: o olho humano não pesa os três canais igualmente, e a
      // média aritmética acusaria de escura uma cena dominada por azul.
      soma += 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2];
    }

    return soma / (data.length / 4) / 255;
  };
}

export const MEDIDOR_DE_LUMINANCIA = new InjectionToken<MedidorDeLuminancia>(
  'MedidorDeLuminancia',
  { providedIn: 'root', factory: criarMedidorDeLuminancia },
);

/**
 * O que a captura sabe num instante: a leitura e o quanto se pode confiar nela.
 *
 * Os dois andam juntos porque são consumidos juntos — a telemetria precisa
 * mandar as duas coisas no mesmo payload, e separá-las abriria a janela em que
 * a métrica de um quadro sobe com o veredito de outro.
 */
export interface LeituraDaCaptura {
  metricas: MetricasFaciais | null;
  incerteza: MotivoDeIncerteza | null;
}

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
  private readonly medirLuminancia = inject(MEDIDOR_DE_LUMINANCIA);

  private detector: DetectorFacial | null = null;
  private video: HTMLVideoElement | null = null;
  private processando = false;
  private publicador: ReturnType<typeof setInterval> | null = null;

  private metricasDoUltimoQuadro: MetricasFaciais | null = null;
  private quadrosDesdeAPublicacao = 0;
  private quadrosComRosto = 0;
  private somaDaAssimetria = 0;
  private instanteDaUltimaPublicacao = 0;
  private ultimoInstanteEnviado = -1;
  private ultimoTempoDeVideo = -1;

  private readonly metricasSignal = signal<MetricasFaciais | null>(null);
  private readonly fpsSignal = signal(0);
  private readonly incertezaSignal = signal<MotivoDeIncerteza | null>(null);

  /** Última leitura de EAR/MAR/Head Pose, ou `null` quando não há rosto no quadro. */
  readonly metricas = this.metricasSignal.asReadonly();

  /** Quadros processados por segundo. A ticket 5 exige pelo menos 15. */
  readonly fps = this.fpsSignal.asReadonly();

  /**
   * Por que a última janela não é confiável, ou `null` quando está tudo bem
   * (ticket 10). É julgado por janela de publicação, e não por quadro, porque
   * detecção intermitente só existe como fenômeno ao longo de vários quadros.
   */
  readonly incerteza = this.incertezaSignal.asReadonly();

  /** Métricas e veredito do mesmo instante, para a telemetria mandar juntos. */
  leitura(): LeituraDaCaptura {
    return { metricas: this.metricasSignal(), incerteza: this.incertezaSignal() };
  }

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
    this.quadrosComRosto = 0;
    this.somaDaAssimetria = 0;
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
    this.quadrosComRosto = 0;
    this.somaDaAssimetria = 0;

    this.metricasSignal.set(null);
    this.fpsSignal.set(0);
    this.incertezaSignal.set(null);
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

    const metricas = calcularMetricas(malha, matriz, video.videoWidth / video.videoHeight);

    this.quadrosComRosto += 1;
    // Acumulada ao longo da janela, e não lida do último quadro na publicação:
    // um quadro só decidindo por todos daria os dois erros opostos — um contorno
    // perdido num único frame marcaria o segundo inteiro como reflexo, e um
    // reflexo constante passaria batido sempre que o último quadro da janela
    // saísse sem rosto.
    this.somaDaAssimetria += metricas.assimetriaOcular;
    this.metricasDoUltimoQuadro = metricas;
  }

  private publicar(): void {
    const agora = this.agora();
    const segundos = (agora - this.instanteDaUltimaPublicacao) / 1000;
    const fps = segundos > 0 ? this.quadrosDesdeAPublicacao / segundos : 0;

    const metricas = this.metricasDoUltimoQuadro;
    const incerteza = this.avaliarJanela();

    this.quadrosDesdeAPublicacao = 0;
    this.quadrosComRosto = 0;
    this.somaDaAssimetria = 0;
    this.instanteDaUltimaPublicacao = agora;

    this.zone.run(() => {
      this.fpsSignal.set(Math.round(fps));
      this.metricasSignal.set(metricas);
      this.incertezaSignal.set(incerteza);
    });
  }

  /**
   * Julga a confiabilidade da janela que acabou de fechar (ticket 10).
   *
   * A luminância é medida **uma vez por janela**, e não por quadro: é uma
   * propriedade do ambiente, que não muda em 250 ms, e ler pixels 30 vezes por
   * segundo custaria mais que toda a extração de landmarks.
   */
  private avaliarJanela(): MotivoDeIncerteza | null {
    const video = this.video;
    if (video === null || this.quadrosDesdeAPublicacao === 0) {
      // Nenhum quadro processado: a captura nem rodou (aba em segundo plano).
      // Isso não é incerteza de captura — é ausência de captura, e o aviso de
      // FPS baixo já cobre o caso sem mandar o aluno acender uma luz à toa.
      return null;
    }

    let luminancia: number;
    try {
      luminancia = this.medirLuminancia(video);
    } catch {
      // Mesma proteção que `detectForVideo` tem em `processarQuadro`, e pelo
      // mesmo motivo: sem ela, uma falha ao ler pixels abortaria `publicar()`
      // antes de atualizar métricas e FPS, e a tela congelaria em silêncio na
      // última leitura boa — com a telemetria reenviando-a indefinidamente.
      // Assumir "claro" mantém a medição rodando; assumir escuro alertaria o
      // aluno sobre uma lâmpada que não tem nada de errado.
      luminancia = 1;
    }

    return avaliarCaptura({
      luminancia,
      presenca: this.quadrosComRosto / this.quadrosDesdeAPublicacao,
      // Média dos quadros em que houve rosto. Sem rosto na janela não há
      // assimetria a avaliar, e `avaliarCaptura` já ignora o campo nesse caso.
      assimetriaOcular:
        this.quadrosComRosto > 0 ? this.somaDaAssimetria / this.quadrosComRosto : 0,
    });
  }

  ngOnDestroy(): void {
    this.parar();
    this.detector?.close();
    this.detector = null;
  }
}
