# Spec — Prova de Conceito: Índice de Engajamento no Estudo (IEE)

**Projeto:** Uso de Inteligência Artificial e Visão Computacional Aplicados à Educação
**Time:** Chrystian Natanael Magalhães Silva Nascimento, Rian Gabriel dos Santos Abreu, Matheus Luiz Ramos Silveira
**Status:** Pronto para implementação (greenfield — nenhum código existe ainda)

> Este spec sintetiza o pré-projeto de TCC (UNIP) e o plano de sprints já definidos na conversa, traduzindo-os para o formato de PRD acionável. Não foi feita nova entrevista com o usuário além da confirmação de seams e destino do documento — todo o conteúdo abaixo já estava decidido no pré-projeto ou no plano de sprints.

## Problem Statement

Estudantes que estudam sozinhos em ambientes digitais — aulas online, videoaulas, plataformas EAD — têm pouca capacidade de perceber quando perderam o foco durante uma sessão de estudo. Notificações, múltiplas abas abertas e conteúdo fragmentado corroem a atenção de forma gradual e silenciosa: o estudante continua fisicamente diante da tela, mas seu nível de envolvimento vai caindo sem que ele perceba, até que o tempo de estudo já deixou de ser produtivo.

Não existe hoje uma ferramenta acessível, não invasiva e eticamente responsável que devolva ao estudante um retrato objetivo do próprio comportamento durante o estudo autônomo. As alternativas de mercado ou são clinicamente invasivas e caras (EEG, biossensores), ou são voltadas à vigilância institucional em sala de aula corporativa — nenhuma delas atende ao estudante individual que estuda em casa, sozinho, e quer apenas entender seus próprios padrões.

## Solution

Uma aplicação web (Angular + Python/FastAPI + PostgreSQL, com deploy na AWS) em que o estudante inicia uma sessão de estudo, autoriza a webcam e tem seus sinais visuais comportamentais — posição da cabeça, abertura dos olhos, indícios de bocejo — extraídos inteiramente no navegador via MediaPipe Face Mesh. Nenhuma imagem ou vídeo bruto é transmitido ou armazenado: apenas coordenadas numéricas dos 468 landmarks faciais chegam ao backend, via WebSocket.

O backend calcula, a cada instante, o Índice de Engajamento no Estudo (IEE) — uma métrica de 0 a 100, calibrada individualmente nos primeiros 60 segundos da sessão (baseline), combinando a estabilidade ocular (EAR) e a orientação da cabeça (Head Pose), com uma penalidade de fadiga (F) vinda de um classificador Random Forest treinado sobre o dataset DAISEE. Ao final da sessão, o estudante recebe um relatório de autopercepção com indicadores e recomendações básicas de autorregulação (pausas, mudança de estratégia) — o sistema explicitamente não diagnostica, não avalia e não julga.

## User Stories

**Cadastro, autenticação e acesso**

1. Como estudante, quero criar uma conta com e-mail e senha, para que meus dados de sessões fiquem vinculados só a mim.
2. Como estudante, quero fazer login com minhas credenciais, para acessar meu histórico de sessões e relatórios.
3. Como estudante, quero que minha senha seja armazenada com hashing (bcrypt), para que ela não fique exposta em caso de vazamento do banco.
4. Como estudante, quero que minha sessão de autenticação expire após um período de inatividade, para que outra pessoa não acesse meus dados no mesmo computador.
5. Como estudante, ao tentar acessar uma área protegida sem estar logado, quero ser redirecionado para a tela de login, para não ver dados que não são meus.
6. Como estudante, quero que meus relatórios e sessões sejam visíveis apenas para mim, para que nenhum professor, instituição ou terceiro tenha acesso aos meus dados comportamentais.

**Início de sessão e permissão de webcam**

7. Como estudante, quero iniciar uma sessão de estudo com um clique, para começar a monitorar meu comportamento sem fricção.
8. Como estudante, quero ser solicitado a autorizar o uso da webcam antes da sessão começar, para manter controle explícito sobre quando estou sendo observado.
9. Como estudante, se eu negar a permissão da webcam, quero receber uma mensagem clara explicando que a sessão não pode ser iniciada sem ela, em vez de a aplicação travar ou falhar silenciosamente.
10. Como estudante, se meu computador não tiver webcam disponível, quero uma mensagem de erro específica, para entender que o problema é de hardware e não da aplicação.
11. Como estudante, quero ver um preview da minha própria imagem durante a sessão, para confirmar que a webcam está funcionando corretamente.

