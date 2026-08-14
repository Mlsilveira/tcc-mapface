/**
 * Cálculo local de EAR, MAR e Head Pose.
 *
 * Este módulo é aritmética pura sobre pontos: não conhece MediaPipe, webcam,
 * Angular nem WebSocket. É o espelho no frontend do que `app/sessoes.py` faz no
 * backend — a regra fica testável sem subir nada em volta.
 */

/** Ponto facial. Deliberadamente não é o tipo do MediaPipe: a regra não importa o fornecedor. */
export interface Ponto {
  x: number;
  y: number;
}

export interface AngulosDaCabeca {
  /** Giro horizontal (negativo à esquerda, positivo à direita), em graus. */
  yaw: number;
  /** Inclinação vertical (negativo para baixo, positivo para cima), em graus. */
  pitch: number;
  /** Rotação no plano da tela, em graus. */
  roll: number;
}

export interface MetricasFaciais {
  ear: number;
  mar: number;
  cabeca: AngulosDaCabeca;
}

/**
 * Índices dos 6 pontos de cada olho, na ordem da fórmula de EAR de
 * Soukupová & Čech: [canto, topo₁, topo₂, canto oposto, base₂, base₁].
 *
 * A fórmula original foi definida para os 68 pontos do dlib; estes são os
 * índices equivalentes na malha do MediaPipe. Estão congelados aqui e cobertos
 * por teste justamente porque são números mágicos que ninguém revisa de cabeça
 * — e porque um índice trocado não gera erro, só um EAR silenciosamente errado.
 */
export const INDICES_OLHO_DIREITO = [33, 160, 158, 133, 153, 144] as const;
export const INDICES_OLHO_ESQUERDO = [362, 385, 387, 263, 373, 380] as const;

/** Pontos do contorno interno da boca, para o MAR. */
export const INDICES_BOCA = {
  labioSuperior: 13,
  labioInferior: 14,
  cantoEsquerdo: 78,
  cantoDireito: 308,
} as const;

/**
 * Distância euclidiana entre dois pontos, corrigida pela proporção da imagem.
 *
 * O MediaPipe normaliza `x` pela **largura** e `y` pela **altura** do frame, de
 * forma independente. Num vídeo 640x480 isso significa que uma mesma distância
 * física vale números diferentes na horizontal e na vertical. Como EAR e MAR são
 * razões entre uma distância vertical e uma horizontal, usar as coordenadas
 * cruas embutiria a proporção do vídeo dentro da métrica — e o valor mudaria só
 * por trocar a resolução da webcam.
 *
 * @param aspecto largura/altura do frame.
 */
export function distancia(a: Ponto, b: Ponto, aspecto: number): number {
  return Math.hypot((a.x - b.x) * aspecto, a.y - b.y);
}

function exigirPonto(landmarks: ReadonlyArray<Ponto>, indice: number): Ponto {
  const ponto = landmarks[indice];
  if (ponto === undefined) {
    throw new RangeError(`Landmark ${indice} ausente: a malha tem ${landmarks.length} pontos.`);
  }
  return ponto;
}

/**
 * Eye Aspect Ratio de um olho: razão entre a abertura vertical média e a
 * largura horizontal. Cai para perto de zero com o olho fechado e fica estável
 * (~0,3) com o olho aberto, independentemente da distância até a câmera.
 */
export function calcularEAROlho(
  landmarks: ReadonlyArray<Ponto>,
  indices: ReadonlyArray<number>,
  aspecto: number,
): number {
  const [p1, p2, p3, p4, p5, p6] = indices.map((indice) => exigirPonto(landmarks, indice));

  const largura = distancia(p1, p4, aspecto);
  if (largura === 0) {
    // Olho degenerado num ponto só: não há razão a calcular, e dividir por zero
    // propagaria NaN para dentro do IEE.
    return 0;
  }

  return (distancia(p2, p6, aspecto) + distancia(p3, p5, aspecto)) / (2 * largura);
}

