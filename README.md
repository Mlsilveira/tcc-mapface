# MapFace — Índice de Engajamento no Estudo (IEE)

Prova de conceito de uma aplicação web que ajuda o estudante a **perceber quando perdeu o foco** durante uma sessão de estudo solitária.

O estudante inicia uma sessão, autoriza a webcam, e seus sinais visuais comportamentais — abertura dos olhos (EAR), orientação da cabeça (Head Pose) e indícios de bocejo (MAR) — são extraídos **inteiramente no navegador** via MediaPipe Face Mesh. O backend calcula o Índice de Engajamento no Estudo, uma métrica de 0 a 100 calibrada individualmente, e ao final entrega um relatório de autopercepção.

O sistema **não diagnostica, não avalia e não julga**. Ele mede proxies comportamentais visuais e devolve isso ao próprio estudante.

## Privacidade por design

Nenhuma imagem ou vídeo sai do navegador — apenas coordenadas numéricas trafegam para o backend, e o schema do banco não tem campo para dados brutos de imagem. Os dados de um estudante são visíveis apenas para ele: não existe papel de professor, coordenação ou administrador.

A avaliação de qualidade da captura (ticket 10) mede a luminância do quadro, e essa é a única leitura de pixels do sistema fora do MediaPipe. Ela também não atravessa: o que sobe é o veredito — um rótulo como `baixa-luz` —, nunca o número que o produziu.

## Stack

| Camada | Tecnologia |
|---|---|
| Frontend | Angular 18 (standalone components, signals) |
| Backend | FastAPI + SQLModel |
| Banco | SQLite na PoC; PostgreSQL previsto para o deploy |
| Autenticação | JWT (python-jose) + bcrypt |
| Visão computacional | MediaPipe Face Mesh (client-side) |
| ML | Random Forest treinado com o dataset DAISEE |
| Infra | AWS (S3, ECR, ECS Fargate, RDS) via Terraform |

## Interface

O visual segue o repertório das plataformas de estudo brasileiras — tela de acesso dividida entre um painel de marca e o formulário, uma cor primária forte, cards arredondados —, mas com o tom da proposta: o MapFace é um espelho, não um vendedor de curso. Nada de contagem de aprovados ou urgência; o que o painel de acesso promete é privacidade e calibração individual.

O sistema de design mora inteiro em [`frontend/src/styles.css`](./frontend/src/styles.css): tokens de cor, tipografia, botões e campos. Índigo é a cor de ação e de marca; verde é reservado ao que está vivo (sessão em andamento, rosto detectado), para não virar decoração. As fontes vêm do Google Fonts, com fallback para a fonte do sistema quando não há rede.

O layout responde em três faixas: abaixo de 960px a tela de acesso empilha o painel de marca sobre o formulário; abaixo de 860px a sessão passa a uma coluna só e o preview da webcam ganha um teto de altura, para que rosto e métricas continuem visíveis juntos; acima de 1600px o painel de marca ganha respiro em vez de esticar o texto.

Antes de a câmera acender, a tela do estudante explica em três passos o que vai acontecer — pedir webcam sem explicar é o jeito mais rápido de o aluno negar a permissão.

**Durante a sessão, a tela não mostra o score.** Um número de atenção competiria com a tarefa que ele mede: o aluno olha para o número, e o ato de olhar derruba o número. O MapFace é um espelho retrospectivo — a leitura vem no relatório, quando ele tem distância para agir sobre ela. O que aparece enquanto ele estuda é só o que dá para resolver na hora: o preview da webcam, o FPS e o alerta de incerteza de captura.

## O relatório

Encerrar a sessão leva direto ao relatório dela. Ele traz a curva do IEE, os indicadores da sessão, os alertas registrados e duas ou três recomendações de autorregulação. Quatro cuidados o atravessam inteiro:

