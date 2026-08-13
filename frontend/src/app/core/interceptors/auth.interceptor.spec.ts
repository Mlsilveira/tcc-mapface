import { HttpClient, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { AuthService } from '../services/auth.service';
import { authInterceptor } from './auth.interceptor';

describe('authInterceptor', () => {
  let http: HttpClient;
  let httpMock: HttpTestingController;
  let authServiceSpy: jasmine.SpyObj<AuthService>;

  beforeEach(() => {
    authServiceSpy = jasmine.createSpyObj('AuthService', ['getToken']);

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
