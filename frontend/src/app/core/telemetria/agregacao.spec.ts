import { LeituraDaCaptura } from '../visao/landmarks.service';
import { MetricasFaciais } from '../visao/metricas';
import { MotivoDeIncerteza } from '../visao/qualidade';
import { agregar } from './agregacao';

function metricas(ear: number, yaw: number): MetricasFaciais {
  return {
    ear,
    mar: 0.05,
    cabeca: { yaw, pitch: 0, roll: 0 },
    assimetriaOcular: 0,
    earDireito: ear,
    earEsquerdo: ear,
  };
}

/** Métricas de um cliente anterior ao classificador: sem os olhos separados. */
function metricasAntigas(ear: number, yaw: number): MetricasFaciais {
  return { ear, mar: 0.05, cabeca: { yaw, pitch: 0, roll: 0 }, assimetriaOcular: 0 };
}

function leitura(ear: number, yaw: number, incerteza: MotivoDeIncerteza | null = null): LeituraDaCaptura {
  return { metricas: metricas(ear, yaw), incerteza };
}

/** Amostra em que o detector não achou rosto. */
function semRosto(incerteza: MotivoDeIncerteza | null = null): LeituraDaCaptura {
  return { metricas: null, incerteza };
}

describe('agregar', () => {
  it('só manda os olhos separados se toda a janela os trouxer', () => {
    // Uma média tirada de metade da janela descreveria outra coisa, e o
    // modelo — treinado sobre janelas inteiras — não teria como distingui-la
    // de um segundo qualquer. Melhor ausente: ausência o pipeline sabe tratar.
    const mista = agregar([
      { metricas: metricas(0.3, 0), incerteza: null },
      { metricas: metricasAntigas(0.3, 0), incerteza: null },
    ]);

    expect(mista!.ear_esq).toBeUndefined();
    expect(mista!.ear_dir).toBeUndefined();
    expect(mista!.pitch).toBe(0);
  });

  it('tira a média das leituras da janela', () => {
    // A captura roda a ~30 FPS e a telemetria sobe a 1 Hz: cada payload
    // representa a janela inteira, não o último quadro dela. Média de
    // 0,30 e 0,20 = 0,25; de 0° e 10° = 5°.
    const payload = agregar([leitura(0.3, 0), leitura(0.2, 10)]);

    expect(payload!.ear).toBeCloseTo(0.25, 10);
    expect(payload!.yaw).toBeCloseTo(5, 10);
    expect(payload!.rosto_detectado).toBeTrue();
  });

  it('ignora os quadros sem rosto ao calcular a média', () => {
    // Contar ausência como zero puxaria o EAR para baixo e viraria "sonolência"
    // no score — quando o aluno só passou meio segundo fora do enquadramento.
    const payload = agregar([leitura(0.3, 0), semRosto(), leitura(0.3, 0), semRosto()]);

    expect(payload!.ear).toBeCloseTo(0.3, 10);
    expect(payload!.rosto_detectado).toBeTrue();
  });

  it('reporta ausência de rosto quando nenhum quadro da janela teve rosto', () => {
    const payload = agregar([semRosto(), semRosto(), semRosto()]);

    expect(payload!.rosto_detectado).toBeFalse();
    expect(payload!.ear).toBe(0);
    expect(payload!.yaw).toBe(0);
  });

  it('não produz payload quando a janela não teve quadro nenhum', () => {
    // Janela vazia significa que a captura nem rodou (aba em segundo plano,
    // por exemplo). Mandar um zero aqui seria inventar um dado.
    expect(agregar([])).toBeNull();
  });

  it('preserva o sinal do yaw ao promediar lados opostos', () => {
    // Olhar 20° para cada lado dentro da mesma janela é, em média, olhar para
    // frente — não 20° para um dos lados.
    const payload = agregar([leitura(0.3, -20), leitura(0.3, 20)]);

    expect(payload!.yaw).toBeCloseTo(0, 10);
  });

  it('leva apenas ear, yaw, mar, presença de rosto e incerteza — nunca landmarks', () => {
    // O contrato do payload é a fronteira de privacidade: o que não estiver
    // aqui não sai do navegador. A lista é fechada de propósito — qualquer
    // campo novo precisa passar por aqui, e é neste momento que alguém tem que
    // perguntar se ele carrega dado bruto de imagem.
    //
    // `mar` entrou na ticket 8: já era calculado desde a ticket 5 mas parava no
    // navegador, e a detecção de bocejo precisa dele no servidor. `incerteza`
    // entrou na ticket 10 e é o único campo que não é medição — é o veredito
    // sobre ela. A luminância que o produziu, essa sim derivada de pixels, não
    // atravessa.
    //
    // `ear_esq`, `ear_dir`, `pitch` e `roll` entraram com o classificador de
    // sonolência, que foi treinado com os olhos separados e a pose completa. A
    // pergunta que esta lista existe para provocar foi feita: são quatro
    // números derivados, do mesmo tipo dos que já saíam. Os 478 landmarks
    // continuam morrendo no navegador, e nenhum quadro atravessa.
    const payload = agregar([leitura(0.3, 0)]);

    expect(Object.keys(payload!).sort()).toEqual([
      'ear',
      'ear_dir',
      'ear_esq',
      'incerteza',
      'mar',
      'pitch',
      'roll',
      'rosto_detectado',
      'yaw',
    ]);
  });

  it('promedia o mar da janela', () => {
    const janela = [leitura(0.3, 0), leitura(0.3, 0)];
    janela[0].metricas!.mar = 0.1;
    janela[1].metricas!.mar = 0.5;

    expect(agregar(janela)!.mar).toBeCloseTo(0.3, 10);
  });

  it('reporta mar zero quando a janela inteira ficou sem rosto', () => {
    expect(agregar([semRosto(), semRosto()])!.mar).toBe(0);
  });

  // --- Incerteza de captura (ticket 10) ------------------------------------

  it('marca a janela como incerta quando a maioria das amostras foi incerta', () => {
    const payload = agregar([
      leitura(0.3, 0, 'baixa-luz'),
      leitura(0.3, 0, 'baixa-luz'),
      leitura(0.3, 0),
    ]);

    expect(payload!.incerteza).toBe('baixa-luz');
  });

  it('não marca a janela por um alerta isolado', () => {
    // Um quadro mais escuro, a mão passando na frente do rosto: 250 ms de
    // condição adversa não podem apagar o segundo inteiro da série. Se a
    // condição é real, ela se sustenta pela janela.
    const payload = agregar([
      leitura(0.3, 0, 'oclusao'),
      leitura(0.3, 0),
      leitura(0.3, 0),
      leitura(0.3, 0),
    ]);

    expect(payload!.incerteza).toBeNull();
  });

  it('descarta a janela pelo total de amostras ruins, não por motivo isolado', () => {
    // O caso da história 17 do spec: aluno de óculos numa sala mal iluminada. A
    // luminância oscila em torno do limiar, então cada amostra acusa uma causa
    // diferente. Contar a maioria por motivo deixaria três leituras descartadas
    // pelo navegador virarem um score no banco — o resultado dependeria de como
    // as causas se distribuem, e não de quanto da janela é confiável.
    const payload = agregar([
      leitura(0.3, 0, 'baixa-luz'),
      leitura(0.3, 0, 'oclusao'),
      leitura(0.3, 0, 'reflexo-ocular'),
      leitura(0.3, 0),
    ]);

    expect(payload!.incerteza).not.toBeNull();
  });

  it('escolhe o motivo mais frequente quando há mais de um', () => {
    const payload = agregar([
      leitura(0.3, 0, 'oclusao'),
      leitura(0.3, 0, 'baixa-luz'),
      leitura(0.3, 0, 'baixa-luz'),
      leitura(0.3, 0, 'baixa-luz'),
    ]);

    expect(payload!.incerteza).toBe('baixa-luz');
  });

  it('reporta incerteza mesmo quando a janela inteira ficou sem rosto', () => {
    // Rosto ausente no escuro é ambíguo por natureza: o aluno pode ter saído, ou
    // a lâmpada pode ter apagado. Marcar a janela é o que impede o backend de
    // gravar um zero afirmando que ele não estava lá.
    const payload = agregar([semRosto('baixa-luz'), semRosto('baixa-luz')]);

    expect(payload!.rosto_detectado).toBeFalse();
    expect(payload!.incerteza).toBe('baixa-luz');
  });
});
