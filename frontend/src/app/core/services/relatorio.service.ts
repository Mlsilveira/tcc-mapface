import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { API_URL } from '../api';
// `import type`: só o formato do ponto interessa aqui. Um import comum
// arrastaria o chart.js para dentro de quem apenas busca o relatório.
import type { PontoDoIEE } from '../../shared/grafico-iee.component';

/**
 * O alerta que a ticket 10 grava quando a captura não foi confiável.
 *
 * Duplicado do backend (`qualidade.ALERTA_INCERTEZA`) porque é contrato de
 * rede, não detalhe interno: o backend devolve o motivo como texto e alguém
 * deste lado precisa saber lê-lo. Há um teste que trava a string.
 */
export const ALERTA_INCERTEZA = 'incerteza-de-captura';

/** Um instante da série do IEE, como o backend o devolve. */
export interface PontoDoRelatorio {
  /** Instante ISO-8601 em UTC. */
  horario: string;
  score: number;
  fadiga: number;
  /** Motivos separados por vírgula, ou `null` quando não houve alerta. */
  alerta: string | null;
}

export interface IndicadoresDoRelatorio {
  n_leituras: number;
  duracao_s: number;
  score_medio: number;
  score_minimo: number;
  score_maximo: number;
  score_inicio: number;
  score_fim: number;
  prop_com_rosto: number;
  prop_com_fadiga: number;
  fadiga_maxima: number;
  desvio_olhar_medio: number;
  prop_captura_incerta: number;
}

/**
 * Uma linha da lista de sessões passadas (ticket 12).
 *
 * Traz o suficiente para o aluno **escolher** qual relatório abrir. Uma lista
 * só com datas o obrigaria a abrir sessão por sessão para lembrar como cada
 * uma foi, que é o oposto de um histórico.
 */
export interface ItemDoHistorico {
  id_sessao: number;
  inicio: string;
  fim: string | null;
  /** `true` enquanto a sessão não foi encerrada — inclusive a que corre agora. */
  parcial: boolean;
  duracao_s: number;
  n_leituras: number;
  score_medio: number;
  teve_fadiga: boolean;
}

export interface Relatorio {
  id_sessao: number;
  inicio: string;
  fim: string | null;
  /** `true` quando a sessão não foi encerrada formalmente. */
  parcial: boolean;
  indicadores: IndicadoresDoRelatorio;
  serie: PontoDoRelatorio[];
  /** Quantas leituras registraram cada tipo de alerta. */
  alertas: Record<string, number>;
  recomendacoes: string[];
}

/**
 * Converte a série do backend na série que o gráfico consome.
 *
 * O trabalho real é um só: **trechos de captura incerta viram `null`**. O banco
 * guarda o score daqueles instantes (a ticket 10 preferiu marcar a leitura a
 * apagá-la), mas o relatório não pode desenhá-los como se descrevessem o aluno
 * — os indicadores já os deixam de fora, e a linha que os ignorasse contaria
 * uma história diferente da dos números ao lado dela.
 *
 * Função pura e exportada de propósito: é a regra que decide o que o aluno vê,
 * e o teste bate nela sem subir componente nenhum.
 */
export function serieParaOGrafico(serie: readonly PontoDoRelatorio[]): PontoDoIEE[] {
  return serie.map((ponto) => ({
    instante: Date.parse(ponto.horario),
    score: capturaIncerta(ponto) ? null : ponto.score,
  }));
}

function capturaIncerta(ponto: PontoDoRelatorio): boolean {
  return (ponto.alerta ?? '').split(',').includes(ALERTA_INCERTEZA);
}

/**
 * As leituras retrospectivas das sessões: o relatório de uma (ticket 11) e a
 * lista de todas (ticket 12).
 *
 * As duas moram juntas porque são a mesma coisa em duas granularidades — é a
 * mesma divisão que o backend faz em `relatorio.py`. E nenhuma guarda estado:
 * o relatório é calculado sob demanda, e um cache aqui seria uma segunda fonte
 * de verdade envelhecendo enquanto a ticket 13 resume os logs por baixo.
 *
 * `SessaoService` fica de fora de propósito: ele é dono da sessão **viva** —
 * heartbeat, encerramento, o signal que a tela observa. Ler o passado não
 * mexe em nada disso.
 */
@Injectable({ providedIn: 'root' })
export class RelatorioService {
  private readonly http = inject(HttpClient);

  buscar(idSessao: number): Observable<Relatorio> {
    return this.http.get<Relatorio>(`${API_URL}/sessoes/${idSessao}/relatorio`);
  }

  /** As sessões do aluno autenticado, da mais recente para a mais antiga. */
  historico(): Observable<ItemDoHistorico[]> {
    return this.http.get<ItemDoHistorico[]>(`${API_URL}/sessoes`);
  }
}
