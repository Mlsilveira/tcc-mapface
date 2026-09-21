import { Component, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import {
  CRIADOR_DE_GRAFICO,
  GraficoDeLinha,
  GraficoIeeComponent,
  PontoDoIEE,
} from './grafico-iee.component';

/**
 * Dublê do chart.js. A biblioteca é um boundary como o MediaPipe e o HTTP:
 * desenha em canvas de verdade e mede texto com as fontes do navegador, o que
 * num teste de unidade só produz fragilidade. O que interessa afirmar aqui é o
 * que o componente **manda** desenhar.
 */
class GraficoFalso implements GraficoDeLinha {
  static criados: GraficoFalso[] = [];

  readonly data = { labels: [] as unknown[], datasets: [{ data: [] as unknown[] }] };
  atualizacoes: Array<string | undefined> = [];
  destruido = false;

  constructor(readonly canvas: HTMLCanvasElement) {
    GraficoFalso.criados.push(this);
  }

  update(modo?: string): void {
    this.atualizacoes.push(modo);
  }

  destroy(): void {
    this.destruido = true;
  }

  get valores(): unknown[] {
    return this.data.datasets[0].data;
  }
}

@Component({
  standalone: true,
  imports: [GraficoIeeComponent],
  template: `<app-grafico-iee [serie]="serie()" />`,
})
class Hospedeiro {
  readonly serie = signal<readonly PontoDoIEE[]>([]);
}

function ponto(score: number | null, minuto = 0): PontoDoIEE {
  return { instante: Date.UTC(2026, 7, 27, 10, minuto), score };
}

describe('GraficoIeeComponent', () => {
  let fixture: ComponentFixture<Hospedeiro>;
  let hospedeiro: Hospedeiro;

  function grafico(): GraficoFalso {
    return GraficoFalso.criados[0];
  }

  beforeEach(() => {
    GraficoFalso.criados = [];

    TestBed.configureTestingModule({
      imports: [Hospedeiro],
      providers: [
        {
          provide: CRIADOR_DE_GRAFICO,
          useValue: (canvas: HTMLCanvasElement) => new GraficoFalso(canvas),
        },
      ],
    });

    fixture = TestBed.createComponent(Hospedeiro);
    hospedeiro = fixture.componentInstance;
  });

  it('desenha a série recebida', () => {
    hospedeiro.serie.set([ponto(80), ponto(60, 1)]);
    fixture.detectChanges();

    expect(grafico().valores).toEqual([80, 60]);
  });

  it('cria um gráfico só, e o atualiza a cada série nova', () => {
    // Recriar o gráfico a cada ponto perderia a escala e piscaria a tela uma vez
    // por segundo.
    hospedeiro.serie.set([ponto(80)]);
    fixture.detectChanges();

    hospedeiro.serie.set([ponto(80), ponto(70, 1)]);
    fixture.detectChanges();

    expect(GraficoFalso.criados.length).toBe(1);
    expect(grafico().valores).toEqual([80, 70]);
  });

  it('interrompe a linha nos pontos não medidos', () => {
    // `null` é o que faz o chart.js quebrar a linha. Substituí-lo por zero
    // desenharia uma queda a zero que não houve; omiti-lo ligaria os dois lados
    // como se o trecho tivesse sido medido.
    hospedeiro.serie.set([ponto(80), ponto(null, 1), ponto(75, 2)]);
    fixture.detectChanges();

    expect(grafico().valores).toEqual([80, null, 75]);
  });

  it('atualiza sem animação', () => {
    // A série anda um ponto por segundo; animar cada chegada deixa a linha em
    // movimento perpétuo no canto do olho de quem está tentando estudar.
    hospedeiro.serie.set([ponto(80)]);
    fixture.detectChanges();

    expect(grafico().atualizacoes).toContain('none');
  });

  it('descreve a tendência para quem não vê o desenho', () => {
    // Um <canvas> é opaco para leitor de tela: sem rótulo, o gráfico
    // simplesmente não existe para quem não o enxerga.
    hospedeiro.serie.set([ponto(90), ponto(70, 1)]);
    fixture.detectChanges();

    const rotulo = fixture.nativeElement.querySelector('canvas').getAttribute('aria-label');
    expect(rotulo).toContain('70 de 100');
    expect(rotulo).toContain('média de 80');
  });

  it('descreve a ausência de medições sem inventar número', () => {
    hospedeiro.serie.set([ponto(null), ponto(null, 1)]);
    fixture.detectChanges();

    const rotulo = fixture.nativeElement.querySelector('canvas').getAttribute('aria-label');
    expect(rotulo).toContain('Ainda sem medições');
  });

  it('destrói o gráfico ao sair da tela', () => {
    // O chart.js registra listeners de resize no window; sem `destroy` eles
    // sobrevivem à tela e vazam a cada entrada e saída da sessão.
    hospedeiro.serie.set([ponto(80)]);
    fixture.detectChanges();

    fixture.destroy();

    expect(grafico().destruido).toBeTrue();
  });
});