- **Duas durações, lado a lado.** "Tempo medido" é quanto tempo houve captura de fato; "sessão aberta" é o relógio de parede. Só o segundo faria a aba esquecida virar tempo de estudo, e a comparação entre os dois é metade do que o relatório informa.
- **Traço, nunca zero.** Sessão sem medida mostra `—`. Zero diria "o aluno estava aqui e desengajado", que é uma afirmação diferente e que estes dados não sustentam.
- **A curva quebra onde não deu para medir.** Os trechos de incerteza não são interpolados nem contados como zero, e a legenda diz quanto tempo ficou de fora.
- **Nenhuma frase afirma estado interno.** O texto diz o que foi observado — "pálpebras pesadas: 12 registros" — e o que fazer a respeito. "Você estava cansado" é uma leitura que abertura ocular, orientação da cabeça e abertura da boca não sustentam, e há teste proibindo essa família de frase.

Sessão derrubada por queda de conexão ou navegador fechado também rende relatório, marcado como **parcial**: o fim considerado é o último sinal que chegou, e não um clique que nunca houve. As sessões encerradas ficam em "Minhas sessões", cada uma com o resumo e o link para o relatório completo.

Quando a sessão declarou um método, o relatório ganha uma segunda leitura: **a sessão vista por blocos**. Cada bloco aparece com a duração que foi declarada ao lado da duração em que houve captura — "25min declarados · 11min com captura" —, e o índice médio dos **blocos de foco** é calculado com as pausas fora da conta. Essa última frase é a ticket 17 inteira: enquanto a sessão era uma média só, os cinco minutos em que o aluno estava corretamente longe da tela entravam no cálculo e o derrubavam, e o sistema penalizava exatamente o comportamento que o método prescreve.

Dois cuidados a mais atravessam essa leitura, e eles são o que a separa de um boletim:

- **Contagem, nunca razão.** A comparação entre a cadência prescrita e a executada sai em blocos contados — "dois dos quatro blocos de foco ficaram entre 20 e 30 minutos" —, e não em percentual, aderência ou nota. A regra não está só no texto: o contrato de cadência carrega a duração-alvo, as durações observadas e as contagens, e **nenhum quociente entre elas**. Quem quiser o percentual precisa acrescentar um campo e justificá-lo, porque `"aderência: 62%"` não afirma estado interno nenhum e passaria calado por qualquer teste de frase. A régua que ela atravessa é a outra, a da ticket 12: oferecer a linha do tempo é útil; desenhar uma seta para cima em cima dela seria afirmar mais do que o dado sustenta.
- **Bloco curto se abstém.** Um bloco com menos de um minuto de medida não recebe média: diz "curto demais para uma média". Num bloco de 12 minutos um ponto espúrio é 1 em 720 e viraria o carimbo daquele bloco; numa sessão de duas horas ele sumia em 7.200. E "curto demais" não é "não deu para medir" — o segundo é a incerteza da ticket 10 do começo ao fim, e os dois mandam o aluno mexer em coisas diferentes.

Todas essas frases nascem no backend, em `app/criterios.py`, pelo mesmo motivo que as recomendações nascem em `app/recomendacoes.py`: é num arquivo só que um teste consegue varrer cada frase que o aluno lê sobre si mesmo. Uma frase escrita no template Angular sairia do alcance da trava de tom no mesmo commit em que nascesse, e ninguém veria.

## O que mantém uma sessão viva

Quem segura a sessão de estudo aberta é **o rosto na câmera**, e só ele. O canal de telemetria grava `ultima_presenca` a cada segundo em que há rosto detectado; passado o limite de ausência sem nenhum, a sessão é encerrada sozinha e o `fim` gravado é o último instante de presença — não o da varredura.

A distinção não é preciosismo. O navegador continua mandando um payload por segundo mesmo com a cadeira vazia (com `rosto_detectado: false`, porque há quadro de vídeo e não há rosto), e o heartbeat de 60 s bate enquanto a aba existir. Enquanto qualquer um dos dois era a evidência de presença, **tempo de aba aberta virava tempo de estudo** e a sessão nunca morria.

