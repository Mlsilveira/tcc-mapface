# Linha do tempo: o que foi construído e o que cada quebra ensinou

Do primeiro commit ao estado atual: 65 commits, 11 dias de trabalho efetivo,
espalhados por seis semanas. Este documento é sobre **a evolução do produto** —
que feature entrou quando, o que ela quebrou, e o que a quebra ensinou.

**Período:** 13/08/2026 a 25/09/2026.

---

## Visão geral

```
ago 13 ████████ fundação: auth, sessão, spec
ago 14 ██████   ML + captura + telemetria
ago 18 ████     o DAiSEE real: o resultado negativo
ago 19 █        identidade visual
ago 21 █
ago 27 ██       incerteza de captura
ago 28 ███████████  o dia da webcam de verdade
       ·········  (três semanas de pausa)
set 19 █
set 20 ███       relatório refinado
set 21 ███████████████  ticket 17: métodos e presença
set 24 ████████████  infra, UTA-RLDD, modelo em produção
```

Dois picos: **28/08** (11 commits) e **21/09** (15). Os dois vieram depois de
descobertas que obrigaram a refazer coisas — e essa é a forma do projeto
inteiro.

---

## Fase 1 — Fundação (13/08)

Cadastro e login (ticket 3), ciclo de vida da sessão (ticket 4), o spec e a
quebra em tickets versionados.

**A primeira descoberta, no mesmo dia.** O `passlib` estava quebrado com bcrypt
4.x e foi trocado por `bcrypt` direto. Junto veio o limite de **72 bytes** — não
caracteres, bytes, porque acento ocupa 2 em UTF-8 — que virou validação
explícita. Sem ela, senhas longas seriam truncadas em silêncio.

> **O padrão que nasce aqui e se repete o projeto inteiro:** o problema não é
> encontrado lendo código, é encontrado rodando. E a correção vem com o
> raciocínio escrito junto.

---

## Fase 2 — O pipeline e a captura (14/08)

Três frentes de uma vez: o pipeline de extração do DAiSEE com o Random Forest
baseline, a captura client-side com EAR/MAR/Head Pose (ticket 5), e o canal de
telemetria WebSocket com agregação a 1 Hz e reconexão (ticket 6).

É aqui que a arquitetura de privacidade se estabelece: **a partir deste ponto, o
rosto é processado no navegador e o que trafega são números.** Não foi uma
decisão de otimização — é o que torna a promessa do produto estrutural em vez de
declaratória.

---

## Fase 3 — O DAiSEE real (18/08)

**O dia mais consequente do projeto.**

O pipeline rodou contra os 8.570 clipes reais, e o resultado era negativo:

| | |
| --- | --- |
| Precisão macro no Test | **0,4753** |
| Acurácia | 0,9501 |
| Acertos na classe minoritária | **0** |
| Previsões "engajado" | 1.783 de 1.784 |

**O modelo empatava com um `DummyClassifier`.** Os dois números juntos contam a
história: 95% dos clipes do DAiSEE são engajados, então responder sempre a mesma
coisa já dá 95% de acurácia. A acurácia alta era o retrato de um modelo que não
fazia nada.

No mesmo dia, duas features entraram como consequência direta: a fórmula real do
IEE com baseline individual (ticket 7) e o **fator de fadiga por regras** (ticket
8), em vez do Random Forest que o pré-projeto prometia.

**Achado colateral, e é um dos melhores do projeto.** O limiar de boca aberta
herdado da literatura (`0,60`) disparava em **21 frames de 514.757**, em 7
clipes de 8.570. O detector de bocejo estava inoperante desde que nasceu, e
ninguém teria notado sem olhar a distribuição — porque um detector que nunca
dispara não produz erro, produz silêncio.

---

## Fase 4 — Identidade visual (19–21/08)

