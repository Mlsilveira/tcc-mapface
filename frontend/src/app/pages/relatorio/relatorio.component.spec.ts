import { HttpErrorResponse } from '@angular/common/http';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { ActivatedRoute, provideRouter } from '@angular/router';
import { of, throwError } from 'rxjs';

import {
  BlocoDoRelatorio,
  Relatorio,
  RelatorioService,
} from '../../core/services/relatorio.service';
import {
  CRIADOR_DE_GRAFICO,
  GraficoDeLinha,
  GraficoIeeComponent,
} from '../../shared/grafico-iee.component';
import { RelatorioComponent } from './relatorio.component';

/** Dublê do chart.js, no mesmo molde de `grafico-iee.component.spec.ts`. */
class GraficoFalso implements GraficoDeLinha {
  readonly data = { labels: [] as unknown[], datasets: [{ data: [] as unknown[] }] };
  update(): void {}
  destroy(): void {}
}

const RELATORIO: Relatorio = {
  id_sessao: 7,
  inicio: '2026-09-21T12:00:00Z',
  fim: '2026-09-21T12:40:00Z',
  parcial: false,
  duracao_total_s: 2400,
  duracao_presente_s: 1800,
  media: 72.4,
  pico: 95,
  vale: 12,
  sonolencia_media: null,
  pontos_medidos: 1750,
  pontos_incertos: 50,
  pontos_zerados: 12,
  alertas_de_fadiga: [{ codigo: 'bocejos', nome: 'Bocejos', ocorrencias: 3 }],
  motivos_de_incerteza: [{ codigo: 'baixa-luz', nome: 'Pouca luz no ambiente', ocorrencias: 50 }],
  recomendacoes: [
    {
      codigo: 'pausa',
      titulo: 'Faça uma pausa curta',
      texto: 'Cinco a dez minutos longe da tela.',
      motivo: 'Bocejos: 3 registros.',
    },
  ],
  serie: [
    { instante: '2026-09-21T12:00:00Z', score: 80, alerta: null },
    { instante: '2026-09-21T12:00:01Z', score: null, alerta: 'baixa-luz' },
    { instante: '2026-09-21T12:00:02Z', score: 60, alerta: null },
  ],
  metodo: 'pomodoro',
  metodo_nome: 'Pomodoro',
  assunto: 'Cálculo II',
  media_de_foco: 68.2,
  duracao_de_foco_s: 3060,
  duracao_de_pausa_s: 600,
  blocos: [
    bloco(1, 'foco', 'Foco', 1500, 1440, 72),
    bloco(2, 'pausa', 'Pausa', 300, 300, null),
    bloco(3, 'foco', 'Foco', 1560, 1500, 64),
  ],
  criterios: [
    {
      codigo: 'cadencia',
      titulo: 'A duração dos seus blocos de foco',
      texto: 'Dois dos dois blocos de foco ficaram entre 20 e 30 minutos.',
      detalhe: 'Blocos de foco: 25 min, 26 min.',
    },
    {
      codigo: 'pausas',
      titulo: 'As pausas ficam fora da média',
      texto: 'Você declarou uma pausa, somando 5 min.',
      detalhe: '5 min declarados em pausa.',
    },
  ],
  cadencia: {
    duracao_alvo_s: 1500,
    duracoes_observadas_s: [1500, 1560],
    blocos_na_faixa: 2,
    blocos_de_foco: 2,
    meta_de_blocos: 4,
  },
};

function bloco(
  indice: number,
  tipo: string,
  tipoNome: string,
  duracao: number,
  captura: number,
  media: number | null,
  observacao: string | null = null,
): BlocoDoRelatorio {
  return {
    indice,
    tipo,
    tipo_nome: tipoNome,
    inicio: '2026-09-21T12:00:00Z',
    fim: '2026-09-21T12:25:00Z',
    duracao_s: duracao,
    duracao_com_captura_s: captura,
    media,
    pontos_medidos: media === null ? 0 : 1400,
    pontos_incertos: 0,
    observacao,
  };
}

/** Uma sessão anterior ao recurso de métodos: `metodo` nulo e nada derivado dele. */
function semMetodo(): Relatorio {
  return {
    ...RELATORIO,
    metodo: null,
    metodo_nome: null,
    assunto: null,
    media_de_foco: null,
    duracao_de_foco_s: 0,
    duracao_de_pausa_s: 0,
    blocos: [],
    criterios: [],
    cadencia: null,
  };
}

