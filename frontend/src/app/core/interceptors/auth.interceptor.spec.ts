import { HttpClient, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { of, throwError } from 'rxjs';

import { AuthService } from '../services/auth.service';
import { tokenQueVenceEm } from '../services/auth.service.spec';
import { authInterceptor } from './auth.interceptor';

describe('authInterceptor', () => {
  let http: HttpClient;
  let httpMock: HttpTestingController;
  let authServiceSpy: jasmine.SpyObj<AuthService>;

  beforeEach(() => {
    authServiceSpy = jasmine.createSpyObj('AuthService', [
      'getToken',
      'credencialPertoDeExpirar',
      'renovar',
    ]);
    authServiceSpy.credencialPertoDeExpirar.and.returnValue(false);

    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptors([authInterceptor])),
        provideHttpClientTesting(),
        { provide: AuthService, useValue: authServiceSpy },
      ],
    });

    http = TestBed.inject(HttpClient);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => httpMock.verify());

  it('anexa o token como Bearer quando o usuário está autenticado', () => {
    authServiceSpy.getToken.and.returnValue('token-fake');

    http.get('/qualquer-recurso').subscribe();

    const requisicao = httpMock.expectOne('/qualquer-recurso');
    expect(requisicao.request.headers.get('Authorization')).toBe('Bearer token-fake');
    requisicao.flush({});
  });

  it('não envia header de autorização quando não há token', () => {
    authServiceSpy.getToken.and.returnValue(null);

    http.get('/qualquer-recurso').subscribe();

    const requisicao = httpMock.expectOne('/qualquer-recurso');
    expect(requisicao.request.headers.has('Authorization')).toBeFalse();
    requisicao.flush({});
  });

  it('preserva os headers que a requisição já trazia', () => {
    authServiceSpy.getToken.and.returnValue('token-fake');

    http.get('/qualquer-recurso', { headers: { 'X-Origem': 'teste' } }).subscribe();

    const requisicao = httpMock.expectOne('/qualquer-recurso');
    expect(requisicao.request.headers.get('X-Origem')).toBe('teste');
    expect(requisicao.request.headers.get('Authorization')).toBe('Bearer token-fake');
    requisicao.flush({});
  });
});

describe('authInterceptor — renovação proativa', () => {
  let http: HttpClient;
  let httpMock: HttpTestingController;
  let authServiceSpy: jasmine.SpyObj<AuthService>;

  beforeEach(() => {
    authServiceSpy = jasmine.createSpyObj('AuthService', [
      'getToken',
      'credencialPertoDeExpirar',
      'renovar',
    ]);
    authServiceSpy.getToken.and.returnValue('token-velho');

    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptors([authInterceptor])),
        provideHttpClientTesting(),
        { provide: AuthService, useValue: authServiceSpy },
      ],
    });

    http = TestBed.inject(HttpClient);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => httpMock.verify());

  it('renova antes de despachar quando a credencial está perto de vencer', () => {
    authServiceSpy.credencialPertoDeExpirar.and.returnValue(true);
    authServiceSpy.renovar.and.returnValue(of('token-novo'));

    http.get('/qualquer-recurso').subscribe();

    const requisicao = httpMock.expectOne('/qualquer-recurso');
    expect(requisicao.request.headers.get('Authorization')).toBe('Bearer token-novo');
    requisicao.flush({});
  });

  it('não renova enquanto a credencial tem folga', () => {
    authServiceSpy.credencialPertoDeExpirar.and.returnValue(false);

    http.get('/qualquer-recurso').subscribe();

    expect(authServiceSpy.renovar).not.toHaveBeenCalled();
    httpMock.expectOne('/qualquer-recurso').flush({});
  });

  it('não avalia renovação para a própria requisição de renovação', () => {
    // A requisição de renovação passa por este interceptor como qualquer outra.
    // Se ela também fosse avaliada, cada renovação dispararia outra,
    // indefinidamente.
    authServiceSpy.credencialPertoDeExpirar.and.returnValue(true);

    http.post('http://localhost:8000/auth/renovar', {}).subscribe();

    expect(authServiceSpy.renovar).not.toHaveBeenCalled();
    const requisicao = httpMock.expectOne('http://localhost:8000/auth/renovar');
    expect(requisicao.request.headers.get('Authorization')).toBe('Bearer token-velho');
    requisicao.flush({ access_token: 'token-novo', token_type: 'bearer' });
  });

  it('despacha com o token antigo quando a renovação falha', () => {
    // A renovação dispara antes do vencimento, então o token antigo ainda vale.
    // Quem tem autoridade para dizer que uma credencial acabou é o servidor —
    // o cliente não inventa um caminho de erro próprio.
    authServiceSpy.credencialPertoDeExpirar.and.returnValue(true);
    authServiceSpy.renovar.and.returnValue(throwError(() => new Error('teto atingido')));

    http.get('/qualquer-recurso').subscribe();

    const requisicao = httpMock.expectOne('/qualquer-recurso');
    expect(requisicao.request.headers.get('Authorization')).toBe('Bearer token-velho');
    requisicao.flush({});
  });
});

describe('authInterceptor — com o AuthService de verdade', () => {
  let http: HttpClient;
  let httpMock: HttpTestingController;

  const TOKEN_NOVO = tokenQueVenceEm(30 * 60);

  beforeEach(() => {
    localStorage.clear();
    // Dois minutos para vencer: dentro da margem de renovação de cinco minutos.
    localStorage.setItem('iee_access_token', tokenQueVenceEm(2 * 60));

    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptors([authInterceptor])),
        provideHttpClientTesting(),
      ],
    });

    http = TestBed.inject(HttpClient);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
    localStorage.clear();
  });

  it('atende várias requisições simultâneas com uma renovação só', () => {
    // O caso real: perto do vencimento, o heartbeat da sessão e um clique do
    // aluno saem quase juntos. Cada um passa pelo interceptor, e sem a
    // deduplicação do AuthService seriam duas renovações concorrentes — a
    // segunda invalidando o token que a primeira acabou de armazenar.
    const tokenAntigo = localStorage.getItem('iee_access_token');

    http.get('/recurso-a').subscribe();
    http.get('/recurso-b').subscribe();

    const renovacoes = httpMock.match('http://localhost:8000/auth/renovar');
    expect(renovacoes.length).toBe(1);
    expect(renovacoes[0].request.headers.get('Authorization')).toBe(`Bearer ${tokenAntigo}`);
    renovacoes[0].flush({ access_token: TOKEN_NOVO, token_type: 'bearer' });

    const a = httpMock.expectOne('/recurso-a');
    const b = httpMock.expectOne('/recurso-b');
    expect(a.request.headers.get('Authorization')).toBe(`Bearer ${TOKEN_NOVO}`);
    expect(b.request.headers.get('Authorization')).toBe(`Bearer ${TOKEN_NOVO}`);
    a.flush({});
    b.flush({});
  });
});
