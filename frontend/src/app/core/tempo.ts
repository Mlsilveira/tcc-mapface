/**
 * Formatação de duração para a interface.
 *
 * Aritmética pura sobre um número de segundos: não conhece Angular, não lê
 * relógio e não depende de fuso. Quem decide *qual* duração mostrar é quem
 * chama; aqui só se decide como ela aparece.
 */

/**
 * Segundos → `MM:SS`, ou `H:MM:SS` quando passa de uma hora.
 *
 * Sem a hora, uma sessão de 90 minutos apareceria como `90:00` — legível, mas
 * fora da convenção de cronômetro que o aluno reconhece. Com ela, `1:30:00`.
 *
 * Valores negativos viram `00:00`. Isso não é paranoia: o início da sessão vem
 * do relógio do servidor e o tempo corrente do relógio do navegador, e alguns
 * segundos de diferença entre os dois são comuns — o cronômetro contar para
 * trás no primeiro segundo seria um bug visível.
 */
export function formatarDuracao(segundos: number): string {
  const total = Math.max(0, Math.floor(segundos));
  const horas = Math.floor(total / 3600);
  const minutos = Math.floor((total % 3600) / 60);
  const resto = total % 60;

  const doisDigitos = (valor: number): string => String(valor).padStart(2, '0');

  return horas > 0
    ? `${horas}:${doisDigitos(minutos)}:${doisDigitos(resto)}`
    : `${doisDigitos(minutos)}:${doisDigitos(resto)}`;
}
