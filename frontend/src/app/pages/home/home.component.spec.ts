import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';
import { Observable, of, throwError } from 'rxjs';

import { AuthService } from '../../core/services/auth.service';
import { InactivityService } from '../../core/services/inactivity.service';
import { Sessao, SessaoService } from '../../core/services/sessao.service';
import { HomeComponent } from './home.component';

const SESSAO_EM_ANDAMENTO: Sessao = {
  id: 7,
  id_aluno: 1,
  inicio: '2026-08-13T12:00:00Z',
  fim: null,
};

/** Dublê do SessaoService: guarda o estado internamente, como o serviço real. */
class SessaoServiceFalso {
  private sessao: Sessao | null = null;
  falharAoIniciar = false;
  /** Simula o 409 do backend: outra aba já iniciou a sessão. */
  jaHaSessaoNoBackend: Sessao | null = null;
  esqueceu = false;

  readonly sessaoAtiva = () => this.sessao;

  definirAtiva(sessao: Sessao | null): void {
    this.sessao = sessao;
  }

  carregarAtiva(): Observable<Sessao | null> {
    this.sessao = this.jaHaSessaoNoBackend ?? this.sessao;
    return of(this.sessao);
  }

  iniciar(): Observable<Sessao> {
    if (this.jaHaSessaoNoBackend) {
      return throwError(() => ({ status: 409 }));
    }
    if (this.falharAoIniciar) {
      return throwError(() => new Error('falhou'));
    }
    this.sessao = SESSAO_EM_ANDAMENTO;
    return of(SESSAO_EM_ANDAMENTO);
  }

  esquecerSessao(): void {
    this.sessao = null;
    this.esqueceu = true;
  }

  encerrar(): Observable<Sessao> {
    const encerrada = { ...SESSAO_EM_ANDAMENTO, fim: '2026-08-13T12:30:00Z' };
    this.sessao = null;
    return of(encerrada);
  }
}

describe('HomeComponent', () => {
  let fixture: ComponentFixture<HomeComponent>;
  let sessaoService: SessaoServiceFalso;
  let authServiceSpy: jasmine.SpyObj<AuthService>;
  let inactivityServiceSpy: jasmine.SpyObj<InactivityService>;
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

  beforeEach(async () => {
    sessaoService = new SessaoServiceFalso();
    authServiceSpy = jasmine.createSpyObj('AuthService', ['logout']);
    inactivityServiceSpy = jasmine.createSpyObj('InactivityService', ['pararMonitoramento']);

    await TestBed.configureTestingModule({
      imports: [HomeComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        { provide: AuthService, useValue: authServiceSpy },
        { provide: InactivityService, useValue: inactivityServiceSpy },
        { provide: SessaoService, useValue: sessaoService },
      ],
    }).compileComponents();

    navegar = spyOn(TestBed.inject(Router), 'navigate').and.resolveTo(true);

    fixture = TestBed.createComponent(HomeComponent);
  });

  describe('sessão de estudo', () => {
    it('mostra o botão de iniciar quando não há sessão em andamento', () => {
      fixture.detectChanges();

      expect(botao('iniciar-sessao')).toBeTruthy();
      expect(botao('encerrar-sessao')).toBeNull();
    });

    it('mostra o botão de encerrar quando já existe sessão em andamento ao carregar a tela', () => {
      sessaoService.definirAtiva(SESSAO_EM_ANDAMENTO);

      fixture.detectChanges();

      expect(botao('encerrar-sessao')).toBeTruthy();
      expect(botao('iniciar-sessao')).toBeNull();
    });

    it('inicia a sessão ao clicar em iniciar e passa a oferecer o encerramento', () => {
      fixture.detectChanges();

      clicar('iniciar-sessao');

      expect(sessaoService.sessaoAtiva()).toEqual(SESSAO_EM_ANDAMENTO);
      expect(botao('encerrar-sessao')).toBeTruthy();
    });

    it('encerra a sessão ao clicar em encerrar', () => {
      sessaoService.definirAtiva(SESSAO_EM_ANDAMENTO);
      fixture.detectChanges();

      clicar('encerrar-sessao');

      expect(sessaoService.sessaoAtiva()).toBeNull();
      expect(botao('iniciar-sessao')).toBeTruthy();
    });

    it('ressincroniza a tela quando o backend responde que já há sessão em andamento', () => {
      // Cenário de duas abas: a aba antiga precisa passar a oferecer
      // "Encerrar", em vez de ficar travada num "Iniciar" que sempre falha.
      fixture.detectChanges();
      sessaoService.jaHaSessaoNoBackend = SESSAO_EM_ANDAMENTO;

      clicar('iniciar-sessao');

      expect(botao('encerrar-sessao')).toBeTruthy();
      expect(texto()).toContain('já tem uma sessão de estudo em andamento');
    });

    it('exibe mensagem de erro quando o backend recusa o início da sessão', () => {
      sessaoService.falharAoIniciar = true;
      fixture.detectChanges();

      clicar('iniciar-sessao');

      expect(texto()).toContain('Não foi possível iniciar');
    });
  });

  describe('logout', () => {
    beforeEach(() => fixture.detectChanges());

    it('desloga e volta para /login ao clicar em Sair', () => {
      clicar('sair');

      expect(authServiceSpy.logout).toHaveBeenCalled();
      expect(navegar).toHaveBeenCalledWith(['/login']);
    });

    it('esquece a sessão de estudo ao sair, para o heartbeat não sobreviver ao logout', () => {
      sessaoService.definirAtiva(SESSAO_EM_ANDAMENTO);

      clicar('sair');

      expect(sessaoService.esqueceu).toBeTrue();
      expect(sessaoService.sessaoAtiva()).toBeNull();
    });

    it('encerra o monitoramento de inatividade ao sair, para não deslogar de novo depois', () => {
      clicar('sair');

      expect(inactivityServiceSpy.pararMonitoramento).toHaveBeenCalled();
    });

    it('não desloga sozinho: só ao clicar em Sair', () => {
      expect(authServiceSpy.logout).not.toHaveBeenCalled();
      expect(navegar).not.toHaveBeenCalled();
    });
  });
});
