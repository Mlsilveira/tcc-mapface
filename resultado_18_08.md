# Resultados da trilha de Machine Learning — 18/08/2026

Relatório da primeira execução completa dos pipelines das tickets 1 e 2 contra o dataset DAiSEE real, e da investigação que se seguiu ao resultado.

**Execução:** Chrystian (trilha ML) · **Data:** 18/08/2026 · **Sprint:** 1

---

## Resumo para quem tem pressa

1. A extração funcionou: **8570 clipes, 514.850 frames, zero falhas**.
2. O Random Forest foi treinado e o artefato está pronto para o backend.
3. **A meta de "precisão superior a 80%" não foi atingida na leitura mais rigorosa** — deu 0,4753. Nas outras duas leituras usuais de "precisão", ela foi atingida com folga (acurácia 0,9501; precisão ponderada 0,9038).
4. Investigamos a fundo: 8 famílias de modelo, 13 configurações de regularização, 4 conjuntos de features, 4 rótulos, varredura de limiar e normalização por sujeito. **O melhor resultado honesto é ~0,66 de acurácia balanceada.**
5. **A meta de 80% é atingível — e é exatamente esse o problema.** Ela pode ser satisfeita por um modelo que quase nunca opina.
6. Há um teto no próprio dataset: mesmo partindo de rótulos humanos, o engajamento só é recuperável a ~0,72. **Recomendamos trocar a métrica da Definition of Done.**
7. Achado colateral: **o detector de bocejo está inoperante** e precisa de recalibração antes da ticket 8.

---

## 1. Como o treinamento foi feito

### 1.1 De vídeo a tabela

O DAiSEE são ~9 mil vídeos de 10 segundos de estudantes assistindo a aulas, cada um com quatro notas de 0 a 3 atribuídas por anotadores humanos: engajamento, tédio, confusão e frustração.

O pipeline da ticket 1 (`ml/extrair_features.py`) faz o seguinte, clipe por clipe:

1. Abre o vídeo e processa 1 frame a cada 5 (~6 quadros por segundo).
2. Roda o MediaPipe Face Mesh, que devolve 468 pontos do rosto.
3. Calcula três métricas por frame:
   - **EAR** (*eye aspect ratio*) — o quanto o olho está aberto
   - **MAR** (*mouth aspect ratio*) — o quanto a boca está aberta, proxy de bocejo
   - **Head Pose** — para onde a cabeça aponta (yaw, pitch, roll), em graus
4. Resume os ~60 frames do clipe em **39 números**: média, desvio, mediana, mínimo e máximo de cada métrica, mais quatro derivados (proporção de frames com rosto, proporção com olhos fechados, etc.).

Resultado: **8570 clipes** viraram 8570 linhas de 39 colunas. Foram 497 vídeos descartados por não terem linha de rótulo correspondente — descasamento conhecido do DAiSEE, contabilizado e não silencioso.

### 1.2 De tabela a modelo

O treino (`ml/treinar.py`) usa o split **que vem do próprio DAiSEE**:

| Split | Clipes | Para que serve |
| --- | --- | --- |
| Train | 5357 | O modelo aprende aqui |
| Validation | 1429 | Escolha de parâmetros |
| Test | 1784 | Medição final, tocado o mínimo possível |

**Por que não embaralhar aleatoriamente:** o DAiSEE é *subject-independent* — nenhuma pessoa aparece em dois splits. Se embaralhássemos, o mesmo rosto cairia no treino e no teste, e o modelo aprenderia a reconhecer *a pessoa* em vez do engajamento. A métrica subiria sem o modelo ter melhorado. Esse é o tipo de erro cujo sintoma é um número **bom**, que ninguém investiga. Há uma verificação automática (`verifica_independencia_de_sujeito`) que falha alto se a propriedade for violada.

O alvo é binário: **engajado = nota 2 ou 3; não engajado = nota 0 ou 1**.

Distribuição das classes:

