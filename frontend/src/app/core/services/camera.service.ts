import { Injectable, OnDestroy, signal } from '@angular/core';

/**
 * Por que a sessão não conseguiu a webcam. Cada motivo tem uma ação diferente
 * do lado do aluno — "negou permissão" se resolve no navegador, "sem webcam" é
 * hardware, "ocupada" é fechar o outro programa. Colapsar tudo num erro
 * genérico deixaria o aluno sem saber o que fazer.
 */
export type MotivoFalhaDeCamera =
  | 'permissao-negada'
  | 'sem-webcam'
  | 'webcam-ocupada'
  | 'contexto-inseguro'
  | 'desconhecido';

export const MENSAGENS_DE_FALHA_DE_CAMERA: Record<MotivoFalhaDeCamera, string> = {
  'permissao-negada':
    'A sessão de estudo não pode começar sem acesso à webcam. Autorize a câmera nas permissões do navegador e tente novamente.',
  'sem-webcam':
    'Nenhuma webcam foi encontrada neste computador. A sessão de estudo precisa de uma câmera para medir o engajamento.',
  'webcam-ocupada':
    'A webcam já está sendo usada por outro programa. Feche o outro aplicativo (Meet, Zoom, Teams) e tente novamente.',
  'contexto-inseguro':
    'O navegador só libera a webcam em conexões seguras (HTTPS) ou em localhost.',
  desconhecido:
    'Não foi possível acessar a webcam. Verifique se ela está conectada e tente novamente.',
};

export class FalhaDeCamera extends Error {
  constructor(readonly motivo: MotivoFalhaDeCamera) {
    super(MENSAGENS_DE_FALHA_DE_CAMERA[motivo]);
    this.name = 'FalhaDeCamera';
  }
}

/**
 * `audio: false` é deliberado e não deve ser afrouxado: o projeto mede sinais
 * visuais, e pedir microfone junto ampliaria a captura para além do que o aluno
 * consentiu — e do que o spec descreve.
 *
 * As restrições são `ideal` e não `exact` de propósito: uma webcam que não
 * entrega exatamente 640x480@30 ainda serve para o cálculo de EAR/HP/MAR, e
 * `exact` faria o navegador recusar a câmera em vez de negociar o mais próximo.
 */
export const RESTRICOES_DE_VIDEO: MediaStreamConstraints = {
  video: {
    width: { ideal: 640 },
    height: { ideal: 480 },
    frameRate: { ideal: 30 },
    facingMode: 'user',
  },
  audio: false,
};

/**
 * Traduz a exceção do `getUserMedia` para um motivo de domínio.
 *
 * Fica fora do serviço, como função pura, para ser testável sem webcam nem
 * navegador real — é o mesmo desenho de `app/sessoes.py` no backend, onde a
 * regra não conhece o transporte.
 */
export function traduzirFalhaDeCamera(erro: unknown): FalhaDeCamera {
  const nome = (erro as { name?: string } | null)?.name;

  switch (nome) {
    // `PermissionDeniedError` e afins são os nomes legados, anteriores à
    // padronização; navegadores antigos ainda podem emiti-los.
    case 'NotAllowedError':
    case 'PermissionDeniedError':
    case 'SecurityError':
      return new FalhaDeCamera('permissao-negada');

    case 'NotFoundError':
    case 'DevicesNotFoundError':
      return new FalhaDeCamera('sem-webcam');

    // Existe câmera, mas o SO não entregou — tipicamente outro programa segurando
    // o dispositivo.
    case 'NotReadableError':
    case 'TrackStartError':
      return new FalhaDeCamera('webcam-ocupada');

    // Só ocorreria com restrições `exact`; como usamos `ideal`, cair aqui indica
    // que alguém apertou as restrições sem querer.
    case 'OverconstrainedError':
    default:
      return new FalhaDeCamera('desconhecido');
  }
}

/**
 * Acesso à webcam e ao seu ciclo de vida. Não sabe nada sobre landmarks, IEE ou
 * sessão de estudo — só entrega um `MediaStream` vivo e garante que ele morra.
 */
@Injectable({ providedIn: 'root' })
export class CameraService implements OnDestroy {
  private readonly streamSignal = signal<MediaStream | null>(null);
  private readonly proporcaoSignal = signal<number | null>(null);

  /** Stream da webcam enquanto houver captura ativa, ou `null`. */
  readonly stream = this.streamSignal.asReadonly();

  /**
   * Proporção (largura ÷ altura) que a câmera está de fato entregando.
   *
   * Existe porque a caixa do preview não pode ser fixa. Uma webcam USB comum
   * entrega 4:3; um celular exposto como câmera do Windows entrega 16:9. Uma
   * caixa 4:3 recebendo 16:9 ou corta 25% da largura (com `cover`) ou fica com
   * barras (com `contain`) — e nenhuma das duas é aceitável num preview cuja
   * função é o aluno conferir o próprio enquadramento.
   *
   * `null` até haver stream, e aí o CSS usa a proporção de fallback.
   */
  readonly proporcao = this.proporcaoSignal.asReadonly();

