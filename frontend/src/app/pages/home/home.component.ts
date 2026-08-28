import { DatePipe, DecimalPipe } from '@angular/common';
import {
  Component,
  ElementRef,
  OnDestroy,
  OnInit,
  computed,
  NgZone,
  effect,
  inject,
  signal,
  untracked,
  viewChild,
} from '@angular/core';
import { Router } from '@angular/router';
import { Observable } from 'rxjs';

import { formatarDuracao } from '../../core/tempo';
import { AuthService } from '../../core/services/auth.service';
import {
  CameraService,
  FalhaDeCamera,
  MENSAGENS_DE_FALHA_DE_CAMERA,
} from '../../core/services/camera.service';
import { InactivityService } from '../../core/services/inactivity.service';
import { SessaoService } from '../../core/services/sessao.service';
import { TelemetriaService } from '../../core/telemetria/telemetria.service';
import { LandmarksService } from '../../core/visao/landmarks.service';
import { IconeComponent } from '../../shared/icone.component';
import { LogoComponent } from '../../shared/logo.component';

@Component({
  selector: 'app-home',
  standalone: true,
  imports: [DatePipe, DecimalPipe, LogoComponent, IconeComponent],
  templateUrl: './home.component.html',
})
export class HomeComponent implements OnInit, OnDestroy {
  private readonly authService = inject(AuthService);
  private readonly cameraService = inject(CameraService);
  private readonly inactivityService = inject(InactivityService);
  private readonly landmarksService = inject(LandmarksService);
  private readonly sessaoService = inject(SessaoService);
  private readonly telemetriaService = inject(TelemetriaService);
  private readonly router = inject(Router);
  private readonly zone = inject(NgZone);

  private readonly preview = viewChild<ElementRef<HTMLVideoElement>>('preview');

  readonly sessaoAtiva = this.sessaoService.sessaoAtiva;
  readonly streamDaWebcam = this.cameraService.stream;

  /**
   * Proporção real da câmera, para a caixa do preview acompanhá-la.
   *
   * Enquanto não há stream fica `null`, e o CSS usa a proporção de fallback —
   * o que reserva o espaço antes do primeiro quadro e evita a tela pular.
   */
  readonly proporcaoDoPreview = this.cameraService.proporcao;
  readonly metricas = this.landmarksService.metricas;
  readonly fps = this.landmarksService.fps;
  readonly score = this.telemetriaService.score;
  readonly telemetriaConectada = this.telemetriaService.conectado;
  readonly capturaConfiavel = this.telemetriaService.capturaConfiavel;

  /** Piso de FPS exigido pela ticket 5. Abaixo disso a interface avisa o aluno. */
  readonly FPS_MINIMO = 15;

  /**
   * Relógio do cronômetro, avançando de segundo em segundo.
   *
   * É um signal em vez de um `Date.now()` lido no template porque o template
   * não tem como saber que o tempo passou: sem uma fonte reativa, o cronômetro
   * só se atualizaria quando outra coisa da tela mudasse.
   */
  private readonly agora = signal(Date.now());
  private relogio: ReturnType<typeof setInterval> | null = null;

  /**
   * Há quanto tempo a sessão corrente começou, formatado, ou `null` sem sessão.
   *
   * O início vem do **servidor**, e não do instante em que esta tela abriu:
   * recarregar a página no meio de uma sessão não pode zerar o cronômetro.
   */
  readonly duracaoDaSessao = computed(() => {
    const sessao = this.sessaoAtiva();
    if (sessao === null) {
      return null;
    }
    return formatarDuracao((this.agora() - new Date(sessao.inicio).getTime()) / 1000);
  });

  erro: string | null = null;
  aguardando = false;

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
          });
        }
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
    // **Fora da zona do Angular**, como o amostrador do `TelemetriaService`.
    // Um `setInterval` dentro dela é uma tarefa periódica que nunca termina, e
    // a aplicação nunca mais fica estável: `whenStable()` deixa de resolver e
    // todo teste assíncrono desta tela estoura por timeout. A escrita no signal
    // agenda a detecção de mudanças por conta própria, então o cronômetro
    // continua redesenhando.
    this.zone.runOutsideAngular(() => {
      this.relogio = setInterval(() => this.agora.set(Date.now()), 1000);
    });

    // Recarregar a página no meio de uma sessão não pode "perder" a sessão:
    // o backend é a fonte da verdade sobre o que está em andamento.
    this.sessaoService.carregarAtiva().subscribe({
      next: (sessao) => {
        // A sessão sobreviveu ao reload, mas a captura não. Sem retomar a
        // webcam aqui, o backend seguiria com uma sessão em andamento que não
        // recebe telemetria nenhuma.
        if (sessao !== null) {
          void this.retomarCaptura();
        }
      },
      error: () => (this.erro = 'Não foi possível verificar se há uma sessão em andamento.'),
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

    this.sessaoService.iniciar().subscribe({
      next: () => (this.aguardando = false),
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
        falha instanceof FalhaDeCamera ? falha.message : MENSAGENS_DE_FALHA_DE_CAMERA['desconhecido'];
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
        this.telemetriaService.iniciar(token, () => this.landmarksService.metricas());
      }
    } catch {
      this.erro =
        'A webcam está funcionando, mas não foi possível carregar o modelo de análise facial. A sessão segue sendo registrada, sem métricas de engajamento.';
    }
  }

  encerrarSessao(): void {
    this.executar(
      () => this.sessaoService.encerrar(),
      'Não foi possível encerrar a sessão de estudo. Tente novamente.',
    );
  }

  sair(): void {
    this.inactivityService.pararMonitoramento();
    this.telemetriaService.parar();
    this.landmarksService.parar();
    this.cameraService.encerrar();
    this.sessaoService.esquecerSessao();
    this.authService.logout();
    this.router.navigate(['/login']);
  }

  private executar(acao: () => Observable<unknown>, mensagemDeErro: string): void {
    this.erro = null;
    this.aguardando = true;

    acao().subscribe({
      next: () => (this.aguardando = false),
      error: () => {
        this.aguardando = false;
        this.erro = mensagemDeErro;
      },
    });
  }

  /**
   * `CameraService` vive na raiz da aplicação e sobrevive a esta tela; sair dela
   * sem desligar a webcam deixaria a captura rodando em segundo plano.
   */
  ngOnDestroy(): void {
    if (this.relogio !== null) {
      clearInterval(this.relogio);
      this.relogio = null;
    }
    this.telemetriaService.parar();
    this.landmarksService.parar();
    this.cameraService.encerrar();
  }
}