| Split | Não engajado | Engajado |
| --- | --- | --- |
| Train | 247 (4,6%) | 5110 (95,4%) |
| Validation | 166 (11,6%) | 1263 (88,4%) |
| **Test** | **88 (4,9%)** | **1696 (95,1%)** |

Guarde esses 88. Eles explicam quase tudo o que vem a seguir.

---

## 2. O resultado principal

| Medida no Test | Valor |
| --- | --- |
| Acurácia | 0,9501 |
| Precisão ponderada | 0,9038 |
| **Precisão macro** | **0,4753** |

Os dois primeiros números parecem excelentes. O terceiro revela que eles são uma miragem.

### Por que 95% de acurácia e 47% de precisão macro descrevem o mesmo modelo

A floresta previu **"engajado" em 1783 dos 1784 clipes** do Test. Ela não aprendeu a reconhecer engajamento — aprendeu que quase todo clipe do DAiSEE é engajado.

> **Exemplo para ilustrar.** Imagine uma turma de 100 alunos: 95 estão concentrados e 5 perderam o foco. Um sistema que simplesmente responde "concentrado" para todo mundo acerta 95 de 100 — **95% de acurácia**. Mas não identificou nenhum dos 5 alunos que precisavam de ajuda, que é justamente a única coisa que o sistema existe para fazer.

A **precisão macro** existe para expor isso. Ela calcula a precisão de cada classe separadamente e tira a média simples, dando à classe de 5 alunos o mesmo peso da classe de 95. Um modelo que ignora a minoria não consegue escondê-la atrás da maioria.

A escolha de medir a meta em precisão macro foi feita **no código, antes de qualquer resultado existir**, e está documentada no `ml/README.md`. É uma decisão de honestidade metodológica que se pagou hoje.

### O baseline empata com um chute fixo

Rodamos um `DummyClassifier` — um "modelo" que responde sempre "engajado" sem olhar para nenhuma feature:

| Modelo | Precisão macro |
| --- | --- |
| Random Forest (300 árvores, 39 features) | 0,4753 |
| **Chute fixo "engajado"** | **0,4753** |

São o mesmo número porque são o mesmo comportamento.

---

## 3. Tudo o que foi avaliado

Antes de aceitar o resultado, testamos sistematicamente cada explicação possível.

### 3.1 Seria sobreajuste (o modelo decorou o treino)?

O `Train` fechou em **1,0000** — acerto perfeito. Isso é assinatura de memorização: 300 árvores sem limite de profundidade decoram 5357 linhas sem esforço.

Testamos 13 configurações de regularização:

| Configuração | Precisão macro (Test) |
| --- | --- |
| Sem regularização (baseline) | 0,4753 |
| `max_depth=6` | 0,5478 |
| `max_depth=10` | 0,5815 |
| `min_samples_leaf=20` | 0,5617 |
| `max_features=0.3` + `leaf=20` | 0,5686 |

Regularizar ajuda no corte desbalanceado (tira o modelo do colapso), mas no corte equilibrado (≥ 3, classes ~54/46) o `Train` cai de 1,00 para 0,69 e **o Test não se mexe** — fica em 0,57–0,60. Um modelo sobreajustado melhora quando é contido; este não melhora.

**Conclusão: o sobreajuste não é o teto.**

### 3.2 Seria o alvo ou o corte da binarização?

| Alvo | Precisão macro |
| --- | --- |
| `engagement`, corte ≥ 2 | 0,4753 |
| `engagement`, corte ≥ 3 | 0,6003 |
| `engagement`, multiclasse 0–3 | 0,3646 |
| **`boredom`, corte ≥ 2** | **0,6748** |
| `confusion`, corte ≥ 2 | 0,4560 |
| `frustration`, corte ≥ 2 | 0,4776 |

`boredom` é o rótulo mais aprendível dos quatro — faz sentido, tédio tem manifestação comportamental mais direta que engajamento. Ainda assim, longe de 80%.