**Calibração de baseline**

12. Como estudante, quero que o sistema calibre silenciosamente meu padrão neutro (EAR e inclinação de cabeça) nos primeiros 60 segundos da sessão, para que o IEE seja relativo ao meu próprio comportamento e não a um padrão genérico.
13. Como estudante que usa óculos, tem assimetria facial ou é neurodivergente, quero que essa calibração individual evite que meu padrão natural seja penalizado como "dispersão", para que o sistema não gere alertas injustos.
14. Como estudante, se eu me ausentar da webcam durante os 60 segundos de calibração, quero que o sistema aguarde e recalibre quando meu rosto for detectado novamente, em vez de calibrar com dados incompletos.

**Captura e processamento em tempo real**

15. Como estudante, quero que a extração de landmarks faciais aconteça no meu próprio navegador, para que nenhuma imagem ou vídeo meu seja enviado à internet.
16. Como estudante, quero que a captura rode a pelo menos 15 FPS, para que a experiência não trave meu computador enquanto estudo.
17. Como estudante, se a iluminação do ambiente estiver ruim, eu usar óculos com reflexo ou meu rosto estiver parcialmente ocluso, quero receber um alerta de "Incerteza de Captura" em vez de um score de engajamento enganoso.
18. Como estudante, se eu me afastar completamente da tela (rosto não detectado), quero que o IEE zere automaticamente, para refletir que não há dados de comportamento observável naquele momento.
19. Como estudante, quero que a conexão de telemetria (WebSocket) tente se reconectar automaticamente se cair, para que uma instabilidade momentânea de rede não interrompa toda a sessão.

**Cálculo do IEE e alertas**

20. ~~Como estudante, quero ver meu score de IEE atualizado em tempo real durante a sessão, para ter uma noção contínua do meu comportamento.~~ — **retirada em 27/08/2026**, ver *Out of Scope*.
21. Como estudante, quero que sinais prolongados de olhos fechados ou bocejos frequentes reduzam meu score via o fator de fadiga, para que padrões físicos associados a cansaço sejam refletidos no índice.
22. Como estudante, quero que o sistema não afirme estar medindo meu estado emocional ou cognitivo real, para que eu entenda os limites do que está sendo medido (proxies comportamentais, não engajamento em sentido pleno).

**Persistência e histórico**

23. Como estudante, quero que cada sessão registre o horário de início e fim, para poder acompanhar minha rotina de estudo ao longo do tempo.
24. Como estudante, quero que os logs de score e alertas fiquem associados apenas a identificadores numéricos pseudonimizados, para que nenhum dado sensível fique exposto no banco.
25. Como estudante, quero que meus logs granulares (segundo a segundo) sejam sumarizados em médias após o encerramento da sessão, para que o sistema não acumule dados brutos desnecessariamente.
26. Como estudante, se o banco de dados estiver indisponível no momento de salvar um log, quero que o sistema não perca a sessão inteira — os dados já capturados devem ser preservados ou reenviados quando a conexão voltar.

**Encerramento de sessão e relatório**

27. Como estudante, quero poder encerrar a sessão manualmente a qualquer momento, para ter controle total sobre quando parar de ser monitorado.
28. Como estudante, se eu ficar inativo/afastado por muito tempo, quero que a sessão seja encerrada automaticamente, para evitar registrar uma sessão "fantasma" sem dados úteis.
29. Como estudante, ao final da sessão, quero ver um relatório com gráfico do IEE ao longo do tempo, indicadores-chave e recomendações básicas de autorregulação (pausas, mudança de estratégia), para poder refletir sobre meu comportamento.
30. Como estudante, quero acessar o histórico de relatórios de sessões anteriores, para acompanhar minha evolução ao longo do semestre.
31. Como estudante, se uma sessão for interrompida por erro (queda de conexão, falha do navegador) antes do encerramento formal, quero ainda assim receber um relatório parcial com os dados capturados até aquele ponto, em vez de perder tudo.

**Privacidade e conformidade**

32. Como estudante, quero que meus dados de telemetria fiquem criptografados em repouso (AES-256) no banco, para que fiquem protegidos mesmo em caso de acesso indevido à infraestrutura.
33. Como estudante, quero que a aplicação nunca grave imagem ou vídeo bruto meu, em nenhuma etapa do pipeline, para que minha privacidade visual seja preservada por design.

**Infraestrutura e disponibilidade**