function comoVazio(): Relatorio {
  return {
    ...RELATORIO,
    media: null,
    pico: null,
    vale: null,
    sonolencia_media: null,
    pontos_medidos: 0,
    pontos_incertos: 0,
    pontos_zerados: 0,
    alertas_de_fadiga: [],
    motivos_de_incerteza: [],
    serie: [],
    recomendacoes: [
      {
        codigo: 'sem-dados',
        titulo: 'Esta sessão não gerou medições',
        texto: 'Nenhuma leitura chegou ao servidor.',
        motivo: 'Nenhum ponto registrado.',
      },
    ],
  };
}

describe('RelatorioComponent', () => {
  let fixture: ComponentFixture<RelatorioComponent>;
  let relatorioService: jasmine.SpyObj<RelatorioService>;

  function montar(id = '7'): void {
    TestBed.configureTestingModule({
      imports: [RelatorioComponent],
      providers: [
        provideRouter([]),
        { provide: RelatorioService, useValue: relatorioService },
        { provide: CRIADOR_DE_GRAFICO, useValue: () => new GraficoFalso() },
        {
          provide: ActivatedRoute,
          useValue: { snapshot: { paramMap: new Map([['id', id]]) } },
        },
      ],
    });

    fixture = TestBed.createComponent(RelatorioComponent);
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
    relatorioService.buscar.and.returnValue(of(RELATORIO));
    TestBed.resetTestingModule();
  });

  describe('curva', () => {
    it('passa a série ao gráfico preservando os pontos não medidos', () => {
      // O nulo é o que faz a linha quebrar. Convertê-lo aqui desfaria a ticket
      // 10 na última linha do caminho, depois de ela ter sido respeitada no
      // navegador, no WebSocket, no banco e na API.
      montar();

      const grafico = fixture.debugElement.query(By.directive(GraficoIeeComponent));
      const serie = grafico.componentInstance.serie() as ReadonlyArray<{ score: number | null }>;

      expect(serie.map((ponto) => ponto.score)).toEqual([80, null, 60]);
    });

    it('converte o instante ISO em milissegundos para o gráfico', () => {
      montar();

      const grafico = fixture.debugElement.query(By.directive(GraficoIeeComponent));
      const serie = grafico.componentInstance.serie() as ReadonlyArray<{ instante: number }>;

      expect(serie[0].instante).toBe(Date.parse('2026-09-21T12:00:00Z'));
    });

    it('diz quanto tempo não pôde ser medido em vez de deixar a quebra sem explicação', () => {
      montar();

      expect(texto('relatorio-incerteza')).toContain('50s');
    });
  });

  describe('indicadores', () => {
    it('mostra o tempo medido ao lado do tempo de sessão aberta (AC-11-5)', () => {
      // Um sozinho engana: 40 minutos de aba aberta com 30 de captura não são
      // "40 minutos de estudo".
      montar();

      expect(texto('relatorio-duracao')).toBe('30min');
      expect(texto('relatorio-duracao-total')).toContain('40min');
    });

    it('mostra a leitura de sonolência como indicador à parte', () => {
      // À parte de propósito: ela não entrou no cálculo do índice. E a nota
      // vem junto do número porque um indicador que acerta dois terços das
      // vezes, apresentado sem ressalva, vira veredito na cabeça de quem lê.
      relatorioService.buscar.and.returnValue(of({ ...RELATORIO, sonolencia_media: 0.62 }));
      montar();

      expect(texto('relatorio-sonolencia')).toBe('62%');
      expect(texto('relatorio-media')).toBe('72');
    });

    it('esconde a sonolência quando não houve leitura', () => {
      // Sessão sem modelo carregado, ou curta demais para fechar a primeira
      // janela depois da calibração. Mostrar 0% diria "perfeitamente desperto",
      // que é afirmação diferente de "não houve leitura".
      relatorioService.buscar.and.returnValue(of({ ...RELATORIO, sonolencia_media: null }));
      montar();

      expect(elemento('relatorio-sonolencia')).toBeNull();
    });

    it('mostra média, pico e vale arredondados', () => {
      montar();

      expect(texto('relatorio-media')).toBe('72');
      expect(texto('relatorio-pico')).toBe('95');
      expect(texto('relatorio-vale')).toBe('12');
    });

    it('mostra um traço, e nunca zero, quando não houve medida', () => {
      // Zero diria "o aluno estava aqui e desengajado". O que houve foi
      // ausência de medição, que é outra afirmação.
      relatorioService.buscar.and.returnValue(
        of({ ...RELATORIO, media: null, pico: null, vale: null }),
      );
      montar();

      expect(texto('relatorio-media')).toBe('—');
      expect(texto('relatorio-pico')).toBe('—');
      expect(texto('relatorio-media')).not.toContain('0');
    });
  });

  describe('alertas', () => {
    it('nomeia os alertas de fadiga registrados', () => {
      montar();

      expect(texto('relatorio-fadiga')).toContain('Bocejos');
      expect(texto('relatorio-fadiga')).toContain('3 registros');
    });

    it('separa condição de captura de sinal observado no aluno', () => {
      // Fadiga é observação sobre a pessoa; incerteza é diagnóstico do
      // equipamento. Na mesma lista, "sua sala estava escura" soaria como um
      // defeito dele.
      montar();

      expect(texto('relatorio-captura')).toContain('Pouca luz no ambiente');
      expect(texto('relatorio-fadiga')).not.toContain('Pouca luz');
    });
  });

  describe('recomendações', () => {
    it('mostra a recomendação com a evidência que a originou (AC-11-3)', () => {
      montar();

      expect(texto('relatorio-recomendacoes')).toContain('Faça uma pausa curta');
      expect(texto('relatorio-recomendacoes')).toContain('Bocejos: 3 registros.');
    });

    it('continua aparecendo numa sessão sem medições', () => {
      relatorioService.buscar.and.returnValue(of(comoVazio()));
      montar();

      expect(texto('relatorio-recomendacoes')).toContain('não gerou medições');
    });
  });

  describe('método e blocos', () => {
    function elementos(teste: string): HTMLElement[] {
      return Array.from(fixture.nativeElement.querySelectorAll(`[data-teste="${teste}"]`));
    }

    it('lista os blocos executados com as duas durações lado a lado (AC-17-9)', () => {
      // Uma duração sozinha engana: "25min de bloco" não diz quanto daquilo
      // teve captura, e a diferença é a informação que o aluno foi buscar.
      montar();

      const blocos = elementos('relatorio-bloco');
      expect(blocos.length).toBe(3);
      expect(blocos[0].textContent).toContain('Bloco 1');
      expect(blocos[0].textContent).toContain('Foco');
      expect(blocos[0].textContent).toContain('25min declarados');
      expect(blocos[0].textContent).toContain('24min com captura');
      expect(blocos[1].textContent).toContain('Pausa');
    });

    it('mostra o índice médio dos blocos de foco separado do da sessão (AC-17-9)', () => {
      // A correção da ticket 17 na tela: a pausa não entra nesta conta, e a
      // legenda diz isso em voz alta para o número não ser lido como o outro.
      montar();

      expect(texto('relatorio-media-foco')).toBe('68');
      expect(texto('relatorio-foco')).toContain('as pausas ficam fora desta conta');
      expect(texto('relatorio-media')).toBe('72');
    });

    it('mostra a cadência em contagem e nunca em percentual (AC-17-10)', () => {
      // A frase vem pronta do backend justamente para que o percentual não
      // possa nascer aqui. O teste trava o que chega à tela.
      montar();

      expect(texto('relatorio-cadencia')).toContain('Dois dos dois blocos de foco');
      expect(texto('relatorio-cadencia')).toContain('entre 20 e 30 minutos');
      expect(texto('relatorio-cadencia')).not.toContain('%');
      expect(texto('relatorio-pausas')).toContain('fora da média');
    });

    it('renderiza um critério novo sem precisar de template novo', () => {
      // A lista de critérios é aberta de propósito: as frases nascem em
      // `app/criterios.py`, e um critério acrescentado lá precisa aparecer aqui
      // sem uma linha de Angular. Se a tela tivesse uma seção por código, o
      // primeiro critério novo sumiria em silêncio.
      relatorioService.buscar.and.returnValue(
        of({
          ...RELATORIO,
          criterios: [
            {
              codigo: 'medida',
              titulo: 'Onde o índice não pôde ser calculado',
              texto: 'Um traço no lugar do índice é a recusa de publicar um número.',
              detalhe: 'Bloco 2: curto demais para uma média.',
            },
          ],
        }),
      );
      montar();

      expect(texto('relatorio-criterio')).toContain('Onde o índice não pôde ser calculado');
      expect(elemento('relatorio-cadencia')).toBeNull();
    });

    it('mostra a frase do backend, e nunca zero, no bloco sem média', () => {
      relatorioService.buscar.and.returnValue(
        of({
          ...RELATORIO,
          blocos: [bloco(1, 'foco', 'Foco', 720, 720, null, 'Curto demais para uma média.')],
        }),
      );
      montar();

      const primeiro = elementos('relatorio-bloco')[0];
      expect(primeiro.textContent).toContain('Curto demais para uma média.');
      expect(primeiro.textContent).toContain('—');
      expect(primeiro.textContent).not.toContain('índice médio 0');
    });

    it('não desenha seção de método, cadência ou bloco na sessão sem método (AC-17-11)', () => {
      // Traço, e não "Sem método": `null` é "esta sessão é anterior ao recurso"
      // e "livre" é uma escolha do aluno. Colapsá-los na tela desfaria a
      // distinção que o modelo custou a preservar.
      relatorioService.buscar.and.returnValue(of(semMetodo()));
      montar();

      expect(texto('relatorio-metodo')).toBe('—');
      expect(texto('relatorio-metodo')).not.toContain('Sem método');
      expect(texto('relatorio-assunto')).toBe('—');
      expect(elemento('relatorio-blocos')).toBeNull();
      expect(elemento('relatorio-cadencia')).toBeNull();
      expect(elemento('relatorio-foco')).toBeNull();
    });

    it('mostra o nome do método escolhido quando ele foi "Sem método"', () => {
      // O outro lado da mesma distinção: aqui houve escolha, e ela aparece.
      relatorioService.buscar.and.returnValue(
        of({ ...RELATORIO, metodo: 'livre', metodo_nome: 'Sem método' }),
      );
      montar();

      expect(texto('relatorio-metodo')).toBe('Sem método');
    });
  });

  describe('estados', () => {
    it('avisa enquanto carrega', () => {
      relatorioService.buscar.and.returnValue(
        new (class {
          subscribe(): { unsubscribe(): void } {
            return { unsubscribe: () => {} };
          }
        })() as never,
      );
      montar();

      expect(elemento('relatorio-carregando')).toBeTruthy();
    });

    it('trata sessão sem pontos como um estado, e não como erro', () => {
      relatorioService.buscar.and.returnValue(of(comoVazio()));
      montar();

      expect(elemento('relatorio-vazio')).toBeTruthy();
      expect(elemento('relatorio-erro')).toBeNull();
      expect(elemento('relatorio-indicadores')).toBeNull();
    });

    it('marca como parcial a sessão que não foi encerrada pelo aluno (AC-11-4)', () => {
      relatorioService.buscar.and.returnValue(of({ ...RELATORIO, parcial: true }));
      montar();

      expect(texto('relatorio-parcial')).toContain('Relatório parcial');
    });

    it('não marca como parcial a sessão encerrada normalmente', () => {
      montar();

      expect(elemento('relatorio-parcial')).toBeNull();
    });

    it('explica o 404 sem revelar se a sessão existe', () => {
      relatorioService.buscar.and.returnValue(
        throwError(() => new HttpErrorResponse({ status: 404 })),
      );
      montar();

      expect(texto('relatorio-erro')).toContain('Relatório não encontrado');
    });

    it('explica que a sessão em andamento ainda não tem relatório', () => {
      relatorioService.buscar.and.returnValue(
        throwError(() => new HttpErrorResponse({ status: 409 })),
      );
      montar();

      expect(texto('relatorio-erro')).toContain('ainda está em andamento');
    });

    it('recusa um id inválido sem chamar o backend', () => {
      montar('abc');

      expect(relatorioService.buscar).not.toHaveBeenCalled();
      expect(texto('relatorio-erro')).toContain('não é válido');
    });
  });
});
