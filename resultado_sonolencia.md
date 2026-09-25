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
| arvores_extremamente_aleatorias | participante | nao (teto) | binario | 0.7366 | 0.0571 | 0.7332 | 1, 3 | - |
| floresta_regularizada | participante | nao (teto) | binario | 0.7318 | 0.0578 | 0.7294 | 1, 3 | - |
| floresta_baseline | participante | nao (teto) | binario | 0.725 | 0.0495 | 0.7236 | 1, 3 | - |
| regressao_logistica | participante | nao (teto) | binario | 0.7224 | 0.0608 | 0.7195 | 1, 3 | - |
| gradiente_histograma | participante | nao (teto) | binario | 0.6924 | 0.0348 | 0.6912 | 1, 3 | - |
| arvores_extremamente_aleatorias | nenhuma | sim | binario | 0.6688 | 0.0134 | 0.6638 | 3, 1 | - |
| regressao_logistica | nenhuma | sim | binario | 0.6622 | 0.0237 | 0.6535 | 1, 3 | - |
| arvores_extremamente_aleatorias | sessao | sim | binario | 0.6553 | 0.018 | 0.6425 | 1, 2 | - |
| floresta_regularizada | sessao | sim | binario | 0.6507 | 0.0316 | 0.6468 | 4, 2 | - |
| floresta_baseline | sessao | sim | binario | 0.6456 | 0.0186 | 0.643 | 4, 3 | - |
| floresta_baseline | nenhuma | sim | binario | 0.6449 | 0.0291 | 0.6426 | 2, 4 | - |
| floresta_regularizada | nenhuma | sim | binario | 0.6441 | 0.0155 | 0.64 | 2, 4 | - |
| gradiente_histograma | sessao | sim | binario | 0.6415 | 0.0254 | 0.6396 | 3, 4 | - |
| gradiente_histograma | nenhuma | sim | binario | 0.6218 | 0.0241 | 0.6199 | 2, 5 | - |
| regressao_logistica | sessao | sim | binario | 0.5538 | 0.0656 | 0.5502 | 1, 4 | - |
| chute_majoritario | participante | nao (teto) | binario | 0.5 | 0.0 | 0.3303 | 1, 2 | - |
| chute_majoritario | sessao | sim | binario | 0.5 | 0.0 | 0.3303 | 1, 2 | - |
| chute_majoritario | nenhuma | sim | binario | 0.5 | 0.0 | 0.3303 | 1, 2 | - |

O `chute_majoritario` é o chão: ele ignora a entrada. Qualquer configuração que não o supere com folga está dizendo que o sinal não está nas features.

**A coluna `reproduzivel` é a que decide o que vai para produção.** A normalização `participante` usa as três gravações da pessoa para definir o que é normal nela — inclusive as que, do ponto de vista de uma sessão em curso, ainda não aconteceram. Ela fica na grade como **teto**: a distância entre ela e a `sessao` é exatamente o que se perde por só poder olhar para o passado. O artefato salvo nunca vem dela.

Medido nesta execução: o teto fica em 0.7366 e o melhor reproduzível em 0.6688 — uma diferença de 0.0678. É o preço de calibrar com o passado, e ele é o mesmo que o produto paga: um aluno que senta já cansado calibra cansado.

## A configuração escolhida

`arvores_extremamente_aleatorias`, normalização `sessao`, alvo `binario`.

Escolhida entre as reproduzíveis em produção. **Empate técnico é decidido pela robustez a câmera, não pela terceira casa decimal:** a validação cruzada mede desempenho dentro do UTA-RLDD, onde todo mundo gravou de celular, e é estruturalmente incapaz de medir a única transposição que o produto precisa fazer — para a webcam de um aluno, noutra distância e noutra lente. A comparação de domínio abaixo mede isso, e entre configurações a menos de um desvio-padrão de distância vence a que calibra por sessão.

**O modelo encontra sinal.** Acurácia balanceada de 0.6553 ± 0.0180 entre os cinco folds, contra 0.50 de um classificador que ignora a entrada. O pior fold fica acima do chão, então o resultado não depende de qual grupo de participantes caiu no teste.

