# O treinamento do Random Forest, do começo ao fim

A história completa da trilha de machine learning do MapFace: o que foi tentado,
o que falhou, por que falhou, o que se fez no lugar, e onde o trabalho está
hoje.

É um relato de **três tentativas**. A primeira não funcionou, a segunda abriu
mão do ML, e a terceira trouxe o ML de volta respondendo outra pergunta.

---

## Sumário

1. [O que o pré-projeto prometia](#1-o-que-o-pré-projeto-prometia)
2. [Tentativa 1 — Random Forest no DAiSEE](#2-tentativa-1--random-forest-no-daisee)
3. [A investigação: seis hipóteses testadas](#3-a-investigação-seis-hipóteses-testadas)
4. [O problema da métrica](#4-o-problema-da-métrica)
5. [Tentativa 2 — abrir mão do ML](#5-tentativa-2--abrir-mão-do-ml)
6. [Tentativa 3 — trocar a pergunta](#6-tentativa-3--trocar-a-pergunta)
7. [As armadilhas do caminho](#7-as-armadilhas-do-caminho)
8. [Os dois datasets juntos](#8-os-dois-datasets-juntos)
9. [Onde o trabalho está](#9-onde-o-trabalho-está)

---

## 1. O que o pré-projeto prometia

O `spec-poc-iee.md` dizia, em três lugares:

> "`F` é a penalidade de fadiga vinda da classificação de padrões sequenciais
> atípicos (pálpebras fechadas prolongadas, bocejos) pelo **Random Forest**."

> "`AnalistaEngajamento` **encapsula o modelo Random Forest** (scikit-learn)."

> "Random Forest treinado e validado com o dataset público **DAISEE**."

E a Definition of Done trazia um portão: **precisão acima de 80%**.

Três afirmações e uma meta. O que aconteceu com cada uma está abaixo.

---

## 2. Tentativa 1 — Random Forest no DAiSEE

### 2.1 O pipeline

Dois passos, rodados fora da aplicação:

```
vídeo → MediaPipe → 7 métricas por frame → 39 features por clipe → Random Forest
```

**Extração** (`ml/extrair_features.py`): 8.570 clipes de 10 s pareados com
rótulo, de 9.067 vídeos em disco. **514.850 linhas de frame**, sem nenhuma
falha de leitura. Amostragem de 1 frame a cada 5 (~6 fps) — uma piscada dura
~100 ms e ainda aparece nessa taxa.

**As 39 features:** cinco agregações (média, desvio, mediana, mín, máx) de sete
métricas (EAR esquerdo, direito e médio, MAR, yaw, pitch, roll), mais quatro
derivadas — proporção de frames com rosto, proporção de olhos fechados,
proporção de boca aberta e número de frames.

**Treino** (`ml/treinar.py`): `RandomForestClassifier`, 300 árvores,
`class_weight="balanced"`, imputação por mediana dentro do pipeline,
`random_state=42` em todas as etapas.

### 2.2 O split — e por que ele não foi sorteado

O split é o **do próprio DAiSEE**, lido da estrutura de pastas:

| Split | Amostras |
| --- | --- |
| Train | 5.357 |
| Validation | 1.429 |
| Test | 1.784 |

O particionamento do dataset é *subject-independent*: um mesmo `user_id` nunca
aparece em dois splits. Um `train_test_split` aleatório colocaria clipes da
mesma pessoa nos dois lados, e **a floresta passaria a reconhecer o rosto em vez
do engajamento** — a métrica subiria sem o modelo ter melhorado.

`treino.verifica_independencia_de_sujeito` falha alto se essa propriedade for
violada, porque o sintoma do vazamento é uma métrica *boa*, e métrica boa
ninguém investiga.

### 2.3 O resultado

| Split | Precisão macro | Acurácia |
| --- | --- | --- |
| Train | **1,0000** | 1,0000 |
| Validation | 0,4419 | 0,8838 |
| Test | **0,4753** | **0,9501** |

E a matriz de confusão do `Test`:

| verdadeiro \ previsto | não engajado | engajado |
| --- | --- | --- |
| **não engajado** | **0** | 88 |
| **engajado** | 1 | 1.695 |

**Zero acertos na classe minoritária.** A floresta previu "engajado" em 1.783
dos 1.784 clipes. A acurácia de 95% é o retrato de um modelo que não faz nada:
95% dos clipes do DAiSEE são engajados, então responder sempre a mesma coisa já
dá 95%.

> **O número que define a tentativa 1:** o modelo **empata com um
> `DummyClassifier`**. Os dois marcam 0,4753 de precisão macro e ~0,50 de
> acurácia balanceada.

O `Train` em 1,0000 é memorização pura: 300 árvores sem limite de profundidade
decoram 5.357 linhas de 39 colunas sem esforço.

---

## 3. A investigação: seis hipóteses testadas

Duas explicações rivais pediam ações opostas — ou o modelo estava sobreajustado
e faltava regularizar, ou o sinal não estava nas features. Foram testadas seis
hipóteses antes de aceitar a segunda.

### 3.1 É sobreajuste?

Treze configurações de regularização. No corte desbalanceado, regularizar tira o
modelo do colapso; no corte equilibrado (≥ 3, classes ~54/46), o `Train` cai de
1,00 para 0,69 e **o Test não se mexe** — fica em 0,57–0,60.

> Um modelo sobreajustado melhora quando é contido. Este não melhora.

### 3.2 É o alvo ou o corte?

Quatro rótulos, dois cortes:

| Alvo | Acurácia balanceada |
| --- | --- |
| `engagement`, corte ≥ 2 | 0,4753 |
| `engagement`, corte ≥ 3 | 0,6003 |
| **`boredom`, corte ≥ 2** | **0,6748** |
| `confusion`, corte ≥ 2 | 0,4560 |
| `frustration`, corte ≥ 2 | 0,4776 |

Tédio é o rótulo mais previsível dos quatro — e ainda assim fica em 0,67.

### 3.3 Faltam features temporais?

Foram construídas: duração de fechamento, contagem de piscadas, PERCLOS por
clipe. **O ganho não veio.** E foi aqui que apareceu o achado colateral da
seção 7.1.

### 3.4 É o Random Forest?

Oito famílias de modelo: regressão logística, SVM, gradient boosting, extra
trees, kNN, naive Bayes, MLP. Nenhuma passou de 0,65.

### 3.5 Faltam dados?

A pergunta "outro dataset resolveria?" foi respondida com uma **curva de
aprendizado** por número de sujeitos:

| Sujeitos no treino | Acurácia balanceada |
| --- | --- |
| 7 | ~0,58 |
| 69 | ~0,63 |

**A curva achatou.** Dez vezes mais sujeitos compraram 0,05, e os últimos dez
não compraram nada. Extrapolando log-linearmente, chegar a 0,80 exigiria
**centenas de milhares de sujeitos** — e a extrapolação é otimista, porque
ignora a saturação visível.

### 3.6 Normalização por sujeito — o único ganho real

A causa raiz: as 39 features são valores **absolutos**, e o EAR neutro de cada
pessoa é diferente. A floresta aprende "este é o fulano" antes de aprender
"fulano está desengajado".

| Modelo | Acurácia balanceada |
| --- | --- |
| RF baseline | 0,4997 |
| RF regularizado, features brutas | 0,6350 |
| **RF regularizado + normalização por sujeito** | **0,6572** |

Sair de 0,4997 (equivalente a moeda) para 0,6572 foi o melhor resultado de todo
o esforço — e é legítimo: nenhum rótulo entra no cálculo da mediana, e os
splits são disjuntos por sujeito.

> **E este achado tem um par no produto:** a normalização por sujeito é
> exatamente o que a calibração de 60 segundos da aplicação já fazia ao vivo. O
> offline e o online chegaram à mesma conclusão por caminhos independentes.

---

## 4. O problema da métrica

### 4.1 A meta de 80% é atingível — e é isso que há de errado com ela

Precisão macro não penaliza omissão. Um modelo que **se recusa a responder**
quase sempre pode marcar 0,80 facilmente:

| Estratégia | Previsões feitas | Precisão macro |
| --- | --- | --- |
| Responder tudo | 1.784 | 0,4753 |
| Responder só com alta confiança | 4 | **0,8511** |
| Responder uma vez | 1 | **0,9756** |

**A meta se deixa satisfazer pelo silêncio.** Um modelo que responde em 4 de
1.784 clipes cumpriria a Definition of Done e seria inútil em produção.

### 4.2 O rótulo impõe um teto

Foi medido o teto do próprio rótulo: prever `engagement` a partir dos **outros
três rótulos humanos do mesmo clipe** — boredom, confusion e frustration — dá
**0,7183** de acurácia balanceada.

> É uma estimativa de teto **por proxy**, e vale dizer com precisão o que ela é
> e o que não é: **não é concordância entre anotadores**. O DAiSEE não publica
> as anotações individuais. O que o número diz é que o rótulo é fracamente
> determinado mesmo por informação humana rica sobre o mesmo clipe.

Se informação humana rica só chega a 0,72, exigir 0,80 de features faciais
agregadas é uma meta que descreve mal o problema.

### 4.3 O que se propôs no lugar

Métricas que **não se deixam satisfazer pelo silêncio**:

| Configuração | F1 macro | Acurácia balanceada |
| --- | --- | --- |
| Chute fixo | 0,4874 | 0,5000 |
| RF baseline (entregue) | 0,4872 | 0,4997 |
| RF regularizado | 0,5592 | 0,6105 |
| Regressão logística | 0,4801 | 0,6479 |
| **RF regularizado + normalização** | — | **0,6572** |

**Proposta registrada para a Definition of Done:** substituir *"precisão
superior a 80%"* por ***"acurácia balanceada superior a 0,65, com o recall da
classe minoritária reportado explicitamente"***.

É um alvo que o trabalho atinge, que não se deixa gamificar, e que representa
honestamente a dificuldade do problema.

---

## 5. Tentativa 2 — abrir mão do ML

### 5.1 O raciocínio

Se o modelo empata com um chute fixo, o `F` derivado dele seria **constante** —
e a penalidade de fadiga seria código morto em produção.

Além disso, há uma diferença de natureza entre as duas coisas que estavam sendo
confundidas:

| | Engajamento | Fadiga |
| --- | --- | --- |
| Natureza | construto subjetivo | estado físico observável |
| Teto do rótulo | ~0,72 mesmo com anotação humana | — |
| Verificável? | não | "a pálpebra ficou fechada por 2 s" — sim |
| Explicável ao aluno? | difícil | direto |

### 5.2 O que se construiu

`DetectorDeFadiga`, três sinais sobre uma janela de 60 s:

| Sinal | Limiar | Penalidade |
| --- | --- | --- |
| **PERCLOS** | proporção > 0,15, satura em 0,40 | até 25 pontos |
| **Microssono** | fechamento contínuo ≥ 2 s | 15 pontos |
| **Bocejo** | MAR acima do limiar por ≥ 2 s | 10 por episódio |

Duas decisões que valem a defesa:

**O limiar de olho fechado é metade da abertura neutra do aluno**, não o 0,20
absoluto da literatura. Quem tem EAR neutro de 0,18 estaria permanentemente "de
olhos fechados" com um limiar fixo — o mesmo problema que a calibração resolve
no score.

**Ausência de rosto não conta como olho fechado** nem entra no denominador do
PERCLOS. Sem rosto não sabemos o que a pálpebra fazia, e contar ausência como
fechamento transformaria "saiu pegar água" em "cochilou".

---

## 6. Tentativa 3 — trocar a pergunta

### 6.1 A hipótese

O problema nunca foi o modelo nem as features. Foi **o rótulo**. O DAiSEE não
rotula sonolência — rotula engajamento, tédio, confusão e frustração.

O **UTA-RLDD** rotula exatamente o que faltava: 60 participantes gravaram três
vídeos de ~10 minutos cada, declarando o próprio estado (0 alerta, 5 vigilância
baixa, 10 sonolento). Classes equilibradas por construção, cinco folds disjuntos
por participante distribuídos pelos autores.

### 6.2 A extração

| | |
| --- | --- |
| Gravações processadas | **182**, zero falhas de leitura |
| Horas de vídeo | ~31 h |
| Janelas de 10 s geradas | **11.279** |
| Distribuição | 3.720 / 3.751 / 3.808 |
| Tempo de extração | ~3 h com 8 processos em paralelo |

Três detalhes do material real que o código precisou aguentar, e que não estão
em README nenhum do dataset: pastas repetidas (`Fold5_part2/Fold5_part2/55/`),
vídeos de sonolência partidos em dois arquivos (`10_1`, `10_2`), e extensões
variando por participante — esquecer o `.m4v` sumiria com o participante 46
inteiro, sem erro.

### 6.3 O resultado

**O modelo discrimina.** É o oposto do que aconteceu no DAiSEE.

| Configuração | Acurácia balanceada | Reproduzível em produção |
| --- | --- | --- |
| Chute fixo | 0,5000 | — |
| ExtraTrees, normalização por sessão | **0,6553 ± 0,0180** | **sim — é o que roda** |
| ExtraTrees, sem normalização | 0,6688 ± 0,0134 | sim |
| ExtraTrees, normalização por participante | 0,7366 ± 0,0571 | **não — é o teto** |

Todos os cinco folds acima do chão. O desvio entre folds é o intervalo de
confiança honesto do número, e está na tabela em vez de escondido atrás da
média.

### 6.4 De onde vem o sinal

| Conjunto de features | Nº | Acurácia balanceada |
| --- | --- | --- |
| Todas | 39 | 0,6688 |
| **Só as derivadas** | 4 | **0,6645** |
| Sem cabeça | 24 | 0,6576 |
| Só olhos | 15 | 0,6550 |
| Só cabeça | 15 | 0,5125 |
| Só boca | 5 | 0,5103 |

**O sinal está nos olhos, e só.** Cabeça sozinha e boca sozinha ficam no chão. E
quatro features derivadas — entre elas `prop_olhos_fechados`, que **é** o
PERCLOS — chegam a 0,6645 das 0,6688 obtidas com todas as 39.

> **Isto valida por medição o desenho da tentativa 2.** As regras do
> `DetectorDeFadiga` foram construídas sobre PERCLOS e fechamento prolongado
> antes de este modelo existir, e o modelo, treinado de forma independente,
> concorda sobre onde está a informação.

### 6.5 Os outros alvos

| Alvo | Acurácia balanceada |
| --- | --- |
| Binário (sonolento vs alerta, descarta o 5) | 0,6553 |
| Binário amplo (5 e 10 vs 0) | 0,6049 |
| Ternário (0, 5, 10) | 0,4514 |

O estado intermediário é o que degrada tudo — o que é consistente com os autores
do dataset o tratarem como ambíguo.

### 6.6 A escolha da configuração de produção

A grade escolheu `sessao` (0,6553) e **não** `nenhuma` (0,6688), apesar do
número menor. A razão está medida:

> A validação cruzada roda **dentro** do UTA-RLDD, onde todo mundo gravou de
> celular. Ela é estruturalmente incapaz de medir a única transposição que o
> produto precisa fazer: para a webcam de um aluno, noutra distância e noutra
> lente.

Em valor absoluto, `ear_esq_min` separa RLDD e DAiSEE com **d de Cohen de
0,97** — mais do que separa as pessoas dentro de cada dataset. Centrando cada
pessoa na própria mediana, cai para **0,23**.

Um modelo treinado em valores absolutos aprende a lente. Um treinado em desvios
da baseline aprende a pessoa. Entre configurações a menos de um desvio-padrão
de distância — indistinguíveis pela medição que temos — vence a que sobrevive à
troca de câmera.

---

## 7. As armadilhas do caminho

Cinco defeitos que teriam produzido **números bonitos e errados**. Cada um foi
pego por medição, não por revisão de código.

### 7.1 O detector de bocejo estava inoperante

`LIMIAR_BOCA_ABERTA = 0,60`, herdado da literatura, classificava como "boca
aberta" **21 frames em 514.757** — distribuídos em 7 clipes de 8.570. Em ~24
horas de vídeo, bocejo nenhum era detectado.

Descoberto ao construir as features temporais. O limiar foi recalibrado a partir
da distribuição observada.

### 7.2 Train/serve skew: treinar com frames, servir com segundos

A extração produz ~60 frames a 6 fps por janela. O backend recebe **uma linha
por segundo**, já resumida no navegador. O `ear_desvio` de 60 medições é **36%
maior** que o de 10 médias por segundo, porque a média já comeu a variação de
dentro do segundo.

Um modelo treinado no primeiro e servido com o segundo aprenderia uma escala que
em produção nunca aparece, e passaria a ver todo mundo anormalmente parado —
**sem erro nenhum no log**.

`agregacao_producao.py` monta as features como o backend as vê. Alinhar os dois
lados custou **0,0015** de acurácia (0,6703 → 0,6688): praticamente de graça.

### 7.3 `n_frames` era uma bandeira de origem disfarçada

Na primeira comparação entre datasets, `n_frames` tinha **d de Cohen de 112**:
60 no DAiSEE contra 10,7 no RLDD. Uma feature que separa os datasets
perfeitamente é um identificador de origem, não uma medida de comportamento — no
treino conjunto, o modelo podia ler "n_frames = 60, logo DAiSEE, logo engajado"
sem olhar para o rosto.

Corrigido agregando o DAiSEE na mesma granularidade.

### 7.4 Fold de teste com uma classe só fazia o chute fixo marcar 0,70

`balanced_accuracy_score` é a média do acerto **por classe presente**. Com uma
classe só, um classificador constante acerta 100% dela e marca 1,0 naquele fold.

Apareceu ao rodar a grade sobre uma extração pela metade, e o `chute_majoritario`
subiu para 0,70. Num relatório, teria passado por desempenho. Hoje o fold é
ignorado e registrado como tal.

### 7.5 A transferência alimentava o modelo com a entrada errada

Um modelo treinado com features centradas recebendo valores absolutos **não erra
alto**: devolvia 0,80 de sonolência para praticamente todo clipe do DAiSEE,
entediado ou não, e o AUC virou ruído. Corrigido, os números ficaram em 0,6142
(desengajamento) e 0,5255 (tédio).

---

## 8. Os dois datasets juntos

Três perguntas separadas, cada uma com resposta própria.

### 8.1 Quanto os domínios diferem

As cinco features mais deslocadas, em valor absoluto:

| Feature | DAiSEE | UTA-RLDD | d de Cohen |
| --- | --- | --- | --- |
| `pitch_max` | 39,12 | 1,57 | 1,30 |
| `pitch_media` | 13,08 | −4,03 | 1,06 |
| `ear_esq_min` | 0,147 | 0,213 | 0,97 |
| `pitch_mediana` | 12,25 | −4,15 | 0,96 |

Depois de centrar cada pessoa na própria mediana, o maior d cai para ~0,34.

> O `pitch` é o mais deslocado, e a explicação é física: no DAiSEE a pessoa olha
> para a tela de um notebook; no RLDD, para a câmera de um celular apoiado. É
> diferença de montagem, não de comportamento.

### 8.2 Transferência — o modelo de sonolência aplicado ao DAiSEE

O DAiSEE **não tem rótulo de sonolência**; ninguém perguntou aos anotadores se a
pessoa estava com sono. Então isto **não é medida de acurácia**, e dizer que é
seria erro grave. É a pergunta de se duas leituras independentes do mesmo rosto
— um modelo treinado noutro dataset e um humano marcando tédio — apontam para o
mesmo lado.

| | AUC |
| --- | --- |
| Sonolência prevista vs. **desengajamento** anotado | **0,6142** |
| Sonolência prevista vs. **tédio** anotado | 0,5255 |

Fraco, consistentemente acima da moeda, e **impossível de vir de ajuste**: o
modelo nunca viu uma linha do DAiSEE.

### 8.3 Treino conjunto — a resposta é negativa

Os dois empilhados sob um alvo compartilhado de "baixo alerta", cada um avaliado
no **próprio** teste, com os mesmos sujeitos nas duas medições:

| Avaliado em | Treinado só nele | Treinado nos dois | Ganho |
| --- | --- | --- | --- |
| DAiSEE | 0,5543 | 0,5471 | **−0,0073** |
| UTA-RLDD | 0,7508 | 0,6988 | **−0,0520** |

**Empilhar piora os dois.** Sonolência e desengajamento não compartilham
assinatura facial suficiente para um modelo se beneficiar de ver ambos.

Era uma aposta explícita, o desenho da avaliação garantiu que soubéssemos o
resultado, e o resultado é negativo. **Isso é achado científico**, ainda que não
seja o achado desejado.

O que funciona é usar cada dataset para o seu construto, mais o DAiSEE como
conjunto de validação cruzada de domínio.

---

## 9. Onde o trabalho está

### O que roda em produção

`ExtraTreesClassifier`, 300 árvores, `max_depth=12`, `min_samples_leaf=10`,
`class_weight="balanced"`, sobre 39 features centradas na baseline da sessão.
4,5 MB de artefato, carregado no boot do backend, inferência em milissegundos.

Ele lê cada janela de 10 segundos da sessão ao vivo. A probabilidade é gravada
em `log_engajamento.sonolencia` e mostrada no relatório **ao lado** do índice —
com a acurácia escrita na nota, porque um indicador que acerta dois terços das
vezes apresentado sem ressalva vira veredito na cabeça de quem lê.

**Ele não entra na fórmula do IEE**, e há teste travando isso: com e sem modelo
carregado, o score e o fator de fadiga saem idênticos.

### O que foi aprendido, em quatro frases

1. **O teto estava no rótulo, não no modelo.** Oito famílias, treze
   regularizações e uma curva de aprendizado foram necessárias para afirmar isso
   com números em vez de com intuição.
2. **Medir contra a própria pessoa é o que faz a diferença.** Foi o único ganho
   real no DAiSEE, é a decisão de produção no RLDD, e é o que a aplicação já
   fazia ao vivo desde a calibração de 60 segundos.
3. **A métrica pode ser o problema.** Uma meta que se satisfaz pelo silêncio não
   mede qualidade; mede disposição a calar.
4. **Trocar a pergunta valeu mais que trocar o modelo.** Nenhuma das oito
   famílias passou de 0,65 prevendo engajamento. Um modelo simples prevendo
   sonolência chega a 0,6553 com sinal real em todos os folds.

### O que fica para o TC2

- Trilha temporal de verdade: LSTM/GRU sobre a sequência, em vez de features
  agregadas por janela
- Um dataset gravado **no contexto de estudo**, com webcam de notebook — é o
  maior limitador metodológico hoje
- Autopercepção do aluno como rótulo: o sistema já coleta a sessão; faltaria
  perguntar como ele se sentiu

---

### Os relatórios de origem

Os números desta síntese vêm de dois relatórios versionados, gerados pelos
próprios scripts de treino:

- [`resultado_18_08.md`](../resultado_18_08.md) — a investigação do DAiSEE
- [`resultado_sonolencia.md`](../resultado_sonolencia.md) — a grade completa do
  UTA-RLDD, com métricas por fold e matriz de confusão

Ambos são reprodutíveis: `random_state` fixo em todas as etapas, e duas
execuções sobre o mesmo dataset produzem exatamente o mesmo modelo e o mesmo
relatório.
