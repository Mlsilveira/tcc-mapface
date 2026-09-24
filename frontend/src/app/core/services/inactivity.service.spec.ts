import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { discardPeriodicTasks, fakeAsync, TestBed, tick } from '@angular/core/testing';
import { Router } from '@angular/router';

import { API_URL as API } from '../api';
import { AuthService } from './auth.service';
import { InactivityService, TEMPO_LIMITE_INATIVIDADE_MS } from './inactivity.service';
import { SessaoService } from './sessao.service';


describe('InactivityService', () => {
  let service: InactivityService;
  let authServiceSpy: jasmine.SpyObj<AuthService>;
  let sessaoService: SessaoService;
  let httpMock: HttpTestingController;
  let routerSpy: jasmine.SpyObj<Router>;

  beforeEach(() => {
    authServiceSpy = jasmine.createSpyObj('AuthService', ['logout']);
    routerSpy = jasmine.createSpyObj('Router', ['navigate']);

    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: AuthService, useValue: authServiceSpy },
        { provide: Router, useValue: routerSpy },
      ],
    });
    service = TestBed.inject(InactivityService);
    sessaoService = TestBed.inject(SessaoService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => service.pararMonitoramento());

  it('encerra a sessão automaticamente após o tempo limite de inatividade', fakeAsync(() => {
    service.iniciarMonitoramento();

    tick(TEMPO_LIMITE_INATIVIDADE_MS);

    expect(authServiceSpy.logout).toHaveBeenCalled();
    expect(routerSpy.navigate).toHaveBeenCalledWith(['/login'], {
      queryParams: { motivo: 'inatividade' },
    });
  }));

  /** Abre uma sessão de estudo e deixa o `effect` de suspensão rodar. */
  function comSessaoDeEstudo(): void {
    sessaoService.iniciar().subscribe();
    httpMock
      .expectOne({ method: 'POST', url: `${API}/sessoes` })
      .flush({ id: 7, id_aluno: 1, inicio: '2026-08-13T12:00:00Z', fim: null });
    TestBed.flushEffects();
  }

  /** Drena os heartbeats do `SessaoService`, que não são o objeto destes testes. */
  function drenarHeartbeats(): void {
    httpMock.match((r) => r.url.includes('/atividade')).forEach((r) => r.flush({}));
    discardPeriodicTasks();
  }

  it('não desloga enquanto houver sessão de estudo em andamento', fakeAsync(() => {
    // A troca central do recurso: durante o estudo, quem responde "tem alguém
    // aqui?" é a câmera, não o teclado. Ler um livro por vinte minutos em frente
    // à webcam era exatamente o que este serviço deslogava — e é o
    // comportamento que o produto quer incentivar. Pior: ele derrubava quem
    // fazia a pausa longa que o método de estudo prescreve.
    service.iniciarMonitoramento();
    comSessaoDeEstudo();

    tick(TEMPO_LIMITE_INATIVIDADE_MS * 2);

    expect(authServiceSpy.logout).not.toHaveBeenCalled();
    expect(sessaoService.sessaoAtiva()).not.toBeNull();
    drenarHeartbeats();
  }));

  it('volta a contar quando a sessão de estudo termina', fakeAsync(() => {
    // Suspender sem retomar seria pior que não suspender: a aba ficaria
    // autenticada para sempre depois da primeira sessão do dia.
    service.iniciarMonitoramento();
    comSessaoDeEstudo();
    tick(TEMPO_LIMITE_INATIVIDADE_MS);
    expect(authServiceSpy.logout).not.toHaveBeenCalled();

    sessaoService.esquecerSessao();
    TestBed.flushEffects();
    tick(TEMPO_LIMITE_INATIVIDADE_MS);

    expect(authServiceSpy.logout).toHaveBeenCalled();
    drenarHeartbeats();
  }));

  it('o relógio recomeça do zero quando a sessão termina', fakeAsync(() => {
    // Quem acabou de encerrar uma sessão de estudo merece os 15 minutos
    // inteiros: retomar de onde parou deslogaria alguém que estava ali agora.
    service.iniciarMonitoramento();
    comSessaoDeEstudo();
    tick(TEMPO_LIMITE_INATIVIDADE_MS * 3);

    sessaoService.esquecerSessao();
    TestBed.flushEffects();
    tick(TEMPO_LIMITE_INATIVIDADE_MS - 1000);

    expect(authServiceSpy.logout).not.toHaveBeenCalled();
    // O temporizador rearmado ainda está na fila — `discardPeriodicTasks` só
    // cuida de `setInterval`, e este é um `setTimeout`.
    service.pararMonitoramento();
    drenarHeartbeats();
  }));

  it('esquece a sessão de estudo ao deslogar por inatividade', fakeAsync(() => {
    // Só se chega ao logout por inatividade **sem** sessão aberta — com sessão,
    // o relógio está suspenso. Mas o estado local precisa ser limpo do mesmo
    // jeito: sem isso, a tela do próximo a logar mostraria a sessão do anterior.
    service.iniciarMonitoramento();

    tick(TEMPO_LIMITE_INATIVIDADE_MS);

    expect(sessaoService.sessaoAtiva()).toBeNull();
    expect(authServiceSpy.logout).toHaveBeenCalled();
  }));

  it('reinicia o temporizador quando há atividade do usuário, adiando o logout', fakeAsync(() => {
    service.iniciarMonitoramento();

    tick(TEMPO_LIMITE_INATIVIDADE_MS - 1000);
    window.dispatchEvent(new Event('mousemove'));
    tick(TEMPO_LIMITE_INATIVIDADE_MS - 1000);

    expect(authServiceSpy.logout).not.toHaveBeenCalled();

    tick(1000 + 1);
    expect(authServiceSpy.logout).toHaveBeenCalled();
  }));

  it('não agenda um segundo temporizador se iniciarMonitoramento for chamado novamente', fakeAsync(() => {
    service.iniciarMonitoramento();
    service.iniciarMonitoramento();

    tick(TEMPO_LIMITE_INATIVIDADE_MS);

    expect(authServiceSpy.logout).toHaveBeenCalledTimes(1);
  }));

  it('para de escutar eventos e cancela o temporizador ao parar o monitoramento', fakeAsync(() => {
    service.iniciarMonitoramento();
    service.pararMonitoramento();

    tick(TEMPO_LIMITE_INATIVIDADE_MS);

    expect(authServiceSpy.logout).not.toHaveBeenCalled();
  }));
});
