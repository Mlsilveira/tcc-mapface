import {
  INDICES_BOCA,
  INDICES_OLHO_DIREITO,
  INDICES_OLHO_ESQUERDO,
  MatrizDeTransformacao,
  Ponto,
  calcularEAR,
  calcularEAROlho,
  calcularMAR,
  calcularMetricas,
  extrairAngulosDaCabeca,
} from './metricas';

const TOTAL_DE_LANDMARKS = 478;

/** Malha com todos os pontos na origem, para o teste posicionar só o que importa. */
function malha(): Ponto[] {
  return Array.from({ length: TOTAL_DE_LANDMARKS }, () => ({ x: 0, y: 0 }));
}

/**
 * Desenha um olho retangular de largura e abertura conhecidas, centrado em
 * (cx, cy), na ordem que a fórmula de EAR espera.
 */
function desenharOlho(
  landmarks: Ponto[],
  indices: ReadonlyArray<number>,
  { cx, cy, largura, abertura }: { cx: number; cy: number; largura: number; abertura: number },
): void {
  const [p1, p2, p3, p4, p5, p6] = indices;
  const meia = largura / 2;
  const alto = cy - abertura / 2;
  const baixo = cy + abertura / 2;

  landmarks[p1] = { x: cx - meia, y: cy };
  landmarks[p2] = { x: cx - meia / 2, y: alto };
  landmarks[p3] = { x: cx + meia / 2, y: alto };
  landmarks[p4] = { x: cx + meia, y: cy };
  landmarks[p5] = { x: cx + meia / 2, y: baixo };
  landmarks[p6] = { x: cx - meia / 2, y: baixo };
}

function desenharBoca(
  landmarks: Ponto[],
  { largura, abertura }: { largura: number; abertura: number },
): void {
  landmarks[INDICES_BOCA.cantoEsquerdo] = { x: -largura / 2, y: 0 };
  landmarks[INDICES_BOCA.cantoDireito] = { x: largura / 2, y: 0 };
  landmarks[INDICES_BOCA.labioSuperior] = { x: 0, y: -abertura / 2 };
  landmarks[INDICES_BOCA.labioInferior] = { x: 0, y: abertura / 2 };
}

type Matriz3x3 = readonly [
  readonly [number, number, number],
  readonly [number, number, number],
  readonly [number, number, number],
];

const IDENTIDADE_3x3: Matriz3x3 = [
  [1, 0, 0],
  [0, 1, 0],
  [0, 0, 1],
];

function rotacaoEmX(graus: number): Matriz3x3 {
  const t = (graus * Math.PI) / 180;
  return [
    [1, 0, 0],
    [0, Math.cos(t), -Math.sin(t)],
    [0, Math.sin(t), Math.cos(t)],
  ];
}

function rotacaoEmY(graus: number): Matriz3x3 {
  const t = (graus * Math.PI) / 180;
  return [
    [Math.cos(t), 0, Math.sin(t)],
    [0, 1, 0],
    [-Math.sin(t), 0, Math.cos(t)],
  ];
}

function rotacaoEmZ(graus: number): Matriz3x3 {
  const t = (graus * Math.PI) / 180;
  return [
    [Math.cos(t), -Math.sin(t), 0],
    [Math.sin(t), Math.cos(t), 0],
    [0, 0, 1],
  ];
}

/** Monta a 4x4 achatada em row-major: `data[linha * 4 + coluna]`. */
function emRowMajor(r: Matriz3x3, translacao: readonly [number, number, number]): MatrizDeTransformacao {
  const [tx, ty, tz] = translacao;
  return {
    rows: 4,
    columns: 4,
    data: [
      r[0][0], r[0][1], r[0][2], tx,
      r[1][0], r[1][1], r[1][2], ty,
      r[2][0], r[2][1], r[2][2], tz,
      0, 0, 0, 1,
    ],
  };
}

/** Monta a 4x4 achatada em column-major: `data[coluna * 4 + linha]`. */
function emColumnMajor(
  r: Matriz3x3,
  translacao: readonly [number, number, number],
): MatrizDeTransformacao {
  const [tx, ty, tz] = translacao;
  return {
    rows: 4,
    columns: 4,
    data: [
      r[0][0], r[1][0], r[2][0], 0,
      r[0][1], r[1][1], r[2][1], 0,
      r[0][2], r[1][2], r[2][2], 0,
      tx, ty, tz, 1,
    ],
  };
}

/** Longe da origem, como um rosto real diante da câmera. */
const TRANSLACAO_TIPICA = [1.5, -2, 30] as const;

