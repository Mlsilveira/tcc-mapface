import { TestBed } from '@angular/core/testing';

import {
  CameraService,
  FalhaDeCamera,
  MENSAGENS_DE_FALHA_DE_CAMERA,
  MotivoFalhaDeCamera,
  RESTRICOES_DE_VIDEO,
  traduzirFalhaDeCamera,
} from './camera.service';

interface TrilhaFalsa {
  readyState: MediaStreamTrackState;
  getSettings: () => MediaTrackSettings;
  stop: jasmine.Spy;
}

function criarTrilhaFalsa(readyState: MediaStreamTrackState = 'live'): TrilhaFalsa {
  const trilha: TrilhaFalsa = {
    readyState,
    stop: jasmine.createSpy('stop'),
    // O dublê precisa honrar a interface que substitui: `getSettings` faz parte
    // de `MediaStreamTrack`, e o serviço a consulta para medir a proporção.
    // 640x480 é o que uma webcam comum entrega.
    getSettings: () => ({ width: 640, height: 480 }),
  };
  trilha.stop.and.callFake(() => (trilha.readyState = 'ended'));
  return trilha;
}

function criarStreamFalso(...trilhas: TrilhaFalsa[]): MediaStream {
  return {
    getTracks: () => trilhas,
    getVideoTracks: () => trilhas,
  } as unknown as MediaStream;
}

function erroComNome(nome: string): Error {
  const erro = new Error(nome);
  erro.name = nome;
  return erro;
}

describe('traduzirFalhaDeCamera', () => {
  const casos: ReadonlyArray<[string, MotivoFalhaDeCamera]> = [
    ['NotAllowedError', 'permissao-negada'],
    ['PermissionDeniedError', 'permissao-negada'],
    ['SecurityError', 'permissao-negada'],
    ['NotFoundError', 'sem-webcam'],
    ['DevicesNotFoundError', 'sem-webcam'],
    ['NotReadableError', 'webcam-ocupada'],
    ['TrackStartError', 'webcam-ocupada'],
    ['OverconstrainedError', 'desconhecido'],
  ];

  casos.forEach(([nome, motivo]) => {
    it(`traduz ${nome} para "${motivo}"`, () => {
      expect(traduzirFalhaDeCamera(erroComNome(nome)).motivo).toBe(motivo);
    });
  });

  it('cai em "desconhecido" para erros sem nome reconhecível', () => {
    expect(traduzirFalhaDeCamera(new Error('qualquer coisa')).motivo).toBe('desconhecido');
    expect(traduzirFalhaDeCamera(null).motivo).toBe('desconhecido');
    expect(traduzirFalhaDeCamera(undefined).motivo).toBe('desconhecido');
  });

  it('produz uma mensagem própria para cada motivo', () => {
    // Mensagens iguais entre motivos anulariam o objetivo de distinguir os
    // casos: o aluno precisa saber se abre as permissões, fecha o Zoom ou
    // procura uma webcam.
    const mensagens = casos.map(([nome]) => traduzirFalhaDeCamera(erroComNome(nome)).message);

    expect(mensagens.every((mensagem) => mensagem.length > 0)).toBeTrue();
    expect(new Set(mensagens).size).toBe(new Set(casos.map(([, motivo]) => motivo)).size);
  });
});

