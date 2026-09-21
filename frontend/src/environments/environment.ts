import { Ambiente } from './ambiente';

/**
 * Configuração de desenvolvimento — o que vale quando se roda `ng serve`.
 *
 * Em produção este arquivo é **substituído** pelo `environment.prod.ts`, pelo
 * `fileReplacements` do `angular.json`. É por isso que nenhum outro arquivo
 * pode importar `environment.prod.ts` diretamente: quem importa daqui recebe o
 * arquivo certo para o build que está rodando, e quem importa de lá recebe
 * produção até em `ng serve`.
 *
 * O valor de desenvolvimento é o mesmo literal que estava em `core/api.ts`
 * antes de existir esta pasta, de propósito: os specs verificam requisições
 * contra `http://localhost:8000` e a suíte roda sobre este arquivo.
 */
export const environment: Ambiente = {
  producao: false,
  apiUrl: 'http://localhost:8000',
};
