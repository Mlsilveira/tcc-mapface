import { formatarDuracao } from './tempo';

describe('formatarDuracao', () => {
  it('mostra minutos e segundos com dois dígitos', () => {
    expect(formatarDuracao(0)).toBe('00:00');
    expect(formatarDuracao(5)).toBe('00:05');
    expect(formatarDuracao(65)).toBe('01:05');
    expect(formatarDuracao(600)).toBe('10:00');
  });

  it('acrescenta a hora quando a sessão passa de 60 minutos', () => {
    // Sem isso, uma sessão de 90 minutos apareceria como 90:00 — legível, mas
    // fora da convenção de cronômetro.
    expect(formatarDuracao(3600)).toBe('1:00:00');
    expect(formatarDuracao(5400)).toBe('1:30:00');
    expect(formatarDuracao(7325)).toBe('2:02:05');
  });

  it('trunca frações de segundo em vez de arredondar', () => {
    // Arredondar faria o cronômetro pular de 00:00 para 00:01 antes de um
    // segundo ter passado.
    expect(formatarDuracao(0.9)).toBe('00:00');
    expect(formatarDuracao(59.99)).toBe('00:59');
  });

  it('trata duração negativa como zero', () => {
    // O início da sessão vem do relógio do servidor e o tempo corrente do
    // navegador; alguns segundos de diferença entre os dois são comuns, e o
    // cronômetro contar para trás seria um bug visível.
    expect(formatarDuracao(-1)).toBe('00:00');
    expect(formatarDuracao(-3600)).toBe('00:00');
  });
});
