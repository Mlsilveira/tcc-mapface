/**
 * O termo de consentimento, em um lugar só.
 *
 * Cadastro e página de privacidade leem daqui, para que o titular nunca veja
 * dois textos diferentes. `VERSAO_TERMO` precisa ser a mesma de
 * `backend/app/consentimento.py`: o servidor recusa aceite de versão diferente,
 * e é assim que um bundle antigo não registra aceite de um texto que mudou.
 *
 * Mudar qualquer cláusula exige subir a versão nos dois lados. É o que faz valer
 * a promessa da última cláusula, de pedir um novo aceite.
 */
export const VERSAO_TERMO = '1.1';

export interface ClausulaDoTermo {
  readonly titulo: string;
  readonly texto: string;
}

export const CLAUSULAS_DO_TERMO: readonly ClausulaDoTermo[] = [
  {
    titulo: 'Quem trata os dados',
    texto:
      'O MapFace é uma prova de conceito acadêmica desenvolvida por estudantes do curso de ' +
      'Ciência da Computação da Universidade Paulista (UNIP), como Trabalho de Conclusão de ' +
      'Curso. Contato: sacmapface@gmail.com.',
  },
  {
    titulo: 'Finalidade',
    texto:
      'Os dados são tratados exclusivamente para gerar, ao final de cada sessão de estudo, um ' +
      'relatório de autopercepção destinado somente a você, com indicadores e recomendações de ' +
      'métodos de estudo. O sistema não realiza diagnóstico de saúde, não avalia desempenho e ' +
      'não compartilha dados com instituições de ensino ou terceiros.',
  },
  {
    titulo: 'Dados coletados',
    texto:
      'Nome, e-mail e senha (armazenada de forma irreversível); método, assunto, meta de blocos ' +
      'e horários de cada sessão; e, uma vez por segundo, métricas numéricas calculadas no seu ' +
      'navegador: abertura dos olhos, abertura da boca, ângulos da cabeça, presença do rosto e ' +
      'qualidade da captura.',
  },
  {
    titulo: 'Dados que não são coletados',
    texto:
      'Nenhuma imagem, vídeo ou ponto do seu rosto é enviado ou armazenado. A imagem da câmera ' +
      'é processada no seu próprio navegador e descartada imediatamente.',
  },
  {
    titulo: 'Base legal',
    texto:
      'Por precaução, as métricas faciais são tratadas como dado pessoal sensível, nos termos ' +
      'do art. 5º, II, da Lei nº 13.709/2018 (LGPD). O projeto adota o consentimento específico ' +
      'e destacado como base legal para esse tratamento (art. 11, I).',
  },
  {
    titulo: 'Idade mínima',
    texto: 'O uso do MapFace é restrito a maiores de 18 anos, por autodeclaração no cadastro.',
  },
  {
    titulo: 'Armazenamento e retenção',
    texto:
      'Os dados ficam em banco de dados na Amazon Web Services, criptografado e inacessível ' +
      'pela internet. Após 24 horas do fim de cada sessão, os registros por segundo são ' +
      'substituídos por médias por minuto. Os dados são mantidos enquanto sua conta existir. As ' +
      'cópias automáticas de segurança do banco são retidas por até 1 dia: após a exclusão da ' +
      'conta, os dados podem permanecer nessas cópias até o fim desse prazo.',
  },
  {
    titulo: 'Seus direitos',
    texto:
      'Você pode, a qualquer momento, acessar seus dados, corrigi-los, revogar este ' +
      'consentimento e excluir sua conta e todos os dados associados (arts. 8º, § 5º, e 18 da ' +
      'LGPD), na página de privacidade do aplicativo. A revogação impede novas sessões, mas não ' +
      'afeta o tratamento realizado antes dela.',
  },
  {
    titulo: 'Versão',
    texto: `Versão ${VERSAO_TERMO} do termo. Em caso de alteração, um novo aceite será solicitado.`,
  },
];

/** O aceite como o backend espera recebê-lo. */
export interface AceiteDoTermo {
  aceitou_termo: boolean;
  declarou_maioridade: boolean;
  versao_termo: string;
}

/** Só existe depois de as duas caixas marcadas: quem chama já validou o formulário. */
export const ACEITE_DA_VERSAO_ATUAL: AceiteDoTermo = {
  aceitou_termo: true,
  declarou_maioridade: true,
  versao_termo: VERSAO_TERMO,
};
