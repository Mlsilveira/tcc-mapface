import { HttpErrorResponse } from '@angular/common/http';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { provideRouter, Router } from '@angular/router';
import { throwError, of } from 'rxjs';

import { AuthService } from '../../core/services/auth.service';
import { LoginComponent } from './login.component';

describe('LoginComponent', () => {
  let fixture: ComponentFixture<LoginComponent>;
  let authServiceSpy: jasmine.SpyObj<AuthService>;
  let navegar: jasmine.Spy;

  beforeEach(async () => {
    authServiceSpy = jasmine.createSpyObj('AuthService', ['login']);

    await TestBed.configureTestingModule({
      imports: [LoginComponent],
      providers: [provideRouter([]), { provide: AuthService, useValue: authServiceSpy }],
    }).compileComponents();

    navegar = spyOn(TestBed.inject(Router), 'navigate').and.resolveTo(true);

    fixture = TestBed.createComponent(LoginComponent);
    fixture.detectChanges();
  });

  function preencher(email: string, senha: string): void {
    const campos = fixture.debugElement.queryAll(By.css('input'));
    const [campoEmail, campoSenha] = campos.map((c) => c.nativeElement as HTMLInputElement);

    campoEmail.value = email;
    campoEmail.dispatchEvent(new Event('input'));
    campoSenha.value = senha;
    campoSenha.dispatchEvent(new Event('input'));
    fixture.detectChanges();
  }

  function submeter(): void {
    fixture.debugElement.query(By.css('form')).triggerEventHandler('submit', new Event('submit'));
    fixture.detectChanges();
  }

  function textoDoErroGeral(): string | null {
    const erro = fixture.debugElement.query(By.css('.erro-geral'));
    return erro ? (erro.nativeElement as HTMLElement).textContent!.trim() : null;
  }

  it('envia as credenciais digitadas e leva o usuário para /home no sucesso', () => {
    authServiceSpy.login.and.returnValue(of({ access_token: 'tk', token_type: 'bearer' }));

    preencher('ana@exemplo.com', 'senhaSegura123');
    submeter();

    expect(authServiceSpy.login).toHaveBeenCalledWith({
      email: 'ana@exemplo.com',
      senha: 'senhaSegura123',
    });
    expect(navegar).toHaveBeenCalledWith(['/home']);
  });

  it('mostra mensagem de erro e não navega quando as credenciais são recusadas', () => {
    authServiceSpy.login.and.returnValue(
      throwError(() => new HttpErrorResponse({ status: 401 })),
    );

    preencher('ana@exemplo.com', 'senhaErrada');
    submeter();

    expect(textoDoErroGeral()).toBe('E-mail ou senha inválidos.');
    expect(navegar).not.toHaveBeenCalled();
  });

  it('não chama o backend quando o formulário está inválido', () => {
    preencher('nao-e-um-email', '');
    submeter();

    expect(authServiceSpy.login).not.toHaveBeenCalled();
  });

  it('exibe os erros de validação dos campos ao tentar submeter em branco', () => {
    submeter();

    const mensagens = fixture.debugElement
      .queryAll(By.css('.campo-erro'))
      .map((e) => (e.nativeElement as HTMLElement).textContent!.trim());

    expect(mensagens).toEqual(['Informe um e-mail válido.', 'Informe sua senha.']);
  });

  it('reabilita o botão após uma tentativa recusada, permitindo tentar de novo', () => {
    authServiceSpy.login.and.returnValue(
      throwError(() => new HttpErrorResponse({ status: 401 })),
    );

    preencher('ana@exemplo.com', 'senhaErrada');
    submeter();

    const botao = fixture.debugElement.query(By.css('button[type="submit"]'))
      .nativeElement as HTMLButtonElement;
    expect(botao.disabled).toBeFalse();
    expect(botao.textContent!.trim()).toBe('Entrar');
  });

  it('limpa o erro anterior ao submeter uma nova tentativa', () => {
    authServiceSpy.login.and.returnValue(
      throwError(() => new HttpErrorResponse({ status: 401 })),
    );
    preencher('ana@exemplo.com', 'senhaErrada');
    submeter();
    expect(textoDoErroGeral()).not.toBeNull();

    authServiceSpy.login.and.returnValue(of({ access_token: 'tk', token_type: 'bearer' }));
    preencher('ana@exemplo.com', 'senhaSegura123');
    submeter();

    expect(textoDoErroGeral()).toBeNull();
  });
});
