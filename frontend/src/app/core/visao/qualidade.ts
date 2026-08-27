/**
 * Quando confiar na captura, e quando dizer que não dá (ticket 10).
 *
 * Como `metricas.ts`, este módulo é aritmética pura: recebe sinais já medidos e
 * devolve um veredito. Não conhece webcam, MediaPipe nem Angular.
 *
 * **Por que o julgamento mora no navegador.** É aqui que a imagem existe. O
 * backend recebe quatro números por segundo, e a partir deles é impossível
 * distinguir "o aluno está de olhos semicerrados" de "a sala está escura e o
 * detector está chutando o contorno da pálpebra". Quem tem os pixels é quem
 * pode responder isso — e os pixels não saem daqui.
 *
 * O que atravessa a rede é o veredito, não a evidência: um rótulo de três
 * palavras. A luminância medida, que é derivada de pixels, morre neste arquivo.
 */

/**
 * Por que a leitura não é confiável. São os três cenários do spec (história 17):
 * iluminação ruim, óculos com reflexo, rosto parcialmente ocluso.
 */
export type MotivoDeIncerteza = 'baixa-luz' | 'reflexo-ocular' | 'oclusao';

export interface SinaisDeCaptura {
  /** Luminância média do quadro, de 0 (preto) a 1 (branco). */
  luminancia: number;
  /**
   * Fração das tentativas de detecção da janela que encontraram rosto.
   *
   * `0` não é oclusão: é ausência — o aluno saiu do enquadramento, e isso é uma
   * medição válida que zera o IEE via `P(t) = 0`. O que denuncia oclusão é o
   * valor intermediário: o rosto está lá, mas o detector o perde e o reencontra.
   */
  presenca: number;
  /** Assimetria entre os olhos, como `metricas.calcularAssimetriaOcular` a define. */
  assimetriaOcular: number;
}

/**
 * Abaixo desta luminância média o MediaPipe ainda costuma achar um rosto, mas
 * os contornos de pálpebra e lábio param de acompanhar o movimento real — o EAR
 * fica achatado e estável, que é exatamente a assinatura de "aluno sonolento".
 * Um score derivado daí não é impreciso, é enganoso.
 *
 * O valor é conservador de propósito: uma sala com luz de teto normal fica bem
 * acima disso, e quem estuda de noite com abajur ainda passa.
 */
export const LUMINANCIA_MINIMA = 0.16;

/**
 * Acima desta assimetria os dois olhos estão contando histórias diferentes.
 *
 * 0,45 significa que um olho aparece quase metade mais fechado que o outro.
 * Assimetria facial real e ângulo da cabeça produzem bem menos que isso; o
 * reflexo do óculos numa lente só produz bem mais.
 */
export const ASSIMETRIA_MAXIMA = 0.45;

/**
 * Detecção intermitente: o rosto aparece em parte da janela e some no resto.
 *
 * Entre 0 e este piso, a leitura agregada do segundo é uma média de poucos
 * quadros — e cada reaparecimento traz um EAR de contorno recém-reencontrado,
 * que é ruído. Acima dele, uma perda ocasional não invalida a janela.
 */
export const PRESENCA_MINIMA = 0.6;

/**
 * Decide se a captura sustenta uma medição, e por que não, quando não sustenta.
 *
 * A ordem das verificações é causal, não arbitrária: pouca luz **produz**
 * assimetria e detecção intermitente, então reportar "reflexo no óculos" para
 * quem está no escuro mandaria o aluno mexer na coisa errada. A causa mais
 * ambiental vem primeiro; a mais específica, depois.
 *
 * @returns o motivo, ou `null` quando a leitura pode ser medida normalmente.
 */
export function avaliarCaptura(sinais: SinaisDeCaptura): MotivoDeIncerteza | null {
  if (sinais.luminancia < LUMINANCIA_MINIMA) {
    return 'baixa-luz';
  }

  if (sinais.presenca > 0 && sinais.presenca < PRESENCA_MINIMA) {
    return 'oclusao';
  }

  // Só faz sentido perguntar dos olhos quando houve rosto para lê-los.
  if (sinais.presenca > 0 && sinais.assimetriaOcular > ASSIMETRIA_MAXIMA) {
    return 'reflexo-ocular';
  }

  return null;
}

/** O que a interface diz ao aluno em cada caso. Ação concreta, nunca diagnóstico. */
export const MENSAGENS_DE_INCERTEZA: Record<MotivoDeIncerteza, string> = {
  'baixa-luz':
    'Está escuro demais para medir com confiança. Acender uma luz de frente para você resolve.',
  'reflexo-ocular':
    'Um dos seus olhos não está sendo lido direito — costuma ser reflexo nos óculos. Mudar o ângulo da luz ou da tela ajuda.',
  oclusao:
    'Seu rosto está aparecendo só em parte. Ajustar o enquadramento da webcam costuma resolver.',
};

export const MENSAGEM_DE_INCERTEZA_GENERICA =
  'As condições de captura não permitem medir com confiança agora.';

/**
 * A frase que corresponde ao motivo, com fallback.
 *
 * O motivo exibido vem do **backend**, que o normaliza antes de gravar — e o
 * rótulo dele pode ser `desconhecida` quando um cliente mais novo reporta uma
 * causa que o servidor ainda não conhece. Nesse caso o aluno continua sabendo
 * que não está sendo medido, que é a informação que não pode faltar.
 */
export function mensagemDeIncerteza(motivo: string | null): string | null {
  if (motivo === null) {
    return null;
  }

  return MENSAGENS_DE_INCERTEZA[motivo as MotivoDeIncerteza] ?? MENSAGEM_DE_INCERTEZA_GENERICA;
}
