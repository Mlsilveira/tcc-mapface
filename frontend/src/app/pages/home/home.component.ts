import { DatePipe, DecimalPipe } from '@angular/common';
import {
  Component,
  ElementRef,
  OnDestroy,
  OnInit,
  computed,
  effect,
  inject,
  signal,
  untracked,
  viewChild,
} from '@angular/core';
import { Router, RouterLink } from '@angular/router';

import { AuthService } from '../../core/services/auth.service';
import {
  CameraService,
  FalhaDeCamera,
  MENSAGENS_DE_FALHA_DE_CAMERA,
} from '../../core/services/camera.service';
import { InactivityService } from '../../core/services/inactivity.service';
import { MetodoService } from '../../core/services/metodo.service';
import {
  Bloco,
  DeclaracaoDeSessao,
  ORIGEM_ALUNO,
  ORIGEM_METODO,
  OrigemDeBloco,
  Sessao,
  SessaoService,
  TIPO_FOCO,
  TIPO_PAUSA,
  TipoDeBloco,
} from '../../core/services/sessao.service';
import { TelemetriaService } from '../../core/telemetria/telemetria.service';
import { LandmarksService } from '../../core/visao/landmarks.service';
import { mensagemDeIncerteza } from '../../core/visao/qualidade';
import { formatarDuracao } from '../../shared/duracao';
import { IconeComponent } from '../../shared/icone.component';
import { LogoComponent } from '../../shared/logo.component';
import {
  blocoAberto,
  duracaoPrescrita,
  ehPausaLonga,
  focosDeclarados,
  segundosRestantes,
} from './ciclo';

/** De quanto em quanto tempo o cronômetro do bloco é redesenhado. */
const PASSO_DO_RELOGIO_MS = 1000;

/**
 * A tela da sessão de estudo.
 *
 * **O que ela deliberadamente não mostra: o score.** O aluno é medido aqui, mas
 * só recebe a leitura no relatório, depois de encerrar. Um número de atenção na
 * tela compete com a tarefa que ele mede — o aluno olha para o número, e o ato
 * de olhar derruba o número —, e o gráfico vira a coisa mais interessante da
 * tela justamente quando o objetivo era o material de estudo.
 *
 * O que aparece durante a sessão é só o que ele pode **agir a respeito agora**:
 * o preview da webcam, o FPS da captura e o alerta de incerteza. Nenhum deles é
 * avaliação de desempenho; os três são diagnóstico do equipamento, e existem
 * para que a sessão não termine num relatório vazio.
 *
 * **O cronômetro do método entrou aqui em 21/09/2026, e a régua mudou com ele.**
 * A regra era "só o que é diagnóstico de equipamento passa", e um cronômetro
 * não é diagnóstico de equipamento nenhum — esticar a frase para acomodá-lo
 * seria a desonestidade barata. A régua passou a ser **nada na tela é derivado
 * do comportamento medido do aluno** (AC-17-8), que é mais precisa que a
 * anterior e continua excluindo o score pelo mesmo motivo de 27/08/2026: o laço
 * de realimentação. O cronômetro não tem esse laço, porque o que ele mostra sai
 * do método declarado e do relógio de parede, e não da medição.
 *
 * Na prática: tempo restante, "foco"/"pausa", "bloco 2 de 4" (só se houve meta
 * declarada) e o aviso da hora da pausa podem aparecer. Score, IEE, cor
 * avaliativa, ícone de aprovação e qualquer frase sobre o estado interno do
 * aluno, não — e `home.component.spec.ts` tem uma trava que quebra se alguém
 * acrescentar um deles.
 */
@Component({
  selector: 'app-home',
  standalone: true,
  imports: [DatePipe, DecimalPipe, RouterLink, LogoComponent, IconeComponent],
  templateUrl: './home.component.html',
})
export class HomeComponent implements OnInit, OnDestroy {
  private readonly authService = inject(AuthService);
  private readonly cameraService = inject(CameraService);
  private readonly inactivityService = inject(InactivityService);
  private readonly landmarksService = inject(LandmarksService);
  private readonly metodoService = inject(MetodoService);
  private readonly sessaoService = inject(SessaoService);
  private readonly telemetriaService = inject(TelemetriaService);
  private readonly router = inject(Router);

