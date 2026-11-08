import { Component } from '@angular/core';

import { CLAUSULAS_DO_TERMO } from '../core/consentimento/termo';

/** O texto integral do termo, igual no cadastro e na página de privacidade. */
@Component({
  selector: 'app-termo-de-consentimento',
  standalone: true,
  template: `
    <ol class="termo" data-teste="termo">
      @for (clausula of clausulas; track clausula.titulo) {
        <li>
          <strong>{{ clausula.titulo }}.</strong>
          {{ clausula.texto }}
        </li>
      }
    </ol>
  `,
})
export class TermoDeConsentimentoComponent {
  readonly clausulas = CLAUSULAS_DO_TERMO;
}
