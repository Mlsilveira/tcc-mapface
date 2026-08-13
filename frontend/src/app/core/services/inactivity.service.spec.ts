import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { discardPeriodicTasks, fakeAsync, TestBed, tick } from '@angular/core/testing';
import { Router } from '@angular/router';

import { AuthService } from './auth.service';
import { InactivityService, TEMPO_LIMITE_INATIVIDADE_MS } from './inactivity.service';
import { SessaoService } from './sessao.service';

const API = 'http://localhost:8000';

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

  it('esquece a sessão de estudo ao deslogar por inatividade', fakeAsync(() => {
    // Sem isso o heartbeat seguiria batendo no backend depois do logout.
    sessaoService.iniciar().subscribe();
    httpMock
      .expectOne({ method: 'POST', url: `${API}/sessoes` })
      .flush({ id: 7, id_aluno: 1, inicio: '2026-08-13T12:00:00Z', fim: null });
    service.iniciarMonitoramento();

    tick(TEMPO_LIMITE_INATIVIDADE_MS);

    expect(sessaoService.sessaoAtiva()).toBeNull();
    // Drena os heartbeats disparados antes do logout — nenhum deles reanima a
    // sessão, porque só o caminho de erro mexe no estado.
    httpMock.match((r) => r.url.includes('/atividade')).forEach((r) => r.flush({}));
    discardPeriodicTasks();
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
