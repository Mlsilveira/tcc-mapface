# Classificador de sonolência — UTA-RLDD

Relatório gerado por `treinar_fadiga.py`. Todos os números vêm de validação cruzada nos cinco folds oficiais do dataset, disjuntos por participante: nenhuma pessoa aparece no treino e no teste da mesma medição.

## O dataset

| janelas | participantes | gravacoes | segundos_por_janela |
| --- | --- | --- | --- |
| 11279 | 60 | 180 | 10 |

Distribuição por estado declarado:

| estado | janelas |
| --- | --- |
| 0 | 3720 |
| 5 | 3751 |
| 10 | 3808 |

**O rótulo é da gravação inteira, e a janela herda.** Ninguém fica sonolento em todos os segundos de dez minutos, então uma janela de um vídeo `10` pode mostrar a pessoa acordada. É ruído de rótulo inerente ao dataset, e é a primeira coisa que explica um teto de acurácia.

## A grade de experimentos

| modelo | normalizacao | reproduzivel | alvo | acuracia_balanceada | desvio_entre_folds | f1_macro | piores_folds | folds_ignorados |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| arvores_extremamente_aleatorias | participante | nao (teto) | binario | 0.7432 | 0.0544 | 0.7406 | 1, 3 | - |
| floresta_regularizada | participante | nao (teto) | binario | 0.7398 | 0.0584 | 0.7378 | 1, 3 | - |
| floresta_baseline | participante | nao (teto) | binario | 0.7242 | 0.0592 | 0.7231 | 1, 3 | - |
| regressao_logistica | participante | nao (teto) | binario | 0.7103 | 0.0671 | 0.7086 | 3, 1 | - |
| gradiente_histograma | participante | nao (teto) | binario | 0.6818 | 0.0543 | 0.6811 | 1, 3 | - |
| arvores_extremamente_aleatorias | nenhuma | sim | binario | 0.6703 | 0.0204 | 0.6668 | 2, 1 | - |
| regressao_logistica | nenhuma | sim | binario | 0.6643 | 0.0402 | 0.6586 | 1, 5 | - |
| floresta_regularizada | nenhuma | sim | binario | 0.6564 | 0.0105 | 0.653 | 4, 5 | - |
| floresta_baseline | nenhuma | sim | binario | 0.6526 | 0.0152 | 0.6496 | 4, 5 | - |
| gradiente_histograma | nenhuma | sim | binario | 0.6506 | 0.0249 | 0.648 | 2, 5 | - |
| floresta_regularizada | sessao | sim | binario | 0.6437 | 0.0238 | 0.6393 | 4, 3 | - |
| arvores_extremamente_aleatorias | sessao | sim | binario | 0.6397 | 0.0223 | 0.6262 | 1, 4 | - |
| floresta_baseline | sessao | sim | binario | 0.6296 | 0.0257 | 0.6277 | 4, 5 | - |
| gradiente_histograma | sessao | sim | binario | 0.6186 | 0.0289 | 0.6173 | 4, 5 | - |
| regressao_logistica | sessao | sim | binario | 0.5459 | 0.0471 | 0.5398 | 1, 5 | - |
| chute_majoritario | participante | nao (teto) | binario | 0.5 | 0.0 | 0.3303 | 1, 2 | - |
| chute_majoritario | sessao | sim | binario | 0.5 | 0.0 | 0.3303 | 1, 2 | - |
| chute_majoritario | nenhuma | sim | binario | 0.5 | 0.0 | 0.3303 | 1, 2 | - |

O `chute_majoritario` é o chão: ele ignora a entrada. Qualquer configuração que não o supere com folga está dizendo que o sinal não está nas features.

**A coluna `reproduzivel` é a que decide o que vai para produção.** A normalização `participante` usa as três gravações da pessoa para definir o que é normal nela — inclusive as que, do ponto de vista de uma sessão em curso, ainda não aconteceram. Ela fica na grade como **teto**: a distância entre ela e a `sessao` é exatamente o que se perde por só poder olhar para o passado. O artefato salvo nunca vem dela.

Medido nesta execução: o teto fica em 0.7432 e o melhor reproduzível em 0.6703 — uma diferença de 0.0730. É o preço de calibrar com o passado, e ele é o mesmo que o produto paga: um aluno que senta já cansado calibra cansado.

## A configuração escolhida

`arvores_extremamente_aleatorias`, normalização `nenhuma`, alvo `binario`. É a melhor entre as reproduzíveis em produção.

