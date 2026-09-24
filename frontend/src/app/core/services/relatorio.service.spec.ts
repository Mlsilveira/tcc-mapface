import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { API_URL as API } from '../api';
import { Relatorio, RelatorioService, SessaoNoHistorico } from './relatorio.service';


const RELATORIO: Relatorio = {
  id_sessao: 7,
  inicio: '2026-09-21T12:00:00Z',
  fim: '2026-09-21T12:40:00Z',
  parcial: false,
  duracao_total_s: 2400,
  duracao_presente_s: 1800,
  media: 72.5,
  pico: 95,
  vale: 0,
  pontos_medidos: 1750,
  pontos_incertos: 50,
  pontos_zerados: 12,
  alertas_de_fadiga: [{ codigo: 'bocejos', nome: 'Bocejos', ocorrencias: 3 }],
  motivos_de_incerteza: [],
  recomendacoes: [],
  serie: [
    { instante: '2026-09-21T12:00:00Z', score: 80, alerta: null },
    { instante: '2026-09-21T12:00:01Z', score: null, alerta: 'baixa-luz' },
  ],
  metodo: 'pomodoro',
  metodo_nome: 'Pomodoro',
  assunto: 'Cálculo II',
  media_de_foco: 80,
  duracao_de_foco_s: 1500,
  duracao_de_pausa_s: 300,
  blocos: [
    {
      indice: 1,
      tipo: 'foco',
      tipo_nome: 'Foco',
      inicio: '2026-09-21T12:00:00Z',
      fim: '2026-09-21T12:25:00Z',
      duracao_s: 1500,
      duracao_com_captura_s: 1440,
      media: 80,
      pontos_medidos: 1440,
      pontos_incertos: 0,
      observacao: null,
    },
  ],
  criterios: [
    {
      codigo: 'cadencia',
      titulo: 'A duração dos seus blocos de foco',
      texto: 'Um bloco de foco ficou entre 20 e 30 minutos.',
      detalhe: 'Blocos de foco: 25 min.',
    },
  ],
  cadencia: {
    duracao_alvo_s: 1500,
    duracoes_observadas_s: [1500],
    blocos_na_faixa: 1,
    blocos_de_foco: 1,
    meta_de_blocos: 4,
  },
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

  afterEach(() => httpMock.verify());

  it('busca o relatório da sessão pedida', () => {
    let recebido: Relatorio | null = null;
    service.buscar(7).subscribe((relatorio) => (recebido = relatorio));

    const requisicao = httpMock.expectOne(`${API}/sessoes/7/relatorio`);
    expect(requisicao.request.method).toBe('GET');
    requisicao.flush(RELATORIO);

    expect(recebido!.media).toBe(72.5);
  });

  it('preserva o score nulo da série', () => {
    // O nulo é o que faz a linha do gráfico quebrar. Se o serviço o
    // normalizasse para zero "por conveniência", a ticket 10 seria desfeita na
    // última camada do caminho.
    let recebido: Relatorio | null = null;
    service.buscar(7).subscribe((relatorio) => (recebido = relatorio));
    httpMock.expectOne(`${API}/sessoes/7/relatorio`).flush(RELATORIO);

    expect(recebido!.serie.map((ponto) => ponto.score)).toEqual([80, null]);
  });

  it('entrega a cadência em contagem, sem nenhum campo de razão normalizada', () => {
    // A trava estrutural chega até aqui de propósito. `"aderência: 62%"` não
    // afirma estado interno nenhum — é aritmética sobre carimbos de tempo — e
    // passaria em silêncio por qualquer teste de texto. O que a barra é o
    // contrato: quem quiser o percentual precisa acrescentar campo dos dois
    // lados e justificar no PR.
    let recebido: Relatorio | null = null;
    service.buscar(7).subscribe((relatorio) => (recebido = relatorio));
    httpMock.expectOne(`${API}/sessoes/7/relatorio`).flush(RELATORIO);

    expect(Object.keys(recebido!.cadencia!).sort()).toEqual([
      'blocos_de_foco',
      'blocos_na_faixa',
      'duracao_alvo_s',
      'duracoes_observadas_s',
      'meta_de_blocos',
    ]);
  });

  it('propaga a falha em vez de devolver um relatório vazio', () => {
    // Relatório vazio e relatório inexistente são estados diferentes, e a tela
    // precisa poder dizer coisas diferentes sobre eles.
    const falhou: { status?: number } = {};
    service.buscar(99).subscribe({ error: (falha) => (falhou.status = falha.status) });

    httpMock
      .expectOne(`${API}/sessoes/99/relatorio`)
      .flush({}, { status: 404, statusText: 'Not Found' });

    expect(falhou.status).toBe(404);
  });

  it('busca o histórico do aluno autenticado', () => {
    let recebido: SessaoNoHistorico[] = [];
    service.historico().subscribe((sessoes) => (recebido = sessoes));

    const requisicao = httpMock.expectOne(`${API}/sessoes/historico`);
    expect(requisicao.request.method).toBe('GET');
    // O backend resolve o aluno pelo token; mandar id na URL abriria espaço
    // para pedir o histórico de outra pessoa.
    expect(requisicao.request.url).not.toContain('aluno');
    requisicao.flush([]);

    expect(recebido).toEqual([]);
  });
});