O limite de ausência é **por sessão**, porque vem do método de estudo declarado: quem escolheu um método tem direito à pausa que ele prescreve. Nenhum método passa do teto absoluto de 20 minutos, e a pausa máxima é resolvida no servidor a partir do catálogo em `app/metodos.py` — o cliente escolhe o método, nunca o número.

Isso convive com duas perguntas que **parecem** a mesma e não são, e cada uma tem sua constante:

| Pergunta | Evidência | Onde mora |
|---|---|---|
| "A sessão acabou?" | `sessao_estudo.ultima_presenca` | `metodos.limite_de_ausencia` — pausa do método + 3 min, teto de 20 |
| "Este vão na série foi perda de captura?" | a série de `log_engajamento` | `presenca.limite_de_ausencia` — 10 min |

Elas compartilhavam uma constante enquanto a série era a única evidência de presença que o sistema tinha. Desde que existe `ultima_presenca`, não é mais, e separá-las é o que abre a janela em que uma pausa declarada de 17 minutos **sai** do tempo de estudo sem **custar** a sessão. Com um limite só, ou a pausa contava como estudo ou derrubava a sessão — e as duas respostas estavam erradas.

Uma consequência que vale dizer em voz alta: **incerteza de captura não desqualifica a presença.** Luz baixa, reflexo no óculos e oclusão parcial estragam a medida do EAR sem tirar ninguém da frente da webcam. O ponto entra na série com `score` nulo, e a sessão segue viva — tratar "não medi" como "não estava lá" seria desfazer a ticket 10 por uma porta lateral.

## O que mantém a credencial viva

Quem segura a sessão de estudo é o rosto na câmera; quem segura o **login** é outra coisa, e por muito tempo ela foi o teto real do sistema sem ninguém perceber. O token durava 30 minutos e não era renovado em lugar nenhum — na prática, **nenhuma sessão de estudo passava de meia hora**. Um ciclo Pomodoro completo era impossível, e não por causa do Pomodoro. O limite ficou escondido porque as sessões gravadas durante o desenvolvimento tinham 1 a 3 minutos.

O token continua valendo 30 minutos, e isso é de propósito: é a janela em que um token roubado serve para alguma coisa. O que mudou é que ela **desliza**. Quando falta menos de 5 minutos para vencer e há requisição saindo, o cliente troca o token por um novo em `POST /auth/renovar`. Cinco minutos porque o heartbeat da sessão bate a cada 60 s: a margem tolera quatro batidas perdidas antes de a credencial vencer sem ninguém ter tentado renová-la.

Deslizar sem limite seria credencial eterna — bastaria um request a cada 29 minutos, e o heartbeat faz isso sozinho, com a aba aberta e ninguém na frente dela. Por isso o token carrega, no próprio `iat`, **quando a sessão de credencial começou**, e esse carimbo é propagado a cada renovação. Passadas 12 horas desde o login, não há mais renovação: **um dia de estudo cabe; um fim de semana esquecido não.** Uma aba deixada aberta numa máquina compartilhada na sexta à noite não continua autenticada na segunda.

Duas propriedades fecham o desenho, e são as duas frases que a defesa precisa:

- **Token expirado não ressuscita.** Renovar exige credencial viva. Aceitar um token vencido faria de qualquer token roubado uma credencial permanente — o access token viraria um refresh token sem nenhuma das garantias de um.
- **O teto viaja dentro do token.** Não há tabela de sessão no servidor. Isso mantém a autenticação stateless e é uma limitação declarada, não um descuido: o que o par access+refresh compraria é poder **revogar**, e revogação depende de estado no servidor. Sem ele, dois tokens são um token com cerimônia.

Sessões longas expuseram um defeito que estava escondido: o canal de telemetria autenticava **uma vez**, na primeira mensagem, e nunca reavaliava. Enquanto tudo morria em 30 minutos isso era invisível — o heartbeat tomava 401 e o cliente desmontava tudo. Com sessões de horas, um WebSocket aberto seria um canal autenticado de vida ilimitada, imune à expiração e ao logout. Agora o servidor guarda o vencimento do token na entrada e o reconfere **uma vez por minuto** — não a cada payload, porque o canal recebe um payload por segundo por aluno e cada um já paga uma escrita no banco. Do outro lado, o cliente reconecta sempre com a credencial **corrente**, e não com a do início da sessão.

