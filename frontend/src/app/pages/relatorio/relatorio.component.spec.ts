import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, provideRouter } from '@angular/router';

import {
  CRIADOR_DE_GRAFICO,
  CriadorDeGrafico,
  GraficoDeLinha,
} from '../../shared/grafico-iee.component';
import {
  ALERTA_INCERTEZA,
  IndicadoresDoRelatorio,
  Relatorio,
} from '../../core/services/relatorio.service';
import { RelatorioComponent } from './relatorio.component';

const API = 'http://localhost:8000';

const INDICADORES: IndicadoresDoRelatorio = {
  n_leituras: 1800,
  duracao_s: 1830,
  score_medio: 72.4,
  score_minimo: 31,
  score_maximo: 95,
  score_inicio: 80,
  score_fim: 58,
  prop_com_rosto: 0.92,
  prop_com_fadiga: 0.11,
  fadiga_maxima: 12,
  desvio_olhar_medio: 8.4,
  prop_captura_incerta: 0.05,
};

function relatorio(parcial: Partial<Relatorio> = {}): Relatorio {
  return {
    id_sessao: 7,
    inicio: '2026-08-13T12:00:00Z',
    fim: '2026-08-13T12:30:30Z',
    parcial: false,
    indicadores: INDICADORES,
    serie: [{ horario: '2026-08-13T12:00:00Z', score: 70, fadiga: 0, alerta: null }],
    alertas: { bocejos: 3, 'olhos-fechados-prolongados': 12 },
    recomendacoes: ['Considere uma pausa antes do próximo bloco de estudo.'],
    ...parcial,
  };
}

/**
 * Dublê do chart.js. A biblioteca desenha em canvas de verdade e mede texto com
 * as fontes do navegador; num teste de unidade isso só produz fragilidade. O
 * que importa aqui é **qual série** o componente entrega ao gráfico.
 */
class GraficoFalso implements GraficoDeLinha {
  readonly data = { labels: [] as unknown[], datasets: [{ data: [] as unknown[] }] };
  update(): void {}
  destroy(): void {}
}

