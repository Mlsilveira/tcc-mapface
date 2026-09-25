# Linha do tempo do desenvolvimento

Do primeiro commit ao estado atual: 64 commits, 11 dias de trabalho efetivo,
espalhados por seis semanas. O que foi construído, o que quebrou, e o que cada
quebra ensinou.

**Período:** 13/08/2026 a 24/09/2026.

---

## Nota sobre autoria — leia antes

O histórico do Git atribui a autoria assim:

| Identidade | Commits | Papel no histórico |
| --- | --- | --- |
| `Clauderson (via Claude)` | 61 | autoria de todo o conteúdo |
| `Matheus Silveira` | 3 | integração — merge dos PRs #1, #2 e #4 |
| `Rian Abreu` | **0** | não aparece em lugar nenhum |

Matheus aparece como **integrador**: os três PRs vieram de branches dele
(`Mlsilveira/feat/tickets-5-6`, `Mlsilveira/design/interface-mapface`,
`Mlsilveira/feat/tickets-9-11`) e foram revisados e mesclados por ele. Os
commits *dentro* dessas branches carregam a identidade do Clauderson.

**Rian Abreu não tem nenhum commit, co-autoria ou menção no repositório.**

> **Isto precisa ser resolvido antes da entrega.** Num TCC, a divisão de
> trabalho declarada no `spec-poc-iee.md` — "Matheus & Rian: frontend,
> infraestrutura; Chrystian: ML e dados" — não bate com o que o histórico
> registra. Se houve contribuição fora do Git (modelagem, documento, testes
> manuais, decisões de produto), ela precisa estar documentada em algum lugar
> que a banca possa verificar. Se a contribuição foi via par a par no mesmo
> terminal, o `Co-Authored-By` existe exatamente para isso e pode ser
> acrescentado daqui para a frente.

O que segue descreve **o que o repositório registra**, sem inferir quem estava
na sala.

---

## Visão geral

```
ago 13 ████████ fundação: auth, sessão, spec
ago 14 ██████   PR #1 — ML + captura + telemetria
ago 18 ████     o DAiSEE real: o resultado negativo
ago 19 █        PR #2 — identidade visual
ago 21 █
ago 27 ██       incerteza de captura
ago 28 ███████████  o dia da webcam de verdade
       ·········  (três semanas de pausa)
set 19 █
set 20 ███       relatório refinado
set 21 ███████████████  ticket 17 + PR #4
set 24 ████████████  infra, UTA-RLDD, modelo em produção
```

Dois picos: **28/08** (11 commits) e **21/09** (15 commits). Os dois vieram
depois de descobertas que obrigaram a refazer coisas.

---

## Fase 1 — Fundação (13/08, 8 commits)

Cadastro e login (ticket 3), ciclo de vida da sessão (ticket 4), o spec e a
quebra em tickets versionados.

**A primeira descoberta, no mesmo dia.** O commit `be438cd` troca `passlib` por
`bcrypt` direto e cobre o limite de 72 bytes. O `passlib` estava quebrado com
bcrypt 4.x, e o limite de 72 **bytes** (não caracteres — acentos ocupam 2)
precisava virar validação explícita, senão senhas longas seriam silenciosamente
truncadas.

> **O padrão que nasce aqui e se repete o projeto inteiro:** o problema não é
> encontrado lendo código, é encontrado rodando. E a correção vem com o
> raciocínio escrito junto.

---

## Fase 2 — O PR #1 (14/08, 6 commits, merge por Matheus)

Três frentes de uma vez: o pipeline de extração do DAiSEE com o Random Forest
baseline, a captura client-side com EAR/MAR/Head Pose (ticket 5), e o canal de
telemetria WebSocket com agregação a 1 Hz e reconexão (ticket 6).

É o PR que estabelece a arquitetura de privacidade: a partir daqui, o rosto é
processado no navegador e o que trafega são números.

---

## Fase 3 — O DAiSEE real (18/08, 4 commits)

**O dia mais consequente do projeto.**

O pipeline rodou contra os 8.570 clipes reais. O relatório `15919b9` registrou o
resultado, e ele era negativo:

| | |
| --- | --- |
| Precisão macro no Test | **0,4753** |
| Acurácia | 0,9501 |
| Acertos na classe minoritária | **0** |
| Previsões "engajado" | 1.783 de 1.784 |

**O modelo empatava com um `DummyClassifier`.**

No mesmo dia, dois commits: a fórmula real do IEE com baseline individual
(ticket 7) e — a consequência direta — o **fator de fadiga por regras** (ticket
8), em vez do Random Forest que o pré-projeto prometia.