A marca MapFace nas telas de acesso e de sessão. O sistema de design inteiro
vive em um arquivo (`styles.css`), com índigo como cor de ação e **verde
reservado ao que está vivo** — sessão em andamento, rosto detectado — para não
virar decoração.

---

## Fase 5 — O dia da webcam de verdade (27–28/08)

O maior bloco de correções do projeto, e **todas vieram de uma sessão real com
uma pessoa na frente da câmera**.

**Ticket 10 — incerteza de captura.** Luz baixa, reflexo no óculos, oclusão
parcial: o sistema passa a se abster de medir em vez de emitir um score
enganoso. O banco grava o ponto com `score` nulo e o motivo em `alerta`. É a
diferença entre "não medi" e "o aluno estava desengajado", e ela atravessa o
produto inteiro daqui para a frente.

**Quatro problemas expostos por sessão real de webcam**, num commit só. Nenhum
teste pegava, porque todos usavam dados sintéticos bem-comportados.

**Bocejo contado duas vezes.** Um bocejo fecha os olhos; o detector marcava isso
como bocejo **e** como fechamento prolongado, penalizando o mesmo evento por dois
caminhos. A separação virou código explícito.

**O MAR real subiu acima do que o dataset mostrava.** Recalibrado a partir da
distribuição do DAiSEE, o limiar teve que ser recalibrado **de novo** a partir de
webcam real — onde o pico chegou a **0,827**, contra 0,746 em 24 horas de
DAiSEE.

> O dataset **subestimava** o sinal que o produto ia ver. É um argumento forte a
> favor de testar com gente, e contra confiar só em benchmark.

**A câmera.** Três câmeras listadas, duas respondendo `NotReadableError`. O
serviço passou a tentar as outras. E o preview aparecia "com zoom": medindo os
pixels das duas capturas de tela, a caixa **não tinha mudado** — o que mudou foi
a proporção da câmera que o fallback escolheu.

Ainda nesse dia entraram o relatório da sessão (ticket 11), a retenção de logs
(ticket 13), o histórico (ticket 12) e o cronômetro na tela.

---

## Fase 6 — A pausa (29/08 a 18/09)

Três semanas sem commits.

---

## Fase 7 — Métodos de estudo e presença (19–21/09)

A retomada começa refinando o relatório — média, pico, vale — e com uma decisão
que parece pequena e não é: **sessão sem medida não reporta zero.** Zero diria "o
aluno estava aqui e desengajado"; o que houve foi ausência de medição, que é
outra afirmação.

Depois vem a ticket 17, que **não estava no plano original** e nasceu de um bug
estrutural.

### O bug da sessão fantasma

A atividade da sessão era renovada a cada payload recebido — a 1 Hz. Só que o
navegador manda payload válido **mesmo sem rosto**, porque há quadro de vídeo e
não há rosto. Somado ao heartbeat de 60 s, isso fazia **cadeira vazia com a
janela aberta renovar a sessão indefinidamente**.

O encerramento automático da ticket 4 era **estruturalmente incapaz de
disparar** durante uma sessão monitorada, e o relatório contava a tarde inteira
como estudo.

A correção mudou a definição de presença: quem mantém a sessão viva passa a ser
**rosto na câmera**, com o limite de ausência vindo do método de estudo
declarado. Quem usa Pomodoro tem cinco minutos de pausa que não contam contra
ele.

### Nenhuma sessão passava de 30 minutos

O token vivia 30 minutos e não havia renovação em lugar nenhum. **Um ciclo
Pomodoro completo era impossível** — e não por causa do Pomodoro. As sessões
gravadas durante o desenvolvimento tinham 1 a 3 minutos, o que escondeu o limite
por meses.

A solução: janela deslizante com teto absoluto carimbado no token. O token
renova enquanto o aluno usa; nenhuma credencial vive mais de 12 horas depois do
login. Doze horas porque é a menor duração que cobre um dia de estudo sem cobrir
um fim de semana esquecido numa máquina compartilhada.