Defesa em uma linha: *o token renova enquanto o aluno usa o sistema, mas nenhuma credencial vive mais que 12 horas depois do login, e renovar exige um token ainda válido.*

## Método de estudo, assunto e blocos

Antes de iniciar, o aluno declara **qual método** vai usar e **qual assunto** vai estudar. O catálogo de métodos vive em código (`backend/app/metodos.py`) e é servido por `GET /metodos` com os nomes legíveis: Pomodoro, 52/17, Flow / Deep Work, Timeboxing e "Sem método". Só entram métodos com assinatura **temporal** — os que diferem por atividade cognitiva (Feynman, active recall, SQ3R) ficam de fora porque EAR, MAR e head pose não os distinguem, e incluí-los faria o sistema afirmar que mede o que não mede.

O cliente manda o **código** do método; o número de segundos da pausa máxima é resolvido no servidor e congelado na sessão. Se viesse do corpo do request, "sessão que nunca encerra" seria um campo de request.

`assunto` é o primeiro campo de conteúdo autoral do banco. Nada o lê, nada o indexa, nada o analisa — ele existe para o aluno reconhecer a própria sessão no histórico. Tem teto de 120 caracteres justamente por isso: campo curto é rótulo, campo longo convida a diário, e diário num banco que ninguém prometeu proteger como diário é uma promessa quebrada que ninguém chegou a fazer em voz alta.

### O que a tela mostra enquanto o aluno estuda

A tela da sessão conduz o método: mostra o **tempo restante do bloco corrente**, o estado (foco ou pausa), "bloco 2 de 4" quando houve meta declarada, e avisa na hora da pausa. A transição é **declarada pelo aluno** — o aviso aparece e persiste, mas o bloco só fecha quando ele diz que fechou, porque um bloco é o que o método mandou fazer **e o aluno aceitou**. O cliente marca a origem como `metodo` quando o cronômetro já tinha zerado e `aluno` quando ele antecipou; é a única coisa que separa "o método foi seguido" de "o método foi reescrito no meio".

Método sem duração de foco prescrita (Flow, Timeboxing) **não ganha cronômetro nem aviso**. O `pausa_s` desses métodos existe para o servidor decidir quando a cadeira vazia encerra a sessão, não para o app prescrever quanto tempo o aluno deve descansar.

O cronômetro entrou aqui **reabrindo** deliberadamente a decisão de 27/08/2026, e a régua mudou com ele. A regra era "durante a sessão o aluno só vê diagnóstico de equipamento", e um cronômetro não é diagnóstico de equipamento nenhum — esticar a frase para acomodá-lo seria desonesto. A régua passou a ser **nada na tela é derivado do comportamento medido do estudante**, que é mais precisa que a anterior e continua excluindo o score pelo mesmo motivo de sempre: o laço de realimentação. O aluno olha para o número e o ato de olhar derruba o número; o cronômetro não tem esse laço, porque tudo que ele mostra sai do método declarado e do relógio de parede.

| Pode aparecer | Não pode, nunca |
|---|---|
| Tempo restante do bloco | Score, IEE, qualquer número derivado da série |
| Estado: "foco" / "pausa" | Cor avaliativa (verde/vermelho), ícone de aprovação |
| "bloco 2 de 4", só se houve meta declarada | "bom/ruim", "você está indo bem", contagem de acerto |
| Aviso "hora da pausa" | Qualquer texto sobre o estado interno do aluno |

A linha de baixo não é prosa: `home.component.spec.ts` tem uma trava que varre o painel da sessão por inventário — todo elemento que a tela exibe está numa lista fechada, e **qualquer elemento a mais é uma falha**, ainda que o texto pareça inofensivo. Um teste ao lado dela acrescenta um indicador à tela e exige que a trava o pegue, para que ela não possa passar por não estar medindo nada.