describe('EAR', () => {
  it('vale ~0 com o olho fechado', () => {
    const landmarks = malha();
    desenharOlho(landmarks, INDICES_OLHO_DIREITO, { cx: 0, cy: 0, largura: 0.1, abertura: 0 });

    expect(calcularEAROlho(landmarks, INDICES_OLHO_DIREITO, 1)).toBe(0);
  });

  it('cresce conforme o olho abre', () => {
    const fechando = malha();
    const abrindo = malha();
    desenharOlho(fechando, INDICES_OLHO_DIREITO, { cx: 0, cy: 0, largura: 0.1, abertura: 0.01 });
    desenharOlho(abrindo, INDICES_OLHO_DIREITO, { cx: 0, cy: 0, largura: 0.1, abertura: 0.04 });

    expect(calcularEAROlho(abrindo, INDICES_OLHO_DIREITO, 1)).toBeGreaterThan(
      calcularEAROlho(fechando, INDICES_OLHO_DIREITO, 1),
    );
  });

  it('não muda quando o aluno se afasta da câmera', () => {
    // O EAR é uma razão justamente para sobreviver a isso: sem essa
    // propriedade, encostar ou afastar da tela viraria "mudança de engajamento".
    const perto = malha();
    const longe = malha();
    desenharOlho(perto, INDICES_OLHO_DIREITO, { cx: 0, cy: 0, largura: 0.2, abertura: 0.06 });
    desenharOlho(longe, INDICES_OLHO_DIREITO, { cx: 0, cy: 0, largura: 0.1, abertura: 0.03 });

    expect(calcularEAROlho(longe, INDICES_OLHO_DIREITO, 1)).toBeCloseTo(
      calcularEAROlho(perto, INDICES_OLHO_DIREITO, 1),
      10,
    );
  });

  it('corrige a distorção das coordenadas normalizadas pela proporção do vídeo', () => {
    // O MediaPipe normaliza x pela largura e y pela altura, separadamente. Sem
    // passar o aspecto, o mesmo olho daria EAR diferente só por trocar a
    // resolução da webcam.
    const larguraEmPixels = 640;
    const alturaEmPixels = 480;
    const aspecto = larguraEmPixels / alturaEmPixels;

    const emPixels = malha();
    desenharOlho(emPixels, INDICES_OLHO_DIREITO, { cx: 320, cy: 240, largura: 60, abertura: 20 });

    const normalizado = malha();
    desenharOlho(normalizado, INDICES_OLHO_DIREITO, {
      cx: 320 / larguraEmPixels,
      cy: 240 / alturaEmPixels,
      largura: 60 / larguraEmPixels,
      abertura: 20 / alturaEmPixels,
    });

    const esperado = calcularEAROlho(emPixels, INDICES_OLHO_DIREITO, 1);

    expect(calcularEAROlho(normalizado, INDICES_OLHO_DIREITO, aspecto)).toBeCloseTo(esperado, 10);
    // E, sem a correção, o valor erra de fato — o teste acima não é vacuidade.
    expect(calcularEAROlho(normalizado, INDICES_OLHO_DIREITO, 1)).not.toBeCloseTo(esperado, 3);
  });

  it('faz a média dos dois olhos', () => {
    const landmarks = malha();
    desenharOlho(landmarks, INDICES_OLHO_DIREITO, { cx: -0.2, cy: 0, largura: 0.1, abertura: 0.04 });
    desenharOlho(landmarks, INDICES_OLHO_ESQUERDO, { cx: 0.2, cy: 0, largura: 0.1, abertura: 0 });

    const direito = calcularEAROlho(landmarks, INDICES_OLHO_DIREITO, 1);

    expect(calcularEAR(landmarks, 1)).toBeCloseTo(direito / 2, 10);
  });

  it('devolve 0 em vez de NaN quando o olho degenera num ponto', () => {
    // Divisão por zero aqui contaminaria o IEE inteiro com NaN.
    expect(calcularEAROlho(malha(), INDICES_OLHO_DIREITO, 1)).toBe(0);
  });

  it('acusa malha incompleta em vez de calcular com lixo', () => {
    expect(() => calcularEAR([{ x: 0, y: 0 }], 1)).toThrowError(RangeError);
  });
});

