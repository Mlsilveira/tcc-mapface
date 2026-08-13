import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed, discardPeriodicTasks, fakeAsync, tick } from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';

import { AuthService } from '../../core/services/auth.service';
import { INTERVALO_ATIVIDADE_MS, Sessao } from '../../core/services/sessao.service';
import { HomeComponent } from './home.component';

const API = 'http://localhost:8000';

const SESSAO_EM_ANDAMENTO: Sessao = {
  id: 7,
  id_aluno: 1,
  inicio: '2026-08-13T12:00:00Z',
  fim: null,
};

const SESSAO_ENCERRADA: Sessao = { ...SESSAO_EM_ANDAMENTO, fim: '2026-08-13T12:30:00Z' };

/**
 * Estes testes rodam com o SessaoService, o AuthService e o InactivityService
 * de verdade: o único dublê é o HTTP, que é o boundary do sistema. Assim eles
 * cobrem a integração entre a tela e o serviço, em vez de um dublê que sempre
 * concorda com o que a tela espera.
 */
describe('HomeComponent', () => {
  let fixture: ComponentFixture<HomeComponent>;
  let httpMock: HttpTestingController;
  let authService: AuthService;
  let navegar: jasmine.Spy;

  function texto(): string {
    return fixture.nativeElement.textContent as string;
  }

  function botao(teste: string): HTMLButtonElement | null {
    return fixture.nativeElement.querySelector(`[data-teste="${teste}"]`);
  }

  function clicar(teste: string): void {
    botao(teste)!.click();
    fixture.detectChanges();
  }

  /** Resolve o GET disparado no ngOnInit e renderiza o resultado. */
  function abrirTela(sessao: Sessao | null): void {
    fixture.detectChanges();
    httpMock.expectOne(`${API}/sessoes/ativa`).flush(sessao);
    fixture.detectChanges();
  }

  beforeEach(async () => {
    localStorage.clear();
    // A tela é protegida pelo authGuard: o aluno só chega aqui autenticado, e o
    // AuthService lê o token do localStorage já ao ser construído.
    localStorage.setItem('iee_access_token', 'token-fake');

    await TestBed.configureTestingModule({
      imports: [HomeComponent],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    }).compileComponents();

    httpMock = TestBed.inject(HttpTestingController);
    authService = TestBed.inject(AuthService);
    navegar = spyOn(TestBed.inject(Router), 'navigate').and.resolveTo(true);

    fixture = TestBed.createComponent(HomeComponent);
  });

  afterEach(() => {
    httpMock.verify();
    localStorage.clear();
  });

  describe('sessão de estudo', () => {
    it('oferece iniciar quando o aluno não tem sessão em andamento', () => {
      abrirTela(null);

      expect(botao('iniciar-sessao')).toBeTruthy();
      expect(botao('encerrar-sessao')).toBeNull();
    });

    it('oferece encerrar quando já existe sessão em andamento ao abrir a tela', () => {
      abrirTela(SESSAO_EM_ANDAMENTO);

      expect(botao('encerrar-sessao')).toBeTruthy();
      expect(botao('iniciar-sessao')).toBeNull();
      expect(texto()).toContain('Sessão em andamento');
    });

    it('inicia a sessão ao clicar em iniciar e passa a oferecer o encerramento', () => {
      abrirTela(null);

      clicar('iniciar-sessao');
      httpMock.expectOne({ method: 'POST', url: `${API}/sessoes` }).flush(SESSAO_EM_ANDAMENTO);
      fixture.detectChanges();

      expect(botao('encerrar-sessao')).toBeTruthy();
    });

    it('encerra a sessão ao clicar em encerrar e volta a oferecer o início', () => {
      abrirTela(SESSAO_EM_ANDAMENTO);

      clicar('encerrar-sessao');
      httpMock.expectOne(`${API}/sessoes/${SESSAO_EM_ANDAMENTO.id}/encerrar`).flush(SESSAO_ENCERRADA);
      fixture.detectChanges();

      expect(botao('iniciar-sessao')).toBeTruthy();
    });

    it('ressincroniza a tela quando o backend responde que já há sessão em andamento', () => {
      // Cenário de duas abas: a aba antiga precisa passar a oferecer "Encerrar",
      // em vez de ficar travada num "Iniciar" que sempre falha.
      abrirTela(null);

      clicar('iniciar-sessao');
      httpMock
        .expectOne({ method: 'POST', url: `${API}/sessoes` })
        .flush({ detail: 'Já existe uma sessão de estudo em andamento' }, {
          status: 409,
          statusText: 'Conflict',
        });
      httpMock.expectOne(`${API}/sessoes/ativa`).flush(SESSAO_EM_ANDAMENTO);
      fixture.detectChanges();

      expect(botao('encerrar-sessao')).toBeTruthy();
      expect(texto()).toContain('já tem uma sessão de estudo em andamento');
    });

    it('avisa quando o backend falha ao iniciar a sessão', () => {
      abrirTela(null);

      clicar('iniciar-sessao');
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

    it('avisa quando o backend falha ao encerrar, mantendo a sessão em andamento', () => {
      abrirTela(SESSAO_EM_ANDAMENTO);

      clicar('encerrar-sessao');
      httpMock
        .expectOne(`${API}/sessoes/${SESSAO_EM_ANDAMENTO.id}/encerrar`)
        .flush({}, { status: 500, statusText: 'Server Error' });
      fixture.detectChanges();

      expect(texto()).toContain('Não foi possível encerrar');
      expect(botao('encerrar-sessao')).toBeTruthy();
    });
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

      clicar('sair');

      tick(INTERVALO_ATIVIDADE_MS * 2);
      httpMock.expectNone(`${API}/sessoes/${SESSAO_EM_ANDAMENTO.id}/atividade`);
      discardPeriodicTasks();
    }));

    it('não desloga sozinho: só ao clicar em Sair', () => {
      abrirTela(SESSAO_EM_ANDAMENTO);

      expect(authService.estaAutenticado()).toBeTrue();
      expect(navegar).not.toHaveBeenCalled();
    });
  });
});
