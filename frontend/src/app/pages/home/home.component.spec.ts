import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import {
  ComponentFixture,
  TestBed,
  discardPeriodicTasks,
  fakeAsync,
  flushMicrotasks,
  tick,
} from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';

import { signal } from '@angular/core';

import { AuthService } from '../../core/services/auth.service';
import { MetodoDeEstudo } from '../../core/services/metodo.service';
import {
  Bloco,
  ESPERA_PARA_RETENTAR_MS,
  INTERVALO_ATIVIDADE_MS,
  Sessao,
} from '../../core/services/sessao.service';
import { TelemetriaService } from '../../core/telemetria/telemetria.service';
import { LandmarksService, LeituraDaCaptura } from '../../core/visao/landmarks.service';
import { MetricasFaciais } from '../../core/visao/metricas';
import { MotivoDeIncerteza } from '../../core/visao/qualidade';
import { HomeComponent } from './home.component';

const API = 'http://localhost:8000';

const SESSAO_EM_ANDAMENTO: Sessao = {
  id: 7,
  id_aluno: 1,
  inicio: '2026-08-13T12:00:00Z',
  fim: null,
};

const SESSAO_ENCERRADA: Sessao = { ...SESSAO_EM_ANDAMENTO, fim: '2026-08-13T12:30:00Z' };

/**
 * `GET /metodos` como o servidor o entrega, com os três casos que mudam o
 * comportamento da tela: um método que prescreve foco e tem pausa longa, um que
 * não prescreve foco nenhum, e a escolha explícita de não usar método.
 */
const CATALOGO_DE_TESTE: MetodoDeEstudo[] = [
  {
    codigo: 'pomodoro',
    nome: 'Pomodoro',
    foco_s: 1500,
    pausa_s: 300,
    ciclos_ate_pausa_longa: 4,
    pausa_longa_s: 900,
  },
  {
    codigo: 'flow',
    nome: 'Flow / Deep Work',
    foco_s: null,
    pausa_s: 300,
    ciclos_ate_pausa_longa: null,
    pausa_longa_s: null,
  },
  {
    codigo: 'livre',
    nome: 'Sem método',
    foco_s: null,
    pausa_s: 300,
    ciclos_ate_pausa_longa: null,
    pausa_longa_s: null,
  },
];

/**
 * A sessão legada: `metodo` ausente é "esta sessão é anterior ao recurso".
 * É o mesmo objeto que os testes antigos usam, e continuar assim é de propósito
 * — todos eles são, agora, o caso de compatibilidade.
 */
const SESSAO_SEM_METODO = SESSAO_EM_ANDAMENTO;

const SESSAO_COM_POMODORO: Sessao = {
  ...SESSAO_EM_ANDAMENTO,
  metodo: 'pomodoro',
  metodo_nome: 'Pomodoro',
  assunto: 'Cálculo II',
  meta_de_blocos: 4,
};

const SESSAO_COM_FLOW: Sessao = {
  ...SESSAO_EM_ANDAMENTO,
  metodo: 'flow',
  metodo_nome: 'Flow / Deep Work',
  assunto: 'Monografia',
  meta_de_blocos: null,
};

function erroComNome(nome: string): Error {
  const erro = new Error(nome);
  erro.name = nome;
  return erro;
}

/**
 * Dublê do motor de visão. É um boundary como o HTTP e o `getUserMedia`: depende
 * de binários WASM e de um arquivo de modelo de vários megabytes, que não têm
 * por que existir numa suíte de unidade. O cálculo de verdade é testado direto
 * em `metricas.spec.ts`, sem passar por aqui.
 */
class LandmarksServiceFalso {
  readonly metricas = signal<MetricasFaciais | null>(null);
  readonly fps = signal(0);
  readonly incerteza = signal<MotivoDeIncerteza | null>(null);
  readonly rostoDetectado = signal(false);

  ativo = false;

  leitura(): LeituraDaCaptura {
    return { metricas: this.metricas(), incerteza: this.incerteza() };
  }

  readonly iniciar = jasmine.createSpy('iniciar').and.callFake(async () => {
    this.ativo = true;
  });

  readonly parar = jasmine.createSpy('parar').and.callFake(() => {
    this.ativo = false;
    this.metricas.set(null);
    this.fps.set(0);
    this.incerteza.set(null);
    this.rostoDetectado.set(false);
  });
}

/** Dublê do canal de telemetria: WebSocket é boundary, como o HTTP. */
class TelemetriaServiceFalso {
  readonly score = signal<number | null>(null);
  readonly conectado = signal(false);
  readonly incerteza = signal<string | null>(null);

  readonly iniciar = jasmine.createSpy('iniciar');
  readonly parar = jasmine.createSpy('parar');
}

const LEITURA: MetricasFaciais = {
  ear: 0.284,
  mar: 0.052,
  cabeca: { yaw: -4.2, pitch: 7.1, roll: 0.5 },
  assimetriaOcular: 0.03,
};

/**
 * Estes testes rodam com o SessaoService, o AuthService e o InactivityService
 * de verdade: os únicos dublês são o HTTP e o `getUserMedia`, que são os
 * boundaries do sistema. Assim eles cobrem a integração entre a tela e o
 * serviço, em vez de um dublê que sempre concorda com o que a tela espera.
 */
