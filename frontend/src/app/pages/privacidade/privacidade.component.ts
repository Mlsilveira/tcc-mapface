import { DatePipe } from '@angular/common';
import { Component, OnInit, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';

import { VERSAO_TERMO } from '../../core/consentimento/termo';
import { AuthService } from '../../core/services/auth.service';
import { ContaService, CorrecaoDePerfil, Perfil } from '../../core/services/conta.service';
import { InactivityService } from '../../core/services/inactivity.service';
import { SessaoService } from '../../core/services/sessao.service';
import { LogoComponent } from '../../shared/logo.component';
import { TermoDeConsentimentoComponent } from '../../shared/termo-de-consentimento.component';

/**
 * Onde o titular exerce o que o termo promete: ler o termo, corrigir os dados,
 * revogar o consentimento e excluir a conta.
 *
 * Revogar e excluir pedem uma segunda confirmação, porque interrompem o uso. A
 * exclusão ainda pede a senha, porque não tem volta.
 */
@Component({
  selector: 'app-privacidade',
  standalone: true,
  imports: [DatePipe, ReactiveFormsModule, RouterLink, LogoComponent, TermoDeConsentimentoComponent],
  templateUrl: './privacidade.component.html',
})
export class PrivacidadeComponent implements OnInit {
  private readonly fb = inject(FormBuilder);
  private readonly contaService = inject(ContaService);
  private readonly authService = inject(AuthService);
  private readonly sessaoService = inject(SessaoService);
  private readonly inactivityService = inject(InactivityService);
  private readonly router = inject(Router);

  readonly versaoAtual = VERSAO_TERMO;
  readonly perfil = signal<Perfil | null>(null);
  readonly erro = signal<string | null>(null);
  readonly aviso = signal<string | null>(null);
  readonly confirmandoRevogacao = signal(false);
  readonly enviando = signal(false);

  readonly formularioDeDados = this.fb.group({
    nome: ['', [Validators.required]],
    email: ['', [Validators.required, Validators.email]],
  });

  readonly formularioDeAceite = this.fb.group({
    aceitouTermo: [false, [Validators.requiredTrue]],
    declarouMaioridade: [false, [Validators.requiredTrue]],
  });

  readonly formularioDeExclusao = this.fb.group({
    senha: ['', [Validators.required]],
  });

  ngOnInit(): void {
    this.contaService.carregar().subscribe({
      next: (perfil) => this.aplicar(perfil),
      error: () => this.erro.set('Não foi possível carregar seus dados.'),
    });
  }

  salvarDados(): void {
    const atual = this.perfil();
    if (atual === null || this.formularioDeDados.invalid) {
      this.formularioDeDados.markAllAsTouched();
      return;
    }

    const { nome, email } = this.formularioDeDados.getRawValue();
    const correcao: CorrecaoDePerfil = {};
    if (nome !== atual.nome) {
      correcao.nome = nome!;
    }
    if (email !== atual.email) {
      correcao.email = email!;
    }

    this.executar(this.contaService.corrigir(correcao), 'Dados atualizados.', (falha) =>
      falha === 409
        ? 'Este e-mail já está cadastrado.'
        : 'Não foi possível atualizar seus dados.',
    );
  }

  aceitar(): void {
    if (this.formularioDeAceite.invalid) {
      this.formularioDeAceite.markAllAsTouched();
      return;
    }

    this.executar(
      this.contaService.aceitarTermo(),
      'Consentimento registrado.',
      () => 'Não foi possível registrar o aceite. Recarregue a página e tente de novo.',
    );
  }

  revogar(): void {
    this.executar(
      this.contaService.revogar(),
      'Consentimento revogado. Novas sessões ficam bloqueadas até um novo aceite.',
      () => 'Não foi possível revogar o consentimento. Tente novamente.',
      () => this.sessaoService.esquecerSessao(),
    );
  }

  excluir(): void {
    if (this.formularioDeExclusao.invalid) {
      this.formularioDeExclusao.markAllAsTouched();
      return;
    }

    this.erro.set(null);
    this.enviando.set(true);
    this.contaService.excluir(this.formularioDeExclusao.getRawValue().senha!).subscribe({
      next: () => {
        this.enviando.set(false);
        this.sessaoService.esquecerSessao();
        this.inactivityService.pararMonitoramento();
        this.authService.logout();
        void this.router.navigate(['/login']);
      },
      error: (falha: { status?: number }) => {
        this.enviando.set(false);
        this.erro.set(
          falha?.status === 403 ? 'Senha incorreta.' : 'Não foi possível excluir a conta.',
        );
      },
    });
  }

  private executar(
    acao: ReturnType<ContaService['carregar']>,
    sucesso: string,
    mensagemDeFalha: (status?: number) => string,
    depois?: () => void,
  ): void {
    this.erro.set(null);
    this.aviso.set(null);
    this.enviando.set(true);

    acao.subscribe({
      next: (perfil) => {
        this.enviando.set(false);
        this.aplicar(perfil);
        this.aviso.set(sucesso);
        depois?.();
      },
      error: (falha: { status?: number }) => {
        this.enviando.set(false);
        this.erro.set(mensagemDeFalha(falha?.status));
      },
    });
  }

  private aplicar(perfil: Perfil): void {
    this.perfil.set(perfil);
    this.confirmandoRevogacao.set(false);
    this.formularioDeDados.reset({ nome: perfil.nome, email: perfil.email });
    this.formularioDeAceite.reset({ aceitouTermo: false, declarouMaioridade: false });
  }
}