### Por fold

| fold | n_treino | n_teste | acuracia_balanceada | f1_macro |
| --- | --- | --- | --- | --- |
| 1 | 6104 | 1424 | 0.6248 | 0.6036 |
| 2 | 6041 | 1487 | 0.6472 | 0.6457 |
| 3 | 5991 | 1537 | 0.6735 | 0.6725 |
| 4 | 6020 | 1508 | 0.6589 | 0.6532 |
| 5 | 5956 | 1572 | 0.6721 | 0.6376 |

### Métricas no pior fold (1)

O pior fold, e não a média: é ele que diz o que acontece quando o grupo de participantes do teste é o mais desfavorável dos cinco.

| classe | precisao | recall | f1 | suporte |
| --- | --- | --- | --- | --- |
| alerta | 0.5917 | 0.8658 | 0.703 | 723 |
| sonolento | 0.735 | 0.3837 | 0.5042 | 701 |
| **macro** | 0.6633 | 0.6248 | 0.6036 | 1424 |

| verdadeiro \ previsto | alerta | sonolento |
| --- | --- | --- |
| **alerta** | 626 | 97 |
| **sonolento** | 432 | 269 |

## Os outros alvos

| modelo | normalizacao | reproduzivel | alvo | acuracia_balanceada | desvio_entre_folds | f1_macro | piores_folds | folds_ignorados |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| arvores_extremamente_aleatorias | sessao | sim | binario | 0.6553 | 0.018 | 0.6425 | 1, 2 | - |
| arvores_extremamente_aleatorias | sessao | sim | binario_amplo | 0.6054 | 0.0198 | 0.5622 | 4, 3 | - |
| arvores_extremamente_aleatorias | sessao | sim | ternario | 0.4188 | 0.0327 | 0.3962 | 1, 4 | - |

`binario` separa sonolento de alerta e descarta a vigilância baixa — é o corte dos autores e o mais usado na literatura. `binario_amplo` joga a fronteira para dentro do estado ambíguo e é mais próximo do que o produto quer penalizar: deixar de estar alerta, não dormir.

## De onde vem o sinal

| conjunto | n_features | acuracia_balanceada | desvio_entre_folds |
| --- | --- | --- | --- |
| so_derivadas | 4 | 0.6768 | 0.029 |
| sem_cabeca | 24 | 0.6571 | 0.0175 |
| todas | 39 | 0.6553 | 0.018 |
| so_olhos | 15 | 0.6211 | 0.0267 |
| so_boca | 5 | 0.5118 | 0.0116 |
| so_cabeca | 15 | 0.4759 | 0.0331 |

### Importância das features

| feature | importancia |
| --- | --- |
| prop_olhos_fechados | 0.1304 |
| ear_min | 0.063 |
| ear_media | 0.0596 |
| ear_esq_min | 0.0551 |
| ear_dir_min | 0.0545 |
| ear_mediana | 0.0504 |
| ear_desvio | 0.0444 |
| ear_dir_mediana | 0.0376 |
| ear_esq_mediana | 0.0375 |
| ear_esq_media | 0.0354 |
| ear_dir_media | 0.0325 |
| ear_dir_desvio | 0.032 |
| ear_esq_desvio | 0.0316 |
| ear_max | 0.0235 |
| mar_max | 0.0235 |

## Os dois datasets juntos

8570 clipes do DAiSEE e 7528 janelas do UTA-RLDD, com as mesmas 39 features.

### Quanto os domínios diferem

O DAiSEE é webcam de notebook a 640x480; o UTA-RLDD é celular em HD. Se as features separarem os datasets mais do que separam as pessoas dentro de cada um, qualquer transferência falha por motivo de câmera, não de comportamento. `d_de_cohen` acima de ~0,8 é onde isso começa a doer.

As cinco features mais deslocadas, em valor absoluto:

