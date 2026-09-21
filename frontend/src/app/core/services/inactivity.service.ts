import { Injectable, NgZone, OnDestroy, effect } from '@angular/core';
import { Router } from '@angular/router';

import { AuthService } from './auth.service';
import { SessaoService } from './sessao.service';

const EVENTOS_DE_ATIVIDADE = ['mousemove', 'keydown', 'click', 'scroll', 'touchstart'];

/** Tempo de inatividade tolerado antes de encerrar a sessão automaticamente. */
export const TEMPO_LIMITE_INATIVIDADE_MS = 15 * 60 * 1000;

/**
 * O relógio de "tem alguém usando esta aba?", medido por mouse e teclado.
 *
 * **Ele fica suspenso enquanto houver sessão de estudo em andamento.** Durante o
 * estudo, quem responde a essa pergunta é a câmera: ler um livro por vinte
 * minutos em frente à webcam é exatamente o comportamento que o produto quer
 * incentivar, e era o comportamento que este serviço deslogava. Pior: ele
 * derrubava justamente quem fazia a pausa longa que o método de estudo
 * prescreve.
 *
 * Fora da sessão ele continua valendo, e é o único relógio que pode valer:
 * sem sessão não há câmera, e não existe outra evidência de que alguém está ali.
 *
 * **A troca que isso representa, declarada em vez de escondida.** Uma aba
 * autenticada e abandonada com sessão aberta sobrevive por `pausa do método +
 * tolerância` (no máximo 20 min) até o backend encerrar a sessão, e só então os
 * 15 minutos daqui voltam a correr — pior caso de cerca de 35 minutos, contra 15
 * antes. É deliberado: o custo é uma janela maior numa máquina destrancada; o
 * benefício é não expulsar quem está estudando.
 */
@Injectable({ providedIn: 'root' })
export class InactivityService implements OnDestroy {
  private temporizador: ReturnType<typeof setTimeout> | null = null;

  /** O guard pediu monitoramento — isto é sobre a rota, não sobre o estado dos ouvintes. */
  private armado = false;

  /** Os ouvintes estão de fato instalados. */
  private monitorando = false;

  private readonly ouvinte = () => this.reiniciarTemporizador();

  constructor(
    private readonly authService: AuthService,
    private readonly sessaoService: SessaoService,
    private readonly router: Router,
    private readonly zone: NgZone,
  ) {
    // A suspensão precisa ser reativa, e não uma checagem no momento de armar:
    // a sessão começa e termina **depois** de o guard ter armado o relógio, e
    // termina também por caminhos que não passam por esta tela (o backend
    // encerra por ausência e o heartbeat descobre sozinho). Um `effect` sobre o
    // signal cobre os dois sentidos sem estado novo.
    //
    // Sem `allowSignalWrites` de propósito: `sincronizar` mexe em ouvintes de
    // DOM e em `setTimeout`, e não escreve signal nenhum. Se um dia escrever, a
    // falha vai apontar para cá — que é o que se quer.
    effect(() => {
      this.sessaoService.sessaoAtiva();
      this.sincronizar();
    });
  }

  /** Arma o relógio de inatividade. Idempotente. */
  iniciarMonitoramento(): void {
    this.armado = true;
    this.sincronizar();
  }

  /** Desarma o relógio. Idempotente. */
  pararMonitoramento(): void {
    this.armado = false;
    this.sincronizar();
  }

  /**
   * Alinha os ouvintes ao que deveria estar valendo agora.
   *
   * Armar e monitorar são estados separados porque a sessão de estudo pode
   * suspender o monitoramento sem desarmar o relógio — e, quando ela termina, é
   * preciso saber se havia algo a retomar. Com um booleano só, encerrar a sessão
   * ou rearmaria o relógio de quem já tinha saído, ou nunca o rearmaria.
   *
   * O temporizador reinicia do zero ao retomar, e isso é o desejado: quem acabou
   * de encerrar uma sessão de estudo merece os 15 minutos inteiros.
   */
  private sincronizar(): void {
    const deveMonitorar = this.armado && this.sessaoService.sessaoAtiva() === null;
    if (deveMonitorar === this.monitorando) {
      return;
    }

    this.monitorando = deveMonitorar;
    if (deveMonitorar) {
      this.zone.runOutsideAngular(() => {
        EVENTOS_DE_ATIVIDADE.forEach((evento) =>
          window.addEventListener(evento, this.ouvinte, { passive: true }),
        );
      });
      this.reiniciarTemporizador();
      return;
    }

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
      // Só chega aqui sem sessão de estudo aberta — com sessão, o relógio está
      // suspenso. Então não há sessão a encerrar no backend, e `esquecerSessao`
      // continua sendo o encerramento local correto.
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