  private readonly preview = viewChild<ElementRef<HTMLVideoElement>>('preview');

  readonly sessaoAtiva = this.sessaoService.sessaoAtiva;
  readonly streamDaWebcam = this.cameraService.stream;
  readonly metricas = this.landmarksService.metricas;
  readonly fps = this.landmarksService.fps;
  readonly telemetriaConectada = this.telemetriaService.conectado;
  readonly incerteza = this.telemetriaService.incerteza;

  /** Piso de FPS exigido pela ticket 5. Abaixo disso a interface avisa o aluno. */
  readonly FPS_MINIMO = 15;

  // ------------------------------------------------- o que o aluno declara ---

  /** Os métodos de `GET /metodos`. Vazio até ele responder — ou se ele falhar. */
  readonly catalogo = this.metodoService.catalogo;

  /** Enquanto for `true`, o catálogo não respondeu: nem sucesso, nem falha. */
  readonly carregandoCatalogo = signal(true);

  /**
   * O catálogo respondeu e não trouxe método nenhum.
   *
   * Estado explícito, e não "lista vazia": a tela precisa dizer que a escolha
   * está indisponível *agora* em vez de sugerir que o sistema não tem métodos.
   */
  readonly catalogoIndisponivel = computed(
    () => !this.carregandoCatalogo() && this.catalogo().length === 0,
  );

  /** Código do método escolhido; string vazia é "não quero declarar". */
  readonly metodoEscolhido = signal('');

  readonly assunto = signal('');

  readonly metaDeBlocos = signal<number | null>(null);

  /**
   * Os tetos de `assunto` e `meta_de_blocos`, repetidos aqui de propósito.
   *
   * O servidor valida os dois (`schemas.LIMITE_ASSUNTO_CARACTERES` e
   * `schemas.META_MAXIMA_DE_BLOCOS`) e continua sendo **a** barreira — o
   * cliente não pode ser a única, porque qualquer `curl` passa por fora dele.
   * O que estes números fazem é outra coisa: impedir que o aluno digite duzentos
   * caracteres para receber um 422 depois de clicar em "Iniciar". Cortesia de um
   * lado, barreira do outro.
   */
  readonly LIMITE_DO_ASSUNTO = 120;
  readonly META_MAXIMA_DE_BLOCOS = 12;

  // -------------------------------------------------- o ciclo em andamento ---

  /** Os blocos já declarados desta sessão, como o servidor os conhece. */
  private readonly blocosDaSessao = signal<readonly Bloco[]>([]);

  /** O bloco em andamento, ou `null` — inclusive em sessão sem método. */
  readonly blocoCorrente = computed(() => blocoAberto(this.blocosDaSessao()));

  /** O método declarado nesta sessão, resolvido contra o catálogo. */
  readonly metodoDaSessao = computed(() => this.metodoService.buscar(this.sessaoAtiva()?.metodo));

  private readonly quantosFocos = computed(() => focosDeclarados(this.blocosDaSessao()));

  /** Segundos que o método prescreve para o bloco corrente, ou `null`. */
  private readonly duracaoDoBloco = computed(() =>
    duracaoPrescrita(this.metodoDaSessao(), this.blocoCorrente(), this.quantosFocos()),
  );

  /**
   * A hora de parede, redesenhada de segundo em segundo enquanto há o que
   * descontar. É um signal, e não uma leitura direta de `Date.now()`, porque
   * `computed` só recalcula quando uma dependência muda — e o relógio do
   * sistema não é uma dependência que o Angular saiba observar.
   */
  private readonly agora = signal(Date.now());

