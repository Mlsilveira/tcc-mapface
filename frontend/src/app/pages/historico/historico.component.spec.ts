import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { ItemDoHistorico } from '../../core/services/relatorio.service';
import { HistoricoComponent } from './historico.component';

const API = 'http://localhost:8000';

function item(parcial: Partial<ItemDoHistorico> = {}): ItemDoHistorico {
  return {
    id_sessao: 7,
    inicio: '2026-08-13T12:00:00Z',
    fim: '2026-08-13T12:30:30Z',
    parcial: false,
    duracao_s: 1830,
    n_leituras: 1800,
    score_medio: 72.4,
    teve_fadiga: false,
    ...parcial,
  };
}

describe('HistoricoComponent', () => {
  let fixture: ComponentFixture<HistoricoComponent>;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [HistoricoComponent],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    });

    httpMock = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(HistoricoComponent);
  });

  afterEach(() => {
    httpMock.verify();
  });

  function elemento(teste: string): HTMLElement | null {
    return fixture.nativeElement.querySelector(`[data-teste="${teste}"]`);
  }

  function responder(itens: ItemDoHistorico[]): void {
    fixture.detectChanges();
    const requisicao = httpMock.expectOne(`${API}/sessoes`);
    expect(requisicao.request.method).toBe('GET');
    requisicao.flush(itens);
    fixture.detectChanges();
  }

  it('avisa que está buscando enquanto o backend não responde', () => {
    fixture.detectChanges();

    expect(elemento('carregando')).toBeTruthy();

    httpMock.expectOne(`${API}/sessoes`).flush([]);
  });

  it('lista as sessões do aluno na ordem em que o backend as manda', () => {
    // A ordenação é do backend (da mais recente para a mais antiga); reordenar
    // aqui criaria uma segunda regra para manter em dia.
    responder([item({ id_sessao: 9 }), item({ id_sessao: 4 })]);

    const links = Array.from(
      elemento('sessoes')?.querySelectorAll('a') ?? [],
    ).map((a) => a.getAttribute('href'));

    expect(links).toEqual(['/relatorio/9', '/relatorio/4']);
  });

  it('leva ao relatório completo de cada sessão anterior', () => {
    responder([item({ id_sessao: 42 })]);

    expect(elemento('sessao-42')?.getAttribute('href')).toBe('/relatorio/42');
  });

  it('mostra a duração e o índice médio de cada sessão', () => {
    responder([item()]);

    // 1830s = 30:30, e 72,4 arredondado.
    expect(elemento('sessao-7')?.textContent).toContain('30:30');
    expect(elemento('sessao-7')?.textContent).toContain('72');
  });

  it('marca a sessão que não foi encerrada', () => {
    responder([item({ fim: null, parcial: true, duracao_s: 0 })]);

    expect(elemento('selo-parcial')).toBeTruthy();
    // Sem "00:00" ao lado de "não encerrada": a sessão não durou zero, ela
    // ainda não tem fim para medir contra.
    expect(elemento('sessao-7')?.textContent).not.toContain('00:00');
  });

  it('não marca como parcial a sessão encerrada normalmente', () => {
    responder([item()]);

    expect(elemento('selo-parcial')).toBeNull();
  });

  it('sinaliza a sessão em que houve registro de cansaço', () => {
    responder([item({ teve_fadiga: true })]);

    expect(elemento('selo-fadiga')).toBeTruthy();
  });

  it('não mostra score de sessão sem nenhuma leitura', () => {
    // Webcam negada: "índice médio 0" afirmaria que o aluno esteve disperso,
    // quando o que houve foi ausência de medição.
    responder([item({ n_leituras: 0, score_medio: 0 })]);

    expect(elemento('sessao-7')?.textContent).toContain('sem medição');
    expect(elemento('sessao-7')?.textContent).not.toContain('0/100');
  });

  it('explica a lista vazia em vez de mostrar um painel em branco', () => {
    responder([]);

    expect(elemento('historico-vazio')).toBeTruthy();
    expect(elemento('sessoes')).toBeNull();
  });

  it('avisa quando o backend falha ao listar as sessões', () => {
    fixture.detectChanges();
    httpMock.expectOne(`${API}/sessoes`).flush({}, { status: 500, statusText: 'Server Error' });
    fixture.detectChanges();

    expect(elemento('erro')?.textContent).toContain('Não foi possível carregar suas sessões');
    expect(elemento('historico-vazio')).toBeNull();
  });
});