### 3.3 Seria falta de features temporais?

As 39 features são médias e desvios. Elas respondem "quão fechado esteve o olho" mas não "**por quanto tempo seguido**" — e é a segunda pergunta que separa uma piscada de uma pálpebra caindo de sono.

> **Exemplo.** Dois alunos com exatamente a mesma média de EAR: um piscou seis vezes rapidamente (atento), o outro fechou os olhos uma vez por três segundos (cochilando). Média idêntica, situações opostas.

Construímos 22 features que dependem da **ordem** dos frames: maior sequência consecutiva de pálpebra fechada, episódios separados entre curtos (piscada) e longos (sonolência), duração de bocejos, maior sequência de olhar desviado, variação entre frames vizinhos (inquietação), inclinação da reta ao longo do clipe (cabeça caindo).

| Conjunto de features | `engagement` ≥ 2 | `engagement` ≥ 3 | `boredom` ≥ 2 |
| --- | --- | --- | --- |
| 39 agregadas (baseline) | 0,4753 | **0,6003** | **0,6748** |
| 22 temporais | 0,4753 | 0,5656 | 0,5960 |
| 61 combinadas | 0,4753 | 0,5742 | 0,5617 |

**Não ajudam, e combinadas pioram.** Com 61 colunas e split por sujeito, features extras dão à floresta mais formas de decorar pessoas.

*Ressalva honesta: isto refuta estas 22 features, não a hipótese temporal inteira. Um modelo de sequência de verdade (LSTM/GRU) opera sobre a série, não sobre resumos dela — e o spec já adiou essa comparação para o TC2.*

### 3.4 Seria o Random Forest?

Oito famílias de classificador, mesmas 39 features:

| Modelo | F1 macro | Acurácia balanceada |
| --- | --- | --- |
| Chute fixo (classe majoritária) | 0,4874 | 0,5000 |
| **Random Forest baseline** | **0,4872** | **0,4997** |
| Random Forest regularizado | 0,5592 | 0,6105 |
| ExtraTrees | 0,5197 | 0,5165 |
| HistGradientBoosting regularizado | 0,4908 | 0,5951 |
| Regressão logística | 0,4801 | **0,6479** |

O baseline entregue é a **pior** escolha disponível — fica abaixo do chute fixo em F1 macro.

### 3.5 Seria falta de dados? (a pergunta "outro dataset resolveria?")

Treinamos com frações crescentes dos sujeitos, medindo sempre no mesmo Test:

| Sujeitos no treino | Clipes | Acurácia balanceada |
| --- | --- | --- |
| 7 | 512 | 0,5592 |
| 17 | 1056 | 0,5748 |
| 28 | 2024 | 0,5867 |
| 38 | 3051 | 0,5961 |
| 48 | 3650 | 0,6027 |
| 59 | 4405 | **0,6115** |
| 69 (todos) | 5357 | 0,6092 |

**A curva achatou.** Dez vezes mais sujeitos (7 → 69) compraram 0,05 de acurácia balanceada, e os últimos 10 sujeitos não compraram nada. Extrapolando log-linearmente, chegar a 0,80 exigiria da ordem de **centenas de milhares de sujeitos** — e essa extrapolação é otimista, porque ignora a saturação visível na curva.

**Mais dados do mesmo tipo não resolvem.**

### 3.6 A normalização por sujeito — o único ganho real

A causa raiz é que as 39 features são valores **absolutos**, e o EAR neutro de cada pessoa é diferente. A floresta aprende "este é o fulano" antes de aprender "fulano está desengajado".

Testamos subtrair de cada feature a mediana daquela pessoa — que é exatamente o que a calibração de 60 segundos da ticket 7 faz ao vivo:

| Modelo | Acurácia balanceada |
| --- | --- |
| RF baseline (entregue) | 0,4997 |
| RF regularizado, features brutas | 0,6350 |
| **RF regularizado + normalização por sujeito** | **0,6572** |

