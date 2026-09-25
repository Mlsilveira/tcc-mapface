# O projeto, suas métricas e a defesa

O que o MapFace é, para que serve, o que dá para medir nele, onde ele é frágil,
e o que responder quando perguntarem.

---

## Sumário

1. [O que é, em um parágrafo](#1-o-que-é-em-um-parágrafo)
2. [Aplicabilidade real](#2-aplicabilidade-real)
3. [Todas as métricas que cabem no TCC](#3-todas-as-métricas-que-cabem-no-tcc)
4. [Pontos de atenção](#4-pontos-de-atenção-o-que-eu-levantaria-antes-que-a-banca-levante)
5. [Pontos de melhoria](#5-pontos-de-melhoria)
6. [O que a banca vai perguntar](#6-o-que-a-banca-vai-perguntar)
7. [Aderência ao que foi proposto](#7-aderência-ao-que-foi-proposto)

---

## 1. O que é, em um parágrafo

O MapFace calcula um **Índice de Engajamento no Estudo (IEE)**, de 0 a 100, a
partir de métricas faciais extraídas da webcam **dentro do navegador do
estudante**. Ele não envia imagem nem vídeo a lugar nenhum: o que trafega são
nove números por segundo. Ao final da sessão, o aluno recebe um relatório de
autopercepção — curva do índice, sinais físicos registrados e recomendações de
autorregulação. O sistema explicitamente **não diagnostica, não avalia e não
julga**.

---

## 2. Aplicabilidade real

### Onde ele funciona

**Autorregulação individual.** É o caso para o qual foi desenhado. O aluno vê,
depois da sessão, que a queda do índice começou aos 34 minutos — e isso é
acionável: ele pode encurtar o bloco na próxima vez.

**Validação de método de estudo.** O sistema conhece Pomodoro, 52/17,
Timeboxing e Flow. Comparar o próprio índice entre métodos é uma pergunta que o
dado sustenta.

**Pesquisa em pequena escala.** A série por segundo, com baseline individual, é
material bruto legítimo para um estudo sobre padrões de atenção.

### Onde ele *não* funciona — e isso precisa estar na defesa

**Avaliação institucional.** Usar o IEE para pontuar alunos seria um uso que os
dados não sustentam: o índice mede proxies comportamentais, não engajamento
cognitivo. A história 22 do spec protege exatamente isso.

**Comparação entre pessoas.** A baseline é individual e recalibrada a cada
sessão. O 72 do João e o 72 da Maria **não são a mesma coisa**, e o sistema não
oferece ranking por decisão de projeto.

**Ambiente não controlado pelo aluno.** Sala de aula com câmera institucional é
outro produto, com outra discussão ética.

---

## 3. Todas as métricas que cabem no TCC

Esta seção existe para o capítulo de resultados. Está separada entre **o que já
está medido** e **o que ainda dá para medir** com o que existe.

### 3.1 Já medido — modelo de ML

| Métrica | Valor | Onde |
| --- | --- | --- |
| Acurácia balanceada (sonolência, CV 5 folds) | **0,6553 ± 0,0180** | `resultado_sonolencia.md` |
| Teto com normalização por participante | 0,7366 | idem |
| Chão (classificador que ignora a entrada) | 0,5000 | idem |
| F1 macro | 0,6425 | idem |
| Acurácia balanceada (engajamento, DAiSEE) | 0,4997 — empata com chute fixo | `resultado_18_08.md` |
| Precisão macro (DAiSEE, baseline da ticket 2) | 0,4753 | `ml/artefatos/relatorio.md` |
| AUC de transferência RLDD → DAiSEE (desengajamento) | 0,6142 | `resultado_sonolencia.md` |
| Ganho do treino conjunto | **−0,0073** e **−0,052** | idem |
| Ablação: só olhos / só cabeça / só boca | 0,6550 / 0,5125 / 0,5103 | idem |

### 3.2 Já medido — dados

| Métrica | Valor |
| --- | --- |
| Clipes do DAiSEE processados | 8.570 (de 9.067 vídeos) |
| Linhas de frame extraídas (DAiSEE) | 514.850 |
| Gravações do UTA-RLDD processadas | 182, **zero falhas de leitura** |
| Janelas de 10 s geradas (UTA-RLDD) | 11.279 |
| Participantes | 60, em 5 folds disjuntos |
| Distribuição de classes (RLDD) | 3.720 / 3.751 / 3.808 |
| Horas de vídeo processadas | ~31 h (RLDD) + ~24 h (DAiSEE) |

### 3.3 Já medido — engenharia

| Métrica | Valor |
| --- | --- |
| Testes automatizados | **996** (426 backend + 326 frontend + 244 ML) |
| Linhas de teste / linhas de código | 15.929 / 14.847 = **1,07** |
| Transferência inicial do bundle | 88 kB |
| Tempo de build de produção | ~6 s |
| Suíte do backend | ~60 s |
| Falhas de leitura na extração | 0 em 182 gravações |

### 3.4 Dá para medir, e ainda não foi — ticket 16

Estas são as metas do capítulo 8 do pré-projeto. Todas são obteníveis com o que
já existe:

| Meta | Como medir | Onde o dado já está |
| --- | --- | --- |
| FPS da webcam (15–30) | já exibido na tela durante a sessão | `landmarks.service.ts` |
| CPU client-side (≤ 25%) | Performance panel do navegador, sessão de 10 min | — |
| Latência do WebSocket (< 200 ms) | carimbo de ida e volta no payload | `telemetria.service.ts` |
| Tempo de resposta do backend (< 100 ms) | log do uvicorn / ALB | — |
| Uptime (99,9%) | **não alcançável** com uma task e RDS Single-AZ — ver 4.1 | — |
| Taxa de erro sob condições adversas (≤ 5%) | proporção de pontos com `score is null` numa sessão com luz baixa | `pontos_incertos` já no relatório |

### 3.5 Métricas de produto que o banco já sustenta

Nenhuma dessas exige código novo — é só consulta:

- **Duração presente vs. duração total** por sessão (a diferença é o achado mais
  interessante do relatório)
- **Distribuição do IEE** por método de estudo
- **Proporção de pontos incertos** por sessão — é uma medida da qualidade do
  ambiente de estudo do aluno
- **Episódios de fadiga por hora de estudo**
- **Curva do índice ao longo do bloco de foco** — onde a atenção cai, em média
- **Concordância entre o `F` por regras e a leitura do modelo** — os dois estão
  gravados lado a lado em `log_engajamento`, e essa comparação é resultado de
  TCC por si só

---

## 4. Pontos de atenção (o que eu levantaria antes que a banca levante)

### 4.1 A meta de 99,9% de uptime é inalcançável por construção

Uma task do ECS Fargate e um RDS Single-AZ não entregam 99,9%. E a task é única
**porque a baseline calibrada vive na memória do processo**: com duas réplicas,
o mesmo aluno recalibraria ao reconectar na outra.

**O que fazer:** ou a ticket 16 mede o que existe e diz isso com todas as
letras, ou a baseline sai para o banco e a topologia muda. A primeira opção é
mais honesta para uma PoC; a segunda é trabalho real.

### 4.2 O modelo acerta dois terços das vezes

0,6553 de acurácia balanceada é sinal real — está a 8 desvios-padrão do chão —
mas está longe de um veredito. Por isso a leitura aparece no relatório **com a
ressalva ao lado** e não entra na fórmula do índice.

### 4.3 O rótulo do UTA-RLDD é da gravação inteira

Ninguém fica sonolento em todos os segundos de dez minutos. Toda janela de um
vídeo "sonolento" conta como sonolenta, inclusive aquelas em que a pessoa está
claramente acordada. **Isso é ruído de rótulo inerente ao dataset**, e é a
primeira coisa que explica o teto de acurácia. Todo trabalho publicado sobre
esse dataset carrega o mesmo.

### 4.4 A calibração por sessão é cega a estado constante

A baseline sai dos primeiros 60 segundos. Se o aluno senta já exausto, a
baseline é de uma pessoa exausta, e o sistema mede o desvio a partir dali.

**Não é um defeito a consertar**: a alternativa — comparar contra uma constante
igual para todo mundo — é precisamente o que a história 13 recusa, e trocaria
essa cegueira por uma pior.

### 4.5 O estado do Terraform é local

Com três pessoas, o `terraform.tfstate` no disco de quem aplicou é a única
fonte de verdade. O backend S3 está escrito e comentado; na prática da PoC,
**uma pessoa aplica**.

### 4.6 A `SECRET_KEY` ainda tem placeholder como padrão

Pendência aberta e **bloqueante para qualquer sessão real na nuvem**: hoje ela
precisa vir do Secrets Manager.

### 4.7 O contexto de gravação dos datasets não é o do produto

O UTA-RLDD foi gravado em celular, em HD, com a pessoa olhando para a câmera. O
produto roda em webcam de notebook, a 640×480, com a pessoa olhando para o
material. Em valor absoluto, `ear_esq_min` separa os dois datasets com d de
Cohen de 0,97 — **mais do que separa as pessoas dentro de cada um**.

É exatamente por isso que o modelo em produção usa features **centradas na
baseline**: medindo cada pessoa contra ela mesma, o d cai para 0,23.

---

## 5. Pontos de melhoria

**Curto prazo, alto retorno:**

1. `SECRET_KEY` no Secrets Manager (bloqueante)
2. Medir as metas da ticket 16 no ambiente publicado
3. Registrar a duração dos episódios de fadiga, além da contagem
4. Persistir a baseline no banco — destrava múltiplas réplicas e a meta de
   uptime de uma vez

**Médio prazo:**

5. Comparar o `F` por regras com a leitura do modelo sobre sessões reais — o
   dado já está gravado
6. Trocar a migração leve por Alembic quando houver mais de uma réplica
7. Calibrar `LIMIAR_MAR_BOCEJO` com gente de verdade; o valor atual veio de
   distribuição em dataset

**Longo prazo, e é onde está o TC2:**

8. Trilha temporal de verdade — LSTM/GRU sobre a sequência, em vez de features
   agregadas por janela
9. Um dataset gravado **no contexto de estudo**, com webcam de notebook. É o
   maior limitador metodológico do trabalho hoje
10. Validação com autopercepção do próprio aluno como rótulo — o sistema já
    coleta a sessão; faltaria perguntar ao aluno como ele se sentiu

---

## 6. O que a banca vai perguntar

### "Vocês guardam a imagem dos alunos?"

**Não, e isso é estrutural, não uma promessa.** A extração de landmarks roda no
navegador via MediaPipe WASM. O que sai são nove números por segundo: EAR (médio
e por olho), MAR, yaw, pitch, roll, presença de rosto e um rótulo de incerteza.

Há **dois testes** que travam isso — um sobre as colunas do banco, outro sobre
as chaves do payload — e ambos falham se alguém adicionar um campo. Eles
falharam de verdade quando o classificador de sonolência entrou, e foi nesse
momento que a pergunta foi feita e registrada no código.

### "Esse índice mede engajamento mesmo?"

**Não em sentido pleno, e o sistema não afirma isso.** Ele mede proxies
comportamentais: estabilidade ocular, orientação da cabeça e sinais físicos de
fadiga. A história 22 do spec existe para que essa limitação seja explícita ao
aluno.

A evidência de que a honestidade aqui é necessária está medida: prever
engajamento no DAiSEE a partir de features faciais empata com um chute fixo, e
mesmo partindo dos outros três rótulos humanos o teto é ~0,72. **O construto é
fracamente determinado até para humanos.**

### "Por que o Random Forest não gera o fator de fadiga, como o pré-projeto dizia?"

Porque foi medido e não funcionava. O modelo do DAiSEE prevê *engajamento*, e no
split de teste ele empata com um `DummyClassifier` — 0,4753 de precisão macro,
com 1.783 de 1.784 clipes previstos como "engajado". O `F` derivado dele seria
**constante**, e a penalidade de fadiga seria código morto.

Fadiga é estado físico observável: "a pálpebra ficou fechada por mais de dois
segundos" tem resposta objetiva, verificável e explicável ao aluno. Engajamento
não tem.

**E a ablação do modelo de sonolência confirma essa escolha por medição:** o
sinal está quase todo nos olhos (só cabeça = 0,5125, só boca = 0,5103), e as
quatro features derivadas — entre elas o PERCLOS — sozinhas chegam a 0,6645 das
0,6688 obtidas com todas as 39. As regras foram construídas sobre exatamente
esses sinais, antes de o modelo existir.

### "Então não tem machine learning no projeto?"

**Tem, e ele roda em produção.** Um classificador treinado nas 11.279 janelas do
UTA-RLDD lê cada janela de 10 segundos da sessão ao vivo. Ele **discrimina**:
0,6553 ± 0,0180 contra 0,50 do chute fixo, com todos os cinco folds acima do
chão.

A diferença em relação ao pré-projeto é *qual* pergunta o modelo responde e
*onde* ele entra: ele lê sonolência, não engajamento, e a leitura é apresentada
ao lado do índice em vez de entrar na fórmula. O índice continua determinístico
e auditável.

### "Por que não usaram deep learning?"

Três razões, em ordem de peso:

1. **O teto não está no modelo, está no rótulo.** A curva de aprendizado
   achatou: dez vezes mais sujeitos compraram 0,05 de acurácia balanceada, e os
   últimos dez não compraram nada. Extrapolando, chegar a 0,80 exigiria centenas
   de milhares de sujeitos.
2. **Interpretabilidade.** A importância de features é o que permite dizer "o
   sinal está nos olhos" — e foi isso que validou o desenho das regras.
3. **Inferência em milissegundos**, num loop a 1 Hz por aluno.

A comparação sistemática com LSTM/GRU/Transformers está declarada como escopo
do TC2.

### "Por que a meta de 80% de precisão foi abandonada?"

Ela não foi abandonada — foi **medida e mostrou-se mal definida**. Três leituras
do mesmo modelo dão 0,4753 (macro), 0,9038 (ponderada) e 0,9501 (acurácia). A
meta é atingível de um jeito perverso: um modelo que responde em 4 dos 1.784
clipes marca 0,8511 de precisão macro. **A métrica se deixa satisfazer pelo
silêncio.**

A proposta registrada é trocá-la por *acurácia balanceada acima de 0,65, com o
recall da classe minoritária reportado explicitamente* — um alvo que o trabalho
atual atinge, que não se deixa gamificar e que representa honestamente a
dificuldade do problema.

### "Por que dois datasets? O que vocês ganharam juntando?"

Cada um responde a um construto: DAiSEE rotula engajamento, UTA-RLDD rotula
sonolência. **Empilhá-los sob um alvo comum foi testado e piora os dois** —
−0,0073 no DAiSEE e −0,052 no RLDD, cada um avaliado no próprio teste contra o
modelo treinado só nele.

O que funciona é usar o DAiSEE como **validação cruzada de domínio**: o modelo
treinado no RLDD, solto sobre 8.570 clipes que nunca viu, ordena-os conforme o
desengajamento anotado por humanos com AUC de 0,6142. Fraco, consistentemente
acima da moeda, e impossível de vir de ajuste.

### "Como vocês garantem que o modelo não decorou os rostos?"

Os splits são **disjuntos por sujeito** nos dois datasets, e há verificação que
falha alto se a propriedade for violada — porque o sintoma do vazamento é uma
métrica *boa*, e métrica boa ninguém investiga.

No UTA-RLDD usamos os cinco folds dos próprios autores, o que também torna o
número comparável com a literatura.

### "E se a pessoa usa óculos, ou tem o rosto diferente do padrão?"

Duas defesas. A **calibração individual** mede cada aluno contra a própria
mediana — quem tem EAR neutro de 0,18 não é penalizado por um limiar fixo de
0,20. E o **tratamento de incerteza**: reflexo no óculos, luz baixa e oclusão
parcial fazem o sistema se abster de medir em vez de emitir um número enganoso.

### "Por que o IEE zera quando a pessoa sai de quadro? Ela pode estar lendo um livro."

Ele zera porque `P(t)` é presença binária, e essa é a história 18. Mas a
consequência foi tratada: **duração total e duração presente são reportadas
separadamente**, e o relatório de quem estudou 40 minutos numa aba aberta por 3
horas diz as duas coisas.

Além disso, a sessão só encerra por ausência quando ela passa do limite do
**método declarado** — quem usa Pomodoro tem cinco minutos de pausa que não
contam contra ele.

### "Esse número de 47 bocejos está certo?"

**Não estava, e foi corrigido.** A janela de fadiga é de 60 segundos, e o
rótulo do ponto diz qual sinal domina a janela naquele instante — então um único
bocejo mantinha o rótulo aceso em até 60 pontos seguidos. Contar pontos
transformava um bocejo em "47 registros".

Hoje a contagem é por **episódio**: trechos contíguos com o mesmo rótulo. Na
sessão real que expôs o problema, 47 virou 3. O detector sempre contou
episódios corretamente dentro da janela; o erro estava na agregação da série.

*(Se perguntarem como foi descoberto: rodando a aplicação com uma pessoa de
verdade. Nenhum dos 996 testes pegava, porque todos afirmavam o comportamento —
e o comportamento estava certo; o que estava errado era a palavra na tela.)*

### "Quanto custa rodar isso?"

O ALB é o item mais caro, ~US$ 18/mês, e não é nível gratuito. RDS
`db.t4g.micro` é elegível ao nível gratuito nos primeiros 12 meses. S3, ECR e
CloudFront ficam em centavos no volume de uma PoC. **Não há NAT Gateway** — ele
custaria por hora mais que todo o resto junto e nada aqui precisa dele.

`terraform destroy` zera o custo entre demonstrações, e é por isso que a
proteção contra remoção do banco vem desligada.

---

## 7. Aderência ao que foi proposto

O `spec-poc-iee.md` lista **35 histórias de usuário**. Situação:

| Grupo | Histórias | Situação |
| --- | --- | --- |
| Cadastro e autenticação | 1–6 | ✅ completas |
| Início de sessão e webcam | 7–11 | ✅ completas |
| Calibração de baseline | 12–14 | ✅ completas |
| Captura e processamento | 15–19 | ✅ completas |
| IEE e alertas | 20–22 | ✅ (20 retirada por decisão registrada) |
| Persistência e histórico | 23–26 | ⚠️ 26 parcial — ver abaixo |
| Encerramento e relatório | 27–31 | ✅ completas |
| Privacidade e conformidade | 32–33 | ✅ 32 provisionada; 33 estrutural |
| Infraestrutura | 34–35 | ⚠️ 34 completa; 35 não alcançável — ver 4.1 |

### As três divergências, e por que cada uma

**A fórmula mudou de origem, não de forma.** O pré-projeto dizia que o `F` viria
do Random Forest; ele vem de regras. A fórmula
`IEE(t) = P(t) × [0,6·EAR_norm + 0,4·HP_norm] − F` está implementada exatamente
como escrita. O que mudou foi *quem produz o `F`*, com a medição que motivou a
troca registrada em `resultado_18_08.md`.

**O CloudFront entrou, e não estava no desenho.** Não é enfeite: o endpoint de
site estático do S3 serve apenas HTTP, e o navegador só libera a webcam em
contexto seguro. Sem ele, o produto falha na única coisa que existe para fazer.

**A história 26 (reenvio de logs) está parcial.** A reconexão do WebSocket
existe e funciona; o que não existe é buffer local dos pontos perdidos durante a
queda. Numa sessão de uma hora com queda de dez segundos, perdem-se dez pontos
de série — o relatório continua válido e a sessão sobrevive.

### O que o trabalho entrega além do proposto

- **Métodos de estudo** (ticket 17): Pomodoro, 52/17, Timeboxing e Flow, com a
  pausa máxima vindo do método — não estava no pré-projeto e corrigiu um bug
  estrutural de ciclo de vida
- **Blocos declarados**, com avaliação por bloco de foco
- **Um segundo dataset e um segundo modelo**, treinados e validados
- **Uma medição negativa publicada** — o treino conjunto piora os dois datasets
  — que é resultado científico, ainda que não seja o resultado desejado

---

### Como eu abriria a defesa

> "Nós propusemos medir engajamento com Random Forest. Medimos, e o modelo
> empatou com um chute fixo. Em vez de maquiar a métrica, investigamos: oito
> famílias de modelo, treze configurações, quatro rótulos, e uma curva de
> aprendizado que mostrou que o teto está no rótulo, não no modelo. Então
> trocamos a pergunta — de engajamento, que é subjetivo, para sonolência, que é
> observável — e fomos atrás de um dataset que a respondesse. O modelo que roda
> hoje acerta dois terços das vezes contra metade de um chute, e o índice
> continua determinístico e explicável ao aluno. O que vamos apresentar não é o
> resultado que planejamos; é o que a medição sustenta."