describe('HomeComponent', () => {
  let fixture: ComponentFixture<HomeComponent>;
  let httpMock: HttpTestingController;
  let authService: AuthService;
  let navegar: jasmine.Spy;
  let getUserMedia: jasmine.Spy;
  let landmarks: LandmarksServiceFalso;
  let telemetria: TelemetriaServiceFalso;

  const mediaDevicesOriginal = Object.getOwnPropertyDescriptor(navigator, 'mediaDevices');
  const streamsCriados: MediaStream[] = [];

  /**
   * Um `MediaStream` de verdade, sem depender de webcam nem de permissão: o
   * canvas produz trilhas reais, que podem ser paradas e inspecionadas. Um
   * objeto falso não serviria — atribuir algo que não é `MediaStream` ao
   * `srcObject` de um <video> estoura no navegador.
   */
  function streamDeTeste(): MediaStream {
    const canvas = document.createElement('canvas');
    canvas.width = 2;
    canvas.height = 2;
    const stream = canvas.captureStream(0);
    streamsCriados.push(stream);
    return stream;
  }

  function texto(): string {
    return fixture.nativeElement.textContent as string;
  }

  function botao(teste: string): HTMLButtonElement | null {
    return fixture.nativeElement.querySelector(`[data-teste="${teste}"]`);
  }

  function preview(): HTMLVideoElement | null {
    return fixture.nativeElement.querySelector('[data-teste="preview-webcam"]');
  }

  function webcamLigada(): boolean {
    return streamsCriados.some((stream) =>
      stream.getVideoTracks().some((track) => track.readyState === 'live'),
    );
  }

  function clicar(teste: string): void {
    botao(teste)!.click();
    fixture.detectChanges();
  }

  /** Clica e espera o `getUserMedia` resolver antes de renderizar de novo. */
  async function clicarEAguardar(teste: string): Promise<void> {
    botao(teste)!.click();
    await fixture.whenStable();
    fixture.detectChanges();
  }

  /**
   * Responde ao `GET /metodos` que a tela dispara no `ngOnInit`.
   *
   * O catálogo é buscado sempre, com ou sem sessão em andamento: depois de um
   * F5 quem precisa dele é a tela da sessão, porque é de `foco_s` que sai o
   * cronômetro. `'falha'` simula o catálogo indisponível (E1).
   */
  function responderCatalogo(catalogo: MetodoDeEstudo[] | 'falha' = CATALOGO_DE_TESTE): void {
    const requisicao = httpMock.expectOne(`${API}/metodos`);
    if (catalogo === 'falha') {
      requisicao.flush({}, { status: 503, statusText: 'Service Unavailable' });
    } else {
      requisicao.flush(catalogo);
    }
  }

  /** Resolve os GETs disparados no ngOnInit e renderiza o resultado. */
  function abrirTela(
    sessao: Sessao | null,
    catalogo: MetodoDeEstudo[] | 'falha' = CATALOGO_DE_TESTE,
  ): void {
    fixture.detectChanges();
    responderCatalogo(catalogo);
    httpMock.expectOne(`${API}/sessoes/ativa`).flush(sessao);
    fixture.detectChanges();
  }

  /** O GET dos blocos que uma sessão com método dispara ao ser assumida. */
  function responderBlocos(sessao: Sessao, blocos: Bloco[]): void {
    httpMock.expectOne(`${API}/sessoes/${sessao.id}/blocos`).flush(blocos);
    fixture.detectChanges();
  }

  /** Um bloco aberto que começou há `haSegundos`, ancorado no relógio do teste. */
  function blocoAberto(tipo: 'foco' | 'pausa', indice: number, haSegundos = 0): Bloco {
    return {
      id: 100 + indice,
      id_sessao: SESSAO_EM_ANDAMENTO.id,
      indice,
      tipo,
      inicio: new Date(Date.now() - haSegundos * 1000).toISOString(),
      fim: null,
      origem: 'metodo',
    };
  }

  /** O mesmo bloco, já fechado — a história que o servidor devolve depois do F5. */
  function blocoFechado(tipo: 'foco' | 'pausa', indice: number, duracaoS: number): Bloco {
    const fim = Date.now() - duracaoS * 1000;
    return {
      ...blocoAberto(tipo, indice),
      inicio: new Date(fim - duracaoS * 1000).toISOString(),
      fim: new Date(fim).toISOString(),
    };
  }

  /** `abrirTela`, mas esperando a retomada da captura quando há sessão viva. */
  async function abrirTelaEAguardar(sessao: Sessao | null): Promise<void> {
    abrirTela(sessao);
    await fixture.whenStable();
    fixture.detectChanges();
  }

  /**
   * Clica em Sair e resolve o encerramento da sessão no backend.
   *
   * Sair com sessão aberta deixou de ser uma operação local: sem avisar o
   * servidor, a sessão sobreviveria até a varredura de ausência e seria fechada
   * como `"inatividade"`, carimbando o relatório como **parcial** — dizendo ao
   * aluno que a sessão foi interrompida quando ele a encerrou de propósito.
   */
  function sair(resposta: Sessao | 'falha' = SESSAO_ENCERRADA): void {
    clicar('sair');
    const requisicao = httpMock.expectOne(`${API}/sessoes/${SESSAO_EM_ANDAMENTO.id}/encerrar`);
    if (resposta === 'falha') {
      requisicao.flush({}, { status: 500, statusText: 'Server Error' });
    } else {
      requisicao.flush(resposta);
    }
    fixture.detectChanges();
  }

  beforeEach(async () => {
    localStorage.clear();
    // A tela é protegida pelo authGuard: o aluno só chega aqui autenticado, e o
    // AuthService lê o token do localStorage já ao ser construído.
    localStorage.setItem('iee_access_token', 'token-fake');

    await TestBed.configureTestingModule({
      imports: [HomeComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        { provide: LandmarksService, useClass: LandmarksServiceFalso },
        { provide: TelemetriaService, useClass: TelemetriaServiceFalso },
      ],
    }).compileComponents();

    httpMock = TestBed.inject(HttpTestingController);
    authService = TestBed.inject(AuthService);
    landmarks = TestBed.inject(LandmarksService) as unknown as LandmarksServiceFalso;
    telemetria = TestBed.inject(TelemetriaService) as unknown as TelemetriaServiceFalso;
    navegar = spyOn(TestBed.inject(Router), 'navigate').and.resolveTo(true);

    getUserMedia = jasmine
      .createSpy('getUserMedia')
      .and.callFake(() => Promise.resolve(streamDeTeste()));
    Object.defineProperty(navigator, 'mediaDevices', {
      value: { getUserMedia },
      configurable: true,
    });

    fixture = TestBed.createComponent(HomeComponent);
  });

  afterEach(() => {
    httpMock.verify();
    localStorage.clear();

    streamsCriados.forEach((stream) => stream.getTracks().forEach((track) => track.stop()));
    streamsCriados.length = 0;

    if (mediaDevicesOriginal) {
      Object.defineProperty(navigator, 'mediaDevices', mediaDevicesOriginal);
    }
  });

  describe('sessão de estudo', () => {
    it('oferece iniciar quando o aluno não tem sessão em andamento', () => {
      abrirTela(null);

      expect(botao('iniciar-sessao')).toBeTruthy();
      expect(botao('encerrar-sessao')).toBeNull();
    });

    it('oferece encerrar quando já existe sessão em andamento ao abrir a tela', async () => {
      await abrirTelaEAguardar(SESSAO_EM_ANDAMENTO);

      expect(botao('encerrar-sessao')).toBeTruthy();
      expect(botao('iniciar-sessao')).toBeNull();
      expect(texto()).toContain('Sessão em andamento');
    });

    it('inicia a sessão ao clicar em iniciar e passa a oferecer o encerramento', async () => {
      abrirTela(null);

      await clicarEAguardar('iniciar-sessao');
      httpMock.expectOne({ method: 'POST', url: `${API}/sessoes` }).flush(SESSAO_EM_ANDAMENTO);
      fixture.detectChanges();

      expect(botao('encerrar-sessao')).toBeTruthy();
    });

    it('encerra a sessão ao clicar em encerrar e volta a oferecer o início', async () => {
      await abrirTelaEAguardar(SESSAO_EM_ANDAMENTO);

      clicar('encerrar-sessao');
      httpMock
        .expectOne(`${API}/sessoes/${SESSAO_EM_ANDAMENTO.id}/encerrar`)
        .flush(SESSAO_ENCERRADA);
      fixture.detectChanges();

      expect(botao('iniciar-sessao')).toBeTruthy();
    });

    it('leva ao relatório da sessão recém-encerrada (AC-11-1)', async () => {
      // O relatório é o fim da jornada: encerrar e ficar na mesma tela deixaria
      // o aluno sem nada, embora a própria tela prometa o contrário.
      await abrirTelaEAguardar(SESSAO_EM_ANDAMENTO);

      clicar('encerrar-sessao');
      httpMock
        .expectOne(`${API}/sessoes/${SESSAO_EM_ANDAMENTO.id}/encerrar`)
        .flush(SESSAO_ENCERRADA);
      fixture.detectChanges();

      expect(navegar).toHaveBeenCalledWith(['/relatorio', SESSAO_ENCERRADA.id]);
    });

    it('não leva ao relatório quando o encerramento falha', async () => {
      // Mandar para o relatório de uma sessão que talvez continue aberta
      // trocaria um erro claro por um 409 que o aluno não sabe interpretar.
      await abrirTelaEAguardar(SESSAO_EM_ANDAMENTO);

      clicar('encerrar-sessao');
      httpMock
        .expectOne(`${API}/sessoes/${SESSAO_EM_ANDAMENTO.id}/encerrar`)
        .flush({}, { status: 500, statusText: 'Server Error' });
      fixture.detectChanges();

      expect(navegar).not.toHaveBeenCalledWith(['/relatorio', SESSAO_ENCERRADA.id]);
    });

    it('oferece o histórico a partir da tela de sessão', () => {
      abrirTela(null);

      const link = fixture.nativeElement.querySelector('[data-teste="ir-para-historico"]');
      expect(link).toBeTruthy();
      expect(link.getAttribute('href')).toBe('/historico');
    });

    it('ressincroniza a tela quando o backend responde que já há sessão em andamento', async () => {
      // Cenário de duas abas: a aba antiga precisa passar a oferecer "Encerrar",
      // em vez de ficar travada num "Iniciar" que sempre falha.
      abrirTela(null);

      await clicarEAguardar('iniciar-sessao');
      httpMock
        .expectOne({ method: 'POST', url: `${API}/sessoes` })
        .flush(
          { detail: 'Já existe uma sessão de estudo em andamento' },
          { status: 409, statusText: 'Conflict' },
        );
      httpMock.expectOne(`${API}/sessoes/ativa`).flush(SESSAO_EM_ANDAMENTO);
      fixture.detectChanges();

      expect(botao('encerrar-sessao')).toBeTruthy();
      expect(texto()).toContain('já tem uma sessão de estudo em andamento');
      // A sessão existe de fato, então a captura tem que continuar viva.
      expect(webcamLigada()).toBeTrue();
    });

    it('avisa quando o backend falha ao iniciar a sessão', async () => {
      abrirTela(null);

      await clicarEAguardar('iniciar-sessao');
      httpMock
        .expectOne({ method: 'POST', url: `${API}/sessoes` })
        .flush({}, { status: 500, statusText: 'Server Error' });
      fixture.detectChanges();

      expect(texto()).toContain('Não foi possível iniciar');
      expect(botao('iniciar-sessao')).toBeTruthy();
    });

    it('avisa quando não consegue verificar se há sessão em andamento ao abrir a tela', () => {
      fixture.detectChanges();
      responderCatalogo();
      httpMock
        .expectOne(`${API}/sessoes/ativa`)
        .flush({}, { status: 500, statusText: 'Server Error' });
      fixture.detectChanges();

      expect(texto()).toContain('Não foi possível verificar');
    });

    it('avisa quando o backend falha ao encerrar, mantendo a sessão em andamento', async () => {
      await abrirTelaEAguardar(SESSAO_EM_ANDAMENTO);

      clicar('encerrar-sessao');
      httpMock
        .expectOne(`${API}/sessoes/${SESSAO_EM_ANDAMENTO.id}/encerrar`)
        .flush({}, { status: 500, statusText: 'Server Error' });
      fixture.detectChanges();

      expect(texto()).toContain('Não foi possível encerrar');
      expect(botao('encerrar-sessao')).toBeTruthy();
    });
  });

  describe('webcam', () => {
    it('pede a webcam antes de criar a sessão no backend', async () => {
      // Se a ordem fosse invertida, negar a permissão deixaria uma sessão órfã
      // no banco, sem log nenhum de engajamento.
      getUserMedia.and.rejectWith(erroComNome('NotAllowedError'));
      abrirTela(null);

      await clicarEAguardar('iniciar-sessao');

      httpMock.expectNone({ method: 'POST', url: `${API}/sessoes` });
      expect(botao('iniciar-sessao')).toBeTruthy();
    });

    it('explica que a sessão não começa sem autorização da webcam', async () => {
      getUserMedia.and.rejectWith(erroComNome('NotAllowedError'));
      abrirTela(null);

      await clicarEAguardar('iniciar-sessao');

      expect(texto()).toContain('Autorize a câmera');
    });

    it('dá uma mensagem de hardware quando não há webcam no computador', async () => {
      getUserMedia.and.rejectWith(erroComNome('NotFoundError'));
      abrirTela(null);

      await clicarEAguardar('iniciar-sessao');

      expect(texto()).toContain('Nenhuma webcam foi encontrada');
    });

    it('avisa que outro programa está usando a webcam', async () => {
      getUserMedia.and.rejectWith(erroComNome('NotReadableError'));
      abrirTela(null);

      await clicarEAguardar('iniciar-sessao');

      expect(texto()).toContain('já está sendo usada por outro programa');
    });

    it('mostra o preview da webcam ligado ao stream durante a sessão', async () => {
      abrirTela(null);

      await clicarEAguardar('iniciar-sessao');
      httpMock.expectOne({ method: 'POST', url: `${API}/sessoes` }).flush(SESSAO_EM_ANDAMENTO);
      fixture.detectChanges();

      const video = preview();
      expect(video).toBeTruthy();
      expect(video!.srcObject).toBe(streamsCriados[0]);
    });

    it('não mostra preview quando não há sessão em andamento', () => {
      abrirTela(null);

      expect(preview()).toBeNull();
    });

    it('retoma a captura ao abrir a tela com uma sessão já em andamento', async () => {
      // Reload no meio da sessão: o backend continua com a sessão viva, então a
      // captura precisa voltar — senão a sessão segue sem telemetria nenhuma.
      await abrirTelaEAguardar(SESSAO_EM_ANDAMENTO);

      expect(getUserMedia).toHaveBeenCalled();
      expect(preview()!.srcObject).toBe(streamsCriados[0]);
    });

    it('explica a falha e mantém a sessão quando a webcam é negada num reload', async () => {
      // O aluno recarregou a página e revogou a permissão no meio da sessão. A
      // sessão continua viva no backend, então matá-la aqui perderia tempo de
      // estudo já registrado — mas seguir em silêncio faria o aluno acreditar
      // que está sendo medido sem estar.
      getUserMedia.and.rejectWith(erroComNome('NotAllowedError'));

      await abrirTelaEAguardar(SESSAO_EM_ANDAMENTO);

      expect(texto()).toContain('Autorize a câmera');
      expect(botao('encerrar-sessao')).toBeTruthy();
    });

    it('não pede a webcam ao abrir a tela sem sessão em andamento', () => {
      abrirTela(null);

      expect(getUserMedia).not.toHaveBeenCalled();
    });

    it('desliga a webcam ao encerrar a sessão', async () => {
      await abrirTelaEAguardar(SESSAO_EM_ANDAMENTO);
      expect(webcamLigada()).toBeTrue();

      clicar('encerrar-sessao');
      httpMock
        .expectOne(`${API}/sessoes/${SESSAO_EM_ANDAMENTO.id}/encerrar`)
        .flush(SESSAO_ENCERRADA);
      fixture.detectChanges();

      expect(webcamLigada()).toBeFalse();
    });

    it('desliga a webcam ao sair', async () => {
      await abrirTelaEAguardar(SESSAO_EM_ANDAMENTO);

      sair();

      expect(webcamLigada()).toBeFalse();
    });

    it('desliga a webcam quando o backend encerra a sessão por inatividade', fakeAsync(() => {
      // Este caminho não passa por clique nenhum: o heartbeat descobre que a
      // sessão morreu. Sem desligar a webcam aqui, a luz da câmera ficaria
      // acesa depois de uma sessão que já não existe.
      abrirTela(SESSAO_EM_ANDAMENTO);
      flushMicrotasks();
      fixture.detectChanges();
      expect(webcamLigada()).toBeTrue();

      tick(INTERVALO_ATIVIDADE_MS);
      httpMock
        .expectOne(`${API}/sessoes/${SESSAO_EM_ANDAMENTO.id}/atividade`)
        .flush(
          { detail: 'Esta sessão de estudo já foi encerrada' },
          { status: 409, statusText: 'Conflict' },
        );
      fixture.detectChanges();

      expect(webcamLigada()).toBeFalse();
      discardPeriodicTasks();
    }));

    it('libera a webcam quando o backend falha ao criar a sessão', async () => {
      abrirTela(null);

      await clicarEAguardar('iniciar-sessao');
      expect(webcamLigada()).toBeTrue();

      httpMock
        .expectOne({ method: 'POST', url: `${API}/sessoes` })
        .flush({}, { status: 500, statusText: 'Server Error' });
      fixture.detectChanges();

      expect(webcamLigada()).toBeFalse();
    });

    it('desliga a webcam ao sair da tela', async () => {
      // O CameraService vive na raiz e sobrevive ao componente; navegar para
      // outra rota não pode deixar a captura rodando em segundo plano.
      await abrirTelaEAguardar(SESSAO_EM_ANDAMENTO);

      fixture.destroy();

      expect(webcamLigada()).toBeFalse();
    });
  });

  describe('análise de landmarks', () => {
    /** Deixa uma sessão ativa com a captura rodando. */
    async function comSessaoAtiva(): Promise<void> {
      abrirTela(null);
      await clicarEAguardar('iniciar-sessao');
      httpMock.expectOne({ method: 'POST', url: `${API}/sessoes` }).flush(SESSAO_EM_ANDAMENTO);
      fixture.detectChanges();
      await fixture.whenStable();
      fixture.detectChanges();
    }

    it('começa a analisar o preview quando a sessão inicia', async () => {
      await comSessaoAtiva();

      expect(landmarks.iniciar).toHaveBeenCalledWith(preview()!);
    });

    it('não analisa nada enquanto não há sessão', () => {
      abrirTela(null);

      expect(landmarks.iniciar).not.toHaveBeenCalled();
    });

    it('para a análise ao encerrar a sessão', async () => {
      await comSessaoAtiva();

      clicar('encerrar-sessao');
      httpMock
        .expectOne(`${API}/sessoes/${SESSAO_EM_ANDAMENTO.id}/encerrar`)
        .flush(SESSAO_ENCERRADA);
      fixture.detectChanges();

      expect(landmarks.parar).toHaveBeenCalled();
      expect(landmarks.ativo).toBeFalse();
    });

    it('para a análise quando o backend encerra a sessão por inatividade', fakeAsync(() => {
      abrirTela(SESSAO_EM_ANDAMENTO);
      flushMicrotasks();
      fixture.detectChanges();

      tick(INTERVALO_ATIVIDADE_MS);
      httpMock
        .expectOne(`${API}/sessoes/${SESSAO_EM_ANDAMENTO.id}/atividade`)
        .flush(
          { detail: 'Esta sessão de estudo já foi encerrada' },
          { status: 409, statusText: 'Conflict' },
        );
      fixture.detectChanges();

      expect(landmarks.ativo).toBeFalse();
      discardPeriodicTasks();
    }));

    it('mostra EAR, MAR e head pose enquanto há rosto', async () => {
      await comSessaoAtiva();

      landmarks.metricas.set(LEITURA);
      fixture.detectChanges();

      expect(texto()).toContain('0.284');
      expect(texto()).toContain('0.052');
      expect(texto()).toContain('-4.2');
      expect(texto()).toContain('7.1');
    });

    it('avisa quando não há rosto no quadro, em vez de mostrar números vazios', async () => {
      await comSessaoAtiva();

      landmarks.metricas.set(null);
      fixture.detectChanges();

      expect(texto()).toContain('Rosto não detectado');
    });

    it('mostra o FPS da captura', async () => {
      await comSessaoAtiva();

      landmarks.fps.set(27);
      fixture.detectChanges();

      expect(texto()).toContain('27 FPS');
    });

    it('avisa quando a captura cai abaixo do piso de 15 FPS', async () => {
      // O piso está nos critérios da ticket 5; sem o aviso, o aluno não teria
      // como saber que a medição está degradada.
      await comSessaoAtiva();

      landmarks.fps.set(9);
      fixture.detectChanges();
      expect(fixture.nativeElement.querySelector('[data-teste="fps-baixo"]')).toBeTruthy();

      landmarks.fps.set(28);
      fixture.detectChanges();
      expect(fixture.nativeElement.querySelector('[data-teste="fps-baixo"]')).toBeNull();
    });

    it('mostra o alerta de incerteza de captura com a ação que resolve', async () => {
      // Ticket 10. O alerta reflete o que o **backend** decidiu, e não o
      // veredito local: o que a tela mostra tem que ser o que aconteceu com o
      // dado gravado.
      await comSessaoAtiva();

      telemetria.incerteza.set('baixa-luz');
      fixture.detectChanges();

      const alerta = fixture.nativeElement.querySelector('[data-teste="incerteza-de-captura"]');
      expect(alerta).toBeTruthy();
      expect(alerta.textContent).toContain('Incerteza de captura');
      expect(alerta.textContent).toContain('Acender uma luz');
    });

    it('tira o alerta de incerteza quando volta a medir', async () => {
      await comSessaoAtiva();

      telemetria.incerteza.set('oclusao');
      fixture.detectChanges();
      expect(
        fixture.nativeElement.querySelector('[data-teste="incerteza-de-captura"]'),
      ).toBeTruthy();

      telemetria.incerteza.set(null);
      fixture.detectChanges();
      expect(fixture.nativeElement.querySelector('[data-teste="incerteza-de-captura"]')).toBeNull();
    });

    it('mantém a sessão viva quando o modelo de visão falha ao carregar', async () => {
      // Perder as métricas é ruim; perder a sessão de estudo inteira por causa
      // do modelo seria pior.
      landmarks.iniciar.and.rejectWith(new Error('modelo indisponível'));

      await comSessaoAtiva();

      expect(botao('encerrar-sessao')).toBeTruthy();
      expect(texto()).toContain('não foi possível carregar o modelo');
    });
  });

  describe('privacidade', () => {
    it('não deixa nenhum dado facial sair do navegador durante a sessão', fakeAsync(() => {
      // O critério final da ticket 5, e a promessa central do projeto.
      //
      // ESCOPO: só o canal HTTP. O WebSocket da ticket 6 não passa pelo
      // HttpClient, então o httpMock é cego para ele — o que sobe por lá é
      // travado em `telemetria.service.spec.ts` ("nunca envia landmarks") e em
      // `agregacao.spec.ts`. Sem esta nota, o teste daria uma garantia mais
      // ampla do que realmente tem.
      abrirTela(SESSAO_EM_ANDAMENTO);
      flushMicrotasks();
      fixture.detectChanges();

      // Métricas fluindo, como numa sessão real com rosto no quadro.
      landmarks.metricas.set(LEITURA);
      landmarks.fps.set(30);
      fixture.detectChanges();

      tick(INTERVALO_ATIVIDADE_MS * 2);

      const requisicoes = httpMock.match(() => true);
      requisicoes.forEach((requisicao) => requisicao.flush(SESSAO_EM_ANDAMENTO));

      const permitidas = [`${API}/sessoes/${SESSAO_EM_ANDAMENTO.id}/atividade`];

      expect(requisicoes.length).toBeGreaterThan(0);
      for (const { request } of requisicoes) {
        expect(permitidas).toContain(request.url);
        // Corpo vazio é o que garante que nem métrica, nem landmark, nem frame
        // viajam de carona num endpoint legítimo.
        expect(request.body).toEqual({});
      }

      discardPeriodicTasks();
    }));

    it('não envia nada ao backend quando o rosto é detectado', fakeAsync(() => {
      // A detecção acontece inteiramente no navegador: aparecer no quadro não
      // pode disparar tráfego nenhum.
      abrirTela(SESSAO_EM_ANDAMENTO);
      flushMicrotasks();
      fixture.detectChanges();

      landmarks.metricas.set(LEITURA);
      fixture.detectChanges();
      landmarks.metricas.set({ ...LEITURA, ear: 0.05 });
      fixture.detectChanges();

      httpMock.expectNone(() => true);

      discardPeriodicTasks();
    }));
  });

  describe('telemetria', () => {
    async function comSessaoAtiva(): Promise<void> {
      abrirTela(null);
      await clicarEAguardar('iniciar-sessao');
      httpMock.expectOne({ method: 'POST', url: `${API}/sessoes` }).flush(SESSAO_EM_ANDAMENTO);
      fixture.detectChanges();
      await fixture.whenStable();
      fixture.detectChanges();
    }

    it('abre o canal com o token do aluno ao iniciar a sessão', async () => {
      await comSessaoAtiva();

      expect(telemetria.iniciar).toHaveBeenCalled();
      expect(telemetria.iniciar.calls.mostRecent().args[0]).toBe('token-fake');
    });

    it('alimenta a telemetria com as métricas da captura, não com landmarks', async () => {
      // O segundo argumento é a única porta de entrada de dados no canal: se um
      // dia alguém passar a malha crua por aqui, é neste ponto que aparece.
      // Desde a ticket 10 ele carrega também o veredito de qualidade, que
      // precisa vir do mesmo instante que as métricas.
      await comSessaoAtiva();

      const lerCaptura = telemetria.iniciar.calls.mostRecent().args[1] as () => {
        metricas: unknown;
        incerteza: unknown;
      };
      landmarks.metricas.set(LEITURA);
      landmarks.incerteza.set('baixa-luz');

      expect(lerCaptura().metricas).toBe(LEITURA);
      expect(lerCaptura().incerteza).toBe('baixa-luz');
    });

    it('não abre canal nenhum sem sessão em andamento', () => {
      abrirTela(null);

      expect(telemetria.iniciar).not.toHaveBeenCalled();
    });

    it('fecha o canal ao encerrar a sessão', async () => {
      await comSessaoAtiva();

      clicar('encerrar-sessao');
      httpMock
        .expectOne(`${API}/sessoes/${SESSAO_EM_ANDAMENTO.id}/encerrar`)
        .flush(SESSAO_ENCERRADA);
      fixture.detectChanges();

      expect(telemetria.parar).toHaveBeenCalled();
    });

    it('fecha o canal ao sair', async () => {
      await comSessaoAtiva();

      sair();

      expect(telemetria.parar).toHaveBeenCalled();
    });
  });

  describe('logout', () => {
    it('desloga e volta para /login ao clicar em Sair', () => {
      abrirTela(null);

      clicar('sair');

      expect(authService.estaAutenticado()).toBeFalse();
      expect(navegar).toHaveBeenCalledWith(['/login']);
    });

    it('para o heartbeat ao sair, para ele não sobreviver ao logout', fakeAsync(() => {
      abrirTela(SESSAO_EM_ANDAMENTO);
      flushMicrotasks();
      fixture.detectChanges();

      sair();

      tick(INTERVALO_ATIVIDADE_MS * 2);
      httpMock.expectNone(`${API}/sessoes/${SESSAO_EM_ANDAMENTO.id}/atividade`);
      discardPeriodicTasks();
    }));

    it('encerra a sessão de estudo no backend antes de deslogar', async () => {
      // Sem isto o servidor fecharia a sessão sozinho, mais tarde, marcando-a
      // como interrompida — e o relatório sairia **parcial** para uma sessão que
      // o aluno encerrou deliberadamente ao sair. O encerramento vai antes do
      // logout porque precisa do token, que ainda é válido neste instante.
      await abrirTelaEAguardar(SESSAO_EM_ANDAMENTO);

      clicar('sair');

      httpMock
        .expectOne(`${API}/sessoes/${SESSAO_EM_ANDAMENTO.id}/encerrar`)
        .flush(SESSAO_ENCERRADA);
      expect(authService.estaAutenticado()).toBeFalse();
      expect(navegar).toHaveBeenCalledWith(['/login']);
    });

    it('desloga mesmo quando o backend falha ao encerrar a sessão', async () => {
      // O aluno pediu para sair, e sair é o que acontece. A sessão órfã é
      // varrida depois; um logout que não desloga seria um problema pior que um
      // relatório marcado como parcial.
      await abrirTelaEAguardar(SESSAO_EM_ANDAMENTO);

      sair('falha');

      expect(authService.estaAutenticado()).toBeFalse();
      expect(navegar).toHaveBeenCalledWith(['/login']);
    });

    it('não desloga sozinho: só ao clicar em Sair', async () => {
      await abrirTelaEAguardar(SESSAO_EM_ANDAMENTO);

      expect(authService.estaAutenticado()).toBeTrue();
      expect(navegar).not.toHaveBeenCalled();
    });
  });

  // ==========================================================================
  // Método de estudo, assunto e ciclo (ticket 17)
  // ==========================================================================

  function elemento(teste: string): HTMLElement | null {
    return fixture.nativeElement.querySelector(`[data-teste="${teste}"]`);
  }

  function textoDe(teste: string): string {
    return elemento(teste)?.textContent?.trim() ?? '';
  }

  function campo(teste: string): HTMLInputElement {
    return elemento(teste) as HTMLInputElement;
  }

  function escrever(teste: string, valor: string): void {
    const entrada = campo(teste);
    entrada.value = valor;
    entrada.dispatchEvent(new Event('input'));
    fixture.detectChanges();
  }

  function escolherMetodo(codigo: string): void {
    const escolha = elemento('escolher-metodo') as HTMLSelectElement;
    escolha.value = codigo;
    escolha.dispatchEvent(new Event('change'));
    fixture.detectChanges();
  }

  /**
   * Abre a tela numa sessão que declara método, respondendo a lista de blocos
   * que o servidor tem sobre ela. É o caminho do F5: o estado do bloco corrente
   * vem de `GET /sessoes/{id}/blocos`, nunca da memória da aba.
   */
  /**
   * O sinal de atividade que o `SessaoService` manda de minuto em minuto.
   *
   * Todo teste que avança o relógio um minuto inteiro o encontra pelo caminho —
   * ele é independente do ciclo, e continua batendo enquanto a sessão existe.
   */
  function absorverHeartbeat(): void {
    httpMock
      .expectOne(`${API}/sessoes/${SESSAO_EM_ANDAMENTO.id}/atividade`)
      .flush(SESSAO_EM_ANDAMENTO);
  }

  function abrirCiclo(sessao: Sessao, blocos: Bloco[]): void {
    abrirTela(sessao);
    responderBlocos(sessao, blocos);
    flushMicrotasks();
    fixture.detectChanges();
  }

  describe('declaração do método e do assunto (AC-17-6)', () => {
    it('renderiza o catálogo com os nomes legíveis, nunca os códigos', () => {
      abrirTela(null);

      const escolha = elemento('escolher-metodo') as HTMLSelectElement;
      const rotulos = Array.from(escolha.options).map((opcao) => opcao.textContent!.trim());

      expect(rotulos).toContain('Pomodoro');
      expect(rotulos).toContain('Flow / Deep Work');
      expect(rotulos).toContain('Sem método');

      // Se o rótulo fosse igual ao código, `52-17` apareceria para o aluno — e o
      // `metodo_nome` que o backend devolve estaria sendo ignorado.
      for (const opcao of Array.from(escolha.options)) {
        if (opcao.value !== '') {
          expect(opcao.textContent!.trim()).not.toBe(opcao.value);
        }
      }
    });

    it('leva método, assunto e meta de blocos ao POST /sessoes', async () => {
      abrirTela(null);

      escolherMetodo('pomodoro');
      escrever('campo-assunto', 'Cálculo II, integrais por partes');
      escrever('campo-meta', '4');

      await clicarEAguardar('iniciar-sessao');
      const requisicao = httpMock.expectOne({ method: 'POST', url: `${API}/sessoes` });
      expect(requisicao.request.body).toEqual({
        metodo: 'pomodoro',
        assunto: 'Cálculo II, integrais por partes',
        meta_de_blocos: 4,
      });
      requisicao.flush(SESSAO_COM_POMODORO);
      responderBlocos(SESSAO_COM_POMODORO, [blocoAberto('foco', 1)]);
    });

    it('começa sem declarar nada quando o aluno não preenche nada', async () => {
      // Comportamento protegido: o corpo vazio é o caminho de "Sem método", e é
      // o que as telas anteriores a este recurso mandam.
      abrirTela(null);

      await clicarEAguardar('iniciar-sessao');
      const requisicao = httpMock.expectOne({ method: 'POST', url: `${API}/sessoes` });
      expect(requisicao.request.body).toEqual({});
      requisicao.flush(SESSAO_SEM_METODO);
      fixture.detectChanges();
    });

    it('abre o primeiro bloco de foco assim que a sessão com método começa', async () => {
      // Sem esta declaração, o primeiro bloco só nasceria na primeira pausa — e
      // o relatório perderia a borda de abertura do ciclo inteiro.
      abrirTela(null);
      escolherMetodo('pomodoro');

      await clicarEAguardar('iniciar-sessao');
      httpMock.expectOne({ method: 'POST', url: `${API}/sessoes` }).flush(SESSAO_COM_POMODORO);
      responderBlocos(SESSAO_COM_POMODORO, []);

      const transicao = httpMock.expectOne(`${API}/sessoes/${SESSAO_COM_POMODORO.id}/blocos`);
      expect(transicao.request.body).toEqual({ tipo: 'foco', origem: 'metodo' });
      transicao.flush(blocoAberto('foco', 1));
      fixture.detectChanges();

      expect(textoDe('estado-do-bloco')).toContain('Foco');
    });
  });

  describe('condução do ciclo (AC-17-7)', () => {
    it('mostra o tempo restante do bloco e o desconta com o relógio', fakeAsync(() => {
      abrirCiclo(SESSAO_COM_POMODORO, [blocoAberto('foco', 1)]);

      expect(textoDe('cronometro')).toContain('25min');

      tick(60 * 1000);
      absorverHeartbeat();
      fixture.detectChanges();

      expect(textoDe('cronometro')).toContain('24min');
      discardPeriodicTasks();
    }));

    it('avisa a hora da pausa na virada, e não antes', fakeAsync(() => {
      abrirCiclo(SESSAO_COM_POMODORO, [blocoAberto('foco', 1, 1499)]);

      expect(elemento('aviso-de-pausa')).toBeNull();

      tick(1000);
      fixture.detectChanges();

      expect(textoDe('aviso-de-pausa')).toContain('Hora da pausa');
      discardPeriodicTasks();
    }));

    it('registra a transição para a pausa, com a origem do método', fakeAsync(() => {
      // O cronômetro já tinha zerado quando o aluno declarou: ele seguiu o
      // plano, e é isso que `origem: "metodo"` afirma.
      abrirCiclo(SESSAO_COM_POMODORO, [blocoAberto('foco', 1, 1500)]);

      clicar('transicao-de-bloco');
      const requisicao = httpMock.expectOne(`${API}/sessoes/${SESSAO_COM_POMODORO.id}/blocos`);
      expect(requisicao.request.body).toEqual({ tipo: 'pausa', origem: 'metodo' });
      requisicao.flush(blocoAberto('pausa', 2));
      fixture.detectChanges();

      expect(textoDe('estado-do-bloco')).toContain('Pausa');
      discardPeriodicTasks();
    }));

    it('registra a volta ao foco, e marca como do aluno quando ele antecipa', fakeAsync(() => {
      // A pausa ainda não tinha acabado. A distinção é a única coisa que separa
      // "o método foi seguido" de "o método foi reescrito no meio".
      abrirCiclo(SESSAO_COM_POMODORO, [blocoAberto('pausa', 2, 10)]);

      clicar('transicao-de-bloco');
      const requisicao = httpMock.expectOne(`${API}/sessoes/${SESSAO_COM_POMODORO.id}/blocos`);
      expect(requisicao.request.body).toEqual({ tipo: 'foco', origem: 'aluno' });
      requisicao.flush(blocoAberto('foco', 3));
      fixture.detectChanges();

      expect(textoDe('estado-do-bloco')).toContain('Foco');
      discardPeriodicTasks();
    }));

    it('conta "bloco N de M" quando houve meta declarada', fakeAsync(() => {
      abrirCiclo(SESSAO_COM_POMODORO, [blocoFechado('foco', 1, 1500), blocoAberto('foco', 2)]);

      expect(textoDe('contador-de-blocos')).toBe('bloco 2 de 4');
      discardPeriodicTasks();
    }));

    it('conduz até a pausa longa e aí oferece o encerramento', fakeAsync(() => {
      // O teto desta story: a sessão é um ciclo, mas quem a encerra continua
      // sendo o aluno. O app conduz e oferece; não decide por ele.
      abrirCiclo(SESSAO_COM_POMODORO, [
        blocoFechado('foco', 1, 1500),
        blocoFechado('foco', 2, 1500),
        blocoFechado('foco', 3, 1500),
        blocoAberto('foco', 4, 1500),
      ]);

      expect(textoDe('aviso-de-pausa')).toContain('pausa longa');
      expect(botao('encerrar-sessao')).toBeTruthy();
      discardPeriodicTasks();
    }));
  });

  // ==========================================================================
  // AC-17-8 — a trava.
  //
  // A régua foi reformulada em 21/09/2026: **nada na tela da sessão pode ser
  // derivado do comportamento medido do aluno**. O cronômetro passa porque não
  // tem laço de realimentação — o que ele mostra sai do método declarado e do
  // relógio de parede. Score, IEE, cor avaliativa e qualquer frase sobre o
  // estado interno do aluno, não.
  //
  // Esta trava precisa **poder falhar**. Se ela só checasse a ausência de um
  // `data-teste` conhecido, não protegeria nada: o indicador do futuro viria com
  // um nome que ninguém previu. Por isso ela funciona por inventário — tudo que
  // a tela exibe hoje está listado abaixo, e qualquer elemento a mais é uma
  // violação, mesmo que seu texto pareça inofensivo. O teste seguinte
  // acrescenta um indicador à tela e exige que a trava o pegue; sem ele, não
  // haveria como saber se esta trava mede alguma coisa.
  //
  // ESCOPO: a trava enxerga o que está renderizado dentro do painel da sessão.
  // Ela não sabe o que passa pelo WebSocket (isso é `telemetria.service.spec.ts`)
  // nem o que o relatório mostra depois de encerrar — lá o score é o produto.
  // ==========================================================================

  /** Tudo que a tela da sessão pode exibir hoje. Acrescentar item aqui é uma decisão. */
  const PERMITIDO_NA_TELA_DA_SESSAO = [
    'sessao-em-andamento',
    'encerrar-sessao',
    'preview-webcam',
    'metricas',
    'fps',
    'fps-baixo',
    'incerteza-de-captura',
    'ear',
    'mar',
    'head-pose',
    'sem-rosto',
    'estado-do-bloco',
    'cronometro',
    'contador-de-blocos',
    'aviso-de-pausa',
    'transicao-de-bloco',
  ];

  /** Palavras que só existem se alguém leu a medição para escrevê-las. */
  const VOCABULARIO_DA_MEDICAO = [
    /score/i,
    /\biee\b/i,
    /índice/i,
    /engajament/i,
    /desempenho/i,
    /\bnota\b/i,
    /pontuaç/i,
    /\bpontos\b/i,
    /\bfadiga\b/i,
    /\bbom\b/i,
    /\bruim\b/i,
    /\b[óo]timo\b/i,
    /\bp[ée]ssimo\b/i,
    /parab[ée]ns/i,
    /você est[áa]/i,
    /\d+\s*%/,
  ];

  /** Classes que pintariam um juízo sem escrever uma palavra. */
  const CLASSES_AVALIATIVAS = /(bom|ruim|positiv|negativ|aprovad|reprovad|sucesso)/i;

  const SCORE_CONHECIDO = 73;

  function painelDaSessao(): HTMLElement {
    return preview()!.closest('.painel') as HTMLElement;
  }

  function violacoesDaFronteira(): string[] {
    const painel = painelDaSessao();
    const violacoes: string[] = [];

    painel.querySelectorAll('[data-teste]').forEach((alvo) => {
      const nome = alvo.getAttribute('data-teste')!;
      if (!PERMITIDO_NA_TELA_DA_SESSAO.includes(nome)) {
        violacoes.push(`elemento não previsto na tela da sessão: ${nome}`);
      }
    });

    painel.querySelectorAll('[class]').forEach((alvo) => {
      const classes = alvo.getAttribute('class') ?? '';
      if (CLASSES_AVALIATIVAS.test(classes)) {
        violacoes.push(`classe avaliativa: ${classes}`);
      }
    });

    const conteudo = painel.textContent ?? '';
    if (conteudo.includes(String(SCORE_CONHECIDO))) {
      violacoes.push(`o valor medido (${SCORE_CONHECIDO}) aparece na tela`);
    }
    for (const termo of VOCABULARIO_DA_MEDICAO) {
      if (termo.test(conteudo)) {
        violacoes.push(`vocabulário derivado da medição: ${termo}`);
      }
    }

    return violacoes;
  }

  describe('nada na tela vem da medição (AC-17-8)', () => {
    /** A tela mais cheia que existe: sessão conduzida, com rosto e com score. */
    function sessaoMedindo(): void {
      abrirCiclo(SESSAO_COM_POMODORO, [blocoFechado('foco', 1, 1500), blocoAberto('foco', 2, 600)]);

      telemetria.score.set(SCORE_CONHECIDO);
      landmarks.metricas.set(LEITURA);
      landmarks.fps.set(30);
      fixture.detectChanges();
    }

    it('não exibe score, indicador nem juízo enquanto o aluno estuda', fakeAsync(() => {
      sessaoMedindo();

      expect(violacoesDaFronteira()).toEqual([]);
      discardPeriodicTasks();
    }));

    it('a trava quebra se alguém acrescentar um indicador à tela', fakeAsync(() => {
      // O ponto inteiro da trava acima. Sem este teste, ela poderia estar
      // passando por não medir nada — e ninguém descobriria até o indicador
      // chegar à tela do aluno.
      sessaoMedindo();
      expect(violacoesDaFronteira()).toEqual([]);

      const intruso = document.createElement('p');
      intruso.setAttribute('data-teste', 'indicador-de-engajamento');
      intruso.textContent = `Seu IEE agora: ${SCORE_CONHECIDO}`;
      painelDaSessao().appendChild(intruso);

      expect(violacoesDaFronteira().length).toBeGreaterThan(0);
      discardPeriodicTasks();
    }));

    it('continua mostrando o que o aluno pode resolver agora', fakeAsync(() => {
      // A fronteira não é "a tela fica vazia". Preview, FPS e alerta de
      // incerteza continuam lá: são diagnóstico do equipamento, e a única coisa
      // a respeito da qual ele pode agir enquanto estuda.
      sessaoMedindo();
      telemetria.incerteza.set('baixa-luz');
      fixture.detectChanges();

      expect(preview()).toBeTruthy();
      expect(texto()).toContain('30 FPS');
      expect(elemento('incerteza-de-captura')).toBeTruthy();
      discardPeriodicTasks();
    }));
  });

  describe('casos de borda do ciclo', () => {
    it('E1: catálogo indisponível não impede começar a estudar', async () => {
      abrirTela(null, 'falha');

      expect(elemento('escolher-metodo')).toBeNull();
      expect(textoDe('catalogo-indisponivel')).toContain('sem método declarado');

      await clicarEAguardar('iniciar-sessao');
      const requisicao = httpMock.expectOne({ method: 'POST', url: `${API}/sessoes` });
      expect(requisicao.request.body).toEqual({});
      requisicao.flush(SESSAO_SEM_METODO);
      fixture.detectChanges();

      expect(botao('encerrar-sessao')).toBeTruthy();
    });

    it('E2: método sem duração prescrita não ganha cronômetro nem aviso', fakeAsync(() => {
      // Flow não prescreve bloco. Mostrar "00:00" ou contar os cinco minutos do
      // `pausa_s` seria o app prescrevendo o que o método recusa a prescrever.
      abrirCiclo(SESSAO_COM_FLOW, [blocoAberto('foco', 1, 3600)]);

      expect(textoDe('estado-do-bloco')).toContain('Foco');
      expect(elemento('cronometro')).toBeNull();
      expect(elemento('aviso-de-pausa')).toBeNull();
      discardPeriodicTasks();
    }));

    it('E3: depois do F5 o cronômetro vem do servidor, não do zero', fakeAsync(() => {
      // Dez minutos de bloco já corridos quando a página recarregou. Se o estado
      // viesse da aba, o bloco reiniciaria — e o aluno aprenderia a não
      // recarregar, que é a pior correção possível.
      abrirCiclo(SESSAO_COM_POMODORO, [blocoAberto('foco', 1, 600)]);

      expect(textoDe('cronometro')).toContain('15min');
      discardPeriodicTasks();
    }));

    it('E4: sessão anterior ao recurso é retomada sem ciclo nenhum', async () => {
      // `metodo IS NULL` é "esta sessão é anterior ao recurso". Abrir um bloco
      // nela agora lhe daria um bloco que nunca existiu, começando no meio.
      // O `httpMock.verify()` do afterEach é quem garante que nem o GET de
      // blocos foi disparado.
      await abrirTelaEAguardar(SESSAO_SEM_METODO);

      expect(botao('encerrar-sessao')).toBeTruthy();
      expect(elemento('estado-do-bloco')).toBeNull();
      expect(elemento('cronometro')).toBeNull();
      expect(elemento('contador-de-blocos')).toBeNull();
    });

    it('E5: transição perdida na rede é reapresentada', fakeAsync(() => {
      // O servidor absorve a repetição (200, idempotente por tipo). Retentar é
      // seguro; perder a borda do bloco não é.
      abrirCiclo(SESSAO_COM_POMODORO, [blocoAberto('foco', 1, 1500)]);

      clicar('transicao-de-bloco');
      httpMock
        .expectOne(`${API}/sessoes/${SESSAO_COM_POMODORO.id}/blocos`)
        .flush({}, { status: 503, statusText: 'Service Unavailable' });

      tick(ESPERA_PARA_RETENTAR_MS);
      const retentativa = httpMock.expectOne(`${API}/sessoes/${SESSAO_COM_POMODORO.id}/blocos`);
      expect(retentativa.request.body).toEqual({ tipo: 'pausa', origem: 'metodo' });
      retentativa.flush(blocoAberto('pausa', 2));
      fixture.detectChanges();

      expect(textoDe('estado-do-bloco')).toContain('Pausa');
      discardPeriodicTasks();
    }));

    it('E6: o assunto para no teto de 120 caracteres antes do POST', async () => {
      abrirTela(null);

      escrever('campo-assunto', 'a'.repeat(120));
      expect(campo('campo-assunto').value.length).toBe(120);

      escrever('campo-assunto', 'b'.repeat(121));
      expect(campo('campo-assunto').value.length).toBe(120);

      await clicarEAguardar('iniciar-sessao');
      const requisicao = httpMock.expectOne({ method: 'POST', url: `${API}/sessoes` });
      expect((requisicao.request.body as { assunto: string }).assunto.length).toBe(120);
      requisicao.flush(SESSAO_SEM_METODO);
      fixture.detectChanges();
    });

    it('E7: bloco estourado mantém o aviso e não conta para o negativo', fakeAsync(() => {
      abrirCiclo(SESSAO_COM_POMODORO, [blocoAberto('foco', 1, 1500 + 300)]);

      expect(textoDe('cronometro')).toBe('0s');
      expect(textoDe('aviso-de-pausa')).toContain('Hora da pausa');

      tick(60 * 1000);
      absorverHeartbeat();
      fixture.detectChanges();

      expect(textoDe('cronometro')).toBe('0s');
      expect(textoDe('aviso-de-pausa')).toContain('Hora da pausa');
      discardPeriodicTasks();
    }));

    it('E8: sem meta declarada não há "bloco 2 de 4"', fakeAsync(() => {
      // Sem denominador declarado não há denominador. Inventá-lo é o primeiro
      // passo para o boletim que este produto existe para não emitir.
      abrirCiclo({ ...SESSAO_COM_POMODORO, meta_de_blocos: null }, [
        blocoFechado('foco', 1, 1500),
        blocoAberto('foco', 2),
      ]);

      expect(elemento('cronometro')).toBeTruthy();
      expect(elemento('contador-de-blocos')).toBeNull();
      discardPeriodicTasks();
    }));
  });
});
