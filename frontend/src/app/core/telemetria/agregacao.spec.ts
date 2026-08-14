import { MetricasFaciais } from '../visao/metricas';
import { agregar } from './agregacao';

function leitura(ear: number, yaw: number): MetricasFaciais {
  return { ear, mar: 0.05, cabeca: { yaw, pitch: 0, roll: 0 } };
}

describe('agregar', () => {
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
    const payload = agregar([leitura(0.3, 0), null, leitura(0.3, 0), null]);

    expect(payload!.ear).toBeCloseTo(0.3, 10);
    expect(payload!.rosto_detectado).toBeTrue();
  });

  it('reporta ausência de rosto quando nenhum quadro da janela teve rosto', () => {
    const payload = agregar([null, null, null]);

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

  it('leva apenas ear, yaw e presença de rosto — nunca landmarks', () => {
    // O contrato do payload é a fronteira de privacidade: o que não estiver
    // aqui não sai do navegador.
    const payload = agregar([leitura(0.3, 0)]);

    expect(Object.keys(payload!).sort()).toEqual(['ear', 'rosto_detectado', 'yaw']);
  });
});
