import { HttpClient } from '@angular/common/http';
import { Injectable, OnDestroy, signal } from '@angular/core';
import { Observable, tap, throwError } from 'rxjs';

import { API_URL } from '../api';

export interface Sessao {
  id: number;
  id_aluno: number;
  /** Instante ISO-8601 em UTC. */
  inicio: string;
  /** `null` enquanto a sessão está em andamento. */
  fim: string | null;
}

/**
 * Intervalo entre sinais de atividade. Precisa ficar bem abaixo do limite de
 * inatividade do backend (`sessao_inatividade_minutos`), para que uma falha
 * pontual de rede não derrube a sessão de quem está estudando.
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

  iniciar(): Observable<Sessao> {
    return this.http
      .post<Sessao>(`${API_URL}/sessoes`, {})
      .pipe(tap((sessao) => this.assumir(sessao)));
  }

  encerrar(): Observable<Sessao> {
    const sessao = this.sessaoSignal();
    if (sessao === null) {
      return throwError(() => new Error('Não há sessão de estudo em andamento.'));
    }

    return this.http
      .post<Sessao>(`${API_URL}/sessoes/${sessao.id}/encerrar`, {})
      .pipe(tap(() => this.assumir(null)));
  }

  /**
   * Esquece a sessão localmente, sem avisar o backend — usado no logout, onde
   * o token já não vale mais. Sem isso o heartbeat sobreviveria à saída do
   * aluno e a tela do próximo a logar mostraria a sessão do anterior.
   */
  esquecerSessao(): void {
    this.assumir(null);
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
        if (erro?.status === 401 || erro?.status === 404 || erro?.status === 409) {
          this.assumir(null);
        }
      },
    });
  }

  ngOnDestroy(): void {
    this.pararSinaisDeAtividade();
  }
}
