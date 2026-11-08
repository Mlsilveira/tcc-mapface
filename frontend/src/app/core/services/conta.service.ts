import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, tap } from 'rxjs';

import { API_URL } from '../api';
import { ACEITE_DA_VERSAO_ATUAL } from '../consentimento/termo';
import { Objetivo } from '../objetivo';
import { AuthService } from './auth.service';

export interface Perfil {
  id: number;
  nome: string;
  email: string;
  termo_versao: string | null;
  termo_aceito_em: string | null;
  consentimento_revogado_em: string | null;
  consentimento_vigente: boolean;
  /** `null` em conta criada antes do campo existir. */
  objetivo: Objetivo | null;
}

export interface CorrecaoDePerfil {
  nome?: string;
  email?: string;
  objetivo?: Objetivo;
}

interface PerfilCorrigido extends Perfil {
  access_token: string | null;
}

/** Os direitos do titular sobre a própria conta (LGPD, arts. 8º, § 5º, e 18). */
@Injectable({ providedIn: 'root' })
export class ContaService {
  private readonly http = inject(HttpClient);
  private readonly authService = inject(AuthService);

  carregar(): Observable<Perfil> {
    return this.http.get<Perfil>(`${API_URL}/auth/me`);
  }

  /** O token é emitido sobre o e-mail: corrigi-lo troca a credencial em uso. */
  corrigir(dados: CorrecaoDePerfil): Observable<Perfil> {
    return this.http.patch<PerfilCorrigido>(`${API_URL}/auth/me`, dados).pipe(
      tap((resposta) => {
        if (resposta.access_token) {
          this.authService.armazenarToken(resposta.access_token);
        }
      }),
    );
  }

  aceitarTermo(): Observable<Perfil> {
    return this.http.post<Perfil>(`${API_URL}/auth/consentimento`, ACEITE_DA_VERSAO_ATUAL);
  }

  revogar(): Observable<Perfil> {
    return this.http.delete<Perfil>(`${API_URL}/auth/consentimento`);
  }

  excluir(senha: string): Observable<void> {
    return this.http.delete<void>(`${API_URL}/auth/conta`, { body: { senha } });
  }
}
