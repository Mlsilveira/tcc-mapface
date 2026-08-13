import { HttpClient } from '@angular/common/http';
import { Injectable, signal } from '@angular/core';
import { Observable, tap } from 'rxjs';

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

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly tokenSignal = signal<string | null>(this.lerTokenArmazenado());

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

  private armazenarToken(token: string): void {
    localStorage.setItem(CHAVE_TOKEN, token);
    this.tokenSignal.set(token);
  }

  private lerTokenArmazenado(): string | null {
    return localStorage.getItem(CHAVE_TOKEN);
  }
}