describe('CameraService', () => {
  let service: CameraService;
  let getUserMedia: jasmine.Spy;
  const mediaDevicesOriginal = Object.getOwnPropertyDescriptor(navigator, 'mediaDevices');

  function instalarMediaDevices(valor: unknown): void {
    Object.defineProperty(navigator, 'mediaDevices', { value: valor, configurable: true });
  }

  beforeEach(() => {
    TestBed.configureTestingModule({});
    service = TestBed.inject(CameraService);

    getUserMedia = jasmine.createSpy('getUserMedia');
    instalarMediaDevices({ getUserMedia });
  });

  afterEach(() => {
    if (mediaDevicesOriginal) {
      Object.defineProperty(navigator, 'mediaDevices', mediaDevicesOriginal);
    }
  });

  it('começa sem stream', () => {
    expect(service.stream()).toBeNull();
  });

  it('entrega o stream da webcam e passa a expô-lo', async () => {
    const stream = criarStreamFalso(criarTrilhaFalsa());
    getUserMedia.and.resolveTo(stream);

    await expectAsync(service.solicitarAcesso()).toBeResolvedTo(stream);
    expect(service.stream()).toBe(stream);
  });

  it('nunca pede microfone junto com a câmera', async () => {
    // O projeto mede sinais visuais. Pedir áudio ampliaria a captura para além
    // do que o aluno consentiu.
    getUserMedia.and.resolveTo(criarStreamFalso(criarTrilhaFalsa()));

    await service.solicitarAcesso();

    expect(getUserMedia).toHaveBeenCalledWith(RESTRICOES_DE_VIDEO);
    expect((RESTRICOES_DE_VIDEO as { audio: boolean }).audio).toBeFalse();
  });

  it('reaproveita a captura em andamento em vez de abrir uma segunda', async () => {
    const stream = criarStreamFalso(criarTrilhaFalsa());
    getUserMedia.and.resolveTo(stream);

    await service.solicitarAcesso();
    await expectAsync(service.solicitarAcesso()).toBeResolvedTo(stream);

    expect(getUserMedia).toHaveBeenCalledTimes(1);
  });

  it('pede acesso de novo quando as trilhas do stream anterior já morreram', async () => {
    // Acontece quando o aluno desconecta a webcam ou revoga a permissão no meio
    // da sessão: o objeto continua existindo, mas a captura está congelada.
    const morto = criarStreamFalso(criarTrilhaFalsa('ended'));
    const novo = criarStreamFalso(criarTrilhaFalsa());
    getUserMedia.and.resolveTo(morto);

    await service.solicitarAcesso();
    getUserMedia.and.resolveTo(novo);

    await expectAsync(service.solicitarAcesso()).toBeResolvedTo(novo);
    expect(getUserMedia).toHaveBeenCalledTimes(2);
  });

  it('falha com motivo de permissão negada e não guarda stream nenhum', async () => {
    getUserMedia.and.rejectWith(erroComNome('NotAllowedError'));

    await expectAsync(service.solicitarAcesso()).toBeRejectedWith(
      jasmine.objectContaining({ motivo: 'permissao-negada' } as Partial<FalhaDeCamera>),
    );
    expect(service.stream()).toBeNull();
  });

  it('distingue ausência de webcam de recusa de permissão', async () => {
    getUserMedia.and.rejectWith(erroComNome('NotFoundError'));

    await expectAsync(service.solicitarAcesso()).toBeRejectedWith(
      jasmine.objectContaining({ motivo: 'sem-webcam' } as Partial<FalhaDeCamera>),
    );
  });

  it('acusa contexto inseguro sem sequer chamar o getUserMedia', async () => {
    // Fora de HTTPS/localhost o navegador não expõe `mediaDevices`. Sem este
    // caminho, o erro apareceria como um TypeError cru para o aluno.
    instalarMediaDevices(undefined);

    await expectAsync(service.solicitarAcesso()).toBeRejectedWith(
      jasmine.objectContaining({ motivo: 'contexto-inseguro' } as Partial<FalhaDeCamera>),
    );
    expect(getUserMedia).not.toHaveBeenCalled();
  });

  it('desliga todas as trilhas ao encerrar e esquece o stream', async () => {
    const trilha = criarTrilhaFalsa();
    getUserMedia.and.resolveTo(criarStreamFalso(trilha));

    await service.solicitarAcesso();
    service.encerrar();

    expect(trilha.stop).toHaveBeenCalled();
    expect(service.stream()).toBeNull();
  });

  it('encerra sem reclamar quando não há captura em andamento', () => {
    expect(() => service.encerrar()).not.toThrow();
    expect(service.stream()).toBeNull();
  });

  it('desliga a webcam ao ser destruído', async () => {
    const trilha = criarTrilhaFalsa();
    getUserMedia.and.resolveTo(criarStreamFalso(trilha));

    await service.solicitarAcesso();
    service.ngOnDestroy();

    expect(trilha.stop).toHaveBeenCalled();
  });
});

/**
 * Quando o dispositivo escolhido pelo navegador não inicia, o serviço tenta os
 * outros antes de desistir.
 *
 * Isto não é hipótese: numa máquina de teste com três câmeras — uma webcam USB,
 * a câmera virtual do OBS e um celular exposto como câmera do Windows — o
 * Chrome elegeu a USB, que estava travada em `NotReadableError`, e a sessão não
 * começava. Havia uma câmera funcionando o tempo todo.
 */