### Blocos declarados, e não inferidos

O aluno passa a declarar método, assunto e meta antes de começar, e a sessão é
conduzida por blocos de foco e pausa. Só entram métodos com assinatura
**temporal** — Pomodoro, 52/17, Timeboxing, Flow. Feynman, active recall e SQ3R
ficaram de fora porque EAR, MAR e head pose **não distinguem "explicar em voz
alta" de "reler"**, e oferecê-los faria o sistema afirmar que mede o que não
mede.

### Uma linha de implementação inteira foi preterida

Duas implementações concorrentes das mesmas tickets existiam. A decisão foi
manter uma e descartar a outra, recuperando dela apenas a escolha de câmera e o
enquadramento. As branches descartadas continuam no remoto com prefixo
`descartada/` — rastreáveis, não apagadas.

---

## Fase 8 — Infraestrutura, segundo dataset e produção (24–25/09)

O dia mais denso, e o que fecha o arco do ML.

### Terraform (ticket 14)

Quatro módulos: rede, site, registro e banco. E uma descoberta que mudou a
arquitetura:

> **O CloudFront não é enfeite.** O endpoint de site estático do S3 serve apenas
> HTTP, e o navegador só libera `getUserMedia` em contexto seguro. Publicar o
> Angular direto no S3 entregaria uma aplicação que carrega, faz login, deixa
> iniciar a sessão e falha na única coisa que existe para fazer.

Consequência em cascata: site em HTTPS obriga `wss://`, que obriga TLS no
backend, que obriga um ALB — e o ACM não emite certificado para nome de ALB. A
saída foi **não ter um segundo domínio**: o ALB vira segundo origin do mesmo
CloudFront. Com isso, o CORS desaparece, o `wss` funciona e o frontend deixa de
ter qualquer URL de ambiente para configurar.

### O segundo dataset

O problema nunca foi o modelo nem as features. Era **o rótulo**: o DAiSEE não
rotula sonolência. O UTA-RLDD rotula.

| | |
| --- | --- |
| Gravações processadas | **182**, zero falhas de leitura |
| Horas de vídeo | ~31 h |
| Janelas de 10 s | **11.279** |
| Participantes | 60, em 5 folds disjuntos |

**O modelo discrimina:** 0,6553 ± 0,0180 contra 0,50 do chute fixo, com todos os
cinco folds acima do chão. É o oposto do que aconteceu no DAiSEE.

E a ablação confirmou por medição o desenho das regras da fase 3: **o sinal está
nos olhos**. Cabeça sozinha dá 0,5125, boca sozinha 0,5103 — as duas no chão —,
enquanto as quatro features derivadas (entre elas o PERCLOS) chegam a 0,6645 das
0,6688 obtidas com todas as 39.

### Cinco armadilhas pegas por medição

Cada uma teria produzido número bonito e errado:

| Armadilha | O sintoma |
| --- | --- |
| Treino a 6 fps, produção a 1 Hz | `ear_desvio` 36% maior no treino que em produção |
| `n_frames` como bandeira de origem | d de Cohen de 112 entre os datasets |
| Fold de teste com uma classe só | o chute fixo marcando 0,70 |
| Transferência com entrada errada | 0,80 de sonolência para todo clipe |
| Normalização irreproduzível | o melhor número vinha do futuro da sessão |

A quinta é a mais interessante: centrar cada feature na mediana do participante
dá o melhor número da grade (0,7366), mas usa as três gravações dele — inclusive
o que, da perspectiva de uma sessão em curso, ainda não aconteceu. Ela ficou na
grade como **teto**, e o artefato saiu da calibração por sessão, que é a única
que o navegador consegue reproduzir.

### Dois defeitos que só a aplicação rodando expôs

**Abrir uma sessão respondia 500.** A coluna `sessao_estudo.resumida` saiu do
modelo, continuou no banco como `NOT NULL` sem default, e **todo `INSERT` passou
a falhar** em qualquer banco anterior à remoção. Nem a suíte pegava — cada teste
cria o banco a partir dos modelos de hoje — nem um banco novo sofria.