  private readonly restanteDoBloco = computed(() => {
    const duracao = this.duracaoDoBloco();
    const bloco = this.blocoCorrente();
    if (duracao === null || bloco === null) {
      return null;
    }
    return segundosRestantes(bloco.inicio, duracao, this.agora());
  });

  /**
   * O tempo restante do bloco, já em frase, ou `null` quando não há prescrição.
   *
   * Reusa `formatarDuracao` em vez de um `mm:ss` próprio, e a escolha tem
   * consequência: o cronômetro mostra "24min" e só desce a segundos no último
   * minuto. É o que se quer. Um número mudando a cada segundo no canto da tela
   * compete com o material de estudo — o mesmo argumento que tirou o score
   * daqui —, e "24min" responde à única pergunta que o aluno faz de relance.
   */
  readonly cronometro = computed(() => {
    const restante = this.restanteDoBloco();
    return restante === null ? null : formatarDuracao(restante);
  });

  /**
   * "bloco 2 de 4", **só se houve meta declarada**.
   *
   * Sem denominador declarado não há denominador. Inventar um — usando os
   * ciclos do método, por exemplo — daria ao aluno um placar que ele nunca
   * pediu, e placar é o primeiro passo para o boletim que este produto inteiro
   * existe para não emitir.
   */
  readonly contadorDeBlocos = computed(() => {
    const meta = this.sessaoAtiva()?.meta_de_blocos;
    if (meta === null || meta === undefined || this.blocoCorrente() === null) {
      return null;
    }
    return `bloco ${this.quantosFocos()} de ${meta}`;
  });

  /**
   * O aviso da virada, ou `null` enquanto o bloco corre.
   *
   * É operacional, nunca juízo: diz o que fazer agora e não diz nada sobre como
   * foi o bloco que acabou. Ele **persiste** enquanto o aluno não declara a
   * transição — quem estourou o tempo prescrito precisa continuar vendo o
   * aviso, e não recebê-lo uma vez e perdê-lo.
   */
  readonly avisoDeTransicao = computed(() => {
    const bloco = this.blocoCorrente();
    const restante = this.restanteDoBloco();
    if (bloco === null || restante === null || restante > 0) {
      return null;
    }

    const fechandoOCiclo = ehPausaLonga(this.metodoDaSessao(), this.quantosFocos());

    if (bloco.tipo === TIPO_FOCO) {
      return fechandoOCiclo
        ? 'Hora da pausa longa: este era o último bloco de foco do ciclo.'
        : 'Hora da pausa. O bloco de foco só fecha quando você declarar.';
    }

    return fechandoOCiclo
      ? 'O ciclo terminou. Volte ao foco para começar outro, ou encerre a sessão.'
      : 'A pausa acabou. Volte ao foco quando estiver pronto.';
  });

  /** O rótulo do botão que declara a transição, na direção em que ela vai. */
  readonly acaoDoBloco = computed(() =>
    this.blocoCorrente()?.tipo === TIPO_FOCO ? 'Declarar pausa' : 'Voltar ao foco',
  );

  /**
   * O que dizer ao aluno quando a captura não sustenta uma medição (ticket 10).
   *
   * A mensagem é sempre uma ação que ele pode tomar — acender uma luz, mudar o
   * ângulo — e nunca uma leitura sobre ele. "Não consegui medir" é sobre o
   * sistema; "você parece disperso", dito a partir de um dado ruim, seria uma
   * afirmação sobre a pessoa tirada de uma lâmpada fraca.
   */
  mensagemDeIncerteza(): string | null {
    return mensagemDeIncerteza(this.incerteza());
  }

  erro: string | null = null;
  aguardando = false;

  private relogio: ReturnType<typeof setInterval> | null = null;

