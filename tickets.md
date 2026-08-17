# Tickets: Prova de Conceito — Índice de Engajamento no Estudo (IEE)

Quebra do spec [`spec-poc-iee.md`](./spec-poc-iee.md) em fatias verticais, em ordem de dependência. Duas trilhas rodam em paralelo até convergirem: **ML** (Chrystian) e **App/Infra** (Matheus & Rian, com apoio pontual de Chrystian no backend/infra).

Trabalhe a **fronteira**: qualquer ticket cujos bloqueadores já estejam concluídos pode começar. As tickets 1–2 (ML) não bloqueiam 3–7 (App) — só convergem na ticket 8.

## 1. Extração de features do DAISEE

**O que construir:** um pipeline offline que roda o MediaPipe Face Mesh sobre os vídeos do dataset DAISEE e produz um dataset tabular rotulado (EAR, Head Pose, MAR) pronto para treino.

**Bloqueada por:** Nenhuma — pode começar imediatamente.

- [ ] Dataset DAISEE baixado e organizado localmente
- [x] Pipeline extrai EAR, Head Pose (yaw/pitch) e MAR por frame via MediaPipe
- [x] Saída é um dataset tabular (CSV/parquet) com features + rótulos originais do DAISEE (engagement/boredom/confusion/frustration)
- [x] Pipeline é reproduzível via script, não um processo manual

O pipeline está em [`ml/`](./ml/) e roda com `python extrair_features.py --raiz <DAiSEE>`. Falta só o download do dataset, que exige o formulário de acesso do IIIT Hyderabad.

## 2. Treinar e validar Random Forest baseline

**O que construir:** o primeiro modelo Random Forest treinado e validado, com relatório de métricas.

**Bloqueada por:** Ticket 1.

- [ ] Random Forest treinado sobre o dataset tabular da Ticket 1
- [x] Split de treino/validação/teste definido e documentado
- [ ] Relatório com acurácia, precisão, recall e F1-Score
- [ ] Meta de precisão > 80% atingida, ou desvio justificado no relatório
- [x] Modelo serializado como artefato carregável pelo backend

O treino, as métricas e o relatório estão implementados em [`ml/`](./ml/) e rodam com `python treinar.py`. O que falta depende da ticket 1 estar de fato executada: sem o DAiSEE em disco não existe modelo treinado nem número de precisão para reportar. O split adotado é o do próprio DAiSEE (subject-independent), e a meta de 80% é medida sobre a **precisão macro** no `Test` — com ~85% de clipes "engajado", acurácia e precisão ponderada subiriam quase de graça.

## 3. Cadastro e login

**O que construir:** um estudante consegue criar conta, fazer login e acessar áreas protegidas da aplicação.

**Bloqueada por:** Nenhuma — pode começar imediatamente.

- [ ] Endpoint de registro (nome, e-mail, senha) com hashing bcrypt
- [ ] Endpoint de login retornando JWT
- [ ] Telas de cadastro e login em Angular
- [ ] Rotas protegidas redirecionam para login se o usuário não estiver autenticado
- [ ] Sessão de autenticação expira após período de inatividade

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

A regra vive em [`backend/app/analista.py`](./backend/app/analista.py), sem conhecer HTTP nem banco — é o seam principal do spec. O acumulador da calibração é **persistido** a cada payload (`backend/app/calibracao.py`), e não guardado na conexão: o WebSocket da ticket 6 reconecta sozinho, e um acumulador em memória reiniciaria os 60s a cada queda. O payload ganhou `pitch`, porque Head Pose é yaw *e* pitch — só com yaw, cabeça baixa e cabeça virada ficam indistinguíveis. `F` já tem encaixe na fórmula, valendo 0 até a ticket 8.

## 8. Fator de fadiga via Random Forest

**O que construir:** o modelo treinado na trilha ML entra em produção, penalizando o IEE quando padrões de fadiga (pálpebras fechadas prolongadas, bocejos) são detectados.

**Bloqueada por:** Ticket 7 e Ticket 2.

- [ ] Modelo da Ticket 2 carregado pelo backend
- [ ] `AnalistaEngajamento.validar_fadiga` classifica padrões sequenciais atípicos
- [ ] Fator F subtraído do score do IEE quando fadiga é detectada
- [ ] Testes unitários com sequências sintéticas de fadiga

## 9. Dashboard ao vivo

**O que construir:** o estudante vê seu score de IEE evoluindo em tempo real durante a sessão.

**Bloqueada por:** Ticket 7.

- [ ] Gráfico do IEE atualizado em tempo real (chart.js) durante a sessão
- [ ] Score numérico exibido ao vivo na interface

## 10. Tratamento de condições adversas

**O que construir:** em vez de gerar um score enganoso, o sistema sinaliza incerteza quando as condições de captura são ruins.

**Bloqueada por:** Ticket 7.

- [ ] Alerta de "Incerteza de Captura" em cenários de baixa luz, óculos reflexivos ou oclusão
- [ ] O alerta não é registrado como score corrompido no banco
- [ ] Score zera quando o rosto fica ausente por tempo prolongado

## 11. Relatório de autopercepção

**O que construir:** ao encerrar a sessão, o estudante recebe um relatório com indicadores, alertas e recomendações.

**Bloqueada por:** Ticket 8.

- [ ] Relatório gerado automaticamente ao encerrar a sessão
- [ ] Inclui gráfico do IEE, indicadores-chave e alertas de fadiga registrados
- [ ] Inclui recomendações básicas de autorregulação (pausas, mudança de estratégia)
- [ ] Relatório parcial é gerado mesmo se a sessão for interrompida por erro (queda de conexão, falha do navegador)

## 12. Histórico de sessões

**O que construir:** o estudante consegue revisitar relatórios de sessões passadas.

**Bloqueada por:** Ticket 11.

- [ ] Lista de sessões passadas do aluno autenticado
- [ ] Acesso ao relatório completo de cada sessão anterior

## 13. Sumarização e retenção de logs

**O que construir:** os logs granulares deixam de se acumular indefinidamente, sendo resumidos após o fim de cada sessão.

**Bloqueada por:** Ticket 11.

- [ ] Logs granulares (segundo a segundo) sumarizados em médias após o encerramento da sessão
- [ ] Indexação/particionamento temporal em `horario_registro`

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