/** EAR médio dos dois olhos. */
export function calcularEAR(landmarks: ReadonlyArray<Ponto>, aspecto: number): number {
  const direito = calcularEAROlho(landmarks, INDICES_OLHO_DIREITO, aspecto);
  const esquerdo = calcularEAROlho(landmarks, INDICES_OLHO_ESQUERDO, aspecto);
  return (direito + esquerdo) / 2;
}

/**
 * Mouth Aspect Ratio: razão entre a abertura vertical da boca e sua largura.
 * Sobe durante o bocejo, que é o sinal que a ticket 8 usa para fadiga.
 */
export function calcularMAR(landmarks: ReadonlyArray<Ponto>, aspecto: number): number {
  const superior = exigirPonto(landmarks, INDICES_BOCA.labioSuperior);
  const inferior = exigirPonto(landmarks, INDICES_BOCA.labioInferior);
  const esquerdo = exigirPonto(landmarks, INDICES_BOCA.cantoEsquerdo);
  const direito = exigirPonto(landmarks, INDICES_BOCA.cantoDireito);

  const largura = distancia(esquerdo, direito, aspecto);
  if (largura === 0) {
    return 0;
  }

  return distancia(superior, inferior, aspecto) / largura;
}

/** Matriz de transformação facial, no formato que o MediaPipe devolve. */
export interface MatrizDeTransformacao {
  rows: number;
  columns: number;
  data: ArrayLike<number>;
}

const GRAUS_POR_RADIANO = 180 / Math.PI;

/**
 * Descobre se a matriz 4x4 veio em column-major (convenção OpenGL) ou row-major.
 *
 * O `.d.ts` do `@mediapipe/tasks-vision` descreve `data` apenas como "os valores
 * num array unidimensional achatado", sem dizer a ordem — e ler na ordem errada
 * não estoura erro nenhum, só devolve ângulos silenciosamente errados. Em vez de
 * apostar, deduzimos da própria matriz: numa transformação rígida, os três
 * valores de translação são muito maiores que os de rotação, que vivem em
 * [-1, 1]. O trio de maior magnitude denuncia o layout.
 */
function ehColumnMajor(data: ArrayLike<number>): boolean {
  const somaColumnMajor = Math.abs(data[12]) + Math.abs(data[13]) + Math.abs(data[14]);
  const somaRowMajor = Math.abs(data[3]) + Math.abs(data[7]) + Math.abs(data[11]);
  // Empate (rosto exatamente na origem) é improvável na prática; nesse caso
  // ficamos com a convenção do OpenGL, que é a que o MediaPipe usa.
  return somaColumnMajor >= somaRowMajor;
}

/**
 * Extrai yaw/pitch/roll da matriz de transformação facial.
 *
 * Decomposição Tait-Bryan assumindo R = Rz(roll) · Ry(yaw) · Rx(pitch).
 */
export function extrairAngulosDaCabeca(matriz: MatrizDeTransformacao): AngulosDaCabeca {
  if (matriz.rows !== 4 || matriz.columns !== 4 || matriz.data.length < 16) {
    throw new RangeError(
      `Esperava uma matriz 4x4, recebi ${matriz.rows}x${matriz.columns} com ${matriz.data.length} valores.`,
    );
  }

  const colunaPrimeiro = ehColumnMajor(matriz.data);
  const r = (linha: number, coluna: number): number =>
    colunaPrimeiro ? matriz.data[coluna * 4 + linha] : matriz.data[linha * 4 + coluna];

  return {
    pitch: Math.atan2(r(2, 1), r(2, 2)) * GRAUS_POR_RADIANO,
    yaw: Math.atan2(-r(2, 0), Math.hypot(r(2, 1), r(2, 2))) * GRAUS_POR_RADIANO,
    roll: Math.atan2(r(1, 0), r(0, 0)) * GRAUS_POR_RADIANO,
  };
}

/** Calcula as três métricas de uma vez, a partir de uma malha e sua matriz de pose. */
export function calcularMetricas(
  landmarks: ReadonlyArray<Ponto>,
  matriz: MatrizDeTransformacao,
  aspecto: number,
): MetricasFaciais {
  return {
    ear: calcularEAR(landmarks, aspecto),
    mar: calcularMAR(landmarks, aspecto),
    cabeca: extrairAngulosDaCabeca(matriz),
  };
}