34. Como time de desenvolvimento, quero que toda a infraestrutura AWS (S3, ECR, ECS Fargate, RDS) seja provisionada via Terraform, para que o ambiente seja reproduzível e portátil entre contas.
35. Como estudante, quero que o sistema mantenha alta disponibilidade (meta de 99,9% de uptime durante testes de estresse), para que uma sessão de estudo não seja interrompida por instabilidade do serviço.

## Implementation Decisions

- **Captura e extração de features (client-side):** Angular + `@mediapipe/face_mesh`, extraindo 468 landmarks faciais no navegador. Cálculo local de Eye Aspect Ratio (EAR), Head Pose (yaw/pitch) e Mouth Aspect Ratio (MAR). Apenas coordenadas numéricas saem do navegador — nunca frames de vídeo.
- **Transporte:** API RESTful (`@angular/common/http`) para autenticação e operações de CRUD; WebSockets (via `WebSocketManager` no FastAPI) para o streaming contínuo de telemetria durante a sessão.
- **Núcleo de inferência — `AnalistaEngajamento`:** classe Python que recebe o vetor de features normalizado e devolve o score do IEE e os alertas. Encapsula o modelo Random Forest (scikit-learn) e a lógica de cálculo — ver fórmula abaixo. Este módulo não depende de banco, WebSocket ou UI.
- **Fórmula do IEE:** `IEE(t) = P(t) × [(0.6 × EAR_norm) + (0.4 × HP_norm)] − F`, onde `P(t)` é presença facial binária (zera o índice se o rosto não for detectado), `EAR_norm` e `HP_norm` são normalizados contra a baseline individual do aluno (calibrada nos primeiros 60s), e `F` é a penalidade de fadiga vinda da classificação de padrões sequenciais atípicos (pálpebras fechadas prolongadas, bocejos via MAR) pelo Random Forest.
- **Persistência — `DatabaseConnector`:** PostgreSQL via `SQLModel` + `psycopg2-binary`. Schema: `aluno` (id, nome, email), `sessao_estudo` (id, id_aluno, inicio, fim), `log_engajamento` (id, id_sessao, horario_registro, score_aluno, flag_fadiga, alerta_gerado, direcao_olhar). Indexação temporal em `horario_registro`; particionamento mensal previsto para mitigar crescimento indefinido. Política de retenção: logs granulares são sumarizados em médias após o fim da sessão.
- **Autenticação:** JWT (`python-jose`) + hashing de senha (`passlib[bcrypt]`); `jwt-decode` no client para gerenciar sessão.
- **Modelo de ML:** Random Forest treinado e validado com o dataset público DAISEE (Gupta et al., 2016). Escolhido em vez de LSTM/GRU/Transformers por operar sobre vetores tabulares já extraídos (sem necessidade de processar sequências temporais na v1), por interpretabilidade (importância de features) e por inferência em milissegundos.
- **Infraestrutura:** AWS — S3 (hospedagem estática do frontend), ECR (registro de imagens Docker do backend), ECS Fargate (execução serverless do FastAPI), RDS (PostgreSQL gerenciado, criptografia AES-256 em repouso). Provisionamento via Terraform (IaC).
- **Privacidade/LGPD por design:** processamento client-side, ausência de armazenamento de imagem/vídeo bruto, identificadores pseudonimizados, dados visíveis apenas ao próprio estudante.

## Testing Decisions

- **Seam principal — `AnalistaEngajamento`:** testes unitários com vetores de features sintéticos (fixtures), cobrindo: engajamento normal, fadiga detectada (olhos fechados prolongados / bocejo recorrente), ausência de rosto (`P(t) = 0` zera o score), e variações de baseline (simulando usuários com óculos ou padrões atípicos). Este é o módulo mais valioso de testar isoladamente porque concentra a lógica de negócio (cálculo do IEE) sem depender de rede, banco ou UI — testar aqui primeiro.
- **Validação do modelo:** avaliação offline contra um split de validação do DAISEE, reportando acurácia, precisão, recall e F1-Score. Não é um teste unitário convencional, mas um relatório de validação versionado, com o gate de "precisão > 80%" referenciado na Definition of Done do plano de sprints.
- **Seam secundário — `WebSocketManager`:** teste de integração com um client de teste enviando payloads JSON simulados de landmarks, validando que o roteamento para `AnalistaEngajamento` e a chamada de persistência ocorrem corretamente.
- **Seam secundário — `DatabaseConnector`:** testes estilo repositório contra uma instância de PostgreSQL de teste, cobrindo `salvar_log` e `buscar_historico` — validando round-trip correto e a ausência de qualquer campo de imagem/vídeo bruto no schema.
- **Seam secundário — extração de features no frontend:** testes unitários em Angular/Jasmine para as funções de cálculo de EAR/HP/MAR a partir de arrays de landmarks fixos, validando que os valores numéricos batem com a fórmula esperada.
- **Testes funcionais/E2E (prioridade menor):** fluxo fumaça (login → iniciar sessão → autorizar webcam → encerrar → ver relatório) cobrindo a jornada completa; pode rodar manualmente nas sprints de teste ou via Cypress/Playwright contra o stack local.
- **Prior art:** nenhum — projeto greenfield, sem testes existentes para referenciar.

