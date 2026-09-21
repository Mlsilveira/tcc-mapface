import { DatePipe, DecimalPipe } from '@angular/common';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';

import { Relatorio, RelatorioService } from '../../core/services/relatorio.service';
import { formatarDuracao } from '../../shared/duracao';
import { GraficoIeeComponent, PontoDoIEE } from '../../shared/grafico-iee.component';
import { IconeComponent } from '../../shared/icone.component';
import { LogoComponent } from '../../shared/logo.component';

/**
 * O relatório de autopercepção de uma sessão encerrada (ticket 11).
 *
 * É a contrapartida da tela de sessão, que deliberadamente não mostra nada:
 * tudo o que foi medido enquanto o aluno estudava chega aqui de uma vez, depois
 * que ele parou. O MapFace é um espelho retrospectivo, e esta é a superfície do
 * espelho.
 *
 * **Três distinções que a tela não pode colapsar**, porque são o que as tickets
 * 8 e 10 compraram:
 *
 * - *Tempo medido* não é *tempo de sessão aberta*. Os dois aparecem lado a
 *   lado; exibir só o segundo faria a aba esquecida virar tempo de estudo.
 * - *Não deu para medir* não é *score zero*. Média nula vira um traço com
 *   explicação, nunca um "0" — que diria que o aluno estava ali e desengajado.
 * - *Alerta de fadiga* não é *motivo de incerteza*. O primeiro é observação
 *   sobre o aluno, o segundo é diagnóstico do equipamento, e misturá-los faria
 *   "sua sala estava escura" soar como um defeito dele.
 *
 * **E uma quarta, que a ticket 17 acrescentou.** *Sem método declarado* não é
 * *método "livre"*. A sessão anterior ao recurso abre com traço e sem seção de
 * método nenhuma; a sessão em que o aluno escolheu não usar método abre com o
 * nome dessa escolha. Colapsar as duas na renderização desfaria a distinção que
 * o modelo custou a preservar.
 *
 * **Nenhuma frase de critério nasce neste arquivo.** Elas chegam prontas de
 * `app/criterios.py`, onde o teste de tom as varre — uma frase escrita aqui
 * sairia do alcance dele, e a trava morreria no mesmo commit em que o recurso
 * nasce. O template renderiza `titulo`, `texto` e `detalhe` e não decide nada
 * sobre o que eles dizem.
 */
@Component({
  selector: 'app-relatorio',
  standalone: true,
  imports: [DatePipe, DecimalPipe, RouterLink, GraficoIeeComponent, IconeComponent, LogoComponent],
  templateUrl: './relatorio.component.html',
})
export class RelatorioComponent implements OnInit {
  private readonly rota = inject(ActivatedRoute);
  private readonly relatorioService = inject(RelatorioService);

  readonly relatorio = signal<Relatorio | null>(null);
  readonly carregando = signal(true);
  readonly erro = signal<string | null>(null);

  /**
   * A série no formato do gráfico: instante em milissegundos, score como está.
   *
   * O `null` é repassado intocado. Convertê-lo para zero aqui seria desfazer a
   * ticket 10 na última linha do caminho, depois de ela ter sido respeitada no
   * navegador, no WebSocket, no banco e na API.
   */
  readonly serie = computed<readonly PontoDoIEE[]>(() =>
    (this.relatorio()?.serie ?? []).map((ponto) => ({
      instante: Date.parse(ponto.instante),
      score: ponto.score,
    })),
  );

  /** Sessão encerrada sem que nenhuma leitura tenha chegado ao servidor. */
  readonly semDados = computed(() => {
    const relatorio = this.relatorio();
    return relatorio !== null && relatorio.pontos_medidos + relatorio.pontos_incertos === 0;
  });

  ngOnInit(): void {
    const id = Number(this.rota.snapshot.paramMap.get('id'));

    if (!Number.isInteger(id) || id <= 0) {
      // URL digitada à mão ou link truncado. Pedir `/sessoes/NaN/relatorio` ao
      // backend só trocaria esta mensagem por um 422 menos legível.
      this.carregando.set(false);
      this.erro.set('Este endereço de relatório não é válido.');
      return;
    }

    this.relatorioService.buscar(id).subscribe({
      next: (relatorio) => {
        this.relatorio.set(relatorio);
        this.carregando.set(false);
      },
      error: (falha: { status?: number }) => {
        this.carregando.set(false);
        this.erro.set(this.mensagemDeFalha(falha?.status));
      },
    });
  }

  duracao(segundos: number): string {
    return formatarDuracao(segundos);
  }

  /**
   * Quanto da sessão não pôde ser medido, em segundos.
   *
   * Sai de `pontos_incertos` e não da diferença entre as durações: os pontos
   * chegam a 1 Hz, então cada ponto incerto é um segundo em que a captura
   * estava rodando e ainda assim não produziu número — que é uma informação
   * diferente de "a captura estava parada".
   */
  segundosIncertos(): number {
    return this.relatorio()?.pontos_incertos ?? 0;
  }

  /**
   * O `data-teste` de um critério, derivado do código que o backend mandou.
   *
   * Os dois critérios que as ACs nomeiam — cadência e pausas — ganham seletor
   * próprio; os demais compartilham um. Derivar do código em vez de montar uma
   * seção por critério mantém a lista aberta: um critério novo aparece na tela
   * sem precisar de template novo, que é o ponto de as frases nascerem no
   * backend.
   */
  testeDoCriterio(codigo: string): string {
    if (codigo === 'cadencia' || codigo === 'pausas') {
      return `relatorio-${codigo}`;
    }
    return 'relatorio-criterio';
  }

  private mensagemDeFalha(status?: number): string {
    if (status === 404) {
      // Mesma mensagem que o backend produz para sessão de outro aluno: se a
      // tela distinguisse os dois casos, ela reintroduziria no navegador o
      // oráculo de existência que o 404 do servidor existe para fechar.
      return 'Relatório não encontrado.';
    }
    if (status === 409) {
      return 'Esta sessão ainda está em andamento. O relatório fica disponível quando você encerrá-la.';
    }
    return 'Não foi possível carregar o relatório. Tente novamente em instantes.';
  }
}