**Achado colateral:** o limiar de boca aberta herdado da literatura (`0,60`)
disparava em **21 frames de 514.757**, em 7 clipes de 8.570. O detector de
bocejo estava inoperante desde sempre, e ninguém teria notado sem olhar a
distribuição.

---

## Fase 4 — Identidade visual (19–21/08, PR #2, merge por Matheus)

A marca MapFace nas telas de acesso e de sessão. O sistema de design inteiro
vive em um arquivo (`styles.css`), com índigo como cor de ação e verde reservado
ao que está vivo — para não virar decoração.

---

## Fase 5 — O dia da webcam de verdade (27–28/08, 13 commits)

O maior bloco de correções do projeto, e **todas vieram de uma sessão real com
uma pessoa na frente da câmera**.

**Ticket 10 — incerteza de captura.** Luz baixa, reflexo no óculos, oclusão
parcial: o sistema passa a se abster de medir em vez de emitir um score
enganoso. O banco grava o ponto com `score` nulo e o motivo em `alerta`.

**`03e443f` — "corrigir quatro problemas expostos por sessão real de webcam".**
Quatro defeitos que nenhum teste pegava porque todos os testes usavam dados
sintéticos bem-comportados.

**`248c8e4` — separar bocejo de microssono, e recalibrar o MAR.** Um bocejo
fecha os olhos; o detector contava isso **duas vezes**, como bocejo e como
fechamento prolongado. E o limiar de MAR, recalibrado a partir da distribuição
do DAiSEE, teve que ser recalibrado de novo a partir de webcam real — onde o
pico chegou a 0,827, contra 0,746 em 24 horas de DAiSEE.

> O dataset **subestimava** o sinal que o produto ia ver. É um argumento forte
> a favor de testar com gente, e contra confiar só em benchmark.

**`be0b27b` e `185c636` — a câmera.** Três câmeras listadas, duas respondendo
`NotReadableError`. O serviço passa a tentar as outras. E o preview aparecia
"com zoom": medindo os pixels das duas capturas de tela, a caixa não tinha
mudado — o que mudou foi a proporção da câmera escolhida pelo fallback.

Ainda nesse dia: relatório da sessão (ticket 11, backend), retenção de logs
(ticket 13), histórico (ticket 12) e o cronômetro na tela.

---

## Fase 6 — A pausa (29/08 a 18/09)

Três semanas sem commits. O repositório fica parado enquanto a linha paralela
de desenvolvimento acontece fora dele.

---

## Fase 7 — A ticket 17 e o PR #4 (19–21/09, 19 commits)

A retomada começa refinando o relatório — média, pico, vale, e a decisão de que
**sessão sem medida não reporta zero** (`43c8920`): zero diria "o aluno estava
aqui e desengajado", e o que houve foi ausência de medição.

Depois vem a ticket 17, que não estava no plano original e nasceu de um bug
estrutural.

### O bug da sessão fantasma

`ec29c0c` é o commit mais importante desta fase. O texto dele explica:

> A atividade da sessão era renovada a cada payload recebido — a 1 Hz. Só que o
> navegador manda payload válido mesmo sem rosto, porque há quadro de vídeo e
> não há rosto. Somado ao heartbeat de 60 s, isso fazia **cadeira vazia com a
> janela aberta renovar a sessão indefinidamente**.

O encerramento automático da ticket 4 era **estruturalmente incapaz de
disparar** durante uma sessão monitorada, e o relatório contava a tarde inteira
como estudo. A correção: quem mantém a sessão viva passa a ser **rosto na
câmera**, com o limite de ausência vindo do método de estudo declarado.

### O segundo bug: nenhuma sessão passava de 30 minutos

`856dffe`. O token vivia 30 minutos e não havia renovação em lugar nenhum. **Um
ciclo Pomodoro completo era impossível** — e não por causa do Pomodoro. As
sessões gravadas durante o desenvolvimento tinham 1 a 3 minutos, o que escondeu
o limite por meses.

A solução: janela deslizante com teto absoluto carimbado no token. O token
renova enquanto o aluno usa; nenhuma credencial vive mais de 12 horas depois do
login.

### A decisão de preterir uma linha inteira

`0924ade` — "a linha paralela das tickets 10 a 13 é preterida". Duas
implementações concorrentes das mesmas tickets existiam; a decisão foi manter a
da branch `feat/tickets-9-11` e descartar a outra, recuperando dela apenas a
escolha de câmera e o enquadramento (`6b93a89`).