### O que é um bloco

Um bloco é o **plano executado**: o que o método mandou fazer e o aluno aceitou, declarado na transição e fechado na transição seguinte. O aplicativo conduz o método com o cronômetro na tela, então as bordas são **declaradas**, nunca inferidas da série.

Inferir custaria caro de um jeito invisível: a janela do detector de fadiga carrega resíduo por até 60 s depois de o aluno sair, e `score = 0` é ambíguo entre "cadeira vazia" e "fadiga saturada". Pior: uma queda de Wi-Fi seria indistinguível de uma pausa real, e rede instável passaria a **fabricar** blocos Pomodoro no relatório de quem não fez nenhum.

Um bloco **não é afirmação de presença**, e essa distinção é a mesma que o resto do sistema já faz. Fazer "bloco de foco" significar "o aluno estava ali, focado" obrigaria a reconciliar cada bloco com a série toda vez, e erraria. Os dois ficam lado a lado:

> *"Bloco 3 (foco): 25 min planejados · 11 min com captura · IEE médio 54"*

A discrepância entre as duas primeiras durações é informação para o aluno, não inconsistência a esconder — é a mesma retórica de duração total ao lado de duração presente.

### Por que os blocos moram numa tabela própria

Porque derivá-los na leitura é impossível, e a impossibilidade seria **silenciosa**. Passadas 24 horas a série é colapsada em médias por minuto (ticket 13); blocos derivados existiriam por um dia e depois mudariam sozinhos. Relatório que muda sozinho é exatamente o que a ticket 13 inteira foi construída para impedir. Guardar um JSON no resumo da sessão também não serve: aquela linha só é escrita no encerramento, e a sessão derrubada por queda de conexão fecharia com os blocos reconstruídos a partir de nada.

`bloco_estudo` fica **fora da retenção**: são poucas linhas por sessão, contra um ponto por segundo de `log_engajamento`. Apagá-las não pagaria nem o `DELETE`, e levaria junto o relatório do método.

Bloco com `fim` nulo dentro de sessão encerrada é dado corrompido — os dois caminhos de encerramento (o clique e a varredura de ausência) fecham o bloco aberto com o mesmo `fim` da sessão.

### Sessão antiga

`metodo IS NULL` é **"esta sessão é anterior ao recurso"**, e `"livre"` é **"o aluno escolheu estudar sem método"**. Os dois precisam de representações diferentes: colapsá-los faria a migração inventar uma escolha que ninguém fez. Sessão sem método abre sem blocos, sem cadência e **sem seção de método nenhuma** — no relatório e no histórico ela aparece com traço, pela mesma disciplina de *"Traço, nunca zero"*. Sessão **com** método e sem bloco nenhum é um terceiro estado, e o relatório diz isso em voz alta em vez de renderizá-la como as anteriores ao recurso.

## Estado atual

Implementado:

