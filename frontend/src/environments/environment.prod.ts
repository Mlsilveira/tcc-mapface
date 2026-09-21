import { Ambiente } from './ambiente';

/**
 * Configuração de produção — entra no lugar do `environment.ts` no build
 * `--configuration production` (ver `fileReplacements` no `angular.json`).
 *
 * **O valor abaixo é um marcador, não um endereço.** Quem escreve o Terraform
 * só conhece a URL real depois que a infra sobe, então o endereço de produção
 * não mora aqui: ele chega pela variável de ambiente `MAPFACE_API_URL`, que o
 * `npm run build:producao` lê e escreve nesta linha antes de chamar o `ng
 * build`. Publicar exige setar a variável, não editar código-fonte.
 *
 * O marcador é um host que **não resolve**, e não `localhost`, de propósito. Se
 * alguém publicar um bundle sem passar pelo script, o site falha na cara de
 * quem abrir — que é o sintoma certo. Com `localhost` o erro seria invisível na
 * origem e visível só no efeito: cada visitante tentando falar com o backend da
 * própria máquina dele.
 */
export const environment: Ambiente = {
  producao: true,
  apiUrl: 'https://api.invalida.mapface',
};