  constructor() {
    // A sessão pode terminar por caminhos que não passam por esta tela: o
    // backend encerra por inatividade e o heartbeat descobre isso sozinho. Se a
    // webcam só fosse desligada no clique de "Encerrar", ela continuaria ligada
    // depois de uma sessão que já morreu no servidor.
    //
    // `allowSignalWrites` porque desligar a câmera altera o signal de stream —
    // é um efeito colateral sobre recurso externo, que é justamente o que este
    // effect existe para coordenar.
    // `untracked` é essencial aqui: `encerrar()` lê o signal do stream, e sem
    // isolá-lo o effect passaria a depender também da câmera. Aí ligar a webcam
    // reagendaria o próprio effect — que, com a sessão ainda não criada,
    // desligaria a câmera recém-ligada. Exatamente a janela entre o
    // `getUserMedia` e a resposta do POST /sessoes.
    effect(
      () => {
        if (this.sessaoAtiva() === null) {
          untracked(() => {
            this.telemetriaService.parar();
            this.landmarksService.parar();
            this.cameraService.encerrar();
            // Os blocos são da sessão que acabou. Mantê-los faria a próxima
            // nascer no meio do ciclo da anterior.
            this.blocosDaSessao.set([]);
          });
        }
      },
      { allowSignalWrites: true },
    );

    // O relógio de parede só corre quando existe um bloco com duração prescrita
    // para descontar. Deixá-lo correndo sempre custaria um `setInterval` vivo na
    // tela inicial, em toda sessão sem método e em toda sessão de Flow — e faria
    // cada teste em `fakeAsync` desta tela ter de descartar uma tarefa periódica
    // que não existe para ele.
    //
    // `allowSignalWrites` porque ligar o relógio acerta a hora antes do primeiro
    // tique: sem isso o bloco seria desenhado com o instante em que a tela foi
    // construída, que pode ser muito antes — o aluno recarregou a página e ficou
    // um minuto lendo o pedido de permissão da webcam.
    effect(
      () => {
        const conduzindo = this.duracaoDoBloco() !== null;
        untracked(() => (conduzindo ? this.ligarRelogio() : this.desligarRelogio()));
      },
      { allowSignalWrites: true },
    );

    // O <video> só existe enquanto há sessão, então a ligação entre stream e
    // elemento precisa ser refeita toda vez que um dos dois aparece. A análise
    // de landmarks só pode começar depois que os dois existem: o MediaPipe lê
    // quadros do elemento, não do stream.
    effect(
      () => {
        const elemento = this.preview()?.nativeElement;
        const stream = this.streamDaWebcam();
        if (!elemento) {
          return;
        }

        elemento.srcObject = stream;
        if (stream !== null) {
          untracked(() => void this.analisar(elemento));
        }
      },
      { allowSignalWrites: true },
    );
  }

  ngOnInit(): void {
    this.carregarCatalogo();

    // Recarregar a página no meio de uma sessão não pode "perder" a sessão:
    // o backend é a fonte da verdade sobre o que está em andamento.
    this.sessaoService.carregarAtiva().subscribe({
      next: (sessao) => {
        // A sessão sobreviveu ao reload, mas a captura não. Sem retomar a
        // webcam aqui, o backend seguiria com uma sessão em andamento que não
        // recebe telemetria nenhuma.
        if (sessao !== null) {
          void this.retomarCaptura();
          this.sincronizarBlocos(sessao);
        }
      },
      error: () => (this.erro = 'Não foi possível verificar se há uma sessão em andamento.'),
    });
  }

  /**
   * Busca o catálogo de métodos.
   *
   * Buscado sempre, e não só quando a tela inicial aparece: depois de um F5 quem
   * precisa do catálogo é a tela da **sessão**, porque é de `foco_s` que sai o
   * cronômetro. Condicionar a busca daria duas regras para o mesmo dado.
   *
   * Falhar aqui não bloqueia nada. Trocar uma escolha opcional por uma
   * regressão no caminho principal — "não dá para estudar porque um GET
   * auxiliar caiu" — seria pagar caro demais por um recurso que o aluno pode
   * simplesmente não usar.
   */
  private carregarCatalogo(): void {
    this.metodoService.carregar().subscribe({
      next: () => this.carregandoCatalogo.set(false),
      error: () => this.carregandoCatalogo.set(false),
    });
  }

