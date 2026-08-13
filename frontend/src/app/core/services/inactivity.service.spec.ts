import { fakeAsync, TestBed, tick } from '@angular/core/testing';
import { Router } from '@angular/router';

import { AuthService } from './auth.service';
import { InactivityService, TEMPO_LIMITE_INATIVIDADE_MS } from './inactivity.service';
import { SessaoService } from './sessao.service';

describe('InactivityService', () => {
  let service: InactivityService;
  let authServiceSpy: jasmine.SpyObj<AuthService>;
  let sessaoServiceSpy: jasmine.SpyObj<SessaoService>;
  let routerSpy: jasmine.SpyObj<Router>;

  beforeEach(() => {
    authServiceSpy = jasmine.createSpyObj('AuthService', ['logout']);
    sessaoServiceSpy = jasmine.createSpyObj('SessaoService', ['esquecerSessao']);
    routerSpy = jasmine.createSpyObj('Router', ['navigate']);

    TestBed.configureTestingModule({
      providers: [
        { provide: AuthService, useValue: authServiceSpy },
        { provide: SessaoService, useValue: sessaoServiceSpy },
        { provide: Router, useValue: routerSpy },
      ],
    });
    service = TestBed.inject(InactivityService);
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
    service.iniciarMonitoramento();

    tick(TEMPO_LIMITE_INATIVIDADE_MS);

    expect(sessaoServiceSpy.esquecerSessao).toHaveBeenCalled();
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
