# Trilha ML — extração de features do DAiSEE e Random Forest baseline

Tickets [1 e 2](../tickets.md). Dois pipelines offline, rodados à mão fora da aplicação: um transforma os vídeos do DAiSEE num dataset tabular, o outro treina e avalia o Random Forest cujo artefato o backend carrega na ticket 8.

Este diretório tem ambiente próprio, separado do backend. MediaPipe, OpenCV e scikit-learn somam centenas de MB e nada disso precisa entrar na imagem Docker do FastAPI — o backend consome apenas o `.joblib` resultante.

## Estado

Os dois pipelines estão implementados e testados, mas **ainda não foram executados contra o DAiSEE real** — o dataset não está baixado. Ver [Obtendo o dataset](#obtendo-o-dataset). Até lá, `artefatos/relatorio.md` não existe e a meta de precisão de 80% da ticket 2 continua sem verificação empírica.

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
