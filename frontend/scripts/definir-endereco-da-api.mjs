/**
 * Escreve o endereço da API no `environment.prod.ts` antes do build.
 *
 * Existe por um descompasso de calendário: quem publica o frontend precisa
 * saber a URL do backend, e essa URL só existe depois que a infra sobe. Sem
 * este script, publicar significaria abrir um arquivo `.ts`, editar uma string
 * e torcer para ninguém commitar o endereço de produção junto — ou seja,
 * publicar exigiria editar código-fonte.
 *
 * O Angular não lê variável de ambiente em tempo de build (não há `DefinePlugin`
 * exposto no builder `application`), então o caminho mais curto entre
 * `MAPFACE_API_URL` e o bundle é este: reescrever uma linha do arquivo que o
 * `fileReplacements` já usa. Nenhuma peça nova no build; só o valor.
 *
 * Uso: `MAPFACE_API_URL=https://api.exemplo.com npm run build:producao`
 */
import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const ARQUIVO = join(
  dirname(fileURLToPath(import.meta.url)),
  '..',
  'src',
  'environments',
  'environment.prod.ts',
);

// A linha exata que guarda o valor. Um regex estreito, e não uma busca por
// `http`, porque os comentários do arquivo também falam de URLs: o que se quer
// trocar é o campo, não toda ocorrência que se pareça com um endereço.
const LINHA_DO_ENDERECO = /^(\s*apiUrl: ')([^']*)(',)$/m;

function falhar(mensagem) {
  console.error(`\n  definir-endereco-da-api: ${mensagem}\n`);
  process.exit(1);
}

const endereco = (process.env['MAPFACE_API_URL'] ?? '').trim();

// Falha fechado, e não segue com o marcador. Um build de produção silencioso e
// apontando para lugar nenhum é pior que um build que não acontece: o erro
// aparece no navegador do usuário, horas depois, longe de quem publicou.
if (endereco === '') {
  falhar(
    'a variável MAPFACE_API_URL não está definida.\n' +
      '  Ela é o endereço público do backend, e só existe depois que a infra sobe.\n' +
      '  Exemplo: MAPFACE_API_URL=https://api.exemplo.com npm run build:producao',
  );
}

let url;
try {
  url = new URL(endereco);
} catch {
  falhar(`MAPFACE_API_URL não é uma URL válida: ${endereco}`);
}

if (url.protocol !== 'https:' && url.protocol !== 'http:') {
  // Aceitar `ws://` aqui seria aceitar o engano que a derivação de esquema
  // existe para evitar: o que se configura é a API, e o canal de telemetria sai
  // dela.
  falhar(`MAPFACE_API_URL precisa começar com https:// ou http:// — veio ${url.protocol}//`);
}

if (url.protocol === 'http:' && url.hostname !== 'localhost') {
  // Aviso, não erro: um endereço interno em http tem uso legítimo em teste. Mas
  // em http o canal de telemetria vira `ws://`, e navegador nenhum abre `ws://`
  // a partir de uma página servida por https.
  console.warn(
    `\n  definir-endereco-da-api: atenção — ${endereco} usa http://, então a telemetria usará ws://.\n` +
      '  Se o site for servido por https, o navegador vai recusar esse canal.\n',
  );
}

const original = readFileSync(ARQUIVO, 'utf8');
if (!LINHA_DO_ENDERECO.test(original)) {
  falhar(`não achei a linha "apiUrl: '...'" em ${ARQUIVO} — o arquivo mudou de forma?`);
}

// Sem barra final, pelo mesmo motivo que o `core/api.ts` a remove: aqui o erro
// é corrigido antes de entrar no bundle, e lá continua havendo rede de proteção
// para o caso de o arquivo ser editado à mão.
const normalizado = endereco.replace(/\/+$/, '');
writeFileSync(
  ARQUIVO,
  original.replace(
    LINHA_DO_ENDERECO,
    (_linha, antes, _valor, depois) => `${antes}${normalizado}${depois}`,
  ),
  'utf8',
);

console.log(`  definir-endereco-da-api: produção apontando para ${normalizado}`);
