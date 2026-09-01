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
 * O relatório de autopercepção de uma sessão (ticket 11).
 *
 * Não guarda estado: o relatório é calculado sob demanda pelo backend, e um
 * cache aqui seria uma segunda fonte de verdade envelhecendo enquanto a ticket
 * 13 resume os logs por baixo.
 */
@Injectable({ providedIn: 'root' })
export class RelatorioService {
  private readonly http = inject(HttpClient);

  buscar(idSessao: number): Observable<Relatorio> {
    return this.http.get<Relatorio>(`${API_URL}/sessoes/${idSessao}/relatorio`);
  }
}
