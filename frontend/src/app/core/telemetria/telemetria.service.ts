import { Injectable, InjectionToken, NgZone, OnDestroy, inject, signal } from '@angular/core';

import { API_URL, baseDeWebSocket } from '../api';
import { LeituraDaCaptura } from '../visao/landmarks.service';
import { AuthService } from '../services/auth.service';
import { PayloadDeTelemetria, agregar } from './agregacao';

/**
 * URL do canal de telemetria.
 *
 * Deriva da API para não haver duas configurações — o que este comentário já
 * afirmava enquanto a linha abaixo era um literal com `localhost` dentro.
 * Agora é verdade: a única coisa configurável é `API_URL`, e o esquema `ws`/
 * `wss` acompanha o `http`/`https` dela sozinho (ver `baseDeWebSocket`).
 */
export const URL_DA_TELEMETRIA = `${baseDeWebSocket(API_URL)}/telemetria`;

/**
 * De quanto em quanto tempo uma amostra é tirada da captura.
 *
 * Casado com a cadência de publicação do `LandmarksService`: amostrar mais
 * rápido que ele só repetiria a mesma leitura.
 */
export const INTERVALO_DE_AMOSTRAGEM_MS = 250;

/** Cadência da telemetria. O spec fala em logs "segundo a segundo". */
export const INTERVALO_DE_ENVIO_MS = 1000;

/**
 * Quantas amostras formam uma janela de envio.
 *
 * A amostragem e o envio saem do **mesmo** temporizador de propósito. Com dois
 * temporizadores independentes, a amostra que cai exatamente na fronteira do
 * segundo pertence a uma janela ou à outra conforme a ordem em que os timers
 * disparam — e o resultado é uma leitura vazando para a janela seguinte, sem
 * erro nenhum, só com o número levemente errado.
 */
export const AMOSTRAS_POR_JANELA = INTERVALO_DE_ENVIO_MS / INTERVALO_DE_AMOSTRAGEM_MS;

export const DELAY_INICIAL_DE_RECONEXAO_MS = 1000;
export const DELAY_MAXIMO_DE_RECONEXAO_MS = 30000;

/** O mínimo que o serviço usa de um WebSocket — o suficiente para dublar em teste. */
export interface CanalDeTelemetria {
  send(dados: string): void;
  close(): void;
  onopen: (() => void) | null;
  onmessage: ((evento: { data: string }) => void) | null;
  onclose: (() => void) | null;
}

export type CriadorDeCanal = (url: string) => CanalDeTelemetria;

export const CRIADOR_DE_CANAL = new InjectionToken<CriadorDeCanal>('CriadorDeCanal', {
  providedIn: 'root',
  factory: (): CriadorDeCanal => (url) => new WebSocket(url) as unknown as CanalDeTelemetria,
});

/**
 * Leva as métricas faciais ao backend e recebe o score de volta (ticket 6).
 *
 * Amostra a captura ao longo de um segundo, resume a janela num payload e
 * envia. O que sai daqui são três números — `ear`, `yaw` e presença de rosto.
 * Nenhum landmark, nenhum frame: a agregação é a última fronteira antes da
 * rede, e `PayloadDeTelemetria` é o contrato que define o que pode atravessá-la.
 */
@Injectable({ providedIn: 'root' })
export class TelemetriaService implements OnDestroy {
  private readonly zone = inject(NgZone);
  private readonly criarCanal = inject(CRIADOR_DE_CANAL);
  private readonly authService = inject(AuthService);

  private canal: CanalDeTelemetria | null = null;
  private tokenInicial: string | null = null;
  private lerCaptura: (() => LeituraDaCaptura) | null = null;

  private janela: LeituraDaCaptura[] = [];
  private amostrador: ReturnType<typeof setInterval> | null = null;
  private amostrasNaJanela = 0;
  private reconexao: ReturnType<typeof setTimeout> | null = null;
  private delayDeReconexao = DELAY_INICIAL_DE_RECONEXAO_MS;
  private autenticado = false;
  private encerrado = false;

  private readonly scoreSignal = signal<number | null>(null);
  private readonly calibrandoSignal = signal(false);
  private readonly fadigaSignal = signal(0);
  private readonly motivosSignal = signal<readonly string[]>([]);
  // `string`, e não `MotivoDeIncerteza`: o rótulo é o que o backend gravou, e
  // ele inclui `desconhecida` para uma causa que o servidor ainda não conhece.
  // Fingir aqui que só os três motivos existem faria o `Record` de mensagens
  // devolver `undefined` sem que o compilador avisasse.
  private readonly incertezaSignal = signal<string | null>(null);
  private readonly conectadoSignal = signal(false);

