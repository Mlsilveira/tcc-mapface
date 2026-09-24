/**
 * Garante o modelo do MediaPipe antes de compilar.
 *
 * O arquivo tem ~3,7 MB de pesos e **não é versionado** (`.gitignore` na raiz):
 * binário grande em repositório de código incha o histórico para sempre, já que
 * o Git guarda cada versão inteira.
 *
 * A consequência de esquecê-lo é a pior possível para diagnosticar: o build
 * passa, o site sobe, o login funciona, a sessão inicia — e a captura falha
 * **só** na hora de ligar a câmera, que é o último passo e o mais fácil de
 * confundir com problema de permissão ou de webcam. Por isso o download é um
 * passo do `npm run build`, e não uma linha de README que alguém lê uma vez.
 *
 * Se o arquivo já existe, não há rede envolvida: build offline continua
 * funcionando, e não se paga download a cada compilação.
 */
import { createWriteStream } from 'node:fs';
import { mkdir, stat, rm } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { Readable } from 'node:stream';
import { pipeline } from 'node:stream/promises';
import { fileURLToPath } from 'node:url';

const ORIGEM =
  'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task';

const DESTINO = resolve(
  dirname(fileURLToPath(import.meta.url)),
  '..',
  'src/assets/mediapipe/face_landmarker.task',
);

/** Abaixo disto o arquivo é resto de download interrompido, não modelo. */
const TAMANHO_MINIMO_BYTES = 1_000_000;

async function jaEstaNoLugar() {
  try {
    const { size } = await stat(DESTINO);
    return size >= TAMANHO_MINIMO_BYTES;
  } catch {
    return false;
  }
}

async function baixar() {
  const resposta = await fetch(ORIGEM);
  if (!resposta.ok || !resposta.body) {
    throw new Error(`${resposta.status} ${resposta.statusText}`);
  }

  await mkdir(dirname(DESTINO), { recursive: true });

  // Grava em arquivo temporário e só renomeia no fim — um download cortado no
  // meio deixaria no lugar certo um arquivo com o nome certo e o conteúdo pela
  // metade, e a próxima execução o aceitaria como pronto.
  const parcial = `${DESTINO}.parcial`;
  try {
    await pipeline(Readable.fromWeb(resposta.body), createWriteStream(parcial));
    const { rename } = await import('node:fs/promises');
    await rename(parcial, DESTINO);
  } catch (erro) {
    await rm(parcial, { force: true });
    throw erro;
  }
}

if (await jaEstaNoLugar()) {
  console.log('Modelo do MediaPipe já está em src/assets/mediapipe/.');
} else {
  console.log('Baixando o modelo do MediaPipe (~3,7 MB)…');
  try {
    await baixar();
    console.log('Modelo do MediaPipe pronto.');
  } catch (erro) {
    console.error(`\nNão foi possível baixar o modelo do MediaPipe: ${erro.message}`);
    console.error(`Baixe manualmente de ${ORIGEM}`);
    console.error('e salve em frontend/src/assets/mediapipe/face_landmarker.task\n');
    process.exit(1);
  }
}
