import {
  ASSIMETRIA_MAXIMA,
  LUMINANCIA_MINIMA,
  MENSAGEM_DE_INCERTEZA_GENERICA,
  MENSAGENS_DE_INCERTEZA,
  PRESENCA_MINIMA,
  SinaisDeCaptura,
  avaliarCaptura,
  mensagemDeIncerteza,
} from './qualidade';

/** Uma captura em condições boas: sala iluminada, rosto inteiro, olhos simétricos. */
function captura(sobrescreve: Partial<SinaisDeCaptura> = {}): SinaisDeCaptura {
  return { luminancia: 0.45, presenca: 1, assimetriaOcular: 0.05, ...sobrescreve };
}

describe('avaliarCaptura', () => {
  it('não reclama de uma captura em condições normais', () => {
    expect(avaliarCaptura(captura())).toBeNull();
  });

  it('acusa baixa luz abaixo do piso de luminância', () => {
    expect(avaliarCaptura(captura({ luminancia: LUMINANCIA_MINIMA - 0.01 }))).toBe('baixa-luz');
  });

  it('aceita a luminância exatamente no piso', () => {
    // O limiar é uma fronteira, não uma zona morta: quem está exatamente nele
    // continua sendo medido.
    expect(avaliarCaptura(captura({ luminancia: LUMINANCIA_MINIMA }))).toBeNull();
  });

  it('acusa oclusão quando o rosto aparece só em parte dos quadros', () => {
    expect(avaliarCaptura(captura({ presenca: PRESENCA_MINIMA - 0.1 }))).toBe('oclusao');
  });

  it('não confunde ausência total de rosto com oclusão', () => {
    // Presença zero é o aluno fora do enquadramento — uma medição válida, que
    // zera o IEE via P(t) = 0. Chamar isso de incerteza faria o sistema se
    // abster justamente quando tem algo verdadeiro a dizer.
    expect(avaliarCaptura(captura({ presenca: 0 }))).toBeNull();
  });

  it('acusa reflexo quando um olho discorda do outro', () => {
    expect(avaliarCaptura(captura({ assimetriaOcular: ASSIMETRIA_MAXIMA + 0.1 }))).toBe(
      'reflexo-ocular',
    );
  });

  it('tolera a assimetria facial que todo rosto tem', () => {
    expect(avaliarCaptura(captura({ assimetriaOcular: 0.2 }))).toBeNull();
  });

  it('não avalia os olhos quando não houve rosto para lê-los', () => {
    // Sem rosto, a assimetria da última leitura é lixo herdado — julgar por ela
    // produziria um alerta de óculos para quem saiu da frente da webcam.
    expect(avaliarCaptura(captura({ presenca: 0, assimetriaOcular: 3 }))).toBeNull();
  });

  it('reporta a causa ambiental antes das que ela mesma provoca', () => {
    // Pouca luz produz detecção intermitente e assimetria. Reportar "reflexo no
    // óculos" para quem está no escuro mandaria o aluno mexer na coisa errada.
    const noEscuroEInstavel = captura({
      luminancia: 0.05,
      presenca: 0.3,
      assimetriaOcular: 2,
    });

    expect(avaliarCaptura(noEscuroEInstavel)).toBe('baixa-luz');
  });
});

describe('mensagemDeIncerteza', () => {
  it('não diz nada quando não há motivo', () => {
    expect(mensagemDeIncerteza(null)).toBeNull();
  });

  it('traduz cada motivo conhecido numa ação que o aluno pode tomar', () => {
    for (const [motivo, mensagem] of Object.entries(MENSAGENS_DE_INCERTEZA)) {
      expect(mensagemDeIncerteza(motivo)).toBe(mensagem);
    }
  });

  it('ainda avisa quando o motivo é desconhecido', () => {
    // O backend normaliza rótulos que não conhece para `desconhecida`. Ficar em
    // silêncio aí deixaria o aluno vendo o gráfico parar sem explicação.
    expect(mensagemDeIncerteza('desconhecida')).toBe(MENSAGEM_DE_INCERTEZA_GENERICA);
  });
});
