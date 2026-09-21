import { HttpClient } from '@angular/common/http';
import { Injectable, OnDestroy, signal } from '@angular/core';
import { Observable, retry, tap, throwError, timer } from 'rxjs';

import { API_URL } from '../api';

export interface Sessao {
  id: number;
  id_aluno: number;
  /** Instante ISO-8601 em UTC. */
  inicio: string;
  /** `null` enquanto a sessão está em andamento. */
  fim: string | null;

  /**
   * Código do método declarado, ou `null`.
   *
   * `null` aqui significa **"esta sessão é anterior ao recurso"**, e não "o
   * aluno escolheu não usar método" — essa escolha tem código próprio
   * (`"livre"`). Colapsar as duas faria uma sessão antiga ganhar cronômetro e
   * bloco inventado ao ser retomada com F5.
   */
  metodo?: string | null;

  /**
   * O nome legível do método, resolvido pelo servidor a partir do catálogo.
   *
   * Vem junto do código porque os dois servem a leitores diferentes: o código
   * é o que o cliente compara com o catálogo para saber quantos minutos tem o
   * bloco; o nome é o que o aluno lê. Sem ele, a tela mostraria `52-17`.
   */
  metodo_nome?: string | null;

  assunto?: string | null;

  /**
   * Quantos blocos de foco o aluno planejou, se declarou algum.
   *
   * Viaja na sessão, e não só na memória da tela, porque é o denominador de
   * "bloco 2 de 4" e precisa sobreviver a um reload. Guardá-lo no cliente
   * criaria duas verdades sobre um número que o aluno declarou uma vez só.
   */
  meta_de_blocos?: number | null;
}

/** O aluno declarou que está trabalhando no material. */
export const TIPO_FOCO = 'foco';

/** O aluno declarou que parou — a pausa do método, ou a que ele decidiu tirar. */
export const TIPO_PAUSA = 'pausa';

export type TipoDeBloco = typeof TIPO_FOCO | typeof TIPO_PAUSA;

/** A transição aconteceu na hora que o método previa. */
export const ORIGEM_METODO = 'metodo';

/** O aluno antecipou a transição por conta própria. */
export const ORIGEM_ALUNO = 'aluno';

export type OrigemDeBloco = typeof ORIGEM_METODO | typeof ORIGEM_ALUNO;

/** Um bloco declarado, como o servidor o devolve. */
export interface Bloco {
  id: number;
  id_sessao: number;
  indice: number;
  tipo: TipoDeBloco;
  /** Instante ISO-8601 em UTC. */
  inicio: string;
  /** `null` enquanto o bloco é o que está em andamento. */
  fim: string | null;
  origem: OrigemDeBloco;
}

/**
 * O que o aluno declarou na tela inicial, antes de começar.
 *
 * Os três campos são opcionais e o objeto inteiro também: sessão sem método,
 * sem assunto e sem meta é um estado legítimo, e é o que acontece quando o
 * aluno não quer declarar nada.
 */
export interface DeclaracaoDeSessao {
  metodo?: string | null;
  assunto?: string | null;
  meta_de_blocos?: number | null;
}

/**
 * Quantas vezes o cliente reapresenta uma transição que não chegou.
 *
 * Retentar é seguro e **não retentar não é**: o servidor absorve a repetição
 * (200, idempotente por tipo, preservando o instante da primeira declaração),
 * enquanto uma transição perdida some com a borda de um bloco — e um bloco sem
 * borda vira um bloco de duração errada no relatório do aluno, sem que nada
 * estoure em lugar nenhum.
 */
export const TENTATIVAS_DE_TRANSICAO = 2;

/** Espera antes de reapresentar a transição; cresce a cada tentativa. */
export const ESPERA_PARA_RETENTAR_MS = 2000;

/**
 * Monta o corpo do `POST /sessoes` com o que de fato foi declarado.
 *
 * Campo não declarado é **omitido**, e não enviado como `null`. Os dois
 * significariam a mesma coisa para o servidor, mas só a omissão mantém o corpo
 * literalmente vazio quando nada foi declarado — que é o caminho de "Sem
 * método", é o que as telas anteriores a este recurso mandam, e é o que os
 * testes existentes travam.
 */
function corpoDeclarado(declaracao: DeclaracaoDeSessao): Record<string, unknown> {
  const corpo: Record<string, unknown> = {};

  if (declaracao.metodo) {
    corpo['metodo'] = declaracao.metodo;
  }

  const assunto = declaracao.assunto?.trim();
  if (assunto) {
    corpo['assunto'] = assunto;
  }

  if (declaracao.meta_de_blocos !== null && declaracao.meta_de_blocos !== undefined) {
    corpo['meta_de_blocos'] = declaracao.meta_de_blocos;
  }

  return corpo;
}

/**
 * Se vale reapresentar uma transição que falhou.
 *
 * Só falha de transporte: status 0 é a rede que caiu, 5xx é o servidor que
 * tropeçou, e os dois somem sozinhos. Um 409 ("esta sessão já foi encerrada")
 * ou um 422 ("tipo fora do vocabulário") são respostas definitivas — insistir
 * neles só gastaria bateria para receber a mesma recusa três vezes.
 */
function valeRetentar(falha: { status?: number }): boolean {
  const status = falha?.status ?? 0;
  return status === 0 || status >= 500;
}

/**
 * Intervalo entre sinais de atividade.
 *
 * Este heartbeat **não mantém mais a sessão viva** — quem faz isso é o rosto na
 * câmera, registrado a 1 Hz pelo canal de telemetria. A mudança foi necessária
 * porque o heartbeat bate sozinho enquanto a aba existir, com ou sem aluno na
 * cadeira: enquanto ele era a evidência de presença, tempo de aba aberta virava
 * tempo de estudo.
 *
 * O que ele continua fazendo é descobrir barato que o servidor já encerrou a
 * sessão — o 409 desta rota é o que dispara a ressincronização da tela.
 */