Sair de 0,4997 (equivalente a moeda) para 0,6572 é o melhor resultado de todo o esforço, e é legítimo: nenhum rótulo entra no cálculo da mediana, e os splits são disjuntos por sujeito.

---

## 4. Por que a meta de 80% deve ser revista

Esta é a seção mais importante do relatório.

### 4.1 A meta é atingível — e é isso que há de errado com ela

Usando ExtraTrees e ajustando o limiar de decisão:

| Limiar | Precisão macro | Sinaliza "não engajado" | Acertos | Alunos ignorados |
| --- | --- | --- | --- | --- |
| 0,40 | **0,8511** ✅ | 4 clipes | 3 | 85 de 88 |
| 0,70 | 0,6131 | 22 clipes | 6 | 82 de 88 |
| 0,90 | 0,5319 | 336 clipes | 34 | 54 de 88 |
| 0,24 | **0,9756** ✅ | **1 clipe** | 1 | 87 de 88 |

O modelo da primeira linha **cumpre a Definition of Done**. Ele arrisca quatro palpites em 88 casos reais e ignora os outros 85. O da última linha, com 97,56% de precisão, dá **um único palpite**.

> **Por que isso acontece.** Precisão pergunta apenas: *"dos palpites que você deu, quantos estavam certos?"* Ela nunca pergunta *"quantos você deixou de dar?"*. Um modelo que só fala quando tem certeza quase absoluta tem precisão altíssima — e utilidade nula.
>
> É como avaliar um médico apenas pela taxa de acerto dos diagnósticos que ele emite. Um médico que se recusasse a diagnosticar qualquer caso duvidoso teria acerto quase perfeito, e seria um péssimo médico.

**Uma meta que pode ser satisfeita pelo silêncio não mede o que queremos medir.**

### 4.2 O rótulo impõe um teto que nenhum modelo atravessa

Fizemos um teste que estabelece um limite superior para qualquer modelo possível.

Em vez de prever `engagement` a partir dos landmarks, demos ao modelo uma informação que ele **nunca teria na vida real**: os outros três rótulos humanos do mesmo clipe — `boredom`, `confusion` e `frustration`. São julgamentos de pessoas que assistiram ao vídeo, e carregam incomparavelmente mais informação do que qualquer coisa que o MediaPipe extraia de pixels.

| Entrada do modelo | Acurácia balanceada | Precisão macro |
| --- | --- | --- |
| 39 features visuais (MediaPipe) | 0,6105 | 0,5493 |
| **3 rótulos humanos do mesmo clipe** | **0,7183** | 0,5574 |
| Rótulos humanos + features visuais | 0,6439 | 0,5675 |

**Mesmo partindo de julgamento humano sobre o mesmo clipe, o engajamento só é recuperável a ~71,83%.**

A leitura é direta: se o que humanos observaram naquele vídeo determina o rótulo de engajamento apenas parcialmente, então **o rótulo carrega uma parcela grande de subjetividade irredutível**. `engagement` no DAiSEE não é um fato objetivo do vídeo, como "há um rosto" ou "os olhos estão fechados" — é uma interpretação. Duas pessoas assistindo ao mesmo clipe podem discordar legitimamente sobre se aquele aluno estava engajado.

Nenhum extrator de features vai superar o julgamento humano do mesmo vídeo. Logo, **exigir 80% de precisão macro de um modelo visual é exigir que ele seja mais consistente com o rótulo do que a própria interpretação humana consegue ser.**

Se a informação humana sobre um clipe recupera o rótulo a apenas ~71,83%, uma meta de 80% não descreve a qualidade do modelo — descreve uma expectativa incompatível com a natureza do problema. **A meta está mal definida, não o trabalho mal feito.**