As branches descartadas continuam no remoto, com prefixo `descartada/` —
rastreáveis, não apagadas.

---

## Fase 8 — Infraestrutura, segundo dataset e produção (24/09, 12 commits)

O dia mais denso, e o que fecha o arco do ML.

### Terraform (ticket 14)

Quatro módulos. E uma descoberta que mudou a arquitetura:

> **O CloudFront não é enfeite.** O endpoint de site estático do S3 serve apenas
> HTTP, e o navegador só libera `getUserMedia` em contexto seguro. Publicar o
> Angular direto no S3 entregaria uma aplicação que carrega, faz login, deixa
> iniciar a sessão e falha na única coisa que existe para fazer.

Consequência em cascata: site em HTTPS obriga `wss://`, que obriga TLS no
backend, que obriga um ALB — e o ACM não emite certificado para nome de ALB. A
saída foi **não ter um segundo domínio**: o ALB vira segundo origin do mesmo
CloudFront.

### O UTA-RLDD

182 gravações, 31 horas de vídeo, **zero falhas de leitura**, 11.279 janelas.
Extração em ~3 h com 8 processos paralelos.

O modelo **discrimina**: 0,6553 ± 0,0180 contra 0,50 do chute fixo, com todos os
cinco folds acima do chão. É o oposto do que aconteceu no DAiSEE.

### Cinco armadilhas pegas por medição

Cada uma teria produzido número bonito e errado:

| Armadilha | O sintoma |
| --- | --- |
| Train/serve skew | `ear_desvio` 36% maior no treino que em produção |
| `n_frames` como bandeira de origem | d de Cohen de 112 entre os datasets |
| Fold com uma classe só | o chute fixo marcando 0,70 |
| Transferência com entrada errada | 0,80 de sonolência para todo clipe |
| Normalização irreproduzível em produção | o melhor número vinha do futuro da sessão |

### Dois defeitos que só a aplicação rodando expôs

**`7a8153b`.** Abrir uma sessão respondia **500**: a coluna
`sessao_estudo.resumida` saiu do modelo, continuou no banco como `NOT NULL` sem
default, e **todo `INSERT` passou a falhar** em qualquer banco anterior à
remoção. Nem a suíte pegava (cada teste cria o banco dos modelos de hoje), nem
um banco novo sofria.

E a leitura de sonolência **não voltava ao navegador** — o relatório a mostrava,
a tela ao vivo não. Cada lado, sozinho, funcionava.

### O último achado: 47 bocejos

**`7b3196b`.** Um teste com pessoa real acusou 47 bocejos numa sessão de dois
minutos. Não eram 47 bocejos: eram 47 **segundos** com o rótulo aceso, em três
trechos contíguos.

A janela de fadiga é de 60 segundos, e o rótulo diz qual sinal domina a janela
*naquele instante*. Um único bocejo mantinha o rótulo aceso por até 60 pontos.
**O detector sempre contou episódios corretamente**; o erro estava na agregação
da série.

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
| 10 | 24/09 | "47 bocejos" eram 47 segundos | Contagem por episódio |

**Oito das dez vieram de rodar o sistema, não de revisá-lo.** As duas exceções
(1 e 8) vieram de olhar a distribuição dos dados.

---

## O que o arco conta

O projeto começou prometendo medir engajamento com Random Forest. Mediu,
descobriu que não dava, investigou por que, trocou a pergunta e voltou com um
modelo que funciona — respondendo sonolência em vez de engajamento, e ficando
**ao lado** do índice em vez de dentro dele.

No meio disso, três bugs estruturais que invalidavam medições inteiras foram
encontrados porque alguém sentou na frente da webcam: a sessão que nunca
morria, a credencial que não deixava estudar uma hora, e a contagem que
transformava um bocejo em quarenta e sete.

> **A lição que atravessa a linha do tempo:** este projeto mede pessoas, e
> nenhuma suíte de testes substitui uma pessoa. Dos dez achados mais
> importantes, oito exigiram um rosto de verdade na frente da câmera.

---

## Números de hoje

| | |
| --- | --- |
| Commits | 64 |
| Dias com commit | 11 |
| Testes automatizados | 996 (426 backend + 326 frontend + 244 ML) |
| Linhas de teste / linhas de código | 1,07 |
| Tickets fechadas | 15 de 17 (faltam a 15 e a 16) |
| Histórias de usuário atendidas | 33 de 35 |
| Modelos em produção | 1 |
| Datasets processados | 2 — 55 horas de vídeo |
