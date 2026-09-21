import { formatarDuracao } from './duracao';

describe('formatarDuracao', () => {
  it('mostra segundos abaixo de um minuto, onde o número ainda conta uma história', () => {
    expect(formatarDuracao(0)).toBe('0s');
    expect(formatarDuracao(12)).toBe('12s');
    expect(formatarDuracao(59)).toBe('59s');
  });

  it('passa a minutos a partir de um minuto', () => {
    expect(formatarDuracao(60)).toBe('1min');
    expect(formatarDuracao(3_180)).toBe('53min');
  });

  it('mostra horas e minutos em sessões longas', () => {
    expect(formatarDuracao(3_600)).toBe('1h');
    expect(formatarDuracao(4_800)).toBe('1h 20min');
  });

  it('não inventa precisão de segundo em duração longa', () => {
    expect(formatarDuracao(3_157)).toBe('52min');
  });

  it('trata duração negativa como zero em vez de exibir "-1s"', () => {
    // Relógios de cliente e servidor discordam; o relatório não pode mostrar
    // tempo negativo por causa de alguns milissegundos de deriva.
    expect(formatarDuracao(-5)).toBe('0s');
  });
});
