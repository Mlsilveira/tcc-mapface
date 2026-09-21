/**
 * A forma que os dois arquivos de ambiente têm que ter.
 *
 * Mora fora deles de propósito: o `fileReplacements` troca `environment.ts` por
 * `environment.prod.ts` no build de produção, então um arquivo de ambiente não
 * pode tirar o tipo do outro — em produção ele estaria descrevendo a si mesmo.
 * Com o contrato aqui, acrescentar uma chave e esquecer dela no outro arquivo
 * vira erro de compilação, em vez de uma propriedade `undefined` que só aparece
 * depois de publicado.
 */
export interface Ambiente {
  /** Se este é o bundle de produção. */
  readonly producao: boolean;

  /**
   * Base da API REST. O canal de telemetria sai daqui também — ver
   * `baseDeWebSocket` em `app/core/api.ts`.
   */
  readonly apiUrl: string;
}
