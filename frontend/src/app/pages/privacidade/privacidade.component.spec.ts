import { HttpErrorResponse } from '@angular/common/http';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { provideRouter, Router } from '@angular/router';
import { of, throwError } from 'rxjs';

import { AuthService } from '../../core/services/auth.service';
import { ContaService, Perfil } from '../../core/services/conta.service';
import { InactivityService } from '../../core/services/inactivity.service';
import { SessaoService } from '../../core/services/sessao.service';
import { PrivacidadeComponent } from './privacidade.component';

const VIGENTE: Perfil = {
  id: 1,
  nome: 'Ana',
  email: 'ana@exemplo.com',
  termo_versao: '1.1',
  termo_aceito_em: '2026-11-08T10:00:00Z',
  consentimento_revogado_em: null,
  consentimento_vigente: true,
};

const REVOGADO: Perfil = {
  ...VIGENTE,
  consentimento_revogado_em: '2026-11-08T11:00:00Z',
  consentimento_vigente: false,
};

describe('PrivacidadeComponent', () => {
  let fixture: ComponentFixture<PrivacidadeComponent>;
  let conta: jasmine.SpyObj<ContaService>;
  let auth: jasmine.SpyObj<AuthService>;
  let sessao: jasmine.SpyObj<SessaoService>;
  let navegar: jasmine.Spy;

  async function abrir(perfil: Perfil): Promise<void> {
    conta = jasmine.createSpyObj('ContaService', [
      'carregar',
      'corrigir',
      'aceitarTermo',
      'revogar',
      'excluir',
    ]);
    conta.carregar.and.returnValue(of(perfil));
    auth = jasmine.createSpyObj('AuthService', ['logout']);
    sessao = jasmine.createSpyObj('SessaoService', ['esquecerSessao']);

    await TestBed.configureTestingModule({
      imports: [PrivacidadeComponent],
      providers: [
        provideRouter([]),
        { provide: ContaService, useValue: conta },
        { provide: AuthService, useValue: auth },
        { provide: SessaoService, useValue: sessao },
        {
          provide: InactivityService,
          useValue: jasmine.createSpyObj('InactivityService', ['pararMonitoramento']),
        },
      ],
    }).compileComponents();

    navegar = spyOn(TestBed.inject(Router), 'navigate').and.resolveTo(true);
    fixture = TestBed.createComponent(PrivacidadeComponent);
    fixture.detectChanges();
  }

  function clicar(teste: string): void {
    (fixture.debugElement.query(By.css(`[data-teste="${teste}"]`)).nativeElement as HTMLElement).click();
    fixture.detectChanges();
  }

  function texto(): string {
    return (fixture.nativeElement as HTMLElement).textContent ?? '';
  }

  it('só revoga depois da segunda confirmação', async () => {
    await abrir(VIGENTE);
    conta.revogar.and.returnValue(of(REVOGADO));

    clicar('revogar');
    expect(conta.revogar).not.toHaveBeenCalled();

    clicar('confirmar-revogacao');

    expect(conta.revogar).toHaveBeenCalled();
    expect(sessao.esquecerSessao).toHaveBeenCalled();
    expect(texto()).toContain('Revogado em');
  });

  it('não reaceita sem as duas declarações', async () => {
    await abrir(REVOGADO);

    fixture.componentInstance.formularioDeAceite.patchValue({ aceitouTermo: true });
    fixture.componentInstance.aceitar();

    expect(conta.aceitarTermo).not.toHaveBeenCalled();
  });

  it('reaceita com as duas declarações', async () => {
    await abrir(REVOGADO);
    conta.aceitarTermo.and.returnValue(of(VIGENTE));

    fixture.componentInstance.formularioDeAceite.setValue({
      aceitouTermo: true,
      declarouMaioridade: true,
    });
    fixture.componentInstance.aceitar();
    fixture.detectChanges();

    expect(conta.aceitarTermo).toHaveBeenCalled();
    expect(texto()).toContain('Revogar consentimento');
  });

  it('envia só o que mudou nos dados', async () => {
    await abrir(VIGENTE);
    conta.corrigir.and.returnValue(of({ ...VIGENTE, nome: 'Ana S.' }));

    fixture.componentInstance.formularioDeDados.patchValue({ nome: 'Ana S.' });
    fixture.componentInstance.salvarDados();

    expect(conta.corrigir).toHaveBeenCalledWith({ nome: 'Ana S.' });
  });

  it('avisa quando o novo e-mail já está em uso', async () => {
    await abrir(VIGENTE);
    conta.corrigir.and.returnValue(throwError(() => new HttpErrorResponse({ status: 409 })));

    fixture.componentInstance.formularioDeDados.patchValue({ email: 'rui@exemplo.com' });
    fixture.componentInstance.salvarDados();
    fixture.detectChanges();

    expect(texto()).toContain('Este e-mail já está cadastrado.');
  });

  it('desloga e volta ao login depois de excluir', async () => {
    await abrir(VIGENTE);
    conta.excluir.and.returnValue(of(undefined));

    fixture.componentInstance.formularioDeExclusao.setValue({ senha: 'minha-senha' });
    fixture.componentInstance.excluir();

    expect(conta.excluir).toHaveBeenCalledWith('minha-senha');
    expect(auth.logout).toHaveBeenCalled();
    expect(navegar).toHaveBeenCalledWith(['/login']);
  });

  it('continua na tela com senha errada', async () => {
    await abrir(VIGENTE);
    conta.excluir.and.returnValue(throwError(() => new HttpErrorResponse({ status: 403 })));

    fixture.componentInstance.formularioDeExclusao.setValue({ senha: 'errada' });
    fixture.componentInstance.excluir();
    fixture.detectChanges();

    expect(texto()).toContain('Senha incorreta.');
    expect(auth.logout).not.toHaveBeenCalled();
  });

  it('não pede exclusão sem a senha', async () => {
    await abrir(VIGENTE);

    fixture.componentInstance.excluir();

    expect(conta.excluir).not.toHaveBeenCalled();
  });
});