## Out of Scope

- **Exibir o score do IEE ao aluno durante a sessão de estudo** (retirada da história 20 em 27/08/2026, depois de implementada e avaliada). Um score de atenção na tela compete com a tarefa que ele mede: o aluno olha para o número, e o ato de olhar derruba o número — a medição interfere no medido. O gráfico também passa a disputar atenção com o material de estudo, que era o objetivo declarado da sessão. O feedback do sistema é **retrospectivo por decisão de projeto**: as métricas alimentam o relatório de autopercepção do fim da sessão (história 29), onde o aluno as lê com distância suficiente para agir sobre elas. Durante a sessão aparecem apenas avisos **operacionais e acionáveis** — preview da webcam, FPS e o alerta de Incerteza de Captura (história 17) —, que são diagnóstico do equipamento e existem para que a sessão não termine num relatório vazio.

  **Revisão de 21/09/2026.** O cronômetro do método de estudo, introduzido em 21/09/2026, **não cabe nessa exceção** — um cronômetro não é diagnóstico de equipamento, e esticar a exceção para acomodá-lo seria a desonestidade barata. Ele entra por uma razão própria, e a razão é o que torna a regra mais precisa em vez de mais frouxa: o argumento de 27/08 era o **laço de realimentação** — o aluno olha para o número, e o ato de olhar derruba o número. O cronômetro não tem esse laço, porque **nada do que ele mostra é derivado do comportamento medido do aluno**. Ele conduz um método que o próprio aluno escolheu e não afirma nada sobre ele. A régua passa a ser essa, e ela continua excluindo o score.
- Medir as dimensões cognitiva ou emocional do engajamento — a visão computacional não acessa esses constructos; o sistema mede apenas proxies comportamentais visuais.
- Qualquer forma de diagnóstico clínico (fadiga mental, TDAH, TEA ou outras condições de saúde).
- Comparação sistemática entre Random Forest, LSTM, GRU e Transformers temporais — adiada para o TC2.
- Acesso de terceiros (professores, coordenação, instituição) aos dados ou relatórios de um estudante — o sistema é estritamente individual e não tem papel de administrador/supervisor.
- Modelagem de custos de escala comercial ou alta disponibilidade de produção — esta é uma Prova de Conceito, não um MVP comercial.
- Suporte a múltiplos rostos simultâneos no quadro da webcam.
- Aplicativo mobile nativo — a solução é uma aplicação web para desktop/laptop com webcam.
- Gravação, upload ou reprodução de vídeo da sessão de estudo.

## Further Notes

- **Estado atual:** nenhum código existe ainda (confirmado nesta conversa) — este spec é a base de implementação para as 13 sprints semanais já planejadas (13/08 a 12/11/2026, com buffer até 15/11 para a banca).
- **Divisão de papéis já definida:** Matheus & Rian — frontend Angular, parte do backend, infraestrutura/deploy AWS; Chrystian — ML e dados (DAISEE, treino/validação do Random Forest, cálculo do IEE), parte do backend, apoio pontual em infra.
- **Risco conhecido e já documentado no pré-projeto:** o dataset DAISEE tem viés cultural/geográfico (contexto acadêmico indiano); os resultados de validação devem ser interpretados como evidência de viabilidade técnica em ambiente controlado, não como validade universal — isso deve constar explicitamente no relatório de validação da Sprint 7.
- **Meta mínima de sucesso:** PoC funcionando ponta a ponta ao menos localmente (webcam → landmarks → IEE → banco → relatório). O deploy na AWS é meta do plano, mas é tratado como stretch goal caso o cronograma das sprints 8–9 atrase.
- **Decisão pendente/deferida:** a fórmula do fator de fadiga (F) depende de thresholds que só podem ser calibrados com dados reais de teste — a recalibração está prevista para a Sprint 11 do plano de sprints, após os primeiros testes de usuário.
