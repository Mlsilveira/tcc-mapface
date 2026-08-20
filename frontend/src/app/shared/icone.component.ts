import { Component, Input } from '@angular/core';

/** Nomes dos ícones disponíveis. Fechado de propósito: um conjunto pequeno é o
 *  que mantém a interface parecendo desenhada pela mesma mão. */
export type NomeDeIcone = 'cadeado' | 'alvo' | 'grafico' | 'relogio' | 'bussola' | 'olho';

/**
 * Ícones de traço, no mesmo peso do símbolo do MapFace.
 *
 * Vieram no lugar dos emojis: emoji muda de desenho conforme o sistema
 * operacional e some sobre o painel escuro da tela de acesso. Como usam
 * `currentColor`, herdam a cor de onde estão.
 */
@Component({
  selector: 'app-icone',
  standalone: true,
  template: `
    <svg
      class="icone"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width="1.7"
      stroke-linecap="round"
      stroke-linejoin="round"
      aria-hidden="true"
    >
      @switch (nome) {
        @case ('cadeado') {
          <rect x="4" y="10.5" width="16" height="10" rx="2.5" />
          <path d="M8 10.5V7.5a4 4 0 0 1 8 0v3" />
          <circle cx="12" cy="15.5" r="1.2" fill="currentColor" stroke="none" />
        }
        @case ('alvo') {
          <circle cx="12" cy="12" r="8.2" />
          <circle cx="12" cy="12" r="4.2" />
          <circle cx="12" cy="12" r="1.1" fill="currentColor" stroke="none" />
        }
        @case ('grafico') {
          <path d="M4 19.5h16" />
          <path d="M6.5 15.5l4-4.5 3 2.5 4.5-5.5" />
          <circle cx="18" cy="8" r="1.4" fill="currentColor" stroke="none" />
        }
        @case ('relogio') {
          <circle cx="12" cy="12" r="8.2" />
          <path d="M12 7.5V12l3 1.8" />
        }
        @case ('bussola') {
          <circle cx="12" cy="12" r="8.2" />
          <path d="M14.8 9.2l-1.6 4.4-4.4 1.6 1.6-4.4z" />
        }
        @case ('olho') {
          <path d="M2.8 12S6.5 6.2 12 6.2 21.2 12 21.2 12 17.5 17.8 12 17.8 2.8 12 2.8 12z" />
          <circle cx="12" cy="12" r="2.6" />
        }
      }
    </svg>
  `,
})
export class IconeComponent {
  @Input({ required: true }) nome!: NomeDeIcone;
}
