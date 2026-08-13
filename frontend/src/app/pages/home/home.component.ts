import { Component } from '@angular/core';
import { Router } from '@angular/router';

import { AuthService } from '../../core/services/auth.service';
import { InactivityService } from '../../core/services/inactivity.service';

@Component({
  selector: 'app-home',
  standalone: true,
  templateUrl: './home.component.html',
})
export class HomeComponent {
  constructor(
    private readonly authService: AuthService,
    private readonly inactivityService: InactivityService,
    private readonly router: Router,
  ) {}

  sair(): void {
    this.inactivityService.pararMonitoramento();
    this.authService.logout();
    this.router.navigate(['/login']);
  }
}
