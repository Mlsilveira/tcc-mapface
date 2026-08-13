import { Injectable, NgZone, OnDestroy } from '@angular/core';
import { Router } from '@angular/router';

import { AuthService } from './auth.service';
import { SessaoService } from './sessao.service';

const EVENTOS_DE_ATIVIDADE = ['mousemove', 'keydown', 'click', 'scroll', 'touchstart'];

/** Tempo de inatividade tolerado antes de encerrar a sessão automaticamente. */
export const TEMPO_LIMITE_INATIVIDADE_MS = 15 * 60 * 1000;

@Injectable({ providedIn: 'root' })
export class InactivityService implements OnDestroy {
  private temporizador: ReturnType<typeof setTimeout> | null = null;
  private monitorando = false;
  private readonly ouvinte = () => this.reiniciarTemporizador();

  constructor(
    private readonly authService: AuthService,
    private readonly sessaoService: SessaoService,
    private readonly router: Router,
    private readonly zone: NgZone,
  ) {}

  /** Começa a observar atividade do usuário e agenda o encerramento por inatividade. Idempotente. */
  iniciarMonitoramento(): void {
    if (this.monitorando) {
      return;
    }
    this.monitorando = true;

    this.zone.runOutsideAngular(() => {
      EVENTOS_DE_ATIVIDADE.forEach((evento) =>
        window.addEventListener(evento, this.ouvinte, { passive: true }),
      );
    });

    this.reiniciarTemporizador();
  }

  pararMonitoramento(): void {
    if (!this.monitorando) {
      return;
    }
    this.monitorando = false;

    EVENTOS_DE_ATIVIDADE.forEach((evento) => window.removeEventListener(evento, this.ouvinte));

    if (this.temporizador) {
      clearTimeout(this.temporizador);
      this.temporizador = null;
    }
  }

  private reiniciarTemporizador(): void {
    if (this.temporizador) {
      clearTimeout(this.temporizador);
    }
    this.temporizador = setTimeout(
      () => this.encerrarPorInatividade(),
      TEMPO_LIMITE_INATIVIDADE_MS,
    );
  }

  private encerrarPorInatividade(): void {
    this.zone.run(() => {
      this.pararMonitoramento();
      this.sessaoService.esquecerSessao();
      this.authService.logout();
      this.router.navigate(['/login'], { queryParams: { motivo: 'inatividade' } });
    });
  }

  ngOnDestroy(): void {
    this.pararMonitoramento();
  }
}