  /**
   * A webcam é pedida **antes** de criar a sessão no backend. Se a ordem fosse
   * invertida, negar a permissão deixaria uma `sessao_estudo` órfã no banco —
   * sem nenhum log de engajamento, e virando um relatório vazio mais adiante.
   */
  async iniciarSessao(): Promise<void> {
    this.erro = null;
    this.aguardando = true;

    try {
      await this.cameraService.solicitarAcesso();
    } catch (falha) {
      this.aguardando = false;
      this.erro =
        falha instanceof FalhaDeCamera
          ? falha.message
          : MENSAGENS_DE_FALHA_DE_CAMERA['desconhecido'];
      return;
    }

    this.sessaoService.iniciar(this.declaracao()).subscribe({
      next: (sessao) => {
        this.aguardando = false;
        this.sincronizarBlocos(sessao);
      },
      error: (falha: { status?: number }) => {
        this.aguardando = false;

        if (falha?.status === 409) {
          // Outra aba já iniciou a sessão. Ressincronizar em vez de deixar a
          // tela travada oferecendo "Iniciar" para algo que já está rodando —
          // e manter a câmera ligada, porque a sessão existe de fato.
          this.erro = 'Você já tem uma sessão de estudo em andamento.';
          this.sessaoService.carregarAtiva().subscribe({
            error: () => this.cameraService.encerrar(),
          });
          return;
        }

        // Sem sessão para alimentar, não há motivo para a webcam seguir ligada.
        this.cameraService.encerrar();
        this.erro = 'Não foi possível iniciar a sessão de estudo. Tente novamente.';
      },
    });
  }

  escolherMetodo(evento: Event): void {
    this.metodoEscolhido.set((evento.target as HTMLSelectElement).value);
  }

  /**
   * Trunca em vez de recusar.
   *
   * O `maxlength` do campo já impede digitar além do teto; o que sobra é o
   * aluno que **cola** um parágrafo inteiro, e esse caso precisa terminar no
   * mesmo lugar — com 120 caracteres no campo, à vista dele — em vez de render
   * um 422 depois do clique em "Iniciar".
   */
  escreverAssunto(evento: Event): void {
    const campo = evento.target as HTMLInputElement;
    this.assunto.set(campo.value.slice(0, this.LIMITE_DO_ASSUNTO));
  }

  /**
   * Campo vazio é meta **não declarada**, e não zero.
   *
   * A diferença importa na tela da sessão: sem meta não existe "bloco 2 de 4",
   * e um zero que atravessasse até lá viraria um "bloco 2 de 0".
   */
  escreverMeta(evento: Event): void {
    const bruto = (evento.target as HTMLInputElement).value.trim();
    if (bruto === '') {
      this.metaDeBlocos.set(null);
      return;
    }

    const numero = Math.trunc(Number(bruto));
    this.metaDeBlocos.set(
      Number.isFinite(numero) && numero >= 1 ? Math.min(numero, this.META_MAXIMA_DE_BLOCOS) : null,
    );
  }

  private declaracao(): DeclaracaoDeSessao {
    return {
      metodo: this.metodoEscolhido() || null,
      assunto: this.assunto(),
      meta_de_blocos: this.metaDeBlocos(),
    };
  }

