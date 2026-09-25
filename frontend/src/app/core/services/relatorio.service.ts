import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { API_URL } from '../api';

/**
 * Um ponto da curva, como o backend o entrega.
 *
 * `score: null` é a incerteza da ticket 10 e atravessa a rede como nulo de
 * propósito — é ele que faz a linha do gráfico quebrar em vez de ligar os dois
 * lados de um trecho que não foi medido.
 */
export interface PontoDoRelatorio {
  /** Instante ISO-8601 em UTC. */
  instante: string;
  score: number | null;
  alerta: string | null;
}

/** Um alerta agregado: o código para a máquina, o nome para a pessoa. */
export interface AlertaDoRelatorio {
  codigo: string;
  nome: string;
  ocorrencias: number;
}

export interface RecomendacaoDoRelatorio {
  codigo: string;
  titulo: string;
  texto: string;
  motivo: string;
}

/**
 * Um bloco declarado, com o que a série diz sobre ele (ticket 17).
 *
 * As duas durações viajam juntas pela mesma razão que `duracao_total_s` e
 * `duracao_presente_s`: "25min declarados · 11min com captura" informa o aluno
 * de um jeito que nenhuma das duas sozinha informaria.
 *
 * `media: null` é a abstenção, e `observacao` é a frase que explica qual das
 * três abstenções foi — ela vem pronta do backend, e não é montada aqui. Uma
 * frase escrita no template sairia do alcance do teste de tom que varre
 * `app/criterios.py`, e a trava morreria no mesmo commit.
 */
export interface BlocoDoRelatorio {
  indice: number;
  /** `foco` ou `pausa` — o código, para a máquina. */
  tipo: string;
  /** O mesmo tipo com nome legível, traduzido no backend como os alertas. */
  tipo_nome: string;
  inicio: string;
  fim: string | null;
  duracao_s: number;
  duracao_com_captura_s: number;
  media: number | null;
  pontos_medidos: number;
  pontos_incertos: number;
  observacao: string | null;
}

/** Uma leitura da sessão pelo método declarado, já escrita pelo backend. */
export interface CriterioDoRelatorio {
  codigo: string;
  titulo: string;
  texto: string;
  detalhe: string;
}

/**
 * O declarado ao lado do executado — em durações e contagens.
 *
 * **Não existe aqui nenhum campo de razão normalizada**, e o tipo é onde essa
 * regra fica visível para quem escrever a próxima tela. Um `aderencia: number`
 * atravessaria em silêncio todo teste de texto deste projeto; quem quiser o
 * percentual precisa acrescentar campo dos dois lados e justificar no PR.
 */
export interface CadenciaDoRelatorio {
  duracao_alvo_s: number;
  duracoes_observadas_s: number[];
  blocos_na_faixa: number;
  blocos_de_foco: number;
  meta_de_blocos: number | null;
}

export interface Relatorio {
  id_sessao: number;
  inicio: string;
  fim: string | null;
  /** A sessão foi fechada pela varredura de inatividade, e não pelo aluno. */
  parcial: boolean;

  duracao_total_s: number;
  duracao_presente_s: number;

  media: number | null;
  pico: number | null;
  vale: number | null;

  /**
   * Média da leitura do classificador de sonolência, entre 0 e 1.
   *
   * `null` quando não houve leitura: sessão sem modelo carregado, ou curta
   * demais para fechar a primeira janela depois da calibração. Nunca 0 nesse
   * caso — zero diria "o aluno estava perfeitamente desperto", que é afirmação
   * diferente de "não houve leitura".
   */
  sonolencia_media: number | null;

  pontos_medidos: number;
  pontos_incertos: number;
  pontos_zerados: number;

  alertas_de_fadiga: AlertaDoRelatorio[];
  motivos_de_incerteza: AlertaDoRelatorio[];
  recomendacoes: RecomendacaoDoRelatorio[];
  serie: PontoDoRelatorio[];

  /**
   * `null` quando a sessão é anterior ao recurso de métodos — e a tela desenha
   * traço. Não confundir com `'livre'`, que é "o aluno escolheu estudar sem
   * método" e tem nome próprio: colapsar os dois inventaria uma escolha que
   * ninguém fez.
   */
  metodo: string | null;
  metodo_nome: string | null;
  assunto: string | null;

  /** A média do IEE sem os pontos das pausas — a correção da ticket 17. */
  media_de_foco: number | null;
  duracao_de_foco_s: number;
  duracao_de_pausa_s: number;

  blocos: BlocoDoRelatorio[];
  criterios: CriterioDoRelatorio[];
  cadencia: CadenciaDoRelatorio | null;
}

/** Uma linha do histórico — o suficiente para escolher qual sessão abrir. */
export interface SessaoNoHistorico {
  id: number;
  inicio: string;
  fim: string | null;
  parcial: boolean;
  duracao_presente_s: number;
  media: number | null;
  pontos_medidos: number;
  alertas: number;

  /** `null` nas sessões anteriores ao recurso; a lista desenha traço. */
  metodo: string | null;
  metodo_nome: string | null;
  assunto: string | null;
}

@Injectable({ providedIn: 'root' })
export class RelatorioService {
  private readonly http = inject(HttpClient);

  /**
   * O relatório de uma sessão encerrada.
   *
   * Não guarda estado nem cache: o relatório é imutável depois do encerramento,
   * e guardá-lo num signal faria a tela do histórico servir o relatório da
   * sessão anterior por um quadro antes de trocar.
   */
  buscar(idSessao: number): Observable<Relatorio> {
    return this.http.get<Relatorio>(`${API_URL}/sessoes/${idSessao}/relatorio`);
  }

  /** As sessões encerradas do aluno, da mais recente para a mais antiga. */
  historico(): Observable<SessaoNoHistorico[]> {
    return this.http.get<SessaoNoHistorico[]>(`${API_URL}/sessoes/historico`);
  }
}
