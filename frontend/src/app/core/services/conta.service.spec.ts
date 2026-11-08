import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { API_URL } from '../api';
import { VERSAO_TERMO } from '../consentimento/termo';
import { AuthService } from './auth.service';
import { ContaService } from './conta.service';

describe('ContaService', () => {
  let service: ContaService;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    service = TestBed.inject(ContaService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
    localStorage.clear();
  });

  it('envia o aceite da versão atual do termo', () => {
    service.aceitarTermo().subscribe();

    const requisicao = httpMock.expectOne(`${API_URL}/auth/consentimento`);
    expect(requisicao.request.method).toBe('POST');
    expect(requisicao.request.body).toEqual({
      aceitou_termo: true,
      declarou_maioridade: true,
      versao_termo: VERSAO_TERMO,
    });
    requisicao.flush({});
  });

  it('revoga com DELETE em /auth/consentimento', () => {
    service.revogar().subscribe();

    const requisicao = httpMock.expectOne(`${API_URL}/auth/consentimento`);
    expect(requisicao.request.method).toBe('DELETE');
    requisicao.flush({});
  });

  it('manda a senha no corpo da exclusão', () => {
    service.excluir('minha-senha').subscribe();

    const requisicao = httpMock.expectOne(`${API_URL}/auth/conta`);
    expect(requisicao.request.method).toBe('DELETE');
    expect(requisicao.request.body).toEqual({ senha: 'minha-senha' });
    requisicao.flush(null);
  });

  it('adota o token novo quando corrigir o e-mail troca a credencial', () => {
    service.corrigir({ email: 'nova@exemplo.com' }).subscribe();

    httpMock.expectOne(`${API_URL}/auth/me`).flush({ access_token: 'token-novo' });

    expect(TestBed.inject(AuthService).getToken()).toBe('token-novo');
  });

  it('mantém o token atual quando só o nome muda', () => {
    TestBed.inject(AuthService).armazenarToken('token-atual');

    service.corrigir({ nome: 'Ana' }).subscribe();
    httpMock.expectOne(`${API_URL}/auth/me`).flush({ access_token: null });

    expect(TestBed.inject(AuthService).getToken()).toBe('token-atual');
  });
});