> **⚠️ Precisão terminológica — importante para a defesa.**
>
> O número 0,7183 **não é** a concordância entre anotadores (*inter-annotator agreement*) do DAiSEE. Não temos acesso às anotações individuais para calcular isso.
>
> O que ele é: a acurácia balanceada de prever `engagement` a partir dos outros três rótulos humanos do mesmo clipe. É uma **estimativa de teto por proxy** — evidência de que o rótulo é fracamente determinado mesmo por informação humana rica.
>
> Use a formulação precisa. O argumento continua forte e é defensável; a formulação imprecisa ("humanos concordam apenas 71,83% entre si") é derrubável por qualquer membro de banca que peça a fonte do número.

### 4.3 A meta já foi atingida em duas das três leituras

"Precisão superior a 80%" admite três leituras técnicas. Com o modelo **que já está treinado**:

| Leitura | Valor | Meta de 80% |
| --- | --- | --- |
| Acurácia | 0,9501 | ✅ atingida |
| Precisão ponderada | 0,9038 | ✅ atingida |
| Precisão macro | 0,4753 | ❌ não atingida |

Isso não é tecnicalidade: o pré-projeto não especifica qual leitura pretende, e "precisão" no uso coloquial em português normalmente significa acurácia. O time escolheu a leitura mais dura por conta própria, no código, antes de ver qualquer número — e a análise acima mostra por que essa leitura, embora mais honesta, também precisa ser substituída.

### 4.4 O que propomos medir no lugar

Métricas que **não se deixam satisfazer pelo silêncio**, porque penalizam tanto o erro de comissão quanto o de omissão:

- **Acurácia balanceada** — média do acerto em cada classe. Um modelo que ignora a minoria fica preso em 0,50, não importa quão desbalanceado seja o dataset.
- **F1 macro** — combina precisão e recall, de novo com peso igual entre classes.

Resultados honestos com essas métricas:

| Configuração | F1 macro | Acurácia balanceada |
| --- | --- | --- |
| Chute fixo | 0,4874 | 0,5000 |
| RF baseline (entregue) | 0,4872 | 0,4997 |
| RF regularizado | 0,5592 | 0,6105 |
| Regressão logística | 0,4801 | 0,6479 |
| **RF regularizado + normalização por sujeito** | — | **0,6572** |

**Proposta concreta para a Definition of Done:** substituir *"precisão superior a 80%"* por *"acurácia balanceada superior a 0,65, com o recall da classe minoritária reportado explicitamente"*.

É um alvo que o trabalho atual **atinge**, que não pode ser gamificado pelo silêncio, e que representa honestamente a dificuldade do problema.

---

## 5. Achado colateral: o detector de bocejo está inoperante

Descoberto durante a construção das features temporais. É um problema de produto, não de métrica.

A constante `LIMIAR_BOCA_ABERTA = 0,60` classifica como "boca aberta" apenas **21 frames em 514.757** — distribuídos em **7 clipes de 8570**. Em ~24 horas de vídeo.

Distribuição real do MAR:

| Percentil | Valor |
| --- | --- |
| Mediana | 0,0036 |
| p99 | 0,2026 |
| p99,9 | 0,2884 |
| **Máximo do dataset inteiro** | **0,7460** |

A documentação de `ml/metricas.py` calibra a escala como *"boca fechada ~0,02; bocejo escancarado passa de 0,8"*. **Nenhum frame do dataset inteiro alcança 0,8.**

Duas consequências práticas:

1. `prop_boca_aberta` é uma **feature morta** — vale zero em 99,9% dos clipes e não discrimina nada.
2. A detecção de bocejo da ticket 8 **nunca dispararia em produção**, porque o frontend reimplementa a mesma fórmula e o mesmo limiar.

**Ação necessária antes da ticket 8:** recalibrar o limiar empiricamente. A distribuição comporta algo entre 0,25 e 0,30. Fica em aberto se a diferença de escala vem da escolha dos três pares verticais do contorno interno dos lábios ou se o DAiSEE simplesmente tem poucos bocejos francos — separar as duas coisas pede inspeção visual de alguns dos 84 clipes com MAR > 0,30.

---