describe('MAR', () => {
  it('vale ~0 com a boca fechada e sobe ao abrir', () => {
    const fechada = malha();
    const aberta = malha();
    desenharBoca(fechada, { largura: 0.1, abertura: 0 });
    desenharBoca(aberta, { largura: 0.1, abertura: 0.08 });

    expect(calcularMAR(fechada, 1)).toBe(0);
    expect(calcularMAR(aberta, 1)).toBeGreaterThan(calcularMAR(fechada, 1));
  });

  it('é a razão entre abertura e largura da boca', () => {
    const landmarks = malha();
    desenharBoca(landmarks, { largura: 0.2, abertura: 0.05 });

    expect(calcularMAR(landmarks, 1)).toBeCloseTo(0.25, 10);
  });
});

describe('extrairAngulosDaCabeca', () => {
  it('devolve tudo zerado para a matriz identidade', () => {
    const angulos = extrairAngulosDaCabeca(emColumnMajor(IDENTIDADE_3x3, [0, 0, 0]));

    expect(angulos.yaw).toBeCloseTo(0, 10);
    expect(angulos.pitch).toBeCloseTo(0, 10);
    expect(angulos.roll).toBeCloseTo(0, 10);
  });

  it('recupera um yaw conhecido', () => {
    const angulos = extrairAngulosDaCabeca(emColumnMajor(rotacaoEmY(30), TRANSLACAO_TIPICA));

    expect(angulos.yaw).toBeCloseTo(30, 6);
    expect(angulos.pitch).toBeCloseTo(0, 6);
    expect(angulos.roll).toBeCloseTo(0, 6);
  });

  it('recupera um pitch conhecido', () => {
    const angulos = extrairAngulosDaCabeca(emColumnMajor(rotacaoEmX(-20), TRANSLACAO_TIPICA));

    expect(angulos.pitch).toBeCloseTo(-20, 6);
    expect(angulos.yaw).toBeCloseTo(0, 6);
  });

  it('recupera um roll conhecido', () => {
    const angulos = extrairAngulosDaCabeca(emColumnMajor(rotacaoEmZ(15), TRANSLACAO_TIPICA));

    expect(angulos.roll).toBeCloseTo(15, 6);
  });

  it('dá o mesmo resultado em row-major e em column-major', () => {
    // O tipo `Matrix` do @mediapipe/tasks-vision documenta `data` apenas como
    // "valores achatados", sem dizer a ordem. Ler na ordem errada não estoura
    // erro — só devolve ângulos errados. Por isso o layout é deduzido, não
    // assumido.
    const rotacao = rotacaoEmY(25);

    const porColuna = extrairAngulosDaCabeca(emColumnMajor(rotacao, TRANSLACAO_TIPICA));
    const porLinha = extrairAngulosDaCabeca(emRowMajor(rotacao, TRANSLACAO_TIPICA));

    expect(porLinha.yaw).toBeCloseTo(porColuna.yaw, 6);
    expect(porLinha.pitch).toBeCloseTo(porColuna.pitch, 6);
    expect(porLinha.roll).toBeCloseTo(porColuna.roll, 6);
  });

  it('distingue olhar para a direita de olhar para a esquerda', () => {
    const direita = extrairAngulosDaCabeca(emColumnMajor(rotacaoEmY(35), TRANSLACAO_TIPICA));
    const esquerda = extrairAngulosDaCabeca(emColumnMajor(rotacaoEmY(-35), TRANSLACAO_TIPICA));

    expect(direita.yaw).toBeGreaterThan(0);
    expect(esquerda.yaw).toBeLessThan(0);
  });

  it('recusa matrizes que não sejam 4x4', () => {
    expect(() =>
      extrairAngulosDaCabeca({ rows: 3, columns: 3, data: [1, 0, 0, 0, 1, 0, 0, 0, 1] }),
    ).toThrowError(RangeError);
  });
});

describe('calcularMetricas', () => {
  it('junta as três métricas numa leitura só', () => {
    const landmarks = malha();
    desenharOlho(landmarks, INDICES_OLHO_DIREITO, { cx: -0.1, cy: 0, largura: 0.1, abertura: 0.03 });
    desenharOlho(landmarks, INDICES_OLHO_ESQUERDO, { cx: 0.1, cy: 0, largura: 0.1, abertura: 0.03 });
    desenharBoca(landmarks, { largura: 0.2, abertura: 0.05 });

    const metricas = calcularMetricas(
      landmarks,
      emColumnMajor(rotacaoEmY(10), TRANSLACAO_TIPICA),
      1,
    );

    expect(metricas.ear).toBeGreaterThan(0);
    expect(metricas.mar).toBeCloseTo(0.25, 10);
    expect(metricas.cabeca.yaw).toBeCloseTo(10, 6);
  });
});
