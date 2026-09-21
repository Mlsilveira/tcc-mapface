import { HttpClient } from '@angular/common/http';
import { Injectable, signal } from '@angular/core';
import { Observable, finalize, map, shareReplay, tap } from 'rxjs';

import { API_URL } from '../api';

export interface AlunoRegistroPayload {
  nome: string;
  email: string;
  senha: string;
}

export interface AlunoLoginPayload {
  email: string;
  senha: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

const CHAVE_TOKEN = 'iee_access_token';

/** Caminho do endpoint de renovação, exportado porque o interceptor precisa reconhecê-lo. */
export const CAMINHO_DE_RENOVACAO = '/auth/renovar';

/**
 * Quanto antes do vencimento a credencial passa a ser renovada.
 *
 * O número é derivado, não escolhido: a única coisa que garante request em voo
 * durante uma leitura sem teclado nem mouse é o heartbeat da sessão, que bate a
 * cada 60 s. A margem precisa ser maior que esse intervalo, e com folga — cinco
 * minutos toleram **quatro batidas perdidas** (rede oscilando, aba em segundo
 * plano por um instante, backoff da reconexão) antes que a credencial vença sem
 * ninguém ter tentado renová-la.
 *
 * Maior que isso também não serve: a renovação passaria a disparar cedo demais
 * e encurtaria a janela útil de cada token sem comprar nenhuma tolerância a
 * mais.
 */
export const MARGEM_DE_RENOVACAO_MS = 5 * 60 * 1000;

/**
 * Lê o payload de um JWT sem verificar a assinatura.
 *
 * Isto é seguro **porque o cliente não decide nada com o resultado**: quem
 * valida o token é o servidor, a cada request. O único uso aqui é saber quando
 * pedir a renovação — um token forjado com `exp` mentiroso só conseguiria fazer
 * o próprio navegador renovar cedo ou tarde demais, e a renovação ainda teria
 * de passar pelo `/auth/renovar`, que verifica a assinatura.
 *
 * `atob` devolve latin1, então texto acentuado dentro do payload sairia
 * corrompido daqui. Não importa: o único campo lido é `exp`, que é número.
 */
function lerPayload(token: string): Record<string, unknown> | null {
  const partes = token.split('.');
  if (partes.length !== 3) {
    return null;
  }

  try {
    const base64 = partes[1].replace(/-/g, '+').replace(/_/g, '/');
    const faltando = (4 - (base64.length % 4)) % 4;
    const valor: unknown = JSON.parse(atob(base64 + '='.repeat(faltando)));
    return typeof valor === 'object' && valor !== null ? (valor as Record<string, unknown>) : null;
  } catch {
    // Token que não é um JWT legível não tem vencimento conhecido, e o caminho
    // de erro correto é o servidor recusá-lo — não o cliente adivinhar.
    return null;
  }
}

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly tokenSignal = signal<string | null>(this.lerTokenArmazenado());

  /**
   * A renovação em andamento, se houver.
   *
   * Existe por causa de um caso concreto: quando o token se aproxima do
   * vencimento, o heartbeat da sessão, o canal de telemetria e qualquer clique
   * do aluno podem sair juntos, e cada um passaria pelo interceptor pedindo uma
   * renovação. Sem esta referência seriam N chamadas concorrentes ao
   * `/auth/renovar`, cada uma emitindo um token novo e as últimas sobrescrevendo
   * as primeiras no `localStorage` — com a chance real de uma requisição já
   * despachada carregar um token que deixou de ser o armazenado.
   */
  private renovacaoEmVoo: Observable<string> | null = null;

  constructor(private readonly http: HttpClient) {}

  registrar(dados: AlunoRegistroPayload): Observable<unknown> {
    return this.http.post(`${API_URL}/auth/registro`, dados);
  }

  login(dados: AlunoLoginPayload): Observable<TokenResponse> {
    return this.http
      .post<TokenResponse>(`${API_URL}/auth/login`, dados)
      .pipe(tap((resposta) => this.armazenarToken(resposta.access_token)));
  }

  logout(): void {
    localStorage.removeItem(CHAVE_TOKEN);
    this.tokenSignal.set(null);
  }

  getToken(): string | null {
    return this.tokenSignal();
  }

  estaAutenticado(): boolean {
    return this.tokenSignal() !== null;
  }

  /**
   * O token está perto de vencer o bastante para valer a pena renová-lo agora?
   *
   * Responde `false` para token já vencido, e isso é deliberado: não há o que
   * renovar — o servidor recusa token expirado de propósito, para que um token
   * roubado não vire credencial permanente. Tentar mesmo assim colocaria um
   * request condenado na frente de cada request do aluno.
   *
   * Responde `false` também para token ilegível, pelo mesmo motivo: quem decide
   * que um token não vale é o servidor.
   */
  credencialPertoDeExpirar(): boolean {
    const token = this.tokenSignal();
    if (token === null) {
      return false;
    }

    const exp = lerPayload(token)?.['exp'];
    if (typeof exp !== 'number') {
      return false;
    }

    const restanteMs = exp * 1000 - Date.now();
    return restanteMs > 0 && restanteMs < MARGEM_DE_RENOVACAO_MS;
  }

  /**
   * Troca o token atual por um novo, reaproveitando a renovação já em andamento.
   *
   * O `shareReplay` é o que transforma N chamadas simultâneas em **uma**
   * requisição: quem chegar enquanto a anterior está em voo se pendura nela e
   * recebe o mesmo token. O `finalize` solta a referência ao terminar, de modo
   * que a próxima renovação — daqui a 25 minutos — comece limpa em vez de
   * devolver para sempre o token da primeira.
   */
  renovar(): Observable<string> {
    if (this.renovacaoEmVoo !== null) {
      return this.renovacaoEmVoo;
    }

    this.renovacaoEmVoo = this.http
      .post<TokenResponse>(`${API_URL}${CAMINHO_DE_RENOVACAO}`, {})
      .pipe(
        map((resposta) => resposta.access_token),
        tap((token) => this.armazenarToken(token)),
        finalize(() => {
          this.renovacaoEmVoo = null;
        }),
        shareReplay({ bufferSize: 1, refCount: false }),
      );

    return this.renovacaoEmVoo;
  }

  private armazenarToken(token: string): void {
    localStorage.setItem(CHAVE_TOKEN, token);
    this.tokenSignal.set(token);
  }

  private lerTokenArmazenado(): string | null {
    return localStorage.getItem(CHAVE_TOKEN);
  }
}
