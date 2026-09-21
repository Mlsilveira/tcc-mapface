/**
 * Formatação de duração para leitura humana.
 *
 * Vive aqui, e não dentro de um componente, porque o relatório e o histórico
 * precisam da **mesma** frase: "52min" numa tela e "0h 52m" na outra fariam o
 * aluno achar que são números diferentes.
 *
 * O backend manda segundos crus de propósito — quem sabe o idioma e a largura
 * da tela é o navegador. Esta é a metade da decisão que sobrou para o cliente.
 */

/**
 * Segundos para algo que uma pessoa lê de relance.
 *
 * Abaixo de um minuto o número de segundos importa (uma sessão de 12 s conta
 * uma história); acima dele, não — ninguém precisa saber que foram 52 minutos e
 * 37 segundos, e o segundo a mais só rouba atenção do minuto.
 */
export function formatarDuracao(segundos: number): string {
  const total = Math.max(0, Math.round(segundos));

  if (total < 60) {
    return `${total}s`;
  }

  const horas = Math.floor(total / 3600);
  const minutos = Math.floor((total % 3600) / 60);

  if (horas === 0) {
    return `${minutos}min`;
  }

  return minutos === 0 ? `${horas}h` : `${horas}h ${minutos}min`;
}