describe('RelatorioComponent', () => {
  let fixture: ComponentFixture<RelatorioComponent>;
  let httpMock: HttpTestingController;
  let grafico: GraficoFalso;

  function montar(id: string): void {
    TestBed.configureTestingModule({
      imports: [RelatorioComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        {
          provide: ActivatedRoute,
          useValue: { snapshot: { paramMap: new Map([['id', id]]) } },
        },
        { provide: CRIADOR_DE_GRAFICO, useValue: ((): GraficoDeLinha => grafico) as CriadorDeGrafico },
      ],
    });

    httpMock = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(RelatorioComponent);
  }

  beforeEach(() => {
    grafico = new GraficoFalso();
    TestBed.resetTestingModule();
  });

  afterEach(() => {
    httpMock.verify();
  });

  function elemento(teste: string): HTMLElement | null {
    return fixture.nativeElement.querySelector(`[data-teste="${teste}"]`);
  }

  function texto(): string {
    return fixture.nativeElement.textContent ?? '';
  }

  function responder(corpo: Relatorio = relatorio(), id = 7): void {
    fixture.detectChanges();
    httpMock.expectOne(`${API}/sessoes/${id}/relatorio`).flush(corpo);
    fixture.detectChanges();
  }

  it('avisa que está montando o relatório enquanto o backend não responde', () => {
    montar('7');
    fixture.detectChanges();

    expect(elemento('carregando')).toBeTruthy();

    httpMock.expectOne(`${API}/sessoes/7/relatorio`).flush(relatorio());
  });

  it('mostra os indicadores-chave da sessão', () => {
    montar('7');
    responder();

    expect(elemento('score-medio')?.textContent).toContain('72');
    expect(elemento('score-faixa')?.textContent).toContain('31');
    expect(elemento('score-faixa')?.textContent).toContain('95');
    expect(elemento('presenca')?.textContent).toContain('92%');
    expect(elemento('captura-incerta')?.textContent).toContain('5%');
  });

  it('mostra o período e a duração da sessão', () => {
    montar('7');
    responder();

    // 1830s = 30:30. A duração vem do intervalo medido, não do relógio da tela.
    expect(elemento('periodo')?.textContent).toContain('30:30');
  });

  it('destaca a queda quando o índice cai entre o começo e o fim', () => {
    montar('7');
    responder();

    // 80 → 58: 22 pontos, acima do limiar de tendência do backend.
    expect(elemento('tendencia')?.textContent).toContain('22');
  });

  it('não inventa seta de tendência quando a variação é pequena', () => {
    montar('7');
    responder(
      relatorio({ indicadores: { ...INDICADORES, score_inicio: 70, score_fim: 66 } }),
    );

    expect(elemento('tendencia')?.querySelector('.tendencia--queda')).toBeNull();
  });

  it('lista os alertas registrados, do mais frequente para o menos', () => {
    montar('7');
    responder();

    const itens = Array.from(
      elemento('alertas')?.querySelectorAll('li') ?? [],
    ).map((li) => li.textContent ?? '');

    expect(itens.length).toBe(2);
    expect(itens[0]).toContain('Olhos fechados por vários segundos');
    expect(itens[1]).toContain('Bocejos');
  });

  it('omite a seção de alertas quando não houve nenhum', () => {
    montar('7');
    responder(relatorio({ alertas: {} }));

    expect(elemento('alertas')).toBeNull();
  });

  it('mostra as recomendações de autorregulação vindas do backend', () => {
    montar('7');
    responder();

    expect(elemento('recomendacoes')?.textContent).toContain(
      'Considere uma pausa antes do próximo bloco',
    );
  });

  it('entrega ao gráfico a série da sessão, com os trechos incertos apagados', () => {
    montar('7');
    responder(
      relatorio({
        serie: [
          { horario: '2026-08-13T12:00:00Z', score: 80, fadiga: 0, alerta: null },
          { horario: '2026-08-13T12:00:01Z', score: 10, fadiga: 0, alerta: ALERTA_INCERTEZA },
          { horario: '2026-08-13T12:00:02Z', score: 76, fadiga: 0, alerta: null },
        ],
      }),
    );

    expect(grafico.data.datasets[0].data).toEqual([80, null, 76]);
  });

  it('avisa que o relatório é parcial quando a sessão não foi encerrada', () => {
    montar('7');
    responder(relatorio({ fim: null, parcial: true }));

    expect(elemento('relatorio-parcial')).toBeTruthy();
    expect(texto()).toContain('não foi encerrada');
  });

  it('não afirma a causa de a sessão estar aberta', () => {
    // `parcial` só diz que a sessão não tem `fim`, e isso inclui a sessão que
    // está correndo agora — alcançável pelo histórico da ticket 12. Dizer que
    // o navegador caiu seria afirmar uma causa que não sabemos, o mesmo erro
    // que a ticket 10 evita ao nomear o alerta de "incerteza".
    montar('7');
    responder(relatorio({ fim: null, parcial: true }));

    const aviso = elemento('relatorio-parcial')?.textContent ?? '';
    expect(aviso).not.toContain('caíram');
    expect(aviso).not.toContain('navegador');
    expect(aviso).not.toContain('conexão');
  });

  it('não chama a sessão de parcial quando ela foi encerrada normalmente', () => {
    montar('7');
    responder();

    expect(elemento('relatorio-parcial')).toBeNull();
  });

  it('explica a ausência de medição em vez de mostrar zeros', () => {
    // Webcam negada: a sessão existiu, mas nada foi medido. Mostrar "índice
    // médio 0" afirmaria que o aluno esteve disperso, que é o oposto do que
    // aconteceu.
    montar('7');
    responder(
      relatorio({
        indicadores: { ...INDICADORES, n_leituras: 0 },
        serie: [],
        alertas: {},
        recomendacoes: ['Não houve medição nesta sessão — a webcam pode não ter sido autorizada.'],
      }),
    );

    expect(elemento('sem-medicao')).toBeTruthy();
    expect(elemento('score-medio')).toBeNull();
    // A recomendação continua aparecendo: é ela que diz o que fazer a respeito.
    expect(elemento('recomendacoes')?.textContent).toContain('Não houve medição');
  });

  it('explica quando a sessão não é do aluno autenticado', () => {
    montar('7');
    fixture.detectChanges();
    httpMock
      .expectOne(`${API}/sessoes/7/relatorio`)
      .flush({}, { status: 404, statusText: 'Not Found' });
    fixture.detectChanges();

    expect(elemento('erro')?.textContent).toContain('não existe ou não é sua');
  });

  it('avisa quando o backend falha ao montar o relatório', () => {
    montar('7');
    fixture.detectChanges();
    httpMock
      .expectOne(`${API}/sessoes/7/relatorio`)
      .flush({}, { status: 500, statusText: 'Server Error' });
    fixture.detectChanges();

    expect(elemento('erro')?.textContent).toContain('Não foi possível carregar');
  });

  it('recusa um id que não é sessão sem chegar a consultar o backend', () => {
    montar('abacaxi');
    fixture.detectChanges();

    expect(elemento('erro')?.textContent).toContain('Sessão inválida');
    httpMock.expectNone(() => true);
  });
});