  /**
   * Último score devolvido pelo backend, ou `null`.
   *
   * `null` cobre dois casos que a interface precisa distinguir: ainda não
   * chegou nenhum score, e a última leitura foi descartada por incerteza de
   * captura (ticket 10) — este último acompanhado de `incerteza`.
   */
  readonly score = this.scoreSignal.asReadonly();

  /**
   * Se o último score veio do primeiro minuto de calibração (ticket 7).
   *
   * Nesse trecho o backend ainda mede contra uma referência genérica, porque a
   * baseline do aluno não fechou. O número é utilizável, mas não é comparável
   * com o resto da sessão, e o relatório precisa poder dizer isso.
   */
  readonly calibrando = this.calibrandoSignal.asReadonly();

  /**
   * Quanto o fator de fadiga descontou do score, em pontos (ticket 8).
   *
   * Vem acompanhado de `motivosDeFadiga` porque um desconto sem explicação é um
   * número que o aluno não tem como usar.
   */
  readonly fadiga = this.fadigaSignal.asReadonly();

  /** Por que houve penalidade: `palpebras-pesadas`, `olhos-fechados-prolongados`, `bocejos`. */
  readonly motivosDeFadiga = this.motivosSignal.asReadonly();

  /**
   * Por que o backend se absteve de medir, ou `null` (ticket 10).
   *
   * Vem do próprio backend, e não do `LandmarksService`, de propósito: o que a
   * interface mostra tem que ser o que de fato aconteceu com o dado gravado. Um
   * aviso local sobre uma leitura que subiu e virou score seria a interface
   * contando uma história diferente da do banco.
   */
  readonly incerteza = this.incertezaSignal.asReadonly();

  readonly conectado = this.conectadoSignal.asReadonly();

  /**
   * Abre o canal e passa a enviar telemetria. Idempotente.
   *
   * @param lerCaptura devolve a leitura corrente e o veredito sobre ela.
   */
  iniciar(token: string, lerCaptura: () => LeituraDaCaptura): void {
    if (this.canal !== null || this.reconexao !== null) {
      return;
    }

    this.tokenInicial = token;
    this.lerCaptura = lerCaptura;
    this.encerrado = false;
    this.delayDeReconexao = DELAY_INICIAL_DE_RECONEXAO_MS;

    this.conectar();
  }

  /** Encerra o canal e impede qualquer reconexão futura. Idempotente. */
  parar(): void {
    this.encerrado = true;
    this.autenticado = false;

    this.pararTemporizadores();

    if (this.reconexao !== null) {
      clearTimeout(this.reconexao);
      this.reconexao = null;
    }

    if (this.canal !== null) {
      this.canal.onclose = null;
      this.canal.close();
      this.canal = null;
    }

    this.janela = [];
    this.scoreSignal.set(null);
    this.calibrandoSignal.set(false);
    this.fadigaSignal.set(0);
    this.motivosSignal.set([]);
    this.incertezaSignal.set(null);
    this.conectadoSignal.set(false);
  }

  /**
   * A credencial mandada na abertura do canal — sempre a **corrente**.
   *
   * Não é o token recebido em `iniciar`, e a diferença deixou de ser teórica. O
   * canal reconecta sozinho, com backoff, por quantas horas durar a sessão; a
   * credencial, por sua vez, é trocada a cada renovação. Um retrato tirado no
   * começo da sessão estaria vencido na primeira reconexão depois dos 30
   * minutos — e como o servidor passou a reavaliar o `exp` do canal aberto, o
   * desfecho não seria um erro visível: seria o servidor recusando, o cliente
   * reconectando com o mesmo token morto, e um laço de reconexão silencioso
   * até o fim da sessão, com a telemetria parada.
   *
   * O token de `iniciar` fica como recurso para quem não tem credencial
   * armazenada — o caso dos testes, e o de qualquer chamador que queira
   * autenticar o canal explicitamente.
   */
  private tokenDoCanal(): string | null {
    return this.authService.getToken() ?? this.tokenInicial;
  }

  private conectar(): void {
    const canal = this.criarCanal(URL_DA_TELEMETRIA);
    this.canal = canal;

    canal.onopen = () => {
      // Autenticação pela primeira mensagem: WebSocket de navegador não manda
      // header `Authorization`, e token em query string vazaria para log de
      // servidor, proxy e histórico.
      canal.send(JSON.stringify({ token: this.tokenDoCanal() }));
    };

    canal.onmessage = (evento) => this.zone.run(() => this.receber(evento.data));

    canal.onclose = () => this.zone.run(() => this.aoCair());
  }

