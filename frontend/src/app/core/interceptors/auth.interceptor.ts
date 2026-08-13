import { HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';

import { AuthService } from '../services/auth.service';

/** Anexa o JWT armazenado a toda requisição HTTP saindo da aplicação. */
export const authInterceptor: HttpInterceptorFn = (req, next) => {
  const authService = inject(AuthService);
  const token = authService.getToken();

  if (!token) {
    return next(req);
  }

  const requisicaoComToken = req.clone({
    setHeaders: { Authorization: `Bearer ${token}` },
  });
  return next(requisicaoComToken);
};
