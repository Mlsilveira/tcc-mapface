import { TestBed } from '@angular/core/testing';

import {
  CameraService,
  FalhaDeCamera,
  MotivoFalhaDeCamera,
  RESTRICOES_DE_VIDEO,
  traduzirFalhaDeCamera,
} from './camera.service';

interface TrilhaFalsa {
  readyState: MediaStreamTrackState;
  stop: jasmine.Spy;
}

function criarTrilhaFalsa(readyState: MediaStreamTrackState = 'live'): TrilhaFalsa {
  const trilha: TrilhaFalsa = {
    readyState,
    stop: jasmine.createSpy('stop'),
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
