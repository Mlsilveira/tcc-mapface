import { LeituraDaCaptura } from '../visao/landmarks.service';
import { MetricasFaciais } from '../visao/metricas';
import { MotivoDeIncerteza } from '../visao/qualidade';

/**
 * O que sobe para o backend a cada segundo.
 *
 * Este tipo é a fronteira de privacidade do projeto: o que não estiver aqui não
 * sai do navegador. Landmarks, frames e qualquer coisa derivada de imagem ficam
 * do lado de cá — o backend recebe quatro números e nada mais.
 *
 * `mar` entrou na ticket 8. Ele já era calculado aqui desde a ticket 5, mas
 * parava no navegador; a detecção de bocejo do fator de fadiga precisa dele no
 * servidor. Continua sendo um número derivado de landmarks, não uma imagem — a
 * fronteira de privacidade não se moveu.
 *
 * `incerteza` entrou na ticket 10, e é o único campo que não é medição: é o
 * veredito sobre a medição. A evidência que o produziu — a luminância do quadro,
 * que é derivada de pixels — não atravessa; só o rótulo.
 *
 * Os nomes são snake_case porque atravessam a rede para o Python; é o único
 * lugar do frontend onde isso acontece.
 */
export interface PayloadDeTelemetria {
  ear: number;
  yaw: number;
  mar: number;
  rosto_detectado: boolean;
  incerteza: MotivoDeIncerteza | null;
}

/**
 * O motivo que descreve a janela, ou `null` se ela é confiável.
 *
 * Duas perguntas separadas, e a ordem entre elas importa. **Descartar ou não**
 * se decide pelo total de amostras marcadas: exige maioria, porque um alerta
 * isolado de 250 ms — o aluno passou a mão no rosto, um quadro veio mais
 * escuro — não pode apagar o segundo inteiro da série. Só depois, e apenas para
 * dar nome ao descarte, se pergunta **qual motivo** predominou.
 *
 * Juntar as duas contas num contador só faria a decisão depender de como as
 * causas se distribuem em vez de quanto da janela é confiável: três amostras
 * ruins por três motivos diferentes sobem como leitura boa, enquanto as mesmas
 * três sob um motivo só seriam descartadas. Quem estuda de óculos numa sala mal
 * iluminada cai exatamente nesse caso, que é o cenário da história 17 do spec.
 */
function incertezaDaJanela(
  amostras: ReadonlyArray<LeituraDaCaptura>,
): MotivoDeIncerteza | null {
  const contagem = new Map<MotivoDeIncerteza, number>();
  let incertas = 0;

  for (const { incerteza } of amostras) {
    if (incerteza !== null) {
      incertas += 1;
      contagem.set(incerteza, (contagem.get(incerteza) ?? 0) + 1);
    }
  }

  if (incertas * 2 < amostras.length) {
    return null;
  }

  // Empate fica com o motivo que apareceu primeiro na janela: o `Map` itera na
  // ordem de inserção, que aqui é a ordem cronológica das amostras.
  let dominante: MotivoDeIncerteza | null = null;
  let maior = 0;
  for (const [motivo, vezes] of contagem) {
    if (vezes > maior) {
      dominante = motivo;
      maior = vezes;
    }
  }

  return dominante;
}

/**
 * Resume uma janela de captura num único payload.
 *
 * A captura roda na taxa do vídeo (~30 FPS) e a telemetria sobe a 1 Hz, então
 * cada payload precisa representar a janela inteira — e não o último quadro
 * dela, que seria uma amostra arbitrária de 33 ms.
 *
 * @param amostras leituras da janela; `metricas: null` onde não havia rosto.
 * @returns o payload, ou `null` se a janela não teve quadro nenhum.
 */
export function agregar(
  amostras: ReadonlyArray<LeituraDaCaptura>,
): PayloadDeTelemetria | null {
  if (amostras.length === 0) {
    // Sem quadro nenhum a captura nem rodou (aba em segundo plano, por
    // exemplo). Mandar zero seria inventar um dado que ninguém observou.
    return null;
  }

  const incerteza = incertezaDaJanela(amostras);
  const comRosto = amostras
    .map((amostra) => amostra.metricas)
    .filter((metricas): metricas is MetricasFaciais => metricas !== null);

  if (comRosto.length === 0) {
    return { ear: 0, yaw: 0, mar: 0, rosto_detectado: false, incerteza };
  }

  // Os quadros sem rosto ficam fora da média de propósito: contá-los como zero
  // puxaria o EAR para baixo e viraria "sonolência" no score, quando o aluno só
  // saiu do enquadramento por um instante.
  const media = (valores: number[]): number =>
    valores.reduce((soma, valor) => soma + valor, 0) / valores.length;

  // O MAR também vai pela média, e não pelo pico da janela. Um bocejo dura 4–6
  // segundos, então a média de um segundo dentro dele já fica perto do pico; o
  // máximo, em compensação, subiria com um único quadro em que o MediaPipe
  // errou o contorno do lábio, e viraria bocejo fantasma.
  return {
    ear: media(comRosto.map((leitura) => leitura.ear)),
    yaw: media(comRosto.map((leitura) => leitura.cabeca.yaw)),
    mar: media(comRosto.map((leitura) => leitura.mar)),
    rosto_detectado: true,
    incerteza,
  };
}