- **Ticket 3 — Cadastro e login.** Registro com hashing bcrypt, login com JWT, rotas protegidas no Angular e expiração por inatividade.
- **Ticket 4 — Ciclo de vida da sessão de estudo.** Iniciar e encerrar sessão, associada ao aluno autenticado, com encerramento automático por ausência prolongada — medida por rosto na câmera, com o limite vindo do método de estudo declarado.
- **Ticket 5 — Captura client-side.** Permissão de webcam com mensagem por tipo de falha, preview durante a sessão, extração de landmarks via MediaPipe e cálculo local de EAR, MAR e Head Pose, com FPS medido na tela.
- **Ticket 6 — Canal de telemetria.** WebSocket autenticado pela primeira mensagem, agregação a 1 Hz no cliente, reconexão automática com backoff e log persistido em `log_engajamento`.
- **Ticket 7 — Fórmula real do IEE.** `AnalistaEngajamento` calibra a baseline individual do aluno nos primeiros 60 s e passa a medir EAR e Head Pose contra ela, em vez de contra constantes iguais para todo mundo.
- **Ticket 8 — Fator de fadiga.** `DetectorDeFadiga` penaliza o IEE por pálpebra pesada (PERCLOS), fechamento prolongado e bocejo, com os limiares relativos à baseline do aluno. O fator vem de regras, e não do Random Forest — o porquê está em [`resultado_18_08.md`](./resultado_18_08.md).
- **Ticket 10 — Incerteza de captura.** Em pouca luz, com reflexo nos óculos ou com o rosto parcialmente ocluso, o sistema se abstém de medir em vez de emitir um score enganoso: a interface diz o que ajustar e o banco grava o ponto com `score` nulo e o motivo em `alerta`.
- **Ticket 11 — Relatório de autopercepção.** Encerrar leva ao relatório da sessão: curva do IEE, indicadores, alertas nomeados e recomendações de autorregulação. A duração exibida vem da presença real medida pela série, não do tempo de aba aberta, e sessão interrompida rende relatório parcial.
- **Ticket 12 — Histórico de sessões.** Lista das sessões encerradas do aluno, com o resumo de cada uma e acesso ao relatório completo.
- **Ticket 13 — Sumarização e retenção.** Os indicadores são congelados em `resumo_sessao` no encerramento; passadas 24 horas, os pontos por segundo são trocados por médias por minuto. `horario_registro` e `id_sessao` são indexados.

Em andamento:

- **Ticket 17 — Ciclo de vida da sessão dirigido por presença e métodos de estudo.** Quem mantém a sessão viva passou a ser o rosto na câmera, com o limite de ausência vindo do método declarado. O catálogo de métodos, as colunas de contexto, a varredura por sessão, a renovação de credencial, a tabela `bloco_estudo` e a API de transições estão prontos; a tela inicial declara método, assunto e meta, a tela da sessão conduz o ciclo com cronômetro, aviso de pausa e transições gravadas, e o relatório lê a sessão por blocos. **A ticket está fechada** — falta só a revisão do Matheus.

Falta a trilha de infraestrutura — tickets 14 (Terraform) e 15 (deploy na AWS) — e a ticket 16, que mede as metas do capítulo 8 contra o ambiente publicado e por isso depende delas.

O plano completo, com as 16 fatias verticais e suas dependências, está em [`tickets.md`](./tickets.md). O problema, as histórias de usuário e as decisões de arquitetura estão em [`spec-poc-iee.md`](./spec-poc-iee.md).

## Rodando localmente

Pré-requisitos: Python 3.9+, Node 18+.

### Backend

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
.venv/bin/python -m uvicorn app.main:app --reload
```

A API sobe em `http://localhost:8000`, com documentação interativa em `http://localhost:8000/docs`.

Antes de rodar em qualquer ambiente real, troque a `SECRET_KEY` no `.env` por um valor aleatório. O `.env` não é versionado.

### Frontend

```bash
cd frontend
npm install
npm start
```

A aplicação sobe em `http://localhost:4200` e espera o backend em `http://localhost:8000`.

#### Modelo do MediaPipe

Os binários WASM vêm no pacote npm e são copiados pelo build. O arquivo do modelo, não — ele precisa ser baixado uma vez para `frontend/src/assets/mediapipe/`:

```bash
mkdir -p frontend/src/assets/mediapipe && curl -L -o frontend/src/assets/mediapipe/face_landmarker.task https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task
```

Sem ele a sessão ainda inicia e é registrada, mas sem métricas de engajamento — a interface avisa. O arquivo tem ~3 MB e não é versionado.

A webcam só é liberada pelo navegador em contexto seguro: `localhost` funciona, mas um IP na rede local, não.

## Testes

```bash
cd backend && .venv/bin/python -m pytest
```

```bash
cd frontend && npm test
```

A suíte do Angular usa o Chromium que vem com o puppeteer, então não depende de um navegador instalado na máquina. O script roda com `--watch=false`: em modo observador o bundler reconstrói depois da última spec e recarrega o contexto do karma, que reporta "Some of your tests did a full page reload!" — um recarregamento do próprio karma, não de um teste. Enquanto esse ruído existia, o aviso que de fato denuncia um teste que submeteu formulário ou navegou de verdade ficava indistinguível dele.

