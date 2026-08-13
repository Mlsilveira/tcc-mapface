import { HttpErrorResponse } from '@angular/common/http';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { provideRouter, Router } from '@angular/router';
import { of, throwError } from 'rxjs';

import { AuthService } from '../../core/services/auth.service';
import { RegistroComponent } from './registro.component';

describe('RegistroComponent', () => {
  let fixture: ComponentFixture<RegistroComponent>;
  let authServiceSpy: jasmine.SpyObj<AuthService>;
  let navegar: jasmine.Spy;

  beforeEach(async () => {
    authServiceSpy = jasmine.createSpyObj('AuthService', ['registrar']);

    await TestBed.configureTestingModule({
      imports: [RegistroComponent],
      providers: [provideRouter([]), { provide: AuthService, useValue: authServiceSpy }],
    }).compileComponents();

    navegar = spyOn(TestBed.inject(Router), 'navigate').and.resolveTo(true);

    fixture = TestBed.createComponent(RegistroComponent);
    fixture.detectChanges();
  });

  function preencher(nome: string, email: string, senha: string): void {
    const [campoNome, campoEmail, campoSenha] = fixture.debugElement
      .queryAll(By.css('input'))
      .map((c) => c.nativeElement as HTMLInputElement);

    for (const [campo, valor] of [
      [campoNome, nome],
      [campoEmail, email],
      [campoSenha, senha],
    ] as const) {
      campo.value = valor;
      campo.dispatchEvent(new Event('input'));
    }
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

  it('envia os dados digitados e leva o usuário para /login no sucesso', () => {
    authServiceSpy.registrar.and.returnValue(of({}));

    preencher('Ana Souza', 'ana@exemplo.com', 'senhaSegura123');
    submeter();

    expect(authServiceSpy.registrar).toHaveBeenCalledWith({
      nome: 'Ana Souza',
      email: 'ana@exemplo.com',
      senha: 'senhaSegura123',
    });
    expect(navegar).toHaveBeenCalledWith(['/login']);
  });

  it('avisa especificamente quando o e-mail já está cadastrado', () => {
    authServiceSpy.registrar.and.returnValue(
      throwError(() => new HttpErrorResponse({ status: 409 })),
    );

    preencher('Ana Souza', 'ana@exemplo.com', 'senhaSegura123');
    submeter();

    expect(textoDoErroGeral()).toBe('Este e-mail já está cadastrado.');
    expect(navegar).not.toHaveBeenCalled();
  });

  it('mostra mensagem genérica quando o servidor falha por outro motivo', () => {
    authServiceSpy.registrar.and.returnValue(
      throwError(() => new HttpErrorResponse({ status: 500 })),
    );

    preencher('Ana Souza', 'ana@exemplo.com', 'senhaSegura123');
    submeter();

    expect(textoDoErroGeral()).toBe('Não foi possível concluir o cadastro. Tente novamente.');
  });

  it('não chama o backend quando a senha é mais curta que o mínimo do servidor', () => {
    preencher('Ana Souza', 'ana@exemplo.com', 'curta');
    submeter();

    expect(authServiceSpy.registrar).not.toHaveBeenCalled();
    const mensagens = fixture.debugElement
      .queryAll(By.css('.campo-erro'))
      .map((e) => (e.nativeElement as HTMLElement).textContent!.trim());
    expect(mensagens).toEqual(['A senha precisa ter pelo menos 8 caracteres.']);
  });

  it('exibe os erros de todos os campos ao tentar submeter em branco', () => {
    submeter();

    const mensagens = fixture.debugElement
      .queryAll(By.css('.campo-erro'))
      .map((e) => (e.nativeElement as HTMLElement).textContent!.trim());

    expect(mensagens).toEqual([
      'Informe seu nome.',
      'Informe um e-mail válido.',
      'A senha precisa ter pelo menos 8 caracteres.',
    ]);
  });

  it('reabilita o botão após uma falha, permitindo tentar de novo', () => {
    authServiceSpy.registrar.and.returnValue(
      throwError(() => new HttpErrorResponse({ status: 409 })),
    );

    preencher('Ana Souza', 'ana@exemplo.com', 'senhaSegura123');
    submeter();

    const botao = fixture.debugElement.query(By.css('button[type="submit"]'))
      .nativeElement as HTMLButtonElement;
    expect(botao.disabled).toBeFalse();
    expect(botao.textContent!.trim()).toBe('Cadastrar');
  });
});
