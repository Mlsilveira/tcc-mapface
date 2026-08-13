import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';

import { AuthService } from '../services/auth.service';
import { InactivityService } from '../services/inactivity.service';

/** Bloqueia rotas protegidas para quem não está autenticado, redirecionando para /login. */
export const authGuard: CanActivateFn = () => {
  const authService = inject(AuthService);
  const inactivityService = inject(InactivityService);
  const router = inject(Router);

  if (authService.estaAutenticado()) {
    inactivityService.iniciarMonitoramento();
    return true;
  }

  router.navigate(['/login']);
  return false;
};
