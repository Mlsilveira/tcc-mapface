import { HttpInterceptorFn, HttpRequest } from '@angular/common/http';
import { inject } from '@angular/core';
import { catchError, of, switchMap, take } from 'rxjs';

import { AuthService, CAMINHO_DE_RENOVACAO } from '../services/auth.service';

function comCredencial(req: HttpRequest<unknown>, token: string): HttpRequest<unknown> {
  return req.clone({ setHeaders: { Authorization: `Bearer ${token}` } });
}

/**
 * Anexa o JWT a toda requisição e renova a credencial antes que ela vença.
 *
 * **Por que a renovação mora aqui.** O token dura 30 minutos e, até a ticket 17,
 * não era renovado em lugar nenhum — na prática nenhuma sessão de estudo passava
 * de meia hora. Renovar no interceptor aproveita a única evidência confiável de
 * que o aluno ainda está usando o sistema: existir requisição saindo. Um
 * temporizador renovaria a credencial de uma aba esquecida a noite inteira, que
 * é exatamente o que o teto de 12 h do servidor existe para impedir — e seria
 * incoerente o cliente trabalhar contra ele.
 *
 * **Os dois cuidados que este caminho exige**, e que não são teóricos:
 *
 * 1. *O laço.* A própria requisição de renovação passa por aqui. Se ela também
 *    fosse avaliada, cada renovação dispararia outra, indefinidamente. Daí o
 *    desvio explícito pelo caminho de renovação, antes de qualquer outra coisa.
 * 2. *A avalanche.* Perto do vencimento, heartbeat, telemetria e clique do aluno
 *    saem quase juntos e cada um pediria a sua renovação. A deduplicação mora no
 *    `AuthService.renovar`, que compartilha a requisição em voo — o interceptor
 *    pode chamá-la à vontade.
 *
 * Renovação que falha **não** derruba a requisição original: ela segue com o
 * token antigo, que ainda vale (a renovação dispara antes de vencer). Se ele
 * estiver mesmo no fim, o 401 chega do servidor, que é quem tem autoridade para
 * dizer isso — o cliente não inventa um caminho de erro próprio.
 */
export const authInterceptor: HttpInterceptorFn = (req, next) => {
  const authService = inject(AuthService);
  const token = authService.getToken();

  if (!token) {
    return next(req);
  }

  if (req.url.endsWith(CAMINHO_DE_RENOVACAO)) {
    return next(comCredencial(req, token));
  }

  if (!authService.credencialPertoDeExpirar()) {
    return next(comCredencial(req, token));
  }

  return authService.renovar().pipe(
    take(1),
    catchError(() => of(token)),
    switchMap((credencial) => next(comCredencial(req, credencial))),
  );
};