| feature | daisee_media | rldd_media | daisee_desvio | rldd_desvio | d_de_cohen |
| --- | --- | --- | --- | --- | --- |
| n_frames | 10.0384 | 10.7355 | 0.1921 | 0.4411 | 2.0492 |
| pitch_media | 13.0738 | -4.0295 | 17.172 | 14.9156 | 1.0634 |
| pitch_mediana | 12.7934 | -4.1521 | 17.7207 | 15.1 | 1.0293 |
| pitch_max | 22.767 | 1.5696 | 23.3806 | 18.332 | 1.009 |
| pitch_min | 4.636 | -9.2113 | 14.2477 | 14.4749 | 0.9642 |

E depois de medir cada pessoa contra ela mesma:

| feature | daisee_media | rldd_media | daisee_desvio | rldd_desvio | d_de_cohen |
| --- | --- | --- | --- | --- | --- |
| n_frames | 0.0 | -0.1658 | 0.0 | 0.433 | 0.5415 |
| prop_olhos_fechados | 0.0239 | 0.0802 | 0.1177 | 0.2314 | 0.307 |
| ear_media | -0.001 | -0.0073 | 0.0192 | 0.0363 | 0.217 |
| ear_mediana | -0.0012 | -0.0076 | 0.0197 | 0.0377 | 0.2114 |
| ear_min | -0.0032 | -0.0114 | 0.0295 | 0.0514 | 0.1941 |

### Transferência: o modelo de sonolência aplicado ao DAiSEE

O DAiSEE **não tem rótulo de sonolência** — ninguém perguntou aos anotadores se a pessoa estava com sono. Então isto não é acurácia: é a pergunta de se duas leituras independentes do mesmo rosto, um modelo treinado noutro dataset e um humano marcando tédio, apontam para o mesmo lado.

| clipes | auc_vs_tedio | auc_vs_desengajamento | sonolencia_prevista_entediado | sonolencia_prevista_nao_entediado |
| --- | --- | --- | --- | --- |
| 8570 | 0.5255 | 0.6142 | 0.4652 | 0.4515 |

AUC de 0,50 é moeda. Acima disso há concordância, e ela não pode vir de ajuste ao DAiSEE: o modelo nunca viu uma linha dele.

As features do DAiSEE entram centradas na mediana de cada usuário — o análogo mais próximo da calibração por sessão que este dataset permite, já que ele agrupa clipes por pessoa e não por sessão. Alimentar o modelo com valores absolutos devolveria um número plausível e errado, e não um erro visível.

### Treino conjunto

Os dois datasets empilhados sob um alvo compartilhado de **baixo alerta**, com cada um avaliado no seu próprio teste — os mesmos sujeitos nas duas medições, fora de todos os treinos.

| avaliado_em | n_teste | treinado_so_nele | treinado_nos_dois | ganho |
| --- | --- | --- | --- | --- |
| daisee | 1439 | 0.5543 | 0.5471 | -0.0073 |
| rldd | 1501 | 0.7508 | 0.6988 | -0.052 |

**Sonolência e desengajamento não são a mesma coisa.** Empilhar os dois é uma aposta explícita de que os estados compartilham assinatura facial suficiente. O `ganho` é o veredito: positivo, ver o outro dataset ajudou; negativo, atrapalhou.

## Limitações

1. **O rótulo é por gravação.** Toda janela de um vídeo `10` conta como sonolenta, inclusive as em que a pessoa está claramente acordada. O teto de acurácia mede isso junto com a dificuldade real.
2. **A calibração por sessão é cega a estado constante.** A baseline sai das primeiras seis janelas da própria gravação; se a pessoa já começa sonolenta, a baseline é de uma pessoa sonolenta. É a mesma cegueira que o produto tem com um aluno que senta exausto — e a alternativa, comparar contra constante igual para todos, é o que a ticket 7 recusa.
3. **Sonolência não é desengajamento.** O modelo aqui responde sobre estado físico. Usá-lo como medida de engajamento seria afirmar o que ele não mede.
4. **60 participantes.** É o que o dataset tem. O desvio entre folds é o intervalo de confiança honesto do número, e está na tabela.