  private medirProporcao(stream: MediaStream): void {
    // A proporção é refinamento de apresentação; o acesso à câmera não pode
    // depender dela. `getSettings` é padrão em navegador real, mas se faltar —
    // trilha de origem exótica, ambiente antigo — o fallback do CSS resolve, e
    // derrubar `solicitarAcesso` por causa disso seria trocar um enquadramento
    // imperfeito por sessão nenhuma.
    const trilha = stream.getVideoTracks()[0];
    const ajustes = typeof trilha?.getSettings === 'function' ? trilha.getSettings() : undefined;
    const largura = ajustes?.width;
    const altura = ajustes?.height;
    // `aspectRatio` vem direto em alguns navegadores; onde não vier, deriva de
    // largura e altura. Sem nenhum dos dois, o CSS fica com o fallback.
    const proporcao = ajustes?.aspectRatio ?? (largura && altura ? largura / altura : null);
    this.proporcaoSignal.set(proporcao && isFinite(proporcao) && proporcao > 0 ? proporcao : null);
  }

  /**
   * Pede acesso à webcam. Idempotente: chamadas repetidas reaproveitam o stream
   * em andamento em vez de acender uma segunda captura.
   *
   * @throws {FalhaDeCamera} sempre que o acesso não for possível.
   */
  async solicitarAcesso(): Promise<MediaStream> {
    const emAndamento = this.streamSignal();
    if (emAndamento !== null && this.estaVivo(emAndamento)) {
      return emAndamento;
    }

    // Fora de contexto seguro o navegador nem expõe `mediaDevices`, então isso
    // estoura como TypeError em vez de um erro nomeado do getUserMedia.
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new FalhaDeCamera('contexto-inseguro');
    }

    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia(RESTRICOES_DE_VIDEO);
    } catch (erro) {
      stream = await this.tentarOutrosDispositivos(erro);
    }

    this.streamSignal.set(stream);
    this.medirProporcao(stream);
    return stream;
  }

  /**
   * Quando o dispositivo escolhido pelo navegador não inicia, tenta os outros.
   *
   * Sem indicar `deviceId`, quem escolhe a câmera é o navegador — e ele escolhe
   * mal com frequência. Numa máquina de teste com três dispositivos (uma webcam
   * USB, a câmera virtual do OBS e um celular exposto como câmera do Windows),
   * o Chrome elegeu a USB, que estava travada em `NotReadableError`, e a sessão
   * não começava. **Havia uma câmera funcionando o tempo todo**, a duas linhas
   * de distância.
   *
   * Só vale a pena para `NotReadableError`, que significa "o dispositivo existe
   * mas não inicia". Permissão negada não melhora trocando de câmera — negar é
   * decisão do aluno sobre a origem inteira —, e ausência de dispositivo não
   * tem alternativa a tentar.
   *
   * A enumeração vem **depois** da primeira tentativa de propósito: antes de o
   * navegador conceder acesso, `enumerateDevices` devolve entradas anônimas e
   * sem `deviceId` utilizável. É a chamada que falhou que destrava a lista.
   */
  private async tentarOutrosDispositivos(erroOriginal: unknown): Promise<MediaStream> {
    const falha = traduzirFalhaDeCamera(erroOriginal);
    if (falha.motivo !== 'webcam-ocupada') {
      throw falha;
    }

    let dispositivos: MediaDeviceInfo[];
    try {
      dispositivos = (await navigator.mediaDevices.enumerateDevices()).filter(
        (dispositivo) => dispositivo.kind === 'videoinput',
      );
    } catch {
      // Enumerar falhou: nada a acrescentar ao diagnóstico original.
      throw falha;
    }

    for (const dispositivo of dispositivos) {
      try {
        return await navigator.mediaDevices.getUserMedia({
          video: { ...(RESTRICOES_DE_VIDEO.video as MediaTrackConstraints), deviceId: { exact: dispositivo.deviceId } },
          audio: false,
        });
      } catch {
        // Esta não abriu; segue para a próxima. O erro individual não interessa
        // — o que o aluno precisa saber é se alguma funcionou.
      }
    }

    // Nenhuma abriu: o diagnóstico original continua sendo o mais honesto.
    throw falha;
  }

  /**
   * Desliga a webcam. Idempotente.
   *
   * Precisa ser chamado em todo caminho que termina a sessão — encerramento
   * manual, expiração pelo servidor, logout, inatividade e saída da tela. Sem
   * isso a luz da câmera fica acesa depois da sessão, que é exatamente o tipo de
   * comportamento que este projeto promete não ter.
   */
  encerrar(): void {
    const stream = this.streamSignal();
    if (stream === null) {
      return;
    }

    stream.getTracks().forEach((track) => track.stop());
    this.streamSignal.set(null);
    this.proporcaoSignal.set(null);
  }

  /**
   * Um stream cujas trilhas já morreram (aluno desconectou a webcam, ou revogou
   * a permissão pelo navegador) continua sendo um objeto válido. Reaproveitá-lo
   * entregaria uma captura congelada.
   */
  private estaVivo(stream: MediaStream): boolean {
    return stream.getVideoTracks().some((track) => track.readyState === 'live');
  }

  ngOnDestroy(): void {
    this.encerrar();
  }
}
