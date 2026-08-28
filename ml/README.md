# Trilha ML — extração de features do DAiSEE e Random Forest baseline

Tickets [1 e 2](../tickets.md). Dois pipelines offline, rodados à mão fora da aplicação: um transforma os vídeos do DAiSEE num dataset tabular, o outro treina e avalia o Random Forest cujo artefato o backend carrega na ticket 8.

Este diretório tem ambiente próprio, separado do backend. MediaPipe, OpenCV e scikit-learn somam centenas de MB e nada disso precisa entrar na imagem Docker do FastAPI — o backend consome apenas o `.joblib` resultante.

## Estado

Os dois pipelines já rodaram ponta a ponta contra o DAiSEE real (18/08/2026).

A extração processou **8570 clipes** — os 8570 que pareiam vídeo em disco com linha de rótulo, de um total de 9067 vídeos — produzindo **514.850 linhas de frame**, sem nenhuma falha de leitura. O treino produziu o `.joblib`, o `relatorio.md` e o `relatorio.json`.

**A meta de 80% não foi atingida, e a evidência é de que ela não é alcançável com estas features.** Ver [O resultado do baseline](#o-resultado-do-baseline).

## Setup

```bash
uv venv ml/.venv --python 3.11
uv pip install --python ml/.venv/bin/python -r ml/requirements.txt
```

Python 3.11 não é capricho: o `mediapipe` 0.10 não publica wheel para o 3.9 do sistema.

## Obtendo o dataset

O DAiSEE (~2.7 GB) não é redistribuível e exige preencher o formulário de acesso do IIIT Hyderabad. Depois de baixado e descompactado, a árvore precisa estar no formato original:

```
<raiz>/
  DataSet/
    Train/<user_id>/<clip_id>/<clip_id>.avi
    Validation/...
    Test/...
  Labels/
    TrainLabels.csv        ClipID,Boredom,Engagement,Confusion,Frustration
    ValidationLabels.csv
    TestLabels.csv
```

`dados/` e `artefatos/` não são versionados.

## Rodando

### 1. Extrair features

```bash
cd ml && .venv/bin/python extrair_features.py --raiz ~/datasets/DAiSEE
```

Produz `dados/frames.parquet` e `dados/clipes.parquet`. São ~9 mil clipes de 10s: conte horas, não minutos. Comece com `--limite 20` para conferir que a árvore está no formato certo antes de deixar rodando.

A execução grava em shards a cada 50 clipes e **retoma de onde parou** — rodar o mesmo comando de novo pula o que já foi extraído. `--recomecar` ignora os shards; `--so-consolidar` monta os parquets a partir do que já existe, útil para inspecionar uma extração parcial.

`--amostragem N` processa 1 frame a cada N (padrão 5, ou seja ~6 fps). Piscadas duram ~100 ms e ainda aparecem nessa taxa; `--amostragem 1` processa tudo, a um custo cinco vezes maior.

### 2. Treinar

```bash
cd ml && .venv/bin/python treinar.py
```

Produz `artefatos/random_forest.joblib` (o pipeline inteiro, com imputação, mais a ordem das features e a versão do sklearn), `artefatos/relatorio.md` e `artefatos/relatorio.json`.

Sai com código 1 se a meta de precisão não for atingida **e** `--exigir-meta` for passado — o relatório é gravado de qualquer forma, já que é justamente ele que explica a falha.

## O resultado do baseline

A ticket 2 admite "meta atingida **ou** desvio justificado no relatório". Este é o desvio, com o que foi feito para descartar as explicações baratas antes de aceitá-lo.

O baseline (`engagement`, corte `>= 2`) deu **0,4753 de precisão macro no `Test`**, com 0,9501 de acurácia. Os dois números juntos contam a história: a floresta previu "engajado" em 1783 dos 1784 clipes do `Test`. Ela não aprendeu a reconhecer engajamento — aprendeu que quase todo clipe do DAiSEE é engajado. A acurácia de 95% é o retrato de um modelo que não faz nada, e é exatamente por isso que a meta é medida em macro.

O `Train` deu 1,0000 em tudo. Isso é memorização: 300 árvores sem limite de profundidade decoram 5357 linhas de 39 colunas sem esforço. Duas hipóteses explicariam o desvio, e elas pedem ações opostas — ou o modelo está sobreajustado e falta regularizar, ou o sinal não está nas features. Foram testadas:

| Configuração | Precisão macro (Test) |
| --- | --- |
| `engagement`, corte `>= 2` (baseline) | 0,4753 |
| `engagement`, corte `>= 2`, `max_depth=10` | 0,5815 |
| `engagement`, corte `>= 3` (classes ~54/46) | 0,6003 |
| `engagement`, corte `>= 3`, qualquer regularização testada | 0,57–0,60 |
| `engagement`, multiclasse 0–3 | 0,3646 |
| `boredom`, corte `>= 2` | **0,6748** |
| `confusion`, corte `>= 2` | 0,4560 |
| `frustration`, corte `>= 2` | 0,4776 |

**Regularizar ajuda onde o desbalanceamento é extremo e não ajuda onde ele não é.** No corte `>= 2` (95/5), limitar a profundidade tira o modelo do colapso na classe majoritária e leva de 0,4753 a 0,5815. No corte `>= 3` (54/46), onde não há colapso a corrigir, nenhuma combinação de `max_depth`, `min_samples_leaf` e `max_features` passou de 0,60 — o `Train` cai de 1,00 para 0,69 e o `Test` não se mexe. Um modelo sobreajustado melhora quando é contido; este não melhora, o que significa que o teto não é o sobreajuste.

O teto sobre todos os alvos e configurações testadas é **~0,67**. A meta de 80% do pré-projeto foi definida antes de existir qualquer medição e não sobrevive ao contato com o dataset — pelo menos não com features agregadas por clipe e split subject-independent.

Três coisas que o desvio **não** é:

**Não é vazamento nem erro de split.** Fosse vazamento, o número subiria, não cairia. `verifica_independencia_de_sujeito` roda a cada treino e falha alto se um `user_id` aparecer em dois splits.

**Não é falta de dados.** São 8570 clipes, o dataset inteiro, com 0 falhas de extração.

**Não é escolha de hiperparâmetro.** Sete configurações foram testadas nos dois cortes; a variação entre a melhor e a pior é menor que a distância até a meta.

**Não é o limiar de decisão.** Esta merece detalhe, porque é a alavanca que mexe diretamente em precisão e é a primeira coisa que alguém vai perguntar na banca. Precisão e recall trocam entre si: um modelo que só arrisca "não engajado" quando está muito confiante acerta uma fração maior dos palpites que dá. Foi testada uma varredura de limiar de 0,05 a 0,99, escolhendo o valor no `Validation` e aplicando ao `Test` — escolher olhando o próprio `Test` seria ajustar ao gabarito.

| Alvo | Limiar escolhido no `Validation` → `Test` | Teto olhando o próprio `Test` |
| --- | --- | --- |
| `engagement` ≥ 2 | 0,4753 | 0,6248 |
| `engagement` ≥ 3 | 0,6034 | 0,7283 |
| `boredom` ≥ 2 | 0,6450 | 0,6748 |

A coluna da direita é deliberadamente desonesta e existe só para fechar a pergunta "existe *algum* limiar que chegue lá?". Não existe: o máximo é 0,7283, ainda abaixo da meta.

E esse 0,7283 é pior do que o número sugere — vem de **uma única predição** de "não engajado" em 970 casos reais. O mesmo efeito aparece no protocolo honesto: no corte ≥ 2, o limiar escolhido no `Validation` marcava 0,9422 de precisão macro lá, com um único palpite de classe 0 que por sorte estava certo; aplicado ao `Test`, virou 0,0000. É por isso que a varredura reporta **quantos palpites** o modelo dá junto com a precisão. Precisão alta sobre 1 predição é tamanho de amostra, não habilidade.

Fica o registro de uma armadilha para quem retomar isto: **precisão macro é uma meta que se pode atingir calando a boca.** Em todos os experimentos, o ganho de precisão veio de o modelo parar de arriscar — no melhor caso do corte ≥ 2 ele sinaliza 11% dos casos reais de desengajamento; no do corte ≥ 3, 0,1%. Um IEE que só avisa quando tem certeza quase absoluta cumpriria a métrica do pré-projeto e falharia no propósito do produto. Qualquer número de precisão que aparecer daqui para frente precisa vir com o recall ao lado.

**Não é o Random Forest.** Oito famílias de classificador foram testadas sobre as mesmas 39 features (`ExtraTrees`, `HistGradientBoosting` em duas configurações, regressão logística, floresta regularizada, e dois classificadores triviais como piso). Nenhuma muda a ordem de grandeza. O que elas revelam é pior que isso — ver abaixo.

**Não é a falta de features temporais.** Foram construídas 22 features que dependem da ordem dos frames e que nenhuma agregação recupera: maior sequência consecutiva de pálpebra fechada, número de episódios de fechamento separados em curtos (piscada) e longos (sonolência), duração e contagem de bocejos, maior sequência de olhar desviado, variação média entre frames vizinhos (inquietação), inclinação da reta ao longo do clipe (cabeça caindo) e número de inversões de direção do movimento. Resultado:

| Conjunto de features | `engagement` ≥ 2 | `engagement` ≥ 3 | `boredom` ≥ 2 |
| --- | --- | --- | --- |
| 39 agregadas (baseline) | 0,4753 | **0,6003** | **0,6748** |
| 22 temporais | 0,4753 | 0,5656 | 0,5960 |
| 61 combinadas | 0,4753 | 0,5742 | 0,5617 |

Não ajudam, e combinadas chegam a piorar. Com 61 colunas e split por sujeito, features extras dão à floresta mais formas de decorar pessoas. Vale a ressalva honesta: isto refuta *estas* 22 features, não a hipótese temporal inteira — um modelo de sequência de verdade (LSTM/GRU) opera sobre a série, não sobre resumos dela, e o spec já adiou essa comparação para o TC2.

## A meta de 80% é alcançável — e é isso que há de errado com ela

O achado mais importante desta trilha não é um modelo, é sobre a métrica.

**O baseline empata com um classificador constante.** No `engagement` ≥ 2, a floresta marca 0,4753 de precisão macro. Um `DummyClassifier` que responde "engajado" sem olhar para as features marca **0,4753**. São o mesmo número porque são o mesmo comportamento.

**E a meta é atingível varrendo o limiar.** Com `ExtraTrees` no `engagement` ≥ 2:

| Limiar | Precisão macro | Recall da classe 0 | Palpites de "não engajado" | Acertos |
| --- | --- | --- | --- | --- |
| 0,40 | **0,8511** | 0,0341 | 4 | 3 |
| 0,50 | 0,7761 | 0,0341 | 5 | 3 |
| 0,70 | 0,6131 | 0,0682 | 22 | 6 |
| 0,90 | 0,5319 | 0,3864 | 336 | 34 |
| melhor possível (0,24) | **0,9756** | 0,0114 | 1 | 1 |

O modelo de 0,8511 — que **cumpre a Definition of Done do plano de sprints** — arrisca quatro palpites em 88 casos reais de desengajamento e ignora os outros 85. O de 0,9756 dá um palpite. A precisão sobe monotonicamente conforme o modelo cala a boca, porque precisão só pergunta "dos palpites que você deu, quantos estavam certos?" e nunca "quantos você deixou de dar".

Um IEE assim passaria na métrica do pré-projeto e falharia inteiramente no propósito do produto, que é perceber a perda de foco. **A recomendação é trocar a meta, não o modelo.**

### O que medir no lugar

Métricas que não se deixam satisfazer pelo silêncio, com o melhor valor obtido em cada configuração:

| Configuração | F1 macro | Acurácia balanceada |
| --- | --- | --- |
| Trivial (majoritária), `engagement` ≥ 2 | 0,4874 | 0,5000 |
| RF baseline, `engagement` ≥ 2 | 0,4872 | 0,4997 |
| **RF regularizado** (`max_depth=8`, `min_samples_leaf=20`), `engagement` ≥ 2 | **0,5592** | 0,6105 |
| Regressão logística, `engagement` ≥ 2 | 0,4801 | **0,6479** |
| RF regularizado, `boredom` ≥ 2 | 0,5715 | 0,6124 |
| HistGB regularizado, `boredom` ≥ 2 | 0,5702 | **0,6336** |

Duas leituras que valem a defesa. A primeira: o baseline entregue (`RandomForest` sem regularização) é a **pior** escolha disponível para o alvo padrão — fica abaixo do trivial em F1 macro. Regularizar leva a acurácia balanceada de 0,4997 para 0,6105, e a regressão logística chega a 0,6479 detectando 61% dos casos de desengajamento. Em precisão essas opções parecem piores; em utilidade, são incomparavelmente melhores.

A segunda: **~0,61–0,65 de acurácia balanceada é o resultado honesto deste trabalho.** Acima do acaso, longe de resolvido, e coerente com a dificuldade conhecida do DAiSEE. É esse número que sustenta uma defesa, não um 0,85 comprado com silêncio.

Para a ticket 8 vale registrar que **`boredom` é o rótulo mais aprendível dos quatro** (0,6748 de precisão macro; 0,6336 de acurácia balanceada com HistGB regularizado). Faz sentido: tédio tem manifestação comportamental mais direta que engajamento, e é o mais próximo do que o fator de fadiga tenta capturar.

## O detector de bocejo não dispara

Achado colateral da trilha temporal, e é um problema de produto, não de métrica.

`LIMIAR_BOCA_ABERTA = 0,60` classifica **21 frames em 514.757**, distribuídos em **7 clipes de 8570**. A docstring de `metricas.py` calibra a escala como "boca fechada ~0,02; bocejo escancarado passa de 0,8", mas o observado é bem mais baixo:

| Percentil do MAR | Valor |
| --- | --- |
| p50 | 0,0036 |
| p99 | 0,2026 |
| p99,9 | 0,2884 |
| máximo do dataset | 0,7460 |

Nenhum frame em ~24 horas de vídeo alcança o 0,8 documentado. As consequências são duas: `prop_boca_aberta` é uma feature morta — zero em 99,9% dos clipes, sem poder discriminante nenhum — e a detecção de bocejo da ticket 8 **nunca dispararia em produção**, já que o frontend reimplementa a mesma fórmula e o mesmo limiar.

O limiar precisa de recalibração empírica antes da ticket 8 entrar; algo entre 0,25 e 0,30 é o que a distribuição comporta. A Sprint 11 já reserva tempo para recalibrar thresholds de fadiga — este é o primeiro da fila. Fica em aberto se a diferença de escala vem da escolha dos três pares verticais do contorno interno ou se o DAiSEE simplesmente tem poucos bocejos francos; separar as duas coisas pede inspeção visual de alguns dos 84 clipes com MAR > 0,30.

## Decisões que valem a defesa

**O split é o do próprio DAiSEE, não um `train_test_split` aleatório.** O dataset já vem particionado por sujeito: nenhum `user_id` aparece em dois splits. Embaralhar aleatoriamente colocaria o mesmo rosto no treino e no teste, e o modelo passaria a reconhecer a pessoa em vez do engajamento. A métrica subiria sem o modelo ter melhorado — e o sintoma do vazamento é uma métrica *boa*, que ninguém investiga. `treino.verifica_independencia_de_sujeito` falha alto se a propriedade for violada.

**A meta de 80% é medida sobre a precisão macro no `Test`.** Cerca de 85% dos clipes do DAiSEE são "engajado"; um modelo que responde sempre "engajado" já tira ~85% de acurácia e de precisão ponderada sem ter aprendido nada. A macro pondera as duas classes igualmente, então não dá para atingi-la por sorte de distribuição. O relatório mostra as três lado a lado.

**São dois artefatos tabulares, não um.** `frames.parquet` tem uma linha por frame — o critério da ticket 1 pede EAR/Head Pose/MAR por frame, e a ticket 8 precisa da sequência temporal para detectar pálpebra fechada prolongada e bocejo, coisa que a média por clipe apaga. `clipes.parquet` tem uma linha por clipe com 39 features agregadas e os quatro rótulos, e é o que o Random Forest treina, porque o DAiSEE rotula por clipe.

**Ausência de rosto é NaN, nunca 0.** Um EAR zerado é indistinguível de um olho de fato fechado. As linhas de frame sem rosto continuam existindo (senão `prop_frames_com_rosto` mentiria), e a imputação vive dentro do `Pipeline` do sklearn, com a mediana aprendida só no `Train` — o backend não pode ser obrigado a saber imputar.

## Organização

```
esquema.py            contrato de colunas entre extração e treino; os dois lados importam daqui
daisee.py             layout em disco do DAiSEE, CSVs de rótulo, e o join entre os dois
metricas.py           matemática pura de EAR/MAR/head pose sobre os 468 landmarks
extracao.py           vídeo → uma linha por frame, com o detector injetado
agregacao.py          frames → uma linha por clipe, e o join com os rótulos
treino.py             Random Forest, splits, serialização do artefato
relatorio.py          métricas, matriz de confusão, Markdown e JSON
extrair_features.py   CLI da ticket 1
treinar.py            CLI da ticket 2
```

`metricas.py` é a referência de implementação para o frontend: as mesmas fórmulas e os mesmos índices do Face Mesh são reimplementados em TypeScript na ticket 5, e a docstring do módulo documenta os índices e a convenção de sinal dos ângulos para isso.

O detector de landmarks entra em `extracao.py` como dependência injetada, não como import rígido. É o que permite testar a extração com vídeos sintéticos e um detector falso, sem depender do MediaPipe nem do dataset.

## Testes

```bash
cd ml && .venv/bin/python -m pytest
```

168 testes, todos sobre dados sintéticos — árvores DAiSEE montadas em `tmp_path`, vídeos gerados com `cv2.VideoWriter`, landmarks construídos à mão e datasets de clipes com sinal plantado de propósito. Nenhum depende do dataset real, então a suíte roda em segundos numa máquina limpa.

Os testes de `tests/test_integracao.py` exercitam os dois CLIs ponta a ponta, incluindo a retomada de uma extração interrompida e o round-trip do artefato pelo disco.
