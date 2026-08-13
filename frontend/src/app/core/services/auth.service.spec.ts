import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideHttpClient } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';

import { AuthService } from './auth.service';

describe('AuthService', () => {
  let service: AuthService;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    service = TestBed.inject(AuthService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
    localStorage.clear();
  });

  it('não está autenticado quando não há token armazenado', () => {
    expect(service.estaAutenticado()).toBeFalse();
  });

  it('armazena o token e passa a reportar autenticado após login', () => {
    service.login({ email: 'ana@exemplo.com', senha: 'senhaSegura123' }).subscribe();

    const requisicao = httpMock.expectOne('http://localhost:8000/auth/login');
    expect(requisicao.request.method).toBe('POST');
    requisicao.flush({ access_token: 'token-fake', token_type: 'bearer' });

    expect(service.estaAutenticado()).toBeTrue();
    expect(service.getToken()).toBe('token-fake');
    expect(localStorage.getItem('iee_access_token')).toBe('token-fake');
  });

  it('remove o token e reporta não autenticado após logout', () => {
    service.login({ email: 'ana@exemplo.com', senha: 'senhaSegura123' }).subscribe();
    httpMock
      .expectOne('http://localhost:8000/auth/login')
      .flush({ access_token: 'token-fake', token_type: 'bearer' });

    service.logout();

    expect(service.estaAutenticado()).toBeFalse();
    expect(localStorage.getItem('iee_access_token')).toBeNull();
  });

  it('envia os dados corretos para o endpoint de registro', () => {
    const payload = { nome: 'Ana', email: 'ana@exemplo.com', senha: 'senhaSegura123' };
    service.registrar(payload).subscribe();

    const requisicao = httpMock.expectOne('http://localhost:8000/auth/registro');
    expect(requisicao.request.method).toBe('POST');
    expect(requisicao.request.body).toEqual(payload);
    requisicao.flush({});
  });

  it('reidrata o estado de autenticação a partir do localStorage já ao construir o serviço', () => {
    localStorage.setItem('iee_access_token', 'token-existente');

    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    const novoServico = TestBed.inject(AuthService);

    expect(novoServico.estaAutenticado()).toBeTrue();
    expect(novoServico.getToken()).toBe('token-existente');
  });
});
