import { Routes } from '@angular/router';

import { authGuard } from './core/guards/auth.guard';

export const routes: Routes = [
  { path: '', redirectTo: 'login', pathMatch: 'full' },
  {
    path: 'login',
    loadComponent: () => import('./pages/login/login.component').then((m) => m.LoginComponent),
  },
  {
    path: 'registro',
    loadComponent: () =>
      import('./pages/registro/registro.component').then((m) => m.RegistroComponent),
  },
  {
    path: 'home',
    loadComponent: () => import('./pages/home/home.component').then((m) => m.HomeComponent),
    canActivate: [authGuard],
  },
  {
    path: 'historico',
    loadComponent: () =>
      import('./pages/historico/historico.component').then((m) => m.HistoricoComponent),
    canActivate: [authGuard],
  },
  {
    // O id na URL, e não o relatório da "última" sessão: é o mesmo endereço que
    // o histórico da ticket 12 abre, e um relatório que o aluno pode guardar no
    // favorito continua funcionando amanhã.
    path: 'relatorio/:id',
    loadComponent: () =>
      import('./pages/relatorio/relatorio.component').then((m) => m.RelatorioComponent),
    canActivate: [authGuard],
  },
  { path: '**', redirectTo: 'login' },
];
