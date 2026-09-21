import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { of, throwError } from 'rxjs';

import { RelatorioService, SessaoNoHistorico } from '../../core/services/relatorio.service';
import { HistoricoComponent } from './historico.component';

const SESSAO: SessaoNoHistorico = {
  id: 7,
  inicio: '2026-09-21T12:00:00Z',
  fim: '2026-09-21T12:40:00Z',
  parcial: false,
  duracao_presente_s: 1800,
  media: 72.4,
  pontos_medidos: 1750,
  alertas: 3,
  metodo: 'pomodoro',
  metodo_nome: 'Pomodoro',
  assunto: 'Cálculo II',
};

describe('HistoricoComponent', () => {
  let fixture: ComponentFixture<HistoricoComponent>;
  let relatorioService: jasmine.SpyObj<RelatorioService>;

  function montar(): void {
    TestBed.configureTestingModule({
      imports: [HistoricoComponent],
      providers: [provideRouter([]), { provide: RelatorioService, useValue: relatorioService }],
    });

    fixture = TestBed.createComponent(HistoricoComponent);
    fixture.detectChanges();
  }

  function elemento(teste: string): HTMLElement | null {
    return fixture.nativeElement.querySelector(`[data-teste="${teste}"]`);
  }

  function texto(teste: string): string {
    return elemento(teste)?.textContent?.replace(/\s+/g, ' ').trim() ?? '';
  }

  beforeEach(() => {
    relatorioService = jasmine.createSpyObj<RelatorioService>('RelatorioService', [
      'buscar',
      'historico',
    ]);
    relatorioService.historico.and.returnValue(of([SESSAO]));
    TestBed.resetTestingModule();
  });

  it('lista as sessões encerradas com o resumo de cada uma', () => {
    montar();

    const linha = texto('historico-lista');
    expect(linha).toContain('30min');
    expect(linha).toContain('72');
    expect(linha).toContain('3');
  });

  it('leva ao relatório da sessão escolhida', () => {
    montar();

    const link = elemento('historico-lista')!.querySelector('a');
    expect(link!.getAttribute('href')).toBe('/relatorio/7');
  });

  it('mostra um traço, e nunca zero, na sessão sem medida', () => {
    // Mesma distinção do relatório: "não deu para medir" não é "índice zero".
    relatorioService.historico.and.returnValue(of([{ ...SESSAO, media: null, pontos_medidos: 0 }]));
    montar();

    expect(texto('historico-lista')).toContain('—');
  });

  it('mostra o método e o assunto declarados na sessão', () => {
    montar();

    expect(texto('historico-metodo')).toContain('Pomodoro');
    expect(texto('historico-metodo')).toContain('Cálculo II');
  });

  it('mostra um traço, e nunca "Sem método", na sessão anterior ao recurso (AC-17-11)', () => {
    // `null` é "esta sessão é anterior ao recurso"; "livre" é "o aluno escolheu
    // estudar sem método". Colapsá-los na tela inventaria uma escolha que
    // ninguém fez — a mesma disciplina do traço no lugar do zero.
    relatorioService.historico.and.returnValue(
      of([{ ...SESSAO, metodo: null, metodo_nome: null, assunto: null }]),
    );
    montar();

    expect(texto('historico-metodo')).toBe('—');
    expect(texto('historico-metodo')).not.toContain('Sem método');
  });

  it('mostra o nome da escolha quando o aluno escolheu não usar método', () => {
    relatorioService.historico.and.returnValue(
      of([{ ...SESSAO, metodo: 'livre', metodo_nome: 'Sem método', assunto: null }]),
    );
    montar();

    expect(texto('historico-metodo')).toBe('Sem método');
  });

  it('marca a sessão que não foi encerrada pelo aluno', () => {
    relatorioService.historico.and.returnValue(of([{ ...SESSAO, parcial: true }]));
    montar();

    expect(texto('historico-parcial')).toBe('Parcial');
  });

  it('não marca como parcial a sessão encerrada normalmente', () => {
    montar();

    expect(elemento('historico-parcial')).toBeNull();
  });

  it('convida a começar quando ainda não há sessão nenhuma', () => {
    // Lista vazia é um estado esperado — é o primeiro acesso de todo aluno —,
    // e não uma falha a ser reportada.
    relatorioService.historico.and.returnValue(of([]));
    montar();

    expect(elemento('historico-vazio')).toBeTruthy();
    expect(elemento('historico-erro')).toBeNull();
  });

  it('avisa quando não consegue carregar as sessões', () => {
    relatorioService.historico.and.returnValue(throwError(() => new Error('rede')));
    montar();

    expect(texto('historico-erro')).toContain('Não foi possível carregar');
    expect(elemento('historico-vazio')).toBeNull();
  });

  it('avisa enquanto busca', () => {
    relatorioService.historico.and.returnValue(
      new (class {
        subscribe(): { unsubscribe(): void } {
          return { unsubscribe: () => {} };
        }
      })() as never,
    );
    montar();

    expect(elemento('historico-carregando')).toBeTruthy();
  });
});
