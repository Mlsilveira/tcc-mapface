import { DatePipe, DecimalPipe } from '@angular/common';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { Router, RouterLink } from '@angular/router';

import { ItemDoHistorico, RelatorioService } from '../../core/services/relatorio.service';
import { formatarDuracao } from '../../core/tempo';
import { IconeComponent } from '../../shared/icone.component';
import { LogoComponent } from '../../shared/logo.component';

/**
 * Uma linha da lista, já com o que a tela mostra resolvido.
 *
 * A conversão vive fora do template de propósito: decidir que uma sessão sem
 * leitura **não tem score** é regra, não formatação, e o teste bate nela.
 */
export interface LinhaDoHistorico {
  item: ItemDoHistorico;
  duracao: string;
  /** `null` quando a sessão não produziu leitura nenhuma. */
  score: number | null;
}

/**
 * O histórico de sessões do aluno (ticket 12).
 *
 * Cada linha aponta para `/relatorio/:id` — a mesma tela da ticket 11, sem
 * variante "resumida". Um segundo formato de relatório teria de ser mantido em
 * dia com o primeiro, e divergiria na primeira mudança.
 */
@Component({
  selector: 'app-historico',
  standalone: true,
  imports: [DatePipe, DecimalPipe, RouterLink, IconeComponent, LogoComponent],
  templateUrl: './historico.component.html',
})
export class HistoricoComponent implements OnInit {
  private readonly relatorioService = inject(RelatorioService);
  private readonly router = inject(Router);

  readonly itens = signal<ItemDoHistorico[]>([]);
  readonly carregando = signal(true);
  readonly erro = signal<string | null>(null);

  readonly linhas = computed<LinhaDoHistorico[]>(() =>
    this.itens().map((item) => ({
      item,
      // Da sessão em andamento, o backend manda `duracao_s: 0` porque ela não
      // tem `fim`. Mostrar "00:00" ao lado de "em andamento" seria contraditório.
      duracao: item.parcial && item.duracao_s === 0 ? '' : formatarDuracao(item.duracao_s),
      score: item.n_leituras === 0 ? null : item.score_medio,
    })),
  );

  readonly vazio = computed(() => !this.carregando() && this.itens().length === 0);

  ngOnInit(): void {
    this.relatorioService.historico().subscribe({
      next: (itens) => {
        this.itens.set(itens);
        this.carregando.set(false);
      },
      error: () => {
        this.carregando.set(false);
        this.erro.set('Não foi possível carregar suas sessões. Tente novamente.');
      },
    });
  }

  voltar(): void {
    this.router.navigate(['/home']);
  }
}
