import { Component, inject } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';

import { AuthService } from '../../core/services/auth.service';

@Component({
  selector: 'app-registro',
  standalone: true,
  imports: [ReactiveFormsModule, RouterLink],
  templateUrl: './registro.component.html',
})
export class RegistroComponent {
  private readonly fb = inject(FormBuilder);
  private readonly authService = inject(AuthService);
  private readonly router = inject(Router);

  readonly formulario = this.fb.group({
    nome: ['', [Validators.required]],
    email: ['', [Validators.required, Validators.email]],
    senha: ['', [Validators.required, Validators.minLength(8)]],
  });

  erro: string | null = null;
  enviando = false;

  cadastrar(): void {
    if (this.formulario.invalid) {
      this.formulario.markAllAsTouched();
      return;
    }

    this.erro = null;
    this.enviando = true;
    const { nome, email, senha } = this.formulario.getRawValue();

    this.authService.registrar({ nome: nome!, email: email!, senha: senha! }).subscribe({
      next: () => {
        this.enviando = false;
        this.router.navigate(['/login']);
      },
      error: (erro) => {
        this.enviando = false;
        this.erro =
          erro?.status === 409
            ? 'Este e-mail já está cadastrado.'
            : 'Não foi possível concluir o cadastro. Tente novamente.';
      },
    });
  }
}
