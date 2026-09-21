import { MetodoDeEstudo } from '../../core/services/metodo.service';
import { Bloco } from '../../core/services/sessao.service';
import {
  blocoAberto,
  duracaoPrescrita,
  ehPausaLonga,
  focosDeclarados,
  segundosRestantes,
} from './ciclo';

const POMODORO: MetodoDeEstudo = {
  codigo: 'pomodoro',
  nome: 'Pomodoro',
  foco_s: 1500,
  pausa_s: 300,
  ciclos_ate_pausa_longa: 4,
  pausa_longa_s: 900,
};

const FLOW: MetodoDeEstudo = {
  codigo: 'flow',
  nome: 'Flow / Deep Work',
  foco_s: null,
  pausa_s: 300,
  ciclos_ate_pausa_longa: null,
  pausa_longa_s: null,
};

function bloco(parcial: Partial<Bloco>): Bloco {
  return {
    id: 1,
    id_sessao: 7,
    indice: 1,
    tipo: 'foco',
    inicio: '2026-09-21T10:00:00Z',
    fim: null,
    origem: 'metodo',
    ...parcial,
  };
}

describe('ciclo', () => {
  describe('segundosRestantes', () => {
    it('desconta do tempo prescrito o que já passou desde o início do bloco', () => {
      // Conta feita à mão: bloco de 1500 s aberto às 10h00, olhando às 10h07 —
      // 420 s decorridos, 1080 s restantes. Os números não saem da implementação
      // de propósito; se ela mudar a conta, é aqui que precisa doer.
      const restante = segundosRestantes(
        '2026-09-21T10:00:00Z',
        1500,
        Date.parse('2026-09-21T10:07:00Z'),
      );

      expect(restante).toBe(1080);
    });

    it('para em zero quando o bloco estoura, em vez de contar para o negativo', () => {
      // E7. O aluno que não pausa quando o cronômetro zera vê "0s", e não um
      // número crescendo em vermelho: o bloco estourou, e estourar é um estado —
      // não uma dívida a contar, que seria um segundo placar sobre o atraso dele.
      const restante = segundosRestantes(
        '2026-09-21T10:00:00Z',
        1500,
        Date.parse('2026-09-21T10:40:00Z'),
      );

      expect(restante).toBe(0);
    });
  });

  describe('blocoAberto', () => {
    it('acha na lista do servidor o bloco que ainda não fechou', () => {
      // E3. Depois de um F5, é daqui que o cronômetro descobre em que bloco a
      // sessão está — não da memória da aba, que o reload acabou de apagar.
      const lista = [
        bloco({ id: 1, indice: 1, tipo: 'foco', fim: '2026-09-21T10:25:00Z' }),
        bloco({ id: 2, indice: 2, tipo: 'pausa', inicio: '2026-09-21T10:25:00Z' }),
      ];

      expect(blocoAberto(lista)?.id).toBe(2);
    });

    it('devolve nulo quando a sessão ainda não declarou bloco nenhum', () => {
      expect(blocoAberto([])).toBeNull();
    });
  });

  describe('duracaoPrescrita', () => {
    it('não prescreve nada quando o método não prescreve duração de foco', () => {
      // E2. Flow tem `pausa_s`, mas esse número existe para o servidor decidir
      // quando a cadeira vazia encerra a sessão — não para o app dizer ao aluno
      // quanto tempo ele deve descansar.
      expect(duracaoPrescrita(FLOW, bloco({ tipo: 'foco' }), 1)).toBeNull();
      expect(duracaoPrescrita(FLOW, bloco({ tipo: 'pausa' }), 1)).toBeNull();
    });

    it('troca a pausa curta pela longa quando o ciclo fecha', () => {
      const pausa = bloco({ tipo: 'pausa' });

      expect(duracaoPrescrita(POMODORO, pausa, 3)).toBe(300);
      expect(duracaoPrescrita(POMODORO, pausa, 4)).toBe(900);
    });
  });

  describe('focosDeclarados e ehPausaLonga', () => {
    it('conta só os blocos de foco, incluindo o que está aberto', () => {
      const lista = [
        bloco({ id: 1, tipo: 'foco', fim: '2026-09-21T10:25:00Z' }),
        bloco({ id: 2, tipo: 'pausa', fim: '2026-09-21T10:30:00Z' }),
        bloco({ id: 3, tipo: 'foco' }),
      ];

      expect(focosDeclarados(lista)).toBe(2);
    });

    it('não inventa pausa longa para método que não declara ciclo', () => {
      // O 52/17 não tem pausa longa, e dar uma a ele o transformaria num
      // Pomodoro com outros números.
      expect(ehPausaLonga(FLOW, 10)).toBeFalse();
      expect(ehPausaLonga(null, 10)).toBeFalse();
    });
  });
});
