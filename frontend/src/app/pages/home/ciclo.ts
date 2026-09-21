import { MetodoDeEstudo } from '../../core/services/metodo.service';
import { Bloco, TIPO_FOCO } from '../../core/services/sessao.service';

/**
 * A conta do ciclo de estudo, fora do componente.
 *
 * Vive aqui pelo mesmo motivo que `blocos.py` vive fora do router no backend:
 * "quanto falta deste bloco" é uma pergunta sobre dois números e um relógio, e
 * respondê-la dentro do componente obrigaria a montar um TestBed, ligar uma
 * webcam falsa e abrir uma sessão só para conferir uma subtração.
 *
 * **Nada aqui olha para a série do IEE.** Não é omissão: é a AC-17-8. O
 * cronômetro pode aparecer na tela da sessão justamente porque tudo que ele
 * mostra sai do método declarado e do relógio de parede — nenhum número
 * atravessa o caminho que passa pelo comportamento medido do aluno.
 */

/**
 * O bloco em andamento, ou `null` se não há nenhum aberto.
 *
 * Procura de trás para frente porque o aberto é sempre o último: se um dia
 * houver dois sem `fim` — dado corrompido, ou duas abas declarando ao mesmo
 * tempo —, o cronômetro segue o mais recente em vez de travar no primeiro.
 */
export function blocoAberto(blocos: readonly Bloco[]): Bloco | null {
  for (let i = blocos.length - 1; i >= 0; i -= 1) {
    if (blocos[i].fim === null) {
      return blocos[i];
    }
  }
  return null;
}

/** Quantos blocos de foco a sessão já declarou, contando o que está aberto. */
export function focosDeclarados(blocos: readonly Bloco[]): number {
  return blocos.filter((bloco) => bloco.tipo === TIPO_FOCO).length;
}

/**
 * Se a próxima pausa é a longa, que fecha o ciclo.
 *
 * Só métodos que declaram `ciclos_ate_pausa_longa` têm uma — o 52/17 não tem,
 * e inventar uma para ele transformaria um método de dois tempos num Pomodoro
 * com outros números.
 */
export function ehPausaLonga(metodo: MetodoDeEstudo | null, quantosFocos: number): boolean {
  return (
    metodo !== null &&
    metodo.ciclos_ate_pausa_longa !== null &&
    quantosFocos >= metodo.ciclos_ate_pausa_longa
  );
}

/**
 * Quantos segundos o método prescreve para o bloco corrente, ou `null`.
 *
 * **`null` quando o método não prescreve duração de foco** (Flow e Timeboxing,
 * com `foco_s` nulo) — e aí nem a pausa ganha cronômetro. O `pausa_s` desses
 * métodos existe para o servidor decidir quando a cadeira vazia encerra a
 * sessão, não para prescrever quanto tempo o aluno deve descansar: contar cinco
 * minutos regressivos para quem escolheu Flow seria o app prescrevendo o que o
 * método recusa a prescrever.
 */
export function duracaoPrescrita(
  metodo: MetodoDeEstudo | null,
  bloco: Bloco | null,
  quantosFocos: number,
): number | null {
  if (metodo === null || bloco === null || metodo.foco_s === null) {
    return null;
  }

  if (bloco.tipo === TIPO_FOCO) {
    return metodo.foco_s;
  }

  return ehPausaLonga(metodo, quantosFocos)
    ? (metodo.pausa_longa_s ?? metodo.pausa_s)
    : metodo.pausa_s;
}

/**
 * Quanto falta do bloco, em segundos.
 *
 * **Nunca negativo.** O aluno que não pausa quando o cronômetro zera não vê um
 * número descendo abaixo de zero: o bloco estourou, e "estourou" é um estado,
 * não uma dívida a contar. Deixar passar para o negativo também trocaria o
 * aviso de pausa por um segundo placar — desta vez do atraso dele.
 */
export function segundosRestantes(inicio: string, duracaoS: number, agora: number): number {
  const decorridos = (agora - Date.parse(inicio)) / 1000;
  return Math.max(0, duracaoS - decorridos);
}
