import { DatePipe, DecimalPipe } from '@angular/common';
import { Component, OnInit, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { RelatorioService, SessaoNoHistorico } from '../../core/services/relatorio.service';
import { formatarDuracao } from '../../shared/duracao';
import { IconeComponent } from '../../shared/icone.component';
import { LogoComponent } from '../../shared/logo.component';

/**
 * As sessões passadas do aluno (ticket 12).
 *
 * O relatório de uma sessão responde "como foi hoje". O histórico existe para a
 * pergunta que só aparece depois de algumas semanas — "como tem sido" —, e por
 * isso cada linha traz o mínimo para comparar e escolher: quando, quanto tempo
 * de captura, como ficou o índice e se houve alerta.
 *
 * O que ele **não** faz é traçar tendência entre sessões. Comparar a média de
 * terça com a de quinta pressupõe que as duas medem a mesma coisa, e elas não
 * medem: a baseline é recalibrada a cada sessão, o ambiente muda, e duas
 * médias iguais podem vir de sessões muito diferentes. Oferecer a linha do
 * tempo é útil; desenhar uma seta para cima em cima dela seria afirmar mais do
 * que o dado sustenta.
 *
 * A mesma régua vale para o método declarado, que entrou aqui com a ticket 17:
 * cada linha diz **qual** método foi, e nenhuma compara a execução de dois dias.
 * Uma "média de aderência da semana" não está adiada — está proibida, pelo mesmo
 * motivo de sempre: a baseline recalibra a cada sessão, e duas sessões com o
 * mesmo método não medem a mesma coisa.
 */
@Component({
  selector: 'app-historico',
  standalone: true,
  imports: [DatePipe, DecimalPipe, RouterLink, IconeComponent, LogoComponent],
  templateUrl: './historico.component.html',
})
export class HistoricoComponent implements OnInit {
  private readonly relatorioService = inject(RelatorioService);

  readonly sessoes = signal<SessaoNoHistorico[]>([]);
  readonly carregando = signal(true);
  readonly erro = signal<string | null>(null);

  ngOnInit(): void {
    this.relatorioService.historico().subscribe({
      next: (sessoes) => {
        this.sessoes.set(sessoes);
        this.carregando.set(false);
      },
      error: () => {
        this.carregando.set(false);
        this.erro.set('Não foi possível carregar suas sessões. Tente novamente em instantes.');
      },
    });
  }

  duracao(segundos: number): string {
    return formatarDuracao(segundos);
  }
}
