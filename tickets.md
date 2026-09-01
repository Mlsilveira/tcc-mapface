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
