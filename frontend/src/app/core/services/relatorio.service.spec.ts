import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import {
  ALERTA_INCERTEZA,
  PontoDoRelatorio,
  Relatorio,
  RelatorioService,
  serieParaOGrafico,
} from './relatorio.service';

const API = 'http://localhost:8000';

function ponto(parcial: Partial<PontoDoRelatorio> = {}): PontoDoRelatorio {
  return {
    horario: '2026-08-13T12:00:00Z',
    score: 70,
    fadiga: 0,
    alerta: null,
    ...parcial,
  };
}

const RELATORIO: Relatorio = {
  id_sessao: 7,
  inicio: '2026-08-13T12:00:00Z',
  fim: '2026-08-13T12:30:00Z',
  parcial: false,
  indicadores: {
    n_leituras: 1800,
    duracao_s: 1800,
    score_medio: 72.5,
    score_minimo: 30,
    score_maximo: 95,
    score_inicio: 80,
    score_fim: 60,
    prop_com_rosto: 0.92,
    prop_com_fadiga: 0.1,
    fadiga_maxima: 12,
    desvio_olhar_medio: 8.4,
    prop_captura_incerta: 0.05,
  },
  serie: [ponto()],
  alertas: { bocejos: 3 },
  recomendacoes: ['Sessão estável, sem sinais relevantes de dispersão ou cansaço.'],
};

describe('RelatorioService', () => {
  let service: RelatorioService;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    service = TestBed.inject(RelatorioService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('busca o relatório da sessão pedida', () => {
    const recebidos: Relatorio[] = [];
    service.buscar(7).subscribe((relatorio) => recebidos.push(relatorio));

    const requisicao = httpMock.expectOne(`${API}/sessoes/7/relatorio`);
    expect(requisicao.request.method).toBe('GET');
    requisicao.flush(RELATORIO);

    expect(recebidos).toEqual([RELATORIO]);
  });
});

describe('serieParaOGrafico', () => {
  it('converte o horário ISO em instante e preserva o score medido', () => {
    const convertida = serieParaOGrafico([ponto({ horario: '2026-08-13T12:00:00Z', score: 64 })]);

    expect(convertida).toEqual([
      { instante: Date.parse('2026-08-13T12:00:00Z'), score: 64 },
    ]);
  });

  it('apaga o score dos instantes de captura incerta', () => {
    const convertida = serieParaOGrafico([
      ponto({ score: 80 }),
      ponto({ score: 12, alerta: ALERTA_INCERTEZA }),
      ponto({ score: 75 }),
    ]);

    // `null` no meio, e não o 12 gravado: o backend deixou aquele instante de
    // fora dos indicadores, e desenhá-lo faria a linha contradizer os números.
    expect(convertida.map((p) => p.score)).toEqual([80, null, 75]);
  });

  it('reconhece a incerteza quando ela vem acompanhada de outros motivos', () => {
    const convertida = serieParaOGrafico([
      ponto({ score: 40, alerta: `bocejos,${ALERTA_INCERTEZA}` }),
    ]);

    expect(convertida[0].score).toBeNull();
  });

  it('não confunde outro alerta com incerteza', () => {
    // Fadiga é uma medição válida: o score baixo ali é sobre o aluno, e a linha
    // precisa mostrá-lo. Só a incerteza significa "não sabemos".
    const convertida = serieParaOGrafico([ponto({ score: 35, alerta: 'olhos-fechados-prolongados' })]);

    expect(convertida[0].score).toBe(35);
  });
});
