# CPU no cliente — sessão 28 (versão final, build `f2b675e`)

22/11/2026, 21:59–22:14 (horário de Brasília), Microsoft Edge 157, notebook Acer Aspire A515-45
(AMD Ryzen 7 5700U, 16 núcleos lógicos). Gravação da mesma sessão: `sessao-versao-final.json`.

Coluna **CPU** do Gerenciador de Tarefas do navegador (Shift+Esc, aba "All tasks"), anotada à mão
uma vez por minuto, depois da calibração. Nessa coluna, 100 = um núcleo lógico inteiro.

| Minuto | Aba do MapFace | Processo de GPU | Câmera (Video Capture) |
| ---: | ---: | ---: | ---: |
| 1 | 60,3 | 61,0 | 6,0 |
| 2 | 58,0 | 60,0 | 6,2 |
| 3 | 57,4 | 60,5 | 6,2 |
| 4 | 59,7 | 60,3 | 6,3 |
| 5 | 57,4 | 60,8 | 6,3 |
| 6 | 57,1 | 60,0 | 6,2 |
| 7 | 58,1 | 60,3 | 6,2 |
| 8 | 57,4 | 60,5 | 6,3 |
| 9 | 57,1 | 60,0 | 6,2 |
| 10 | 57,0 | 60,3 | 6,2 |
| 11 | 57,4 | 60,8 | 6,3 |
| 12 | 57,1 | 60,0 | 6,2 |
| 13 | 58,1 | 60,3 | 6,2 |
| 14 | 57,1 | 60,0 | 6,2 |
| 15 | 57,1 | 60,0 | 6,2 |
| **Média** | **57,8** | **60,3** | **6,2** |

## Contra a meta (Tabela 9: até 25% do processador, em média, somando a aba e o processo de GPU)

- Soma média aba + GPU: 118,1 (de um núcleo) → 118,1 ÷ 16 núcleos lógicos = **7,4% do processador**.
- Pior minuto: 121,3 → 7,6%.
- **Meta atendida.** O limite equivale a 400 na soma (25% × 16).
- O processo da câmera não integra o critério; somado, o total chegaria a 7,8%.
- Na sessão 10 (08/11, build `f04a533`), só a aba foi medida: 57,4 → 3,6%.