**O modelo encontra sinal.** Acurácia balanceada de 0.6703 ± 0.0204 entre os cinco folds, contra 0.50 de um classificador que ignora a entrada. O pior fold fica acima do chão, então o resultado não depende de qual grupo de participantes caiu no teste.

### Por fold

| fold | n_treino | n_teste | acuracia_balanceada | f1_macro |
| --- | --- | --- | --- | --- |
| 1 | 6104 | 1424 | 0.6584 | 0.6458 |
| 2 | 6041 | 1487 | 0.6584 | 0.6551 |
| 3 | 5991 | 1537 | 0.6599 | 0.6599 |
| 4 | 6020 | 1508 | 0.7108 | 0.7104 |
| 5 | 5956 | 1572 | 0.6639 | 0.6627 |

### Métricas no pior fold (2)

O pior fold, e não a média: é ele que diz o que acontece quando o grupo de participantes do teste é o mais desfavorável dos cinco.

| classe | precisao | recall | f1 | suporte |
| --- | --- | --- | --- | --- |
| alerta | 0.6963 | 0.5466 | 0.6124 | 730 |
| sonolento | 0.6379 | 0.7701 | 0.6978 | 757 |
| **macro** | 0.6671 | 0.6584 | 0.6551 | 1487 |

| verdadeiro \ previsto | alerta | sonolento |
| --- | --- | --- |
| **alerta** | 399 | 331 |
| **sonolento** | 174 | 583 |

## Os outros alvos

| modelo | normalizacao | reproduzivel | alvo | acuracia_balanceada | desvio_entre_folds | f1_macro | piores_folds | folds_ignorados |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| arvores_extremamente_aleatorias | nenhuma | sim | binario | 0.6703 | 0.0204 | 0.6668 | 2, 1 | - |
| arvores_extremamente_aleatorias | nenhuma | sim | binario_amplo | 0.6215 | 0.0301 | 0.6151 | 3, 2 | - |
| arvores_extremamente_aleatorias | nenhuma | sim | ternario | 0.4764 | 0.0269 | 0.4727 | 2, 3 | - |

`binario` separa sonolento de alerta e descarta a vigilância baixa — é o corte dos autores e o mais usado na literatura. `binario_amplo` joga a fronteira para dentro do estado ambíguo e é mais próximo do que o produto quer penalizar: deixar de estar alerta, não dormir.

## De onde vem o sinal

| conjunto | n_features | acuracia_balanceada | desvio_entre_folds |
| --- | --- | --- | --- |
| so_derivadas | 4 | 0.6832 | 0.0488 |
| todas | 39 | 0.6703 | 0.0204 |
| sem_cabeca | 24 | 0.6528 | 0.0172 |
| so_olhos | 15 | 0.6465 | 0.0129 |
| so_boca | 5 | 0.5086 | 0.0495 |
| so_cabeca | 15 | 0.5079 | 0.0487 |

### Importância das features

| feature | importancia |
| --- | --- |
| prop_olhos_fechados | 0.1224 |
| ear_esq_min | 0.0641 |
| ear_min | 0.0614 |
| ear_media | 0.0548 |
| ear_mediana | 0.0475 |
| ear_dir_mediana | 0.0451 |
| ear_esq_media | 0.0415 |
| ear_dir_min | 0.0405 |
| ear_dir_media | 0.0404 |
| ear_esq_mediana | 0.0382 |
| ear_desvio | 0.0347 |
| n_frames | 0.0327 |
| ear_esq_desvio | 0.0287 |
| ear_dir_desvio | 0.0261 |
| roll_mediana | 0.0238 |

## Limitações

1. **O rótulo é por gravação.** Toda janela de um vídeo `10` conta como sonolenta, inclusive as em que a pessoa está claramente acordada. O teto de acurácia mede isso junto com a dificuldade real.
2. **A calibração por sessão é cega a estado constante.** A baseline sai das primeiras seis janelas da própria gravação; se a pessoa já começa sonolenta, a baseline é de uma pessoa sonolenta. É a mesma cegueira que o produto tem com um aluno que senta exausto — e a alternativa, comparar contra constante igual para todos, é o que a ticket 7 recusa.
3. **Sonolência não é desengajamento.** O modelo aqui responde sobre estado físico. Usá-lo como medida de engajamento seria afirmar o que ele não mede.
4. **60 participantes.** É o que o dataset tem. O desvio entre folds é o intervalo de confiança honesto do número, e está na tabela.
