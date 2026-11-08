/**
 * Objetivo de estudo (RF04). Os mesmos três valores de `backend/app/objetivo.py`:
 * cada um dispara uma linha diferente da regra de recomendação (RF17).
 */
export type Objetivo = 'prova' | 'vestibular' | 'pessoal';

export const OBJETIVOS: readonly { codigo: Objetivo; nome: string }[] = [
  { codigo: 'prova', nome: 'Prova específica' },
  { codigo: 'vestibular', nome: 'Vestibular' },
  { codigo: 'pessoal', nome: 'Estudo pessoal' },
];
