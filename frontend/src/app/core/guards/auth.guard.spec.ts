import { TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';

import { AuthService } from '../services/auth.service';
import { InactivityService } from '../services/inactivity.service';
import { authGuard } from './auth.guard';

describe('authGuard', () => {
  let authServiceSpy: jasmine.SpyObj<AuthService>;
  let inactivityServiceSpy: jasmine.SpyObj<InactivityService>;
  let routerSpy: jasmine.SpyObj<Router>;

  beforeEach(() => {
    authServiceSpy = jasmine.createSpyObj('AuthService', ['estaAutenticado']);
    inactivityServiceSpy = jasmine.createSpyObj('InactivityService', ['iniciarMonitoramento']);
    routerSpy = jasmine.createSpyObj('Router', ['navigate']);

    TestBed.configureTestingModule({
      providers: [
        { provide: AuthService, useValue: authServiceSpy },
        { provide: InactivityService, useValue: inactivityServiceSpy },
        { provide: Router, useValue: routerSpy },
      ],
    });
  });

  function executarGuard(): boolean {
    return TestBed.runInInjectionContext(() => authGuard({} as never, {} as never)) as boolean;
  }

  it('permite acesso e inicia o monitoramento de inatividade quando autenticado', () => {
    authServiceSpy.estaAutenticado.and.returnValue(true);

    expect(executarGuard()).toBeTrue();
    expect(inactivityServiceSpy.iniciarMonitoramento).toHaveBeenCalled();
    expect(routerSpy.navigate).not.toHaveBeenCalled();
  });

  it('redireciona para /login quando não autenticado', () => {
    authServiceSpy.estaAutenticado.and.returnValue(false);

    expect(executarGuard()).toBeFalse();
    expect(inactivityServiceSpy.iniciarMonitoramento).not.toHaveBeenCalled();
    expect(routerSpy.navigate).toHaveBeenCalledWith(['/login']);
  });
});
