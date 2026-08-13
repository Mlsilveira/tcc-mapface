import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed, discardPeriodicTasks, fakeAsync, tick } from '@angular/core/testing';

import { INTERVALO_ATIVIDADE_MS, Sessao, SessaoService } from './sessao.service';

const API = 'http://localhost:8000';

const SESSAO_EM_ANDAMENTO: Sessao = {
  id: 7,
  id_aluno: 1,
  inicio: '2026-08-13T12:00:00Z',
  fim: null,
};

describe('SessaoService', () => {
  let service: SessaoService;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    service = TestBed.inject(SessaoService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
  });

  function iniciarSessao(sessao: Sessao = SESSAO_EM_ANDAMENTO): void {
    service.iniciar().subscribe();
    httpMock.expectOne({ method: 'POST', url: `${API}/sessoes` }).flush(sessao);
  }

  it('começa sem sessão em andamento', () => {
    expect(service.sessaoAtiva()).toBeNull();
  });

  it('inicia a sessão e passa a expô-la', () => {
    iniciarSessao();

    expect(service.sessaoAtiva()).toEqual(SESSAO_EM_ANDAMENTO);
  });

  it('carrega a sessão em andamento do backend', () => {
    service.carregarAtiva().subscribe();

    const requisicao = httpMock.expectOne(`${API}/sessoes/ativa`);
    expect(requisicao.request.method).toBe('GET');
    requisicao.flush(SESSAO_EM_ANDAMENTO);

    expect(service.sessaoAtiva()).toEqual(SESSAO_EM_ANDAMENTO);
  });

  it('trata resposta nula de /sessoes/ativa como ausência de sessão', () => {
    service.carregarAtiva().subscribe();
    httpMock.expectOne(`${API}/sessoes/ativa`).flush(null);

    expect(service.sessaoAtiva()).toBeNull();
  });

  it('encerra a sessão em andamento e limpa o estado local', () => {
    iniciarSessao();

    service.encerrar().subscribe();
    const requisicao = httpMock.expectOne(`${API}/sessoes/${SESSAO_EM_ANDAMENTO.id}/encerrar`);
    expect(requisicao.request.method).toBe('POST');
    requisicao.flush({ ...SESSAO_EM_ANDAMENTO, fim: '2026-08-13T12:30:00Z' });

    expect(service.sessaoAtiva()).toBeNull();
  });

  it('limpa o estado local quando o backend diz que a sessão já estava encerrada', fakeAsync(() => {
    // A sessão pode ter expirado por inatividade entre o último heartbeat e o
    // clique em "Encerrar". Insistir em mostrá-la em andamento deixaria o aluno
    // preso num botão de encerrar que falha para sempre.
    iniciarSessao();

    service.encerrar().subscribe({ error: () => undefined });
    httpMock
      .expectOne(`${API}/sessoes/${SESSAO_EM_ANDAMENTO.id}/encerrar`)
      .flush({ detail: 'Esta sessão de estudo já foi encerrada' }, {
        status: 409,
        statusText: 'Conflict',
      });

    expect(service.sessaoAtiva()).toBeNull();

    tick(INTERVALO_ATIVIDADE_MS * 2);
    httpMock.expectNone(`${API}/sessoes/${SESSAO_EM_ANDAMENTO.id}/atividade`);
    discardPeriodicTasks();
  }));

  it('falha ao encerrar quando não há sessão em andamento, sem chamar o backend', () => {
    let erro: unknown = null;
    service.encerrar().subscribe({ error: (e) => (erro = e) });

    expect(erro).toBeTruthy();
  });

  it('envia sinal de atividade periodicamente enquanto a sessão está em andamento', fakeAsync(() => {
    iniciarSessao();

    tick(INTERVALO_ATIVIDADE_MS);
    httpMock
      .expectOne(`${API}/sessoes/${SESSAO_EM_ANDAMENTO.id}/atividade`)
      .flush(SESSAO_EM_ANDAMENTO);

    tick(INTERVALO_ATIVIDADE_MS);
    httpMock
      .expectOne(`${API}/sessoes/${SESSAO_EM_ANDAMENTO.id}/atividade`)
      .flush(SESSAO_EM_ANDAMENTO);

    discardPeriodicTasks();
  }));

  it('para de enviar sinais de atividade depois do encerramento', fakeAsync(() => {
    iniciarSessao();

    service.encerrar().subscribe();
    httpMock
      .expectOne(`${API}/sessoes/${SESSAO_EM_ANDAMENTO.id}/encerrar`)
      .flush({ ...SESSAO_EM_ANDAMENTO, fim: '2026-08-13T12:30:00Z' });

    tick(INTERVALO_ATIVIDADE_MS * 2);
    httpMock.expectNone(`${API}/sessoes/${SESSAO_EM_ANDAMENTO.id}/atividade`);

    discardPeriodicTasks();
  }));

  it('limpa o estado local quando o backend já encerrou a sessão por inatividade', fakeAsync(() => {
    // Se o servidor encerrou a sessão e a interface continuasse mostrando
    // "em andamento", o aluno acharia que está sendo monitorado sem estar.
    iniciarSessao();

    tick(INTERVALO_ATIVIDADE_MS);
    httpMock
      .expectOne(`${API}/sessoes/${SESSAO_EM_ANDAMENTO.id}/atividade`)
      .flush({ detail: 'Esta sessão de estudo já foi encerrada' }, { status: 409, statusText: 'Conflict' });

    expect(service.sessaoAtiva()).toBeNull();

    tick(INTERVALO_ATIVIDADE_MS * 2);
    httpMock.expectNone(`${API}/sessoes/${SESSAO_EM_ANDAMENTO.id}/atividade`);

    discardPeriodicTasks();
  }));

  it('limpa o estado local quando o token expira no meio da sessão', fakeAsync(() => {
    // O JWT expira em 30 min, bem antes do fim de uma sessão de estudo longa.
    // Sem tratar o 401, a tela seguiria dizendo "em andamento" para sempre.
    iniciarSessao();

    tick(INTERVALO_ATIVIDADE_MS);
    httpMock
      .expectOne(`${API}/sessoes/${SESSAO_EM_ANDAMENTO.id}/atividade`)
      .flush({ detail: 'Não foi possível validar as credenciais' }, {
        status: 401,
        statusText: 'Unauthorized',
      });

    expect(service.sessaoAtiva()).toBeNull();

    tick(INTERVALO_ATIVIDADE_MS * 2);
    httpMock.expectNone(`${API}/sessoes/${SESSAO_EM_ANDAMENTO.id}/atividade`);

    discardPeriodicTasks();
  }));

  it('esquece a sessão sem chamar o backend e para os sinais de atividade', fakeAsync(() => {
    iniciarSessao();

    service.esquecerSessao();

    expect(service.sessaoAtiva()).toBeNull();
    tick(INTERVALO_ATIVIDADE_MS * 2);
    httpMock.expectNone(`${API}/sessoes/${SESSAO_EM_ANDAMENTO.id}/atividade`);

    discardPeriodicTasks();
  }));

  it('retoma os sinais de atividade ao recarregar uma sessão já em andamento', fakeAsync(() => {
    service.carregarAtiva().subscribe();
    httpMock.expectOne(`${API}/sessoes/ativa`).flush(SESSAO_EM_ANDAMENTO);

    tick(INTERVALO_ATIVIDADE_MS);
    const atividade = httpMock.expectOne(`${API}/sessoes/${SESSAO_EM_ANDAMENTO.id}/atividade`);
    expect(atividade.request.method).toBe('POST');
    atividade.flush(SESSAO_EM_ANDAMENTO);

    discardPeriodicTasks();
  }));
});