describe('CameraService — dispositivo alternativo', () => {
  let service: CameraService;
  let getUserMedia: jasmine.Spy;
  let enumerateDevices: jasmine.Spy;
  const mediaDevicesOriginal = Object.getOwnPropertyDescriptor(navigator, 'mediaDevices');

  const NAO_INICIA = Object.assign(new Error('Could not start video source'), {
    name: 'NotReadableError',
  });

  function dispositivo(deviceId: string, label: string): MediaDeviceInfo {
    return { deviceId, label, kind: 'videoinput', groupId: 'g' } as MediaDeviceInfo;
  }

  beforeEach(() => {
    TestBed.configureTestingModule({});
    service = TestBed.inject(CameraService);

    getUserMedia = jasmine.createSpy('getUserMedia');
    enumerateDevices = jasmine.createSpy('enumerateDevices').and.resolveTo([]);
    Object.defineProperty(navigator, 'mediaDevices', {
      value: { getUserMedia, enumerateDevices },
      configurable: true,
    });
  });

  afterEach(() => {
    if (mediaDevicesOriginal) {
      Object.defineProperty(navigator, 'mediaDevices', mediaDevicesOriginal);
    }
  });

  it('usa a segunda câmera quando a escolhida pelo navegador não inicia', async () => {
    const funcionando = criarStreamFalso(criarTrilhaFalsa());
    enumerateDevices.and.resolveTo([
      dispositivo('usb', 'GENERAL WEBCAM'),
      dispositivo('celular', 'S24 Ultra (Câmera Virtual do Windows)'),
    ]);
    getUserMedia.and.callFake((restricoes: MediaStreamConstraints) => {
      const video = restricoes.video as MediaTrackConstraints;
      const id = (video?.deviceId as { exact?: string } | undefined)?.exact;
      return id === 'celular' ? Promise.resolve(funcionando) : Promise.reject(NAO_INICIA);
    });

    expect(await service.solicitarAcesso()).toBe(funcionando);
    expect(service.stream()).toBe(funcionando);
  });

  it('desiste com o diagnóstico original quando nenhuma câmera inicia', async () => {
    enumerateDevices.and.resolveTo([dispositivo('a', 'A'), dispositivo('b', 'B')]);
    getUserMedia.and.rejectWith(NAO_INICIA);

    await expectAsync(service.solicitarAcesso()).toBeRejectedWithError(
      MENSAGENS_DE_FALHA_DE_CAMERA['webcam-ocupada'],
    );
  });

  it('não tenta outras câmeras quando o aluno negou a permissão', async () => {
    // Negar é decisão sobre a origem inteira: trocar de dispositivo não muda
    // nada, e insistir seria pedir permissão de novo por outro caminho.
    enumerateDevices.and.resolveTo([dispositivo('a', 'A')]);
    getUserMedia.and.rejectWith(
      Object.assign(new Error('denied'), { name: 'NotAllowedError' }),
    );

    await expectAsync(service.solicitarAcesso()).toBeRejectedWithError(
      MENSAGENS_DE_FALHA_DE_CAMERA['permissao-negada'],
    );
    expect(enumerateDevices).not.toHaveBeenCalled();
  });

  it('preserva as restrições de vídeo ao trocar de dispositivo', async () => {
    // Sem isso, a câmera alternativa viria sem a negociação de resolução e taxa
    // que o cálculo de EAR/HP/MAR assume.
    enumerateDevices.and.resolveTo([dispositivo('unica', 'Única')]);
    const funcionando = criarStreamFalso(criarTrilhaFalsa());
    let chamadaComId: MediaTrackConstraints | null = null;
    getUserMedia.and.callFake((restricoes: MediaStreamConstraints) => {
      const video = restricoes.video as MediaTrackConstraints;
      if ((video?.deviceId as { exact?: string } | undefined)?.exact) {
        chamadaComId = video;
        return Promise.resolve(funcionando);
      }
      return Promise.reject(NAO_INICIA);
    });

    await service.solicitarAcesso();

    const esperado = RESTRICOES_DE_VIDEO.video as MediaTrackConstraints;
    expect(chamadaComId!.width).toEqual(esperado.width);
    expect(chamadaComId!.frameRate).toEqual(esperado.frameRate);
  });
});

describe('CameraService — proporção da câmera', () => {
  let service: CameraService;
  let getUserMedia: jasmine.Spy;
  const mediaDevicesOriginal = Object.getOwnPropertyDescriptor(navigator, 'mediaDevices');

  function streamCom(ajustes: MediaTrackSettings): MediaStream {
    const trilha = {
      readyState: 'live' as MediaStreamTrackState,
      stop: jasmine.createSpy('stop'),
      getSettings: () => ajustes,
    };
    return {
      getTracks: () => [trilha],
      getVideoTracks: () => [trilha],
    } as unknown as MediaStream;
  }

  beforeEach(() => {
    TestBed.configureTestingModule({});
    service = TestBed.inject(CameraService);
    getUserMedia = jasmine.createSpy('getUserMedia');
    Object.defineProperty(navigator, 'mediaDevices', {
      value: { getUserMedia, enumerateDevices: () => Promise.resolve([]) },
      configurable: true,
    });
  });

  afterEach(() => {
    if (mediaDevicesOriginal) {
      Object.defineProperty(navigator, 'mediaDevices', mediaDevicesOriginal);
    }
  });

  it('começa sem proporção conhecida', () => {
    expect(service.proporcao()).toBeNull();
  });

  it('usa o aspectRatio que a câmera reporta', async () => {
    getUserMedia.and.resolveTo(streamCom({ width: 1280, height: 720, aspectRatio: 16 / 9 }));

    await service.solicitarAcesso();

    expect(service.proporcao()).toBeCloseTo(16 / 9, 6);
  });

  it('deriva a proporção de largura e altura quando o navegador não reporta', async () => {
    getUserMedia.and.resolveTo(streamCom({ width: 640, height: 480 }));

    await service.solicitarAcesso();

    expect(service.proporcao()).toBeCloseTo(4 / 3, 6);
  });

  it('fica nula quando não há como medir, deixando o CSS usar o fallback', async () => {
    getUserMedia.and.resolveTo(streamCom({}));

    await service.solicitarAcesso();

    expect(service.proporcao()).toBeNull();
  });

  it('esquece a proporção ao encerrar', async () => {
    getUserMedia.and.resolveTo(streamCom({ width: 1280, height: 720 }));
    await service.solicitarAcesso();

    service.encerrar();

    expect(service.proporcao()).toBeNull();
  });
});
