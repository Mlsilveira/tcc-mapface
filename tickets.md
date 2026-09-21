# Tickets: Prova de Conceito — Índice de Engajamento no Estudo (IEE)

Quebra do spec [`spec-poc-iee.md`](./spec-poc-iee.md) em fatias verticais, em ordem de dependência. Duas trilhas rodam em paralelo até convergirem: **ML** (Chrystian) e **App/Infra** (Matheus & Rian, com apoio pontual de Chrystian no backend/infra).

Trabalhe a **fronteira**: qualquer ticket cujos bloqueadores já estejam concluídos pode começar. As tickets 1–2 (ML) não bloqueiam 3–7 (App) — só convergem na ticket 8.

## 1. Extração de features do DAISEE

**O que construir:** um pipeline offline que roda o MediaPipe Face Mesh sobre os vídeos do dataset DAISEE e produz um dataset tabular rotulado (EAR, Head Pose, MAR) pronto para treino.

**Bloqueada por:** Nenhuma — pode começar imediatamente.

- [x] Dataset DAISEE baixado e organizado localmente
- [x] Pipeline extrai EAR, Head Pose (yaw/pitch) e MAR por frame via MediaPipe
- [x] Saída é um dataset tabular (CSV/parquet) com features + rótulos originais do DAISEE (engagement/boredom/confusion/frustration)
- [x] Pipeline é reproduzível via script, não um processo manual

O pipeline está em [`ml/`](./ml/) e roda com `python extrair_features.py --raiz <DAiSEE>`. O dataset está em disco em `database/DAiSEE` (fora do versionamento) e pareou **8570 clipes** com rótulo — 497 vídeos do disco não têm linha de rótulo e 1 rótulo não tem vídeo, descasamento normal do DAiSEE e contabilizado por `daisee.descasamento`.

## 2. Treinar e validar Random Forest baseline

**O que construir:** o primeiro modelo Random Forest treinado e validado, com relatório de métricas.

**Bloqueada por:** Ticket 1.

- [x] Random Forest treinado sobre o dataset tabular da Ticket 1
- [x] Split de treino/validação/teste definido e documentado
- [x] Relatório com acurácia, precisão, recall e F1-Score
- [x] Meta de precisão > 80% **não** atingida — desvio justificado no relatório
- [x] Modelo serializado como artefato carregável pelo backend

Treinado em 18/08/2026 sobre os 8570 clipes. O split adotado é o do próprio DAiSEE (subject-independent), e a meta de 80% é medida sobre a **precisão macro** no `Test`: 95% dos clipes do `Test` são "engajado", então acurácia e precisão ponderada sobem quase de graça — a floresta tirou 0,9501 de acurácia prevendo "engajado" em 1783 dos 1784 clipes.

