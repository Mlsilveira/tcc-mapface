import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { API_URL as API } from '../api';
import { MetodoDeEstudo, MetodoService } from './metodo.service';


const CATALOGO: MetodoDeEstudo[] = [
  {
    codigo: 'pomodoro',
    nome: 'Pomodoro',
    foco_s: 1500,
    pausa_s: 300,
    ciclos_ate_pausa_longa: 4,
    pausa_longa_s: 900,
  },
  {
    codigo: '52-17',
    nome: '52/17',
    foco_s: 3120,
    pausa_s: 1020,
    ciclos_ate_pausa_longa: null,
    pausa_longa_s: null,
  },
];

describe('MetodoService', () => {
  let service: MetodoService;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    service = TestBed.inject(MetodoService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => httpMock.verify());

  it('começa sem catálogo e o expõe depois de carregar', () => {
    expect(service.catalogo()).toEqual([]);

    service.carregar().subscribe();
    const requisicao = httpMock.expectOne(`${API}/metodos`);
    expect(requisicao.request.method).toBe('GET');
    requisicao.flush(CATALOGO);

    expect(service.catalogo()).toEqual(CATALOGO);
  });

  it('preserva a ordem em que o servidor entrega os métodos', () => {
    // "Sem método" é o último item do catálogo porque é onde uma opção de escape
    // pertence. Reordenar por nome no cliente a jogaria para o meio da lista.
    service.carregar().subscribe();
    httpMock.expectOne(`${API}/metodos`).flush(CATALOGO);

    expect(service.catalogo().map((metodo) => metodo.codigo)).toEqual(['pomodoro', '52-17']);
  });

  it('devolve nulo para código que não está no catálogo, em vez de estourar', () => {
    // Uma sessão gravada por uma versão que conhecia um método a mais precisa
    // continuar abrindo: quem não acha o método perde o cronômetro, não a
    // sessão — e o nome legível continua vindo da própria sessão.
    service.carregar().subscribe();
    httpMock.expectOne(`${API}/metodos`).flush(CATALOGO);

    expect(service.buscar('pomodoro')?.nome).toBe('Pomodoro');
    expect(service.buscar('metodo-do-futuro')).toBeNull();
    expect(service.buscar(null)).toBeNull();
    expect(service.buscar(undefined)).toBeNull();
  });
});
