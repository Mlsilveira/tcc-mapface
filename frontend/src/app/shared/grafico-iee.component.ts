import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  InjectionToken,
  OnDestroy,
  effect,
  inject,
  input,
  viewChild,
} from '@angular/core';
import { Chart, ChartConfiguration, registerables } from 'chart.js';

/**
 * Um ponto da série do IEE, como o gráfico o consome.
 *
 * `score: null` é o ponto de incerteza da ticket 10, e existe de propósito: sem
 * ele, "não deu para medir" viraria um buraco indistinguível de uma pausa, e a
 * linha ligaria os dois lados como se nada tivesse acontecido no meio.
 */
export interface PontoDoIEE {
  /** Instante em milissegundos desde a época, como `Date.now()`. */
  instante: number;
  score: number | null;
}

/**
 * O mínimo que o componente usa de um gráfico. Existe para que o teste possa
 * dublar a biblioteca: `chart.js` desenha em canvas de verdade e mede texto com
 * as fontes do navegador, o que num teste de unidade só produz fragilidade.
 */
export interface GraficoDeLinha {
  data: { labels: unknown[]; datasets: Array<{ data: unknown[] }> };
  update(modo?: string): void;
  destroy(): void;
}

export type CriadorDeGrafico = (
  canvas: HTMLCanvasElement,
  configuracao: ChartConfiguration<'line'>,
) => GraficoDeLinha;

export const CRIADOR_DE_GRAFICO = new InjectionToken<CriadorDeGrafico>('CriadorDeGrafico', {
  providedIn: 'root',
  factory: (): CriadorDeGrafico => {
    // `registerables` traz escalas, elementos e plugins. Sem isso o chart.js v4
    // sobe sem controlador de linha e falha em runtime, não na compilação.
    Chart.register(...registerables);
    return (canvas, configuracao) =>
      new Chart(canvas, configuracao) as unknown as GraficoDeLinha;
  },
});

/** Acima disto o aluno está em foco, para efeito da faixa de fundo do gráfico. */
export const LIMIAR_DE_FOCO = 60;

/**
 * O IEE ao longo de uma sessão, para o relatório de autopercepção (ticket 11).
 *
 * Desenha, e nada mais: quem decide o que é um ponto é quem passa a série. O
 * componente nasceu para um painel ao vivo durante a sessão, ideia descartada
 * porque um score de atenção na tela compete com a tarefa que ele mede — o
 * aluno olha para o número, e o ato de olhar derruba o número. O desenho
 * sobreviveu à mudança justamente por não saber de onde vêm os dados.
 *
 * **Por que mutar `chart.data` em vez de recriar.** O chart.js mantém estado
 * interno (escalas, animações em curso) que não sobrevive à substituição do
 * objeto de dados; mutar e chamar `update()` é a API que a própria biblioteca
 * oferece para série que muda.
 */
@Component({
  selector: 'app-grafico-iee',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="grafico">
      <canvas #tela role="img" [attr.aria-label]="descricao()"></canvas>
    </div>
  `,
})
export class GraficoIeeComponent implements OnDestroy {
  private readonly criarGrafico = inject(CRIADOR_DE_GRAFICO);
  private readonly tela = viewChild<ElementRef<HTMLCanvasElement>>('tela');

  /** A série a desenhar, do mais antigo para o mais recente. */
  readonly serie = input.required<readonly PontoDoIEE[]>();

  private grafico: GraficoDeLinha | null = null;

  constructor() {
    effect(() => {
      const canvas = this.tela()?.nativeElement;
      const serie = this.serie();

      if (canvas === undefined) {
        return;
      }

      if (this.grafico === null) {
        this.grafico = this.criarGrafico(canvas, this.configuracao());
      }

      this.desenhar(serie);
    });
  }

  /**
   * O que um leitor de tela anuncia no lugar do desenho.
   *
   * Um `<canvas>` é opaco para tecnologia assistiva: sem isto, o gráfico
   * simplesmente não existe para quem não o enxerga. A frase carrega o que a
   * linha mostra — a tendência —, não a lista de pontos.
   */
  descricao(): string {
    const medidos = this.serie().filter((ponto) => ponto.score !== null);

    if (medidos.length === 0) {
      return 'Gráfico do seu engajamento ao longo da sessão. Ainda sem medições.';
    }

    const ultimo = Math.round(medidos[medidos.length - 1].score!);
    const media = Math.round(
      medidos.reduce((soma, ponto) => soma + ponto.score!, 0) / medidos.length,
    );

    return `Gráfico do seu engajamento ao longo da sessão. Agora em ${ultimo} de 100, média de ${media}.`;
  }

  private desenhar(serie: readonly PontoDoIEE[]): void {
    const grafico = this.grafico;
    if (grafico === null) {
      return;
    }

    grafico.data.labels = serie.map((ponto) => this.rotulo(ponto.instante));
    // `null` no lugar do valor é o que faz o chart.js **interromper** a linha.
    // Ligar os dois lados de um trecho não medido desenharia uma medição que
    // não houve, que é o que a ticket 10 evita no banco e não pode reintroduzir
    // na tela.
    grafico.data.datasets[0].data = serie.map((ponto) => ponto.score);

    // Sem animação: a série anda um ponto por segundo, e animar cada chegada
    // deixa a linha em movimento perpétuo no canto do olho de quem está
    // tentando estudar.
    grafico.update('none');
  }

  private rotulo(instante: number): string {
    return new Date(instante).toLocaleTimeString(undefined, {
      hour: '2-digit',
      minute: '2-digit',
    });
  }

  private configuracao(): ChartConfiguration<'line'> {
    return {
      type: 'line',
      data: { labels: [], datasets: [{ label: 'IEE', data: [] }] },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        // A linha é lida como tendência, não como leitura pontual: um tooltip
        // por ponto convidaria o aluno a caçar segundos individuais de um sinal
        // que só significa alguma coisa agregado.
        plugins: { legend: { display: false }, tooltip: { enabled: false } },
        elements: {
          // Sem ponto desenhado: a 1 Hz eles viram uma faixa sólida.
          point: { radius: 0 },
          line: { tension: 0.3, borderWidth: 2 },
        },
        scales: {
          y: {
            // Fixo em 0–100 de propósito. Escala automática faria uma oscilação
            // de três pontos ocupar o gráfico inteiro, e o aluno leria como
            // desabamento o que é ruído.
            min: 0,
            max: 100,
            ticks: { stepSize: 25 },
          },
          x: {
            // Um rótulo a cada minuto, aproximadamente: a 1 Hz, mostrar todos
            // empilharia sessenta horários ilegíveis por minuto de sessão.
            ticks: { maxTicksLimit: 6, autoSkip: true },
          },
        },
      },
    };
  }

  ngOnDestroy(): void {
    // O chart.js registra listeners de resize no `window`; sem `destroy` eles
    // sobrevivem à tela e vazam a cada entrada e saída da sessão.
    this.grafico?.destroy();
    this.grafico = null;
  }
}