**Precisão macro: 0,4753.** O teto sobre sete configurações e os quatro rótulos do DAiSEE é ~0,67 (`boredom`), e regularizar não move o número onde as classes são equilibradas — o gargalo não é sobreajuste, são as features agregadas por clipe. A análise completa, com a tabela de configurações testadas e o que o desvio não é, está em [`ml/README.md`](./ml/README.md#o-resultado-do-baseline), e o relatório completo da execução — com a metodologia, os exemplos e a justificativa para revisar a meta — em [`resultado_18_08.md`](./resultado_18_08.md). É insumo direto da Sprint 7, que já reserva tempo para o relatório de validação e para documentar limitações.

## 3. Cadastro e login

**O que construir:** um estudante consegue criar conta, fazer login e acessar áreas protegidas da aplicação.

**Bloqueada por:** Nenhuma — pode começar imediatamente.

- [x] Endpoint de registro (nome, e-mail, senha) com hashing bcrypt
- [x] Endpoint de login retornando JWT
- [x] Telas de cadastro e login em Angular
- [x] Rotas protegidas redirecionam para login se o usuário não estiver autenticado
- [x] Sessão de autenticação expira após período de inatividade

## 4. Ciclo de vida da sessão de estudo

**O que construir:** um estudante autenticado consegue iniciar e encerrar uma sessão de estudo, registrada em seu nome.

**Bloqueada por:** Ticket 3.

- [x] Tabela `sessao_estudo` (id, id_aluno, inicio, fim)
- [x] Endpoint para iniciar sessão, associada ao aluno autenticado
- [x] Endpoint para encerrar sessão manualmente
- [x] Encerramento automático em caso de inatividade prolongada
- [x] Botões de iniciar/encerrar sessão na interface

## 5. Captura client-side e cálculo local de EAR/HP/MAR

**O que construir:** dentro de uma sessão ativa, o estudante autoriza a webcam e vê seus landmarks e métricas calculadas em tempo real no navegador — sem nada sendo enviado ao backend ainda.

**Bloqueada por:** Ticket 4.

- [x] Integração do MediaPipe Face Mesh no Angular (via `@mediapipe/tasks-vision`)
- [x] Fluxo de permissão de webcam, com mensagem clara em caso de negação
- [x] Mensagem de erro específica quando não há webcam disponível
- [x] Preview da webcam visível ao usuário durante a sessão
- [x] Cálculo local de EAR, Head Pose e MAR a partir dos landmarks
- [x] Captura roda a pelo menos 15 FPS
- [x] Nenhum frame de vídeo ou imagem sai do navegador

## 6. Canal de telemetria (WebSocket) com score stub persistido

**O que construir:** as métricas capturadas no navegador trafegam via WebSocket até o backend, que devolve um score provisório (fórmula simplificada) e grava o log no banco — provando que o pipeline ponta a ponta funciona antes de entrar a complexidade real do IEE.

**Bloqueada por:** Ticket 5.

- [x] `WebSocketManager` no FastAPI recebendo payloads JSON de EAR/HP/MAR
- [x] Reconexão automática do WebSocket em caso de queda de conexão
- [x] Score provisório calculado a cada payload recebido
- [x] Log persistido em `log_engajamento` (horario_registro, score, id_sessao)
- [x] Nenhum campo de imagem/vídeo bruto presente no schema

## 7. Fórmula real do IEE com calibração de baseline

**O que construir:** o score stub é substituído pela fórmula real do IEE, calibrada individualmente para cada estudante nos primeiros 60 segundos da sessão.

**Bloqueada por:** Ticket 6.

- [x] Calibração silenciosa nos primeiros 60s (EAR e Head Pose neutros do aluno)
- [x] Recalibração automática se o aluno se ausentar durante os 60s de calibração
- [x] Fórmula `IEE(t) = P(t) × [(0.6 × EAR_norm) + (0.4 × HP_norm)] − F` implementada em `AnalistaEngajamento`
- [x] `P(t) = 0` zera o score quando o rosto não é detectado
- [x] Testes unitários cobrindo baseline normal e atípica (ex: uso de óculos)

Implementado em [`backend/app/analista.py`](./backend/app/analista.py), com o cálculo saindo de `telemetria.py` — que ficou só com a persistência. `F` entra como parâmetro da fórmula e vale 0 até a ticket 8 ligar o Random Forest.

Duas decisões que valem a defesa: a baseline usa a **mediana** das amostras, não a média, porque as piscadas do minuto de calibração puxariam o EAR neutro para baixo e inflariam o score da sessão inteira; e um `RegistroDeAnalistas` mantém o analista por sessão entre conexões, para que a reconexão automática da ticket 6 não jogue a calibração fora a cada oscilação de rede.

## 8. Fator de fadiga via Random Forest

**O que construir:** o modelo treinado na trilha ML entra em produção, penalizando o IEE quando padrões de fadiga (pálpebras fechadas prolongadas, bocejos) são detectados.

**Bloqueada por:** Ticket 7 e Ticket 2.

- [ ] ~~Modelo da Ticket 2 carregado pelo backend~~ — **substituído por regras**, ver abaixo
- [x] `AnalistaEngajamento.validar_fadiga` classifica padrões sequenciais atípicos
- [x] Fator F subtraído do score do IEE quando fadiga é detectada
- [x] Testes unitários com sequências sintéticas de fadiga

O `F` vem de **regras diretas** sobre a série de EAR e MAR, não do Random Forest da ticket 2. A medição que motivou a troca está em [`resultado_18_08.md`](./resultado_18_08.md): no split de teste, o modelo empata com um classificador que responde sempre "engajado" — o `F` derivado dele seria **constante**, e a penalidade de fadiga seria código morto em produção. Além disso, o modelo prevê *engajamento*, um construto subjetivo com teto de ~0,72 mesmo partindo de anotação humana, enquanto fadiga é estado físico observável: "a pálpebra ficou fechada por mais de dois segundos" tem resposta objetiva, verificável e explicável ao aluno.

Implementado em `DetectorDeFadiga` ([`backend/app/analista.py`](./backend/app/analista.py)), com três sinais somados e limitados a 40 pontos:

- **PERCLOS** — proporção do último minuto com a pálpebra fechada, a métrica clássica de sonolência
- **Microssono** — um fechamento contínuo de 2 s ou mais, que a proporção dilui
- **Bocejo** — MAR acima do limiar por 2 s, tempo suficiente para não ser fala

Duas decisões que valem a defesa: o limiar de olho fechado é **metade da abertura neutra do aluno**, não o 0,20 absoluto da literatura — quem tem EAR neutro de 0,18 estaria permanentemente "de olhos fechados" por um limiar fixo, que é o mesmo problema que a ticket 7 resolveu no score. E ausência de rosto **não** conta como olho fechado nem entra no denominador do PERCLOS: sem rosto não sabemos o que a pálpebra fazia, e contar ausência como fechamento transformaria "saiu para pegar água" em "cochilou".

O payload do WebSocket passou a levar `mar`, que já era calculado no navegador desde a ticket 5 mas parava lá. Os testes que travam as chaves do payload — a fronteira de privacidade — foram atualizados de propósito, em `agregacao.spec.ts` e `telemetria.service.spec.ts`.

**Pendência conhecida:** `LIMIAR_MAR_BOCEJO` está em 0,30, escolhido a partir da distribuição observada no DAiSEE (p99,9 = 0,2884). O valor herdado de 0,60 disparava em 7 clipes de 8570 — bocejo nenhum. A Sprint 11 já reserva tempo para recalibrar thresholds de fadiga com dados reais de teste.

## 9. Dashboard ao vivo — ~~descartada~~, absorvida pela Ticket 11

**Decisão de 27/08/2026.** A ticket foi implementada e depois **retirada do produto**. O painel mostrava o score do IEE e o gráfico atualizando durante a sessão; nada disso chega ao aluno enquanto ele estuda.

**Por quê.** Um score de atenção na tela **compete com a tarefa que ele mede**. O aluno olha para o número, e o ato de olhar derruba o número — a medição interfere no medido. Pior: o gráfico se torna a coisa mais interessante da tela justamente quando o objetivo declarado era o material de estudo. Some-se a isso o custo de manter uma camada de tempo real que não entregava valor proporcional.

O MapFace é um **espelho retrospectivo**, não um monitor cardíaco. O valor está em olhar para a sessão depois que ela terminou, com distância suficiente para tirar conclusões — que é exatamente o que o relatório da ticket 11 faz.

**O que sobrou.** O `GraficoIeeComponent` continua no código e é o gráfico do relatório: ele nunca soube de onde vinham os dados, então sobreviveu à mudança sem alteração. O que saiu foi o painel na tela de sessão e a série em memória — o relatório lê a série do banco, que é onde ela de fato mora.

**O que continua aparecendo durante a sessão**, e por quê: o preview da webcam, o FPS e o alerta de Incerteza de Captura (ticket 10). Nenhum é avaliação de desempenho; os três são diagnóstico do equipamento, e existem para que a sessão não termine num relatório vazio. A régua é essa — durante o estudo, só o que o aluno pode **agir a respeito agora**.

**Impacto no spec:** a história 20 ("ver meu score de IEE atualizado em tempo real durante a sessão") foi movida para *Out of Scope* em [`spec-poc-iee.md`](./spec-poc-iee.md), com a mesma justificativa.

**Revisitada em 21/09/2026 (ticket 17).** O cronômetro do método de estudo entrou na tela da sessão, e isso é uma mudança de escopo deliberada — não um alargamento da exceção de "diagnóstico de equipamento", onde um cronômetro não cabe. A razão que sustenta é a que estava implícita aqui o tempo todo: o problema do score era o **laço de realimentação**, e o cronômetro não tem laço nenhum, porque nada do que ele mostra vem da medição. A régua virou *nada na tela é derivado do comportamento medido do aluno* — mais precisa que a anterior, e o score continua fora. Esta ticket segue descartada.

## 10. Tratamento de condições adversas

**O que construir:** em vez de gerar um score enganoso, o sistema sinaliza incerteza quando as condições de captura são ruins.

**Bloqueada por:** Ticket 7.

- [x] Alerta de "Incerteza de Captura" em cenários de baixa luz, óculos reflexivos ou oclusão
- [x] O alerta não é registrado como score corrompido no banco
- [x] Score zera quando o rosto fica ausente por tempo prolongado

O julgamento mora no navegador ([`qualidade.ts`](./frontend/src/app/core/visao/qualidade.ts)), porque é onde a imagem existe: dos quatro números que sobem por segundo é impossível separar "aluno de olhos semicerrados" de "sala escura e detector chutando o contorno da pálpebra". O que atravessa a rede é o **veredito**, não a evidência — a luminância medida morre no cliente, e a fronteira de privacidade não se move.

Três sinais, com precedência causal (pouca luz *produz* os outros dois, então vem primeiro): luminância média do quadro, taxa de detecção dentro da janela e assimetria entre os olhos. A assimetria é o que denuncia reflexo de óculos: as duas pálpebras descem juntas ao piscar, mas só uma lente reflete.

Duas distinções que valem a defesa. **Ausência não é incerteza:** rosto ausente é uma medição verdadeira (o `P(t) = 0` do spec) e zera o score; incerteza é a recusa de afirmar qualquer coisa, e grava `score = NULL` com o motivo em `alerta`. E a leitura incerta **não entra em lugar nenhum** — não calibra a baseline da ticket 7, não conta como pálpebra fechada no PERCLOS da ticket 8, não vira ponto na série. Contar ausência de informação como olho fechado transformaria "a luz apagou" em "o aluno cochilou".

## 11. Relatório de autopercepção

**O que construir:** ao encerrar a sessão, o estudante recebe um relatório com indicadores, alertas e recomendações.

**Bloqueada por:** Ticket 8.

- [x] Relatório gerado automaticamente ao encerrar a sessão
- [x] Inclui gráfico do IEE, indicadores-chave e alertas de fadiga registrados
- [x] Inclui recomendações básicas de autorregulação (pausas, mudança de estratégia)
- [x] Relatório parcial é gerado mesmo se a sessão for interrompida por erro (queda de conexão, falha do navegador)
- [x] A duração exibida reflete presença real do estudante, não tempo de aba aberta *(AC-11-5, acrescentada em 19/09/2026)*

O relatório sai em `GET /sessoes/{id}/relatorio`, e só para sessão **encerrada**. Recusar a sessão em andamento não é limitação técnica — a série está lá e os indicadores sairiam. É a decisão da ticket 9 defendida na borda: servir o relatório enquanto a sessão roda devolveria o dashboard ao vivo por uma porta lateral, bastando deixar a segunda aba aberta.

**A AC-11-5 é a que mudou mais código.** A única duração disponível era `fim − inicio`, e `fim` vinha da varredura de inatividade, que observa `ultima_atividade` — atualizada pelo heartbeat do navegador a cada 60 s **enquanto a aba estiver aberta**, inclusive com o aluno na cozinha. Aba aberta virava tempo de estudo. A correção troca a fonte da evidência: quem prova presença é a série do IEE, porque cada ponto de `log_engajamento` só existe porque a captura estava rodando. `app/presenca.py` soma os intervalos entre pontos consecutivos e descarta inteiro qualquer vão maior que o limite de inatividade — o mesmo limite da varredura, não uma quarta constante, para que o relatório não contradiga o encerramento automático.

O relatório mostra as **duas** durações lado a lado. "2h de sessão aberta, 40min medidos" ensina algo sobre a tarde que nenhum dos dois números diria sozinho.

Quatro decisões que valem a defesa:

- **Sessão de outro aluno responde 404, não 403.** Um 403 confirmaria que aquela sessão existe, e os ids são sequenciais. Há teste exigindo que sessão inexistente e sessão alheia devolvam **a mesma resposta**, byte a byte.
- **O relatório parcial (AC-11-4) não precisou de caminho próprio.** Quem cai por queda de conexão ou navegador fechado não clica em "Encerrar"; quem fecha a sessão é a varredura. O que faltava era dizer isso ao aluno — daí a coluna `encerramento` (`manual` / `inatividade`), e o selo "Relatório parcial" quando o fim foi inferido, não observado. Sessão anterior a esta ticket fica com `NULL` e é tratada como não-parcial: a migração acrescenta coluna, nunca inventa valor para linha antiga.
- **As recomendações não afirmam estado interno.** `app/recomendacoes.py` concentra cada frase que o aluno lê sobre si mesmo, e um teste parametrizado varre todas as recomendações possíveis proibindo "você estava cansado", "você se distraiu" e parentes. O sistema mede abertura ocular, orientação da cabeça e abertura da boca; o texto diz o que foi *observado* e o que ele *pode fazer*, e deixa a interpretação com ele. É a história 22 do spec aplicada ao único lugar onde o produto escreve frases sobre uma pessoa.
- **Média nula vira um traço, nunca zero.** Na tela, no histórico e no DTO. Zero diria "o aluno estava aqui e desengajado"; o que houve foi ausência de medição. É a distinção que a ticket 10 comprou, e o relatório era exatamente onde ela se perderia sem que nenhum teste anterior percebesse.

**Limitação conhecida:** o indicador se chama `pontos_zerados`, e não `pontos_ausentes`. `calcular_iee` termina em `max(0, bruto − fadiga)`, então `score = 0` tem duas causas — `P(t) = 0` (rosto ausente) e aluno presente cuja fadiga zerou o score — e `log_engajamento` não guarda `rosto_detectado`. Separar de verdade exige coluna nova e migração.

## 12. Histórico de sessões

**O que construir:** o estudante consegue revisitar relatórios de sessões passadas.

**Bloqueada por:** Ticket 11.

- [x] Lista de sessões passadas do aluno autenticado
- [x] Acesso ao relatório completo de cada sessão anterior

`GET /sessoes/historico` devolve as sessões encerradas do aluno, da mais recente para a mais antiga, com o resumo de cada uma — quando, quanto tempo de captura, média e quantos alertas. A série **não** vai junto: a lista inteira com a curva de cada sessão transformaria a tela de histórico no download de todo o histórico.

A rota é declarada antes de `/{id_sessao}/relatorio` de propósito — o FastAPI casa na ordem de registro, e uma dinâmica declarada antes engoliria `historico` como se fosse um id. Há teste travando isso.

**O que a tela deliberadamente não faz é traçar tendência entre sessões.** Comparar a média de terça com a de quinta pressupõe que as duas medem a mesma coisa, e não medem: a baseline é recalibrada a cada sessão e o ambiente muda. Oferecer a linha do tempo é útil; desenhar uma seta para cima em cima dela seria afirmar mais do que o dado sustenta.

## 13. Sumarização e retenção de logs

**O que construir:** os logs granulares deixam de se acumular indefinidamente, sendo resumidos após o fim de cada sessão.

**Bloqueada por:** Ticket 11.

- [x] Logs granulares (segundo a segundo) sumarizados em médias após o encerramento da sessão
- [x] Indexação/particionamento temporal em `horario_registro`

`log_engajamento` é a tabela que cresce: um ponto por segundo, por aluno, por sessão. Uma turma de 30 alunos estudando duas horas por dia gera ~6,5 milhões de linhas por mês, e nada as apagava.

`app/sumarizacao.py` fecha isso em **duas operações, em dois momentos diferentes** — e a separação é a decisão que sustenta a ticket:

1. **No encerramento**, os indicadores são calculados sobre a série completa e congelados em `resumo_sessao`. Não é cache, é correção: média de médias não é média, e recalcular depois sobre a série já colapsada devolveria números *parecidos* com os certos. Parecido é a pior categoria de errado num relatório que o aluno compara com o da semana passada. Há teste com números escolhidos para separar os dois casos — média verdadeira 96,72, média de médias 49,17.
2. **Passadas 24 horas**, os pontos por segundo são trocados por médias por minuto. Não imediatamente, e isso é deliberado: a sessão recém-encerrada é justamente a que o aluno abre em seguida, e uma curva por minuto de uma sessão de oito minutos tem oito pontos. Depois de um dia o valor da série muda de natureza — ninguém revisita o segundo 1.847 de uma terça, mas a forma da curva ainda diz algo.

A varredura é **preguiçosa**, no mesmo molde de `encerrar_inativas`: roda quando o aluno abre o histórico, em vez de depender de um scheduler. A PoC segue sem processo de background, e o custo cai sobre quem se beneficia dele. Em produção com muitos alunos isso vira job — anotado para a ticket 15.

O colapso preserva três coisas que as tickets 10 e 11 custaram a construir, cada uma com teste próprio: um minuto com alguma medida vira a média **só das medidas** (ponto incerto não entra como zero); um minuto inteiramente incerto sobrevive como ponto de `score` nulo (sem ele a curva ligaria os dois lados do buraco); e o rótulo que sobrevive é escolhido **dentro do mesmo vocabulário** — fadiga entre os pontos medidos, incerteza entre os não medidos —, porque uma linha com score e motivo de incerteza ninguém sabe interpretar.

A indexação temporal saiu como índice em `horario_registro` e em `id_sessao`, que é como a série é sempre lida (recortada por sessão, em ordem cronológica). Particionamento de verdade é recurso do PostgreSQL e entra junto com a ticket 14; no SQLite da PoC o índice é o que existe.

## 17. Ciclo de vida da sessão dirigido por presença

> Numerada 17 por ser a mais nova, mas colocada aqui de propósito: ela vem **antes** da trilha de infraestrutura na sequência de trabalho. As tickets 14 a 16 seguem no fim por decisão de escopo, não por ordem.

**O que construir:** a sessão de estudo deixa de ser mantida viva por "aba aberta" e passa a ser mantida viva por **rosto na câmera**, com o limite de ausência vindo do método de estudo que o aluno declarou.

**Bloqueada por:** Ticket 10 (é `rosto_detectado`, já no payload, que vira a evidência).

- [x] `app/metodos.py` — catálogo fechado dos métodos com assinatura temporal observável (Pomodoro, 52/17, Flow, Timeboxing, Sem método), tolerância de retorno e teto absoluto de ausência
- [x] Colunas `metodo`, `assunto`, `meta_de_blocos`, `pausa_maxima_s` e `ultima_presenca` em `sessao_estudo`, com migração e testes
- [x] `sessoes.registrar_presenca` escrita pelo canal de telemetria só quando há rosto
- [x] `encerrar_inativas` com limite **por sessão**, vindo do método
- [x] `sessao_inatividade_minutos` renomeada para `vao_maximo_da_serie_minutos`, com alias do nome antigo
- [x] `POST /auth/renovar` com janela deslizante e teto absoluto na credencial, e reavaliação da expiração no WebSocket
- [x] `InactivityService` suspenso enquanto houver sessão ativa; `sair()` encerra a sessão de verdade
- [x] Tabela `bloco_estudo`, módulo puro `app/blocos.py` e os endpoints de transição
- [x] **AC-17-6:** na tela inicial, o estudante escolhe o método, informa o assunto e, opcionalmente, a meta de blocos
- [x] **AC-17-7:** o aplicativo conduz o método declarado — cronômetro do bloco, aviso da hora da pausa, transições registradas
- [x] **AC-17-8:** nada na tela da sessão é derivado do comportamento medido do estudante
- [x] **AC-17-9:** o relatório lê a sessão por blocos, com os indicadores de cada bloco de foco e as pausas fora da conta
- [x] **AC-17-10:** a cadência declarada é comparada com a executada em **contagem**, nunca em razão, percentual ou nota
- [x] **AC-17-11:** sessão sem método declarado abre com traço, sem seção de método inventada

**A trava que não é de texto.** O risco desta ticket não era uma frase feia — era um número. `"aderência: 62%"` não afirma estado interno nenhum, é aritmética sobre carimbos de tempo, e teria passado em silêncio pelo teste parametrizado de tom que existe desde a ticket 11. Por isso o contrato de cadência é travado por **tipo**: ele carrega `duracao_alvo_s`, `duracoes_observadas_s`, `blocos_na_faixa`, `blocos_de_foco` e `meta_de_blocos`, e um teste varre os campos dos dois lados da rede recusando qualquer `float` que não seja duração nem média. Teste de string é conselho; teste de tipo é regra.

As seis ACs acima nasceram no épico `E02-metodos-de-estudo` do `.wize/`, e não aqui — é a primeira vez neste projeto que o contrato de teste foi escrito **antes** do código. Os contratos estão em `.wize/implementation/tea/E02-metodos-de-estudo/`.

**O bug que ela existe para matar.** `routers/telemetria.py` renovava a atividade da sessão a cada payload recebido — a 1 Hz. Só que o navegador manda payload válido mesmo sem rosto (`rosto_detectado: false`), porque há quadro de vídeo e não há rosto; só para de mandar quando a aba vai para segundo plano. Somado ao heartbeat de 60 s, que bate enquanto a aba existir, isso fazia **cadeira vazia com a janela aberta renovar a sessão indefinidamente**. O encerramento automático da ticket 4 era estruturalmente incapaz de disparar durante uma sessão monitorada, e o relatório contava a tarde inteira como estudo. A ticket 11 tratou o sintoma na duração exibida (`duracao_presente`); esta trata a causa.

**Por que o limite é por sessão.** Avaliar quem usa Pomodoro pelo período inteiro de estudo penaliza exatamente o comportamento que o método prescreve: os cinco minutos em que o aluno está corretamente longe da tela entram na média e a derrubam. Se a pausa é parte do método, o sistema precisa saber qual método é. A pausa máxima é resolvida **no servidor**, a partir do catálogo — o cliente manda o código do método, nunca o número, senão "sessão que nunca encerra" viraria um campo de request. E nenhum método passa do teto de 20 minutos, que é a segunda linha de defesa contra parametrização torta.

**As duas perguntas que pareciam uma.** "A sessão acabou?" e "este vão na série foi perda de captura?" compartilhavam uma constante enquanto a série era a única evidência de presença que existia. Desde que há `ultima_presenca`, não são a mesma pergunta: a primeira se responde com a coluna e o limite do método; a segunda, com a série e os 10 minutos de `presenca.limite_de_ausencia`. Separá-las é o que abre a janela em que uma pausa declarada de 17 minutos sai do tempo de estudo **sem** custar a sessão — antes, ou a pausa contava como estudo ou derrubava a sessão, e as duas respostas estavam erradas.

**Incerteza não é ausência.** Luz baixa, reflexo no óculos e oclusão parcial estragam a medida do EAR sem tirar ninguém da frente da webcam. Achar o rosto é afirmação mais fraca e independente de medi-lo bem, então a presença é registrada mesmo sob incerteza. Exigir o contrário encerraria a sessão de quem estuda num quarto mal iluminado — a mesma confusão entre "não medi" e "não estava lá" que a ticket 10 existe para recusar.

**Os métodos que ficaram de fora.** Feynman, active recall e SQ3R diferem por atividade cognitiva, e EAR, MAR e Head Pose não distinguem "explicar em voz alta" de "reler". Oferecê-los faria o sistema afirmar que mede o que não mede.

## 18. Preparo do software para produção

> Numerada 18, colocada antes da trilha de infraestrutura de propósito: ela é o que torna as tickets 14 e 15 possíveis. Terraform e AWS são responsabilidade de outra pessoa; esta ticket entrega **o software que essa pessoa consegue implantar**.

**O que construir:** a aplicação roda fora da máquina de desenvolvimento, com a garantia de que funciona lá.

**Bloqueada por:** nenhuma.

- [x] Driver PostgreSQL e a suíte inteira rodando contra Postgres, além de SQLite
- [x] `Dockerfile` e `.dockerignore` do backend, mais um `docker-compose.yml` de desenvolvimento só com Postgres
- [x] Configuração por ambiente: `AMBIENTE`, `ORIGENS_PERMITIDAS`, `NIVEL_DE_LOG`
- [x] A aplicação **recusa subir** com a `SECRET_KEY` de exemplo fora de desenvolvimento
- [x] CORS vindo de configuração, com o curinga recusado
- [x] Frontend sem endereço compilado: `environment.prod.ts` e a URL entrando no build
- [x] Sondas `/vivo` e `/pronto`, separadas porque levam a ações opostas
- [x] Log estruturado em JSON, sem conteúdo de aluno
- [x] Handler global de exceção
- [ ] Consentimento explícito, exclusão de dados e rate limit — exigidos por haver usuários reais
- [ ] Seção de limites conhecidos lida por quem decide a topologia — **feito no README**
- [ ] Instrumentação da latência do WebSocket (entra na ticket 16)

**O bug que ela achou, e que teria matado a apresentação.** A primeira execução da suíte contra PostgreSQL deu **44 falhas e 13 erros**, e 43 delas eram a mesma coisa. Toda coluna de instante é `TIMESTAMP WITHOUT TIME ZONE`, e todo instante que o código grava é UTC com fuso explícito. Ao inserir um valor com fuso numa coluna sem fuso, o PostgreSQL **converte para o fuso da sessão de conexão** e só então descarta a informação. Numa máquina em `America/Sao_Paulo`, o instante gravado saía três horas no passado e voltava da leitura como se fosse UTC.

Consequência em produção: **toda sessão de estudo nasceria com `inicio` de três horas atrás** e seria encerrada pela varredura de ausência no primeiro `GET /sessoes/ativa`. Para todo mundo, o tempo inteiro. Os 383 testes verdes em SQLite não diziam nada sobre isso — e é exatamente por isso que "rodar a suíte no banco que vai para produção" era o primeiro item da ordem.

A correção abre a conexão com `-c timezone=UTC`, o que torna a conversão a identidade. A alternativa — declarar as colunas como `TIMESTAMP WITH TIME ZONE` — é o tipo mais correto em absoluto e foi recusada porque muda o **tipo** de colunas existentes, e a migração caseira acrescenta coluna e afrouxa obrigatoriedade, não converte tipo.

**O caminho que nunca tinha rodado.** O ramo PostgreSQL de `_relaxar_obrigatoriedade` (`ALTER COLUMN ... DROP NOT NULL`) existia no código desde a ticket 10 e **nunca havia sido executado uma vez sequer**. Agora tem teste próprio, que distingue os dois ramos pelo **OID da tabela** — reconstruir muda o OID, `ALTER COLUMN` não; contagem de linhas ou lista de colunas não distinguiriam nada.

**O que o SQLite escondia.** Ele não verifica chave estrangeira por padrão, então uma fixture gravava sessão de estudo para um aluno que nunca existiu. Dado inválido nos dois bancos; só um deles dizia.

**O que não foi validado:** o `Dockerfile` foi escrito mas **não construído** — não há Docker na máquina. O que deu para verificar foi o `pip install -r requirements.txt` num venv limpo de Python 3.9.6, que é o passo onde o bug do pin de `sqlmodel`/`pydantic` aparece. Quem tiver Docker precisa rodar um `build` antes de confiar.

## 14. Infraestrutura como código (Terraform)

**O que construir:** toda a infraestrutura AWS provisionável com um comando, sem passos manuais.

**Bloqueada por:** Nenhuma — pode começar imediatamente, em paralelo com as demais.

- [ ] Módulo Terraform para S3 (hospedagem estática do frontend)
- [ ] Módulo Terraform para ECR (registro de imagens Docker do backend)
- [ ] Módulo Terraform para RDS PostgreSQL, com criptografia AES-256 em repouso
- [ ] `terraform apply` provisiona tudo sem intervenção manual

## 15. Deploy na AWS

**O que construir:** a aplicação (mesmo que ainda com o score stub/parcial) acessível publicamente na nuvem, permitindo iterar em ambiente real desde cedo.

**Bloqueada por:** Ticket 6 e Ticket 14.

- [ ] Backend containerizado (Dockerfile) publicado no ECR
- [ ] Backend rodando em ECS Fargate
- [ ] Frontend publicado no S3
- [ ] Variáveis de ambiente e conexão com o RDS configuradas
- [ ] Uma sessão de estudo completa funciona no ambiente publicado

## 16. Validação de performance e resiliência

**O que construir:** confirmar que o sistema implantado atende às metas técnicas do capítulo 8 do pré-projeto.

**Bloqueada por:** Ticket 15 e Ticket 10.

- [ ] FPS da webcam medido (meta 15–30 FPS)
- [ ] Uso de CPU client-side medido (meta ≤ 25%)
- [ ] Latência do WebSocket medida (meta < 200 ms) e tempo de resposta do backend (meta < 100 ms)
- [ ] Uptime medido em teste de estresse (meta 99,9%)
- [ ] Taxa de erro sob condições adversas medida (meta ≤ 5%)
