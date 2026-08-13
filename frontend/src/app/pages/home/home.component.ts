import { DatePipe } from '@angular/common';
import { Component, OnInit, inject } from '@angular/core';
import { Router } from '@angular/router';
import { Observable } from 'rxjs';

import { AuthService } from '../../core/services/auth.service';
import { InactivityService } from '../../core/services/inactivity.service';
import { SessaoService } from '../../core/services/sessao.service';

@Component({
  selector: 'app-home',
  standalone: true,
  imports: [DatePipe],
  templateUrl: './home.component.html',
})
export class HomeComponent implements OnInit {
  private readonly authService = inject(AuthService);
  private readonly inactivityService = inject(InactivityService);
  private readonly sessaoService = inject(SessaoService);
  private readonly router = inject(Router);

  readonly sessaoAtiva = this.sessaoService.sessaoAtiva;

  erro: string | null = null;
  aguardando = false;

  ngOnInit(): void {
    // Recarregar a página no meio de uma sessão não pode "perder" a sessão:
    // o backend é a fonte da verdade sobre o que está em andamento.
    this.sessaoService.carregarAtiva().subscribe({
      error: () => (this.erro = 'Não foi possível verificar se há uma sessão em andamento.'),
    });
  }

  iniciarSessao(): void {
    this.erro = null;
    this.aguardando = true;

    this.sessaoService.iniciar().subscribe({
      next: () => (this.aguardando = false),
      error: (falha: { status?: number }) => {
        this.aguardando = false;

        if (falha?.status === 409) {
          // Outra aba já iniciou a sessão. Ressincronizar em vez de deixar a
          // tela travada oferecendo "Iniciar" para algo que já está rodando.
          this.erro = 'Você já tem uma sessão de estudo em andamento.';
          this.sessaoService.carregarAtiva().subscribe({ error: () => undefined });
          return;
        }

        this.erro = 'Não foi possível iniciar a sessão de estudo. Tente novamente.';
      },
    });
  }

  encerrarSessao(): void {
    this.executar(
      () => this.sessaoService.encerrar(),
      'Não foi possível encerrar a sessão de estudo. Tente novamente.',
    );
  }

  sair(): void {
    this.inactivityService.pararMonitoramento();
    this.sessaoService.esquecerSessao();
    this.authService.logout();
    this.router.navigate(['/login']);
  }

  private executar(acao: () => Observable<unknown>, mensagemDeErro: string): void {
    this.erro = null;
    this.aguardando = true;

    acao().subscribe({
      next: () => (this.aguardando = false),
      error: () => {
        this.aguardando = false;
        this.erro = mensagemDeErro;
      },
    });
  }
}
