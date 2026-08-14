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
import { INTERVALO_ATIVIDADE_MS, Sessao } from '../../core/services/sessao.service';
import { LandmarksService } from '../../core/visao/landmarks.service';
import { MetricasFaciais } from '../../core/visao/metricas';
import { HomeComponent } from './home.component';

const API = 'http://localhost:8000';

const SESSAO_EM_ANDAMENTO: Sessao = {
  id: 7,
  id_aluno: 1,
  inicio: '2026-08-13T12:00:00Z',
  fim: null,
};

const SESSAO_ENCERRADA: Sessao = { ...SESSAO_EM_ANDAMENTO, fim: '2026-08-13T12:30:00Z' };

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
  readonly rostoDetectado = signal(false);

  ativo = false;

  readonly iniciar = jasmine.createSpy('iniciar').and.callFake(async () => {
    this.ativo = true;
  });

  readonly parar = jasmine.createSpy('parar').and.callFake(() => {
    this.ativo = false;
    this.metricas.set(null);
    this.fps.set(0);
    this.rostoDetectado.set(false);
  });
}

const LEITURA: MetricasFaciais = {
  ear: 0.284,
  mar: 0.052,
  cabeca: { yaw: -4.2, pitch: 7.1, roll: 0.5 },
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

  /** Resolve o GET disparado no ngOnInit e renderiza o resultado. */
  function abrirTela(sessao: Sessao | null): void {
    fixture.detectChanges();
    httpMock.expectOne(`${API}/sessoes/ativa`).flush(sessao);
    fixture.detectChanges();
  }

  /** `abrirTela`, mas esperando a retomada da captura quando há sessão viva. */
  async function abrirTelaEAguardar(sessao: Sessao | null): Promise<void> {
    abrirTela(sessao);
    await fixture.whenStable();
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
      ],
    }).compileComponents();

    httpMock = TestBed.inject(HttpTestingController);
    authService = TestBed.inject(AuthService);
    landmarks = TestBed.inject(LandmarksService) as unknown as LandmarksServiceFalso;
    navegar = spyOn(TestBed.inject(Router), 'navigate').and.resolveTo(true);

    getUserMedia = jasmine.createSpy('getUserMedia').and.callFake(() =>
      Promise.resolve(streamDeTeste()),
    );
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

    it('ressincroniza a tela quando o backend responde que já há sessão em andamento', async () => {
      // Cenário de duas abas: a aba antiga precisa passar a oferecer "Encerrar",
      // em vez de ficar travada num "Iniciar" que sempre falha.
      abrirTela(null);

      await clicarEAguardar('iniciar-sessao');
      httpMock.expectOne({ method: 'POST', url: `${API}/sessoes` }).flush(
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

      clicar('sair');

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
      httpMock.expectOne(`${API}/sessoes/${SESSAO_EM_ANDAMENTO.id}/atividade`).flush(
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
      httpMock.expectOne(`${API}/sessoes/${SESSAO_EM_ANDAMENTO.id}/atividade`).flush(
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
      // O critério final da ticket 5, e a promessa central do projeto. Até a
      // ticket 6 nada de telemetria trafega; e mesmo depois, o que sobe são
      // métricas agregadas, nunca imagem. Este teste trava a régua: durante uma
      // sessão ativa, as únicas requisições são de ciclo de vida da sessão, e
      // nenhuma delas carrega corpo.
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

      clicar('sair');

      tick(INTERVALO_ATIVIDADE_MS * 2);
      httpMock.expectNone(`${API}/sessoes/${SESSAO_EM_ANDAMENTO.id}/atividade`);
      discardPeriodicTasks();
    }));

    it('não desloga sozinho: só ao clicar em Sair', async () => {
      await abrirTelaEAguardar(SESSAO_EM_ANDAMENTO);

      expect(authService.estaAutenticado()).toBeTrue();
      expect(navegar).not.toHaveBeenCalled();
    });
  });
});