  /**
   * Põe o cronômetro no bloco que o servidor diz estar aberto.
   *
   * A verdade sobre o bloco corrente é `GET /sessoes/{id}/blocos`, e não a
   * memória desta aba: é o que faz o F5 no meio de um Pomodoro continuar de
   * onde parou em vez de reiniciar o bloco.
   */
  private sincronizarBlocos(sessao: Sessao): void {
    // Sessão anterior ao recurso (`metodo IS NULL`) não tem ciclo para conduzir,
    // e abrir um bloco nela agora lhe daria um bloco que nunca existiu,
    // começando no meio da sessão.
    if (sessao.metodo === null || sessao.metodo === undefined) {
      this.blocosDaSessao.set([]);
      return;
    }

    this.sessaoService.listarBlocos(sessao.id).subscribe({
      next: (lista) => {
        this.blocosDaSessao.set(lista);

        // Sessão com método e sem bloco aberto é sessão que ainda não começou a
        // contar — ou que perdeu a primeira declaração na rede. Os dois casos se
        // resolvem do mesmo jeito, e o servidor absorve a repetição.
        if (blocoAberto(lista) === null) {
          this.declararTransicao(TIPO_FOCO, ORIGEM_METODO);
        }
      },
      error: () => (this.erro = 'Não foi possível recuperar o ciclo desta sessão de estudo.'),
    });
  }

  /**
   * O aluno declarou a transição: sai do foco para a pausa, ou volta.
   *
   * A origem é **derivada do cronômetro**, nunca perguntada: `"metodo"` quando o
   * tempo prescrito já tinha acabado — ele seguiu o plano — e `"aluno"` quando
   * antecipou. É a única coisa que separa "o método foi seguido" de "o método
   * foi reescrito no meio", e o servidor não tem como derivá-la porque não
   * guarda o cronômetro. Sem duração prescrita não há plano a seguir, e toda
   * transição é do aluno.
   */
  alternarBloco(): void {
    const bloco = this.blocoCorrente();
    if (bloco === null) {
      return;
    }

    const seguiuOPlano = this.restanteDoBloco() === 0;
    this.declararTransicao(
      bloco.tipo === TIPO_FOCO ? TIPO_PAUSA : TIPO_FOCO,
      seguiuOPlano ? ORIGEM_METODO : ORIGEM_ALUNO,
    );
  }

  private declararTransicao(tipo: TipoDeBloco, origem: OrigemDeBloco): void {
    const sessao = this.sessaoAtiva();
    if (sessao === null) {
      return;
    }

    this.sessaoService.declararBloco(sessao.id, tipo, origem).subscribe({
      next: (bloco) => this.absorver(bloco),
      // A retentativa já aconteceu dentro do serviço. Chegar aqui significa que
      // a borda se perdeu de vez, e calar transformaria um bloco sem borda num
      // bloco de duração errada no relatório — sem nada estourar em lugar nenhum.
      error: () => (this.erro = 'Não foi possível registrar a mudança de bloco. Tente de novo.'),
    });
  }

  /**
   * Adota o bloco que o servidor acabou de abrir e fecha o anterior na mesma
   * borda. Um `GET` logo depois do `POST` daria o mesmo resultado com uma viagem
   * a mais — e com uma janela em que a tela mostraria dois blocos abertos.
   *
   * Filtrar pelo `id` antes de acrescentar é o que absorve a **retentativa**: o
   * servidor é idempotente por tipo e devolve o mesmo bloco, que aqui substitui
   * a si mesmo em vez de virar um segundo.
   */
  private absorver(novo: Bloco): void {
    const anteriores = this.blocosDaSessao()
      .filter((bloco) => bloco.id !== novo.id)
      .map((bloco) => (bloco.fim === null ? { ...bloco, fim: novo.inicio } : bloco));

    this.blocosDaSessao.set([...anteriores, novo]);
  }

  private ligarRelogio(): void {
    this.agora.set(Date.now());
    if (this.relogio !== null) {
      return;
    }
    this.relogio = setInterval(() => this.agora.set(Date.now()), PASSO_DO_RELOGIO_MS);
  }

  private desligarRelogio(): void {
    if (this.relogio !== null) {
      clearInterval(this.relogio);
      this.relogio = null;
    }
  }

  /**
   * Retoma a captura de uma sessão que já estava em andamento. O navegador
   * lembra a permissão concedida para a origem, então isso normalmente não
   * gera um novo prompt para o aluno.
   */
  private async retomarCaptura(): Promise<void> {
    try {
      await this.cameraService.solicitarAcesso();
    } catch (falha) {
      this.erro =
        falha instanceof FalhaDeCamera
          ? falha.message
          : MENSAGENS_DE_FALHA_DE_CAMERA['desconhecido'];
    }
  }