Do npm 11 em diante, os scripts de instalação das dependências vêm bloqueados por padrão — e o do puppeteer é justamente quem baixa esse Chromium. Em máquina limpa, o `npm test` falha por falta do binário do Chrome sem dizer o porquê. Se acontecer, baixe o navegador explicitamente:

```bash
cd frontend && npx puppeteer browsers install chrome
```

## Organização do código

```
backend/
  app/
    sessoes.py       regras do ciclo de vida da sessão, sem depender de HTTP
    analista.py      calibração da baseline, fórmula do IEE e fator de fadiga
    telemetria.py    persistência da série de engajamento
    relatorio.py     série + sessão → indicadores e relatório montado
    presenca.py      duração por presença real, separando pausa de ausência
    metodos.py       catálogo dos métodos de estudo e limites de ausência
    blocos.py        vocabulário e recorte dos blocos declarados na sessão
    recomendacoes.py nomes dos alertas e recomendações de autorregulação
    criterios.py     avaliação da sessão por blocos, e todas as frases dela
    sumarizacao.py   resumo congelado no encerramento e retenção da série
    security.py      hashing de senha e emissão/validação de JWT
    tempo.py         normalização de datetimes para UTC
    models.py        tabelas aluno, sessao_estudo, bloco_estudo, log_engajamento,
                     resumo_sessao
    database.py      engine, criação de tabelas e migração leve de colunas
    routers/         endpoints de autenticação e de sessão
  tests/
frontend/src/app/
  core/
    services/        auth, sessão de estudo, inatividade, webcam, relatório,
                     catálogo de métodos
    visao/           metricas.ts (EAR/MAR/Head Pose), qualidade.ts (incerteza)
                     e landmarks.service.ts, a ponte com o MediaPipe
    telemetria/      agregação a 1 Hz e o canal WebSocket
    guards/          bloqueio de rotas protegidas
    interceptors/    anexa o JWT às requisições
  pages/             login, registro, sessão de estudo, relatório, histórico
  shared/            marca, ícones, gráfico do IEE e formatação de duração
frontend/src/styles.css   sistema de design: tokens, botões, campos, telas
```

As regras de negócio ficam fora do FastAPI de propósito — `app/sessoes.py`, `app/analista.py`, `app/relatorio.py`, `app/presenca.py`, `app/metodos.py`, `app/blocos.py`, `app/criterios.py` e `app/recomendacoes.py` não conhecem HTTP, banco de requisição nem UI, e é onde os testes de comportamento batem. O `AnalistaEngajamento` é o seam principal do spec: entrou na ticket 7 com a calibração e a fórmula do IEE, e recebe o fator de fadiga na ticket 8. O relatório repete o padrão — `resumir(sessao, serie)` é função pura, testável com séries sintéticas, sem banco nem HTTP.

No frontend a divisão é a mesma: `core/visao/metricas.ts` e `core/visao/qualidade.ts` são aritmética pura — sobre pontos e sobre sinais de captura — e não importam o MediaPipe. Só `landmarks.service.ts` conhece a biblioteca de visão computacional, então trocá-la mexe num arquivo só.

`criar_tabelas` acrescenta ao banco as colunas que os modelos ganharam desde a última execução. `SQLModel.metadata.create_all` só cria tabela nova: numa tabela existente ele não faz nada e não avisa, então uma coluna acrescentada a um modelo só apareceria no primeiro INSERT, como erro no meio da sessão de estudo de alguém. A migração é estreita de propósito — acrescenta coluna, e nada mais. Remover, renomear ou mudar tipo exige decidir o que fazer com os dados já gravados, e é aí que uma ferramenta de migração de verdade passa a valer o próprio peso; a ticket 15 é a candidata natural.

## Equipe

Trabalho de Conclusão de Curso. Duas trilhas em paralelo: **ML** (extração de features do DAISEE e treino do Random Forest) e **App/Infra** (aplicação e provisionamento), convergindo na ticket 8.