export const INTERVALO_ATIVIDADE_MS = 60 * 1000;

@Injectable({ providedIn: 'root' })
export class SessaoService implements OnDestroy {
  private readonly sessaoSignal = signal<Sessao | null>(null);
  private temporizador: ReturnType<typeof setInterval> | null = null;

  /** Sessão de estudo em andamento do aluno autenticado, ou `null`. */
  readonly sessaoAtiva = this.sessaoSignal.asReadonly();

  constructor(private readonly http: HttpClient) {}

  carregarAtiva(): Observable<Sessao | null> {
    return this.http
      .get<Sessao | null>(`${API_URL}/sessoes/ativa`)
      .pipe(tap((sessao) => this.assumir(sessao)));
  }

  iniciar(declaracao: DeclaracaoDeSessao = {}): Observable<Sessao> {
    return this.http
      .post<Sessao>(`${API_URL}/sessoes`, corpoDeclarado(declaracao))
      .pipe(tap((sessao) => this.assumir(sessao)));
  }

  /**
   * Declara que a sessão entrou em foco ou em pausa, agora.
   *
   * O instante é o da chegada do request, e não um campo do corpo: carimbo de
   * tempo vindo do cliente é relógio de navegador desregulado — ou, no caso
   * ruim, escolhido. O que o cliente sabe e o servidor não é **que** a
   * transição aconteceu e se ela veio do cronômetro ou do aluno.
   */
  declararBloco(idSessao: number, tipo: TipoDeBloco, origem: OrigemDeBloco): Observable<Bloco> {
    return this.http.post<Bloco>(`${API_URL}/sessoes/${idSessao}/blocos`, { tipo, origem }).pipe(
      retry({
        count: TENTATIVAS_DE_TRANSICAO,
        delay: (falha: { status?: number }, tentativa: number) =>
          valeRetentar(falha)
            ? timer(ESPERA_PARA_RETENTAR_MS * tentativa)
            : throwError(() => falha),
      }),
    );
  }

  /**
   * Os blocos já declarados da sessão, em ordem.
   *
   * É daqui que o cronômetro sai depois de um F5, e não de estado local: o
   * bloco corrente e o instante em que ele começou são fato do servidor. Se
   * viessem da memória da aba, recarregar a página reiniciaria o bloco — e o
   * aluno aprenderia a não recarregar, que é a pior correção possível.
   */
  listarBlocos(idSessao: number): Observable<Bloco[]> {
    return this.http.get<Bloco[]>(`${API_URL}/sessoes/${idSessao}/blocos`);
  }

  encerrar(): Observable<Sessao> {
    const sessao = this.sessaoSignal();
    if (sessao === null) {
      return throwError(() => new Error('Não há sessão de estudo em andamento.'));
    }

    return this.http.post<Sessao>(`${API_URL}/sessoes/${sessao.id}/encerrar`, {}).pipe(
      tap({
        next: () => this.assumir(null),
        // A sessão pode ter expirado entre o último heartbeat e o clique. Se o
        // servidor já a encerrou, esquecê-la aqui também — senão o aluno fica
        // preso num botão de encerrar que nunca funciona.
        error: (falha: { status?: number }) => {
          if (this.servidorJaEncerrou(falha)) {
            this.assumir(null);
          }
        },
      }),
    );
  }

  /**
   * Esquece a sessão localmente, sem avisar o backend — usado no logout, onde
   * o token já não vale mais. Sem isso o heartbeat sobreviveria à saída do
   * aluno e a tela do próximo a logar mostraria a sessão do anterior.
   */
  esquecerSessao(): void {
    this.assumir(null);
  }

  /**
   * Respostas que significam "esta sessão não está mais viva no servidor":
   * 404/409 quando ele já a encerrou por inatividade, 401 quando o JWT expirou
   * e nenhum sinal nosso vai mais chegar.
   */
  private servidorJaEncerrou(falha: { status?: number }): boolean {
    return falha?.status === 401 || falha?.status === 404 || falha?.status === 409;
  }

  private assumir(sessao: Sessao | null): void {
    this.sessaoSignal.set(sessao);
    if (sessao === null) {
      this.pararSinaisDeAtividade();
    } else {
      this.iniciarSinaisDeAtividade();
    }
  }

  private iniciarSinaisDeAtividade(): void {
    if (this.temporizador !== null) {
      return;
    }
    this.temporizador = setInterval(() => this.sinalizarAtividade(), INTERVALO_ATIVIDADE_MS);
  }

  private pararSinaisDeAtividade(): void {
    if (this.temporizador !== null) {
      clearInterval(this.temporizador);
      this.temporizador = null;
    }
  }

  private sinalizarAtividade(): void {
    const sessao = this.sessaoSignal();
    if (sessao === null) {
      this.pararSinaisDeAtividade();
      return;
    }

    this.http.post<Sessao>(`${API_URL}/sessoes/${sessao.id}/atividade`, {}).subscribe({
      // 404/409: o backend já encerrou esta sessão (inatividade prolongada).
      // 401: o JWT expirou, e nenhum sinal nosso chegará mais — o backend vai
      // encerrar a sessão sozinho. Em todos os casos, continuar mostrando
      // "em andamento" seria mentir para o aluno sobre o monitoramento.
      error: (erro: { status?: number }) => {
        if (this.servidorJaEncerrou(erro)) {
          this.assumir(null);
        }
      },
    });
  }

  ngOnDestroy(): void {
    this.pararSinaisDeAtividade();
  }
}