  /**
   * Liga a extração de landmarks sobre o preview. Falhar aqui não derruba a
   * sessão: o aluno continua com a webcam e o registro de tempo, só sem
   * métricas — melhor que perder a sessão inteira por causa do modelo.
   */
  private async analisar(video: HTMLVideoElement): Promise<void> {
    try {
      await this.landmarksService.iniciar(video);

      // A telemetria só faz sentido depois que há o que medir. O token vai na
      // primeira mensagem do WebSocket, nunca na URL.
      const token = this.authService.getToken();
      if (token !== null) {
        this.telemetriaService.iniciar(token, () => this.landmarksService.leitura());
      }
    } catch {
      this.erro =
        'A webcam está funcionando, mas não foi possível carregar o modelo de análise facial. A sessão segue sendo registrada, sem métricas de engajamento.';
    }
  }

  /**
   * Encerra a sessão e leva ao relatório dela (AC-11-1).
   *
   * A navegação acontece no `next` e não depois da chamada porque o id vem da
   * resposta: `SessaoService.encerrar` já esqueceu a sessão local quando o
   * observable emite, e ler `sessaoAtiva()` aqui devolveria `null`.
   *
   * Falhar em encerrar não navega. O aluno continua na tela da sessão, que é
   * onde ele pode tentar de novo — mandá-lo para um relatório de uma sessão que
   * talvez ainda esteja aberta trocaria um erro claro por um 409 confuso.
   */
  encerrarSessao(): void {
    this.erro = null;
    this.aguardando = true;

    this.sessaoService.encerrar().subscribe({
      next: (sessao) => {
        this.aguardando = false;
        void this.router.navigate(['/relatorio', sessao.id]);
      },
      error: () => {
        this.aguardando = false;
        this.erro = 'Não foi possível encerrar a sessão de estudo. Tente novamente.';
      },
    });
  }

  /**
   * Sai da conta — encerrando de verdade a sessão de estudo, se houver uma.
   *
   * Até aqui `sair()` só chamava `esquecerSessao()`, que é local. O dano era
   * pequeno enquanto a sessão morria sozinha em minutos. Deixou de ser: agora
   * ela sobrevive até o limite de ausência do método, é fechada pela varredura
   * e marcada como `"inatividade"` — e o relatório sai carimbado de **parcial**,
   * dizendo ao aluno que a sessão foi interrompida quando ele a encerrou
   * deliberadamente ao sair.
   *
   * O encerramento vai antes do `logout()` porque precisa do token, que ainda é
   * válido neste instante. E falhar em encerrar **não** prende o aluno na tela:
   * ele pediu para sair, e sair é o que acontece. A sessão órfã é varrida
   * depois; um logout que não desloga seria um problema pior.
   */
  sair(): void {
    if (this.sessaoAtiva() === null) {
      this.descartarSessaoLocalESair();
      return;
    }

    this.sessaoService.encerrar().subscribe({
      next: () => this.descartarSessaoLocalESair(),
      error: () => this.descartarSessaoLocalESair(),
    });
  }

  private descartarSessaoLocalESair(): void {
    this.inactivityService.pararMonitoramento();
    this.telemetriaService.parar();
    this.landmarksService.parar();
    this.cameraService.encerrar();
    this.sessaoService.esquecerSessao();
    this.authService.logout();
    this.router.navigate(['/login']);
  }

  /**
   * `CameraService` vive na raiz da aplicação e sobrevive a esta tela; sair dela
   * sem desligar a webcam deixaria a captura rodando em segundo plano.
   */
  ngOnDestroy(): void {
    this.telemetriaService.parar();
    this.landmarksService.parar();
    this.cameraService.encerrar();
    this.desligarRelogio();
  }
}
