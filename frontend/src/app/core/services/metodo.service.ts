import { HttpClient } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { Observable, tap } from 'rxjs';

import { API_URL } from '../api';

/**
 * Um método de estudo como o catálogo do servidor o descreve.
 *
 * Os nomes dos campos são os do JSON de `GET /metodos`, em snake_case, e não
 * são traduzidos na borda de propósito: um `focoS` aqui e um `foco_s` ali
 * obrigaria quem lê o payload no DevTools a traduzir de cabeça para encontrar
 * o mesmo campo no código. É a mesma escolha que `Sessao` já fazia.
 *
 * `foco_s` nulo é método que **não prescreve** duração de bloco — Flow e
 * Timeboxing. Nulo, e não zero, porque zero desenharia um cronômetro que já
 * nasce vencido, inventando uma prescrição que o método não faz.
 */
export interface MetodoDeEstudo {
  codigo: string;
  nome: string;
  foco_s: number | null;
  pausa_s: number;
  ciclos_ate_pausa_longa: number | null;
  pausa_longa_s: number | null;
}

/**
 * O catálogo de métodos de estudo, como a tela inicial e o cronômetro o veem.
 *
 * **Por que um serviço e não um `fetch` dentro do componente.** O catálogo é
 * lido por dois motivos diferentes na mesma tela: para montar a escolha, antes
 * da sessão, e para saber quantos segundos tem um bloco, durante ela. Sem um
 * dono único, a segunda leitura acabaria virando uma tabela de durações
 * copiada no cliente — e aí o dia em que o Pomodoro fosse reparametrizado no
 * servidor, o cronômetro continuaria contando o que já não vale.
 *
 * **O que ele deliberadamente não guarda: `pausa_maxima_s`.** Esse número é
 * resolvido no servidor a partir do código do método e nunca trafega de volta
 * como opinião do cliente. O que existe aqui é o que serve para *conduzir*, e
 * conduzir não é o mesmo que decidir quando a sessão morre.
 */
@Injectable({ providedIn: 'root' })
export class MetodoService {
  private readonly http = inject(HttpClient);

  private readonly catalogoSignal = signal<readonly MetodoDeEstudo[]>([]);

  /** Os métodos disponíveis, na ordem em que o servidor os entrega. */
  readonly catalogo = this.catalogoSignal.asReadonly();

  /**
   * Busca o catálogo no servidor.
   *
   * A ordem vem pronta de lá e não é reordenada aqui: "Sem método" é o último
   * item porque é onde uma opção de escape pertence, e ordenar por nome no
   * cliente a jogaria para o meio da lista.
   */
  carregar(): Observable<MetodoDeEstudo[]> {
    return this.http
      .get<MetodoDeEstudo[]>(`${API_URL}/metodos`)
      .pipe(tap((metodos) => this.catalogoSignal.set(metodos)));
  }

  /**
   * O método de um código, ou `null` quando ele não está no catálogo carregado.
   *
   * `null` para código desconhecido em vez de erro, pelo mesmo motivo que
   * `metodos.buscar` no backend: uma sessão gravada por uma versão que conhecia
   * um método a mais precisa continuar abrindo. Quem não acha o método perde o
   * cronômetro, não a sessão — e o nome legível continua vindo da própria
   * sessão, que o carrega congelado.
   */
  buscar(codigo: string | null | undefined): MetodoDeEstudo | null {
    if (codigo === null || codigo === undefined) {
      return null;
    }
    return this.catalogo().find((metodo) => metodo.codigo === codigo) ?? null;
  }
}
