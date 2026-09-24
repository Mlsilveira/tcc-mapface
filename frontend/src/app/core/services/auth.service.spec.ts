import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideHttpClient } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';

import { API_URL } from '../api';
import { AuthService, MARGEM_DE_RENOVACAO_MS } from './auth.service';

/**
 * Um JWT com assinatura de mentira e `exp` de verdade.
 *
 * O cliente nunca verifica assinatura — quem faz isso é o servidor, a cada
 * request. O que ele lê do token é só o vencimento, e é isso que estes testes
 * precisam controlar.
 */
export function tokenQueVenceEm(segundos: number): string {
  const payload = { sub: 'ana@exemplo.com', exp: Math.floor(Date.now() / 1000) + segundos };
  const corpo = btoa(JSON.stringify(payload))
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '');
  return `cabecalho.${corpo}.assinatura`;
}

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

    const requisicao = httpMock.expectOne(`${API_URL}/auth/login`);
    expect(requisicao.request.method).toBe('POST');
    requisicao.flush({ access_token: 'token-fake', token_type: 'bearer' });

    expect(service.estaAutenticado()).toBeTrue();
    expect(service.getToken()).toBe('token-fake');
    expect(localStorage.getItem('iee_access_token')).toBe('token-fake');
  });

  it('remove o token e reporta não autenticado após logout', () => {
    service.login({ email: 'ana@exemplo.com', senha: 'senhaSegura123' }).subscribe();
    httpMock
      .expectOne(`${API_URL}/auth/login`)
      .flush({ access_token: 'token-fake', token_type: 'bearer' });

    service.logout();

    expect(service.estaAutenticado()).toBeFalse();
    expect(localStorage.getItem('iee_access_token')).toBeNull();
  });

  it('envia os dados corretos para o endpoint de registro', () => {
    const payload = { nome: 'Ana', email: 'ana@exemplo.com', senha: 'senhaSegura123' };
    service.registrar(payload).subscribe();

    const requisicao = httpMock.expectOne(`${API_URL}/auth/registro`);
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

describe('AuthService — renovação de credencial', () => {
  let service: AuthService;
  let httpMock: HttpTestingController;

  /**
   * A margem é derivada do heartbeat de 60 s com folga para quatro batidas
   * perdidas. Os testes abaixo usam essa definição em vez do número cru: um
   * token que vence em metade da margem está dentro, e um que vence no dobro
   * dela está fora.
   */
  const METADE_DA_MARGEM_S = MARGEM_DE_RENOVACAO_MS / 1000 / 2;
  const DOBRO_DA_MARGEM_S = (MARGEM_DE_RENOVACAO_MS / 1000) * 2;

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

  function comToken(token: string): void {
    service.login({ email: 'ana@exemplo.com', senha: 'senhaSegura123' }).subscribe();
    httpMock
      .expectOne(`${API_URL}/auth/login`)
      .flush({ access_token: token, token_type: 'bearer' });
  }

  it('pede renovação quando falta menos que a margem para o vencimento', () => {
    comToken(tokenQueVenceEm(METADE_DA_MARGEM_S));

    expect(service.credencialPertoDeExpirar()).toBeTrue();
  });

  it('não pede renovação enquanto sobra mais que a margem', () => {
    comToken(tokenQueVenceEm(DOBRO_DA_MARGEM_S));

    expect(service.credencialPertoDeExpirar()).toBeFalse();
  });

  it('não pede renovação para token já vencido', () => {
    // Não há o que renovar: o servidor recusa token expirado de propósito, para
    // que um token roubado não vire credencial permanente. Tentar assim mesmo
    // poria um request condenado na frente de cada request do aluno.
    comToken(tokenQueVenceEm(-60));

    expect(service.credencialPertoDeExpirar()).toBeFalse();
  });

  it('não pede renovação para token ilegível', () => {
    comToken('isto-nao-e-um-jwt');

    expect(service.credencialPertoDeExpirar()).toBeFalse();
  });

  it('guarda o token devolvido pela renovação', () => {
    comToken(tokenQueVenceEm(METADE_DA_MARGEM_S));
    const novo = tokenQueVenceEm(DOBRO_DA_MARGEM_S);

    service.renovar().subscribe();
    httpMock
      .expectOne(`${API_URL}/auth/renovar`)
      .flush({ access_token: novo, token_type: 'bearer' });

    expect(service.getToken()).toBe(novo);
    expect(localStorage.getItem('iee_access_token')).toBe(novo);
  });

  it('atende chamadas simultâneas com uma única requisição de renovação', () => {
    // Perto do vencimento o heartbeat, o canal de telemetria e um clique do
    // aluno saem quase juntos. Sem compartilhar a requisição em voo, cada um
    // emitiria um token novo e o último sobrescreveria os anteriores — com a
    // chance real de uma requisição já despachada levar um token que deixou de
    // ser o armazenado.
    comToken(tokenQueVenceEm(METADE_DA_MARGEM_S));
    const novo = tokenQueVenceEm(DOBRO_DA_MARGEM_S);
    const recebidos: string[] = [];

    service.renovar().subscribe((token) => recebidos.push(token));
    service.renovar().subscribe((token) => recebidos.push(token));
    service.renovar().subscribe((token) => recebidos.push(token));

    httpMock
      .expectOne(`${API_URL}/auth/renovar`)
      .flush({ access_token: novo, token_type: 'bearer' });

    expect(recebidos).toEqual([novo, novo, novo]);
  });

  it('volta a chamar o servidor numa renovação posterior', () => {
    // O par do teste acima: compartilhar a requisição em voo não pode virar
    // cache eterno, senão a renovação seguinte — daqui a 25 minutos — devolveria
    // para sempre o token da primeira.
    comToken(tokenQueVenceEm(METADE_DA_MARGEM_S));

    service.renovar().subscribe();
    httpMock
      .expectOne(`${API_URL}/auth/renovar`)
      .flush({ access_token: tokenQueVenceEm(DOBRO_DA_MARGEM_S), token_type: 'bearer' });

    const maisNovo = tokenQueVenceEm(DOBRO_DA_MARGEM_S + 1);
    service.renovar().subscribe();
    httpMock
      .expectOne(`${API_URL}/auth/renovar`)
      .flush({ access_token: maisNovo, token_type: 'bearer' });

    expect(service.getToken()).toBe(maisNovo);
  });
});