  private receber(bruto: string): void {
    type MensagemDeScore = {
      tipo?: string;
      score?: number | null;
      calibrando?: boolean;
      fadiga?: number;
      motivos_fadiga?: string[];
      incerteza?: string | null;
    };

    let mensagem: MensagemDeScore;
    try {
      mensagem = JSON.parse(bruto) as MensagemDeScore;
    } catch {
      return;
    }

    if (mensagem.tipo === 'autenticado') {
      this.autenticado = true;
      this.conectadoSignal.set(true);
      // Reconectou e o servidor aceitou: o próximo tropeço merece de novo a
      // espera curta.
      this.delayDeReconexao = DELAY_INICIAL_DE_RECONEXAO_MS;
      this.iniciarTemporizadores();
      return;
    }

    if (mensagem.tipo !== 'score') {
      return;
    }

    // `score: null` é a abstenção da ticket 10, e é uma mensagem válida — não
    // um campo faltando. Só um tipo inesperado (string, objeto) é descartado.
    const score = mensagem.score;
    if (typeof score !== 'number' && score !== null) {
      return;
    }

    this.scoreSignal.set(score);
    this.incertezaSignal.set(mensagem.incerteza ?? null);
    // Ausente é tratado como "não está calibrando": um backend anterior à
    // ticket 7 não manda o campo, e assumir calibração eterna deixaria o aviso
    // preso na tela.
    this.calibrandoSignal.set(mensagem.calibrando === true);
    this.fadigaSignal.set(typeof mensagem.fadiga === 'number' ? mensagem.fadiga : 0);
    this.motivosSignal.set(Array.isArray(mensagem.motivos_fadiga) ? mensagem.motivos_fadiga : []);
  }

  private aoCair(): void {
    this.autenticado = false;
    this.conectadoSignal.set(false);
    // O alerta de incerteza pede uma **ação** do aluno ("acenda uma luz"), e a
    // queda pode durar os 30 s do backoff. Mantê-lo na tela sem canal para
    // confirmar que a condição passou faria o aluno mexer na iluminação de novo
    // à toa. O score congelado é ruim; um pedido congelado é pior.
    this.incertezaSignal.set(null);
    this.canal = null;
    this.pararTemporizadores();
    this.janela = [];

    if (this.encerrado) {
      // Sessão encerrada: reconectar aqui deixaria um laço rodando para sempre
      // em segundo plano, falando de uma sessão que não existe mais.
      return;
    }

    this.reconexao = setTimeout(() => {
      this.reconexao = null;
      // Backoff: servidor fora do ar não pode ser martelado a cada segundo por
      // todos os alunos com sessão aberta.
      this.delayDeReconexao = Math.min(this.delayDeReconexao * 2, DELAY_MAXIMO_DE_RECONEXAO_MS);
      this.conectar();
    }, this.delayDeReconexao);
  }

  private iniciarTemporizadores(): void {
    if (this.amostrador !== null) {
      return;
    }

    this.amostrasNaJanela = 0;
    this.zone.runOutsideAngular(() => {
      this.amostrador = setInterval(() => this.amostrar(), INTERVALO_DE_AMOSTRAGEM_MS);
    });
  }

  private pararTemporizadores(): void {
    if (this.amostrador !== null) {
      clearInterval(this.amostrador);
      this.amostrador = null;
    }
    this.amostrasNaJanela = 0;
  }

  private amostrar(): void {
    this.janela.push(this.lerCaptura?.() ?? { metricas: null, incerteza: null });
    this.amostrasNaJanela += 1;

    // Enviar aqui, e não num temporizador próprio, é o que garante que a
    // amostra da fronteira pertence à janela que está sendo fechada.
    if (this.amostrasNaJanela >= AMOSTRAS_POR_JANELA) {
      this.amostrasNaJanela = 0;
      this.enviar();
    }
  }

  private enviar(): void {
    const payload: PayloadDeTelemetria | null = agregar(this.janela);
    // Limpar antes de qualquer saída: uma janela que não foi enviada não pode
    // contaminar a seguinte.
    this.janela = [];

    if (payload === null || this.canal === null || !this.autenticado) {
      return;
    }

    this.canal.send(JSON.stringify(payload));
  }

  ngOnDestroy(): void {
    this.parar();
  }
}
