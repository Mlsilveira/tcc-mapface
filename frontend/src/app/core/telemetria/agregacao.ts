import { MetricasFaciais } from '../visao/metricas';

/**
 * O que sobe para o backend a cada segundo.
 *
 * Este tipo é a fronteira de privacidade do projeto: o que não estiver aqui não
 * sai do navegador. Landmarks, frames e qualquer coisa derivada de imagem ficam
 * do lado de cá — o backend recebe três números e nada mais.
 *
 * Os nomes são snake_case porque atravessam a rede para o Python; é o único
 * lugar do frontend onde isso acontece.
 */
export interface PayloadDeTelemetria {
  ear: number;
  yaw: number;
  rosto_detectado: boolean;
}

/**
 * Resume uma janela de captura num único payload.
 *
 * A captura roda na taxa do vídeo (~30 FPS) e a telemetria sobe a 1 Hz, então
 * cada payload precisa representar a janela inteira — e não o último quadro
 * dela, que seria uma amostra arbitrária de 33 ms.
 *
 * @param leituras quadros da janela; `null` onde não havia rosto.
 * @returns o payload, ou `null` se a janela não teve quadro nenhum.
 */
export function agregar(
  leituras: ReadonlyArray<MetricasFaciais | null>,
): PayloadDeTelemetria | null {
  if (leituras.length === 0) {
    // Sem quadro nenhum a captura nem rodou (aba em segundo plano, por
    // exemplo). Mandar zero seria inventar um dado que ninguém observou.
    return null;
  }

  const comRosto = leituras.filter((leitura): leitura is MetricasFaciais => leitura !== null);

  if (comRosto.length === 0) {
    return { ear: 0, yaw: 0, rosto_detectado: false };
  }

  // Os quadros sem rosto ficam fora da média de propósito: contá-los como zero
  // puxaria o EAR para baixo e viraria "sonolência" no score, quando o aluno só
  // saiu do enquadramento por um instante.
  const media = (valores: number[]): number =>
    valores.reduce((soma, valor) => soma + valor, 0) / valores.length;

  return {
    ear: media(comRosto.map((leitura) => leitura.ear)),
    yaw: media(comRosto.map((leitura) => leitura.cabeca.yaw)),
    rosto_detectado: true,
  };
}