**A leitura de sonolência não voltava ao navegador.** O relatório a mostrava, a
tela ao vivo não. Cada lado, sozinho, funcionava.

### O último achado: 47 bocejos

Um teste com pessoa real acusou **47 bocejos** numa sessão de dois minutos. Não
eram 47 bocejos: eram 47 **segundos** com o rótulo aceso, em três trechos
contíguos.

A janela de fadiga é de 60 segundos, e o rótulo diz qual sinal domina a janela
*naquele instante* — então um único bocejo mantinha o rótulo aceso por até 60
pontos. **O detector sempre contou episódios corretamente**; o erro estava na
agregação da série, e a palavra na tela ("registros") escondia isso.

47 → 3.

---

## As dez descobertas que mais mudaram o projeto

| # | Quando | Descoberta | O que mudou |
| --- | --- | --- | --- |
| 1 | 18/08 | O RF do DAiSEE empata com chute fixo | O `F` passa a vir de regras |
| 2 | 18/08 | Limiar de bocejo dispara em 21 de 514.757 frames | Recalibração; o detector estava morto |
| 3 | 28/08 | MAR real chega a 0,827; DAiSEE só a 0,746 | Dataset subestimava o produto |
| 4 | 28/08 | Bocejo fecha os olhos — contado duas vezes | Separação de bocejo e microssono |
| 5 | 21/09 | Payload sem rosto renovava a sessão | Presença passa a ser rosto na câmera |
| 6 | 21/09 | Token de 30 min impedia um Pomodoro | Credencial deslizante com teto |
| 7 | 24/09 | S3 estático é HTTP puro | CloudFront vira caminho obrigatório |
| 8 | 24/09 | Treino a 6 fps, produção a 1 Hz | Features remontadas como o backend as vê |
| 9 | 24/09 | Coluna órfã `NOT NULL` trava todo INSERT | Migração passa a destravar órfãs |
| 10 | 25/09 | "47 bocejos" eram 47 segundos | Contagem por episódio |

**Oito das dez vieram de rodar o sistema, não de revisá-lo.** As duas exceções —
a 1 e a 8 — vieram de olhar a distribuição dos dados. **Nenhuma veio de leitura
de código.**

---

## Os três padrões que o arco revela

**1. O produto mede pessoas, e nenhuma suíte substitui uma pessoa.** Dos dez
achados mais importantes, oito exigiram um rosto de verdade na frente da câmera.
Os 996 testes automatizados pegam regressão; eles não pegam premissa errada.

**2. Vários defeitos eram invisíveis por construção, não por descuido.** O
detector de bocejo que nunca disparava, a sessão que nunca morria, a credencial
que não deixava estudar uma hora — os três produziam **silêncio**, não erro. Um
sistema que falha alto se conserta; um que falha calado se acumula.

**3. Quando a medição contradiz o plano, o plano cede.** O projeto começou
prometendo medir engajamento com Random Forest. Mediu, descobriu que não dava,
investigou por que — oito famílias de modelo, treze regularizações, uma curva de
aprendizado —, trocou a pergunta de engajamento para sonolência e voltou com um
modelo que funciona. E o colocou **ao lado** do índice em vez de dentro dele,
porque dois terços de acerto é informação, não veredito.

---

## Números de hoje

| | |
| --- | --- |
| Commits | 65 |
| Dias com commit | 11 |
| Testes automatizados | 996 (426 backend + 326 frontend + 244 ML) |
| Linhas de teste / linhas de código | 1,07 |
| Tickets fechadas | 15 de 17 (faltam a 15 e a 16) |
| Histórias de usuário atendidas | 33 de 35 |
| Modelos em produção | 1 |
| Datasets processados | 2 — 55 horas de vídeo |
