import { Component, Input } from '@angular/core';

/**
 * Marca do MapFace: um símbolo de malha facial (os pontos que o MediaPipe lê,
 * ligados entre si) e o nome por extenso.
 *
 * Existe como componente porque a marca aparece nas três telas — login,
 * cadastro e área do estudante — e um SVG copiado três vezes desanda na
 * primeira mudança de traço.
 */
@Component({
  selector: 'app-logo',
  standalone: true,
  template: `
    <span class="logo" [class.logo--claro]="variante === 'claro'">
      <svg class="logo__marca" viewBox="0 0 32 32" role="img" aria-label="MapFace">
        <rect class="logo__fundo" width="32" height="32" rx="9" />
        <path
          class="logo__malha"
          d="M11 11 16 16.5 21 11M11.5 22 16 16.5 20.5 22M11 11 11.5 22M21 11 20.5 22"
          fill="none"
        />
        <g class="logo__pontos">
          <circle cx="11" cy="11" r="2.1" />
          <circle cx="21" cy="11" r="2.1" />
          <circle cx="16" cy="16.5" r="2.1" />
          <circle cx="11.5" cy="22" r="2.1" />
          <circle cx="20.5" cy="22" r="2.1" />
        </g>
      </svg>
      <span class="logo__nome" aria-hidden="true">Map<b>Face</b></span>
    </span>
  `,
})
export class LogoComponent {
  /** `claro` inverte as cores para uso sobre o painel escuro da tela de acesso. */
  @Input() variante: 'padrao' | 'claro' = 'padrao';
}
