import { DatePipe, DecimalPipe, PercentPipe } from '@angular/common';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';

import {
  Relatorio,
  RelatorioService,
  serieParaOGrafico,
} from '../../core/services/relatorio.service';
import { formatarDuracao } from '../../core/tempo';
import { GraficoIeeComponent } from '../../shared/grafico-iee.component';
import { IconeComponent } from '../../shared/icone.component';
import { LogoComponent } from '../../shared/logo.component';

/**
 * Como cada motivo de alerta se chama para o aluno.
 *
 * Os identificadores do banco (`palpebras-pesadas`) existem para o código; o
 * aluno lê a frase. Um motivo desconhecido cai no próprio identificador em vez
 * de sumir: se o backend passar a gravar um alerta novo, é melhor a tela
 * mostrar um nome feio do que esconder que alguma coisa aconteceu.
 */
export const NOMES_DOS_ALERTAS: Record<string, string> = {
  'palpebras-pesadas': 'Pálpebras pesadas',
  'olhos-fechados-prolongados': 'Olhos fechados por vários segundos',
  bocejos: 'Bocejos',
  'incerteza-de-captura': 'Captura instável',
};

/** Um alerta já pronto para a lista da tela. */
export interface AlertaExibido {
  nome: string;
  leituras: number;
}

/**
 * Queda, em pontos, a partir da qual a tela destaca a tendência.
 *
 * É o mesmo `QUEDA_RELEVANTE` que o backend usa para decidir se recomenda algo
 * a respeito — de propósito. Dois limiares diferentes fariam a seta aparecer
 * sem a recomendação ao lado, ou o contrário, e o aluno leria como incoerência.
 */
export const LIMIAR_DE_QUEDA = 15;

@Component({
  selector: 'app-relatorio',
  standalone: true,
  imports: [DatePipe, DecimalPipe, PercentPipe, GraficoIeeComponent, IconeComponent, LogoComponent],
  templateUrl: './relatorio.component.html',
})
export class RelatorioComponent implements OnInit {
  private readonly rota = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly relatorioService = inject(RelatorioService);

  readonly relatorio = signal<Relatorio | null>(null);
  readonly carregando = signal(true);
  readonly erro = signal<string | null>(null);

  /** Exposto para o template, que não enxerga constantes de módulo. */
  readonly LIMIAR_DE_QUEDA = LIMIAR_DE_QUEDA;

  /** A série do IEE já com os trechos incertos apagados. */
  readonly serie = computed(() => {
    const relatorio = this.relatorio();
    return relatorio === null ? [] : serieParaOGrafico(relatorio.serie);
  });

  /**
   * `true` quando a sessão não produziu nenhuma leitura utilizável.
   *
   * Vale a distinção: uma sessão sem medição não é uma sessão ruim, é uma
   * sessão que não foi medida — quase sempre webcam negada. Mostrar zeros ali
   * faria o relatório afirmar que o aluno esteve disperso.
   */
  readonly semMedicao = computed(() => (this.relatorio()?.indicadores.n_leituras ?? 0) === 0);

  readonly duracao = computed(() => {
    const relatorio = this.relatorio();
    return relatorio === null ? '' : formatarDuracao(relatorio.indicadores.duracao_s);
  });

  /**
   * A tendência da sessão, em pontos entre o primeiro e o último terço.
   *
   * Negativo quer dizer que o índice subiu. Quem decide se o número merece
   * destaque é o template — aqui só se calcula.
   */
  readonly queda = computed(() => {
    const indicadores = this.relatorio()?.indicadores;
    return indicadores === undefined ? 0 : indicadores.score_inicio - indicadores.score_fim;
  });

  readonly alertas = computed<AlertaExibido[]>(() => {
    const registrados = this.relatorio()?.alertas ?? {};
    return Object.entries(registrados)
      .map(([motivo, leituras]) => ({ nome: NOMES_DOS_ALERTAS[motivo] ?? motivo, leituras }))
      .sort((a, b) => b.leituras - a.leituras);
  });

  ngOnInit(): void {
    const id = Number(this.rota.snapshot.paramMap.get('id'));

    // Um id que não é número nunca chegaria ao backend como consulta válida, e
    // pedir mesmo assim trocaria uma mensagem clara por um 422 traduzido mal.
    if (!Number.isInteger(id) || id <= 0) {
      this.carregando.set(false);
      this.erro.set('Sessão inválida.');
      return;
    }

    this.relatorioService.buscar(id).subscribe({
      next: (relatorio) => {
        this.relatorio.set(relatorio);
        this.carregando.set(false);
      },
      error: (falha: { status?: number }) => {
        this.carregando.set(false);
        this.erro.set(
          falha?.status === 404
            ? 'Esta sessão não existe ou não é sua.'
            : 'Não foi possível carregar o relatório desta sessão. Tente novamente.',
        );
      },
    });
  }

  voltar(): void {
    this.router.navigate(['/home']);
  }
}