## 6. Recomendações

**Para a orientação:**

1. Revisar o critério de 80% na Definition of Done, com base nas seções 4.1 e 4.2. Levar as três leituras da seção 4.3.
2. Registrar no texto do TCC que o teto observado (~0,72 mesmo com informação humana) é uma **característica do dataset**, não uma limitação da implementação.

**Para o código:**

3. Recalibrar `LIMIAR_BOCA_ABERTA` antes da ticket 8.
4. Considerar trocar o padrão do `treinar.py` para o modelo regularizado com normalização por sujeito. O modelo atualmente entregue produziria um fator de fadiga **constante**, o que tornaria a ticket 8 código morto em produção.

**Para a ticket 8 (fator de fadiga):**

5. Derivar o fator `F` de **regras diretas sobre o EAR** (PERCLOS, duração de fechamento) em vez do classificador. Fadiga é um estado físico observável — "pálpebra fechada por mais de N segundos" tem resposta objetiva e é defensável com muito mais firmeza do que um modelo de 62%.
6. Em paralelo, avaliar datasets de sonolência (UTA-RLDD, NTHU-DDD, YawDD) — *disponibilidade e licenciamento não verificados*. Eles rotulam exatamente o que o produto precisa, com classes equilibradas por construção. Se o acesso sair, o Random Forest volta ao papel que o spec prevê, resolvendo um problema bem posto.
7. **Não colocar o caminho crítico atrás de acesso a dataset.** O formulário do DAiSEE levou semanas; a entrega não pode depender disso.

**Nota técnica para a ticket 8:** o MAR é calculado no navegador mas **não trafega no WebSocket** — o payload leva apenas `ear`, `yaw` e `rosto_detectado`, e há um teste em `frontend/src/app/core/telemetria/agregacao.spec.ts` que trava essas três chaves. Estender o contrato é parte do trabalho.

---

## 7. Como reproduzir

Ambiente: Python 3.11, `ml/.venv`, `random_state=42` fixo em todas as etapas.

```bash
cd ml
.venv/bin/python extrair_features.py --raiz <caminho>/DAiSEE
.venv/bin/python treinar.py
```

Duas execuções sobre o mesmo dataset produzem exatamente o mesmo modelo e o mesmo relatório. Os artefatos ficam em `ml/artefatos/` (não versionados): `random_forest.joblib`, `relatorio.md`, `relatorio.json`.

Variações avaliadas neste relatório:

```bash
.venv/bin/python treinar.py --corte 3
.venv/bin/python treinar.py --modo multiclasse
.venv/bin/python treinar.py --alvo boredom
```

Os experimentos de normalização por sujeito, curva de aprendizado, varredura de limiar e teto por rótulos humanos foram feitos em scripts de rascunho, fora do repositório. Se forem citados na defesa, vale reproduzi-los como scripts versionados.

---

## 8. Limitações desta análise

Registradas para que ninguém — nós inclusive — leia estes resultados como mais definitivos do que são.

- **O teto de 0,7183 é uma estimativa por proxy**, não concordância entre anotadores medida. Ver o aviso da seção 4.2.
- **A refutação da hipótese temporal vale para as 22 features construídas**, não para modelos de sequência (LSTM/GRU), que operam sobre a série e não sobre resumos dela.
- **A extrapolação da curva de aprendizado é log-linear e grosseira.** Ela sustenta a afirmação "mais dados do mesmo tipo não chegam perto de 80%", não uma previsão numérica precisa.
- **Um experimento intermediário foi descartado por vazamento:** ao treinar com Train+Validation, a seleção de hiperparâmetros passou a usar o Test. Aquele resultado (0,6775) não é confiável e não consta das tabelas acima.
- **Nenhuma busca exaustiva de hiperparâmetros foi feita** — 13 configurações não esgotam o espaço. O que sustenta a conclusão é a consistência dos resultados entre famílias de modelo muito diferentes, não a exaustividade da busca.
