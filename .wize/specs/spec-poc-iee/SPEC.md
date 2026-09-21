---
slug: "poc-iee"
status: draft
owner: "Matheus"
companions:
  - iee-e-fadiga.md
  - estado-de-implementacao.md
  - ../../knowledge/document-project/architecture-snapshot.md
  - ../../knowledge/document-project/conventions.md
  - ../../knowledge/document-project/risk-spots.md
  - ../../../spec-poc-iee.md
  - ../../../tickets.md
  - ../../../ml/README.md
  - ../../../resultado_18_08.md
sources:
  - spec-poc-iee.md
  - tickets.md
  - ml/README.md
  - resultado_18_08.md
  - Plano_de_Sprints_TCC.pdf
  - revisao-arquitetura-2026-08-13.pdf
  - "TCC_EM_ABNT (1).pdf"
  - .wize/knowledge/document-project/
assumptions:
  - "O critério de aceite do modelo será renegociado: precisão macro > 0,80 é substituível por acurácia balanceada > 0,65 com recall da classe minoritária reportado. Proposto em resultado_18_08.md, ainda não aceito formalmente pela orientação."
  - "Deploy em nuvem é stretch goal. O critério mínimo de sucesso é a PoC funcionando ponta a ponta, ao menos localmente (spec-poc-iee.md:124)."
  - "CAP-11 permanece no contrato mesmo sendo stretch, porque o capítulo 8 do TCC a lista como evidência de sucesso."
open_questions:
  - "A Definition of Done troca a métrica do modelo? (orientação)"
  - "Deploy em nuvem é requisito de banca ou stretch? (orientação + equipe)"
  - "Quem detém conta e orçamento de nuvem? (equipe)"
  - "O DAiSEE e os artefatos de treino ainda existem em disco? ml/dados e ml/artefatos estão vazios. (Chrystian)"
  - "LIMIAR_MAR_BOCEJO = 0,30 será recalibrado com dados reais? (Chrystian)"
  - "O cronograma de 13 sprints será replanejado? O plano previa relatório em 24/09 e deploy em 15/10. (equipe + orientação)"
---

# SPEC — poc-iee

## Why

Estudantes que estudam sozinhos em ambientes digitais têm pouca capacidade de perceber quando
perderam o foco. Notificações, abas abertas e conteúdo fragmentado corroem a atenção de forma
gradual e silenciosa: o aluno continua diante da tela enquanto o envolvimento cai, sem que ele
note, até o tempo de estudo já ter deixado de ser produtivo.

Não existe ferramenta acessível, não invasiva e eticamente responsável que devolva ao estudante
um retrato objetivo do próprio comportamento durante o estudo autônomo. As alternativas ou são
clínicas, caras e intrusivas (EEG, biossensores), ou servem à vigilância institucional — nenhuma
atende quem estuda em casa, sozinho, e quer apenas entender os próprios padrões.

O MapFace é um espelho retrospectivo para esse estudante. Mede proxies comportamentais visuais
pela webcam e devolve a leitura a ele, e só a ele.

## Capabilities

| ID | Intent | Success |
|---|---|---|
| CAP-1 | O estudante cria conta e acessa apenas os próprios dados | Registro e login funcionam; senha nunca trafega ou repousa em claro; área protegida redireciona quem não está autenticado; sessão de acesso expira por inatividade |
| CAP-2 | O estudante controla quando está sendo observado | Inicia e encerra a sessão de estudo com um clique; sessão fica associada a ele; inatividade prolongada encerra automaticamente em vez de registrar sessão fantasma |
| CAP-3 | Os sinais visuais são extraídos sem que imagem alguma saia do dispositivo | Abertura ocular, orientação da cabeça e abertura da boca são calculadas no navegador a ≥ 15 FPS; nenhum frame, imagem ou vídeo atravessa a rede em nenhuma etapa |
| CAP-4 | A medida é relativa ao próprio estudante, não a um padrão genérico | O padrão neutro é calibrado silenciosamente no início da sessão; quem usa óculos, tem assimetria facial ou é neurodivergente não é penalizado por isso; ausência durante a calibração faz recalibrar em vez de calibrar com dado incompleto |
| CAP-5 | O sistema produz um índice contínuo de engajamento observável | Índice de 0 a 100 combinando estabilidade ocular e orientação da cabeça contra a baseline individual, com penalidade de fadiga; ausência de rosto zera o índice |
| CAP-6 | O sistema se recusa a medir quando não pode medir bem | Em pouca luz, reflexo em lente ou oclusão parcial, a leitura é registrada como incerta com o motivo, nunca como score; a leitura incerta não calibra baseline, não conta como fadiga e não vira ponto da série |
| CAP-7 | Uma instabilidade de rede não custa a sessão | O canal de telemetria reconecta sozinho e a calibração sobrevive à reconexão; dados já capturados não se perdem |
| CAP-8 | O que é gravado não identifica nem expõe o estudante | O schema não tem campo para imagem, vídeo ou landmark bruto; os registros ficam sob identificadores numéricos; os dados repousam cifrados |
| CAP-9 | Ao fim da sessão o estudante recebe uma leitura sobre a qual pode agir | Relatório automático com a curva do índice ao longo do tempo, indicadores-chave, alertas de fadiga registrados e recomendações básicas de autorregulação; sessão interrompida por erro ainda gera relatório parcial |
| CAP-10 | O estudante acompanha a própria evolução | Lista das sessões anteriores e acesso ao relatório completo de cada uma |
| CAP-11 | O ambiente é reproduzível por comando, não por passo manual | A infraestrutura sobe a partir de código versionado, sem intervenção manual, e uma sessão completa funciona no ambiente publicado |

## Constraints

- **Nenhuma imagem ou vídeo atravessa a fronteira do navegador, em nenhuma etapa.** Só números
  agregados sobem. Isso não é uma preferência de implementação: é o que sustenta a promessa de
  privacidade do projeto e a conformidade com a LGPD, e elimina do desenho qualquer arquitetura
  que envie frames para inferência no servidor.
- **A medida é sempre relativa à baseline do próprio estudante**, nunca a um limiar absoluto da
  literatura. Um limiar fixo classificaria como "olho fechado" quem simplesmente tem abertura
  ocular menor.
- **Durante a sessão, nada na tela é derivado do comportamento medido do estudante.** Nada de
  score ou gráfico ao vivo — ver o número compete com a tarefa que o número mede, e o ato de olhar
  derruba o número. Preview, FPS e alerta de captura passam porque são diagnóstico de equipamento.
  O cronômetro do método de estudo (21/09/2026) passa por outra razão: ele conduz um método que o
  próprio estudante escolheu e não afirma nada sobre ele — não há laço de realimentação, porque
  nada do que ele mostra vem da medição. O score continua fora, e a régua reformulada é mais
  precisa que a anterior, não mais frouxa.
- **O sistema não tem papel de professor, coordenação ou administrador.** Não é uma lacuna a
  preencher depois; é o que separa autopercepção de vigilância.
- **A webcam exige contexto seguro.** Sem HTTPS (ou localhost) não há captura, logo não há
  produto. Qualquer topologia de publicação precisa resolver isso antes de qualquer outra coisa.
- **O fator de fadiga vem de regras sobre sinais físicos observáveis, não do classificador.**
  Medição em `resultado_18_08.md`: o modelo empata com um classificador constante, então a
  penalidade derivada dele seria constante e o mecanismo seria código morto.
- **Isto é uma Prova de Conceito acadêmica com prazo de banca**, não um MVP comercial.
  Escala, custo operacional e alta disponibilidade comercial não são requisitos.

## Non-goals

- Exibir o score ao estudante durante a sessão de estudo — retirado do produto em 27/08/2026,
  depois de implementado e avaliado.
- Medir as dimensões cognitiva ou emocional do engajamento. O que a webcam capta são proxies
  comportamentais visuais, e o índice não deve ser lido como engajamento em sentido pleno.
- Qualquer diagnóstico clínico — fadiga mental, TDAH, TEA ou outra condição.
- Comparação sistemática entre Random Forest, LSTM, GRU e Transformers temporais — adiada ao TC2.
- Acesso de terceiros (professor, coordenação, instituição) aos dados de um estudante.
- Modelagem de custos de escala comercial ou alta disponibilidade de produção.
- Suporte a múltiplos rostos simultâneos no quadro.
- Aplicativo mobile nativo.
- Gravação, upload ou reprodução de vídeo da sessão.

## Success signal

Uma sessão de estudo completa, demonstrável de ponta a ponta: o estudante entra, autoriza a
webcam, estuda, encerra — e recebe um relatório com a curva do índice, indicadores e
recomendações, sem que nenhuma imagem tenha saído do navegador e sem que o banco contenha
qualquer dado bruto de imagem.

Roda ao menos localmente; publicado em nuvem é o alvo estendido (CAP-11).

Para a trilha de modelo, o sinal é honesto por construção: qualquer número de precisão vem
acompanhado do recall, porque precisão isolada é satisfazível pelo silêncio.

## Companions

**Escritos por esta spec:**

- `iee-e-fadiga.md` — a fórmula, a calibração e as três regras de fadiga, com os limiares e o
  porquê de cada um. Catálogo de mais de uma linha, logo não cabe no kernel.
- `estado-de-implementacao.md` — o mapa capacidade → ticket → estado em 19/09/2026. Existe porque
  a fonte declara "nenhum código existe ainda", o que deixou de ser verdade.

**Adotados (donos externos, não editados aqui):**

- `spec-poc-iee.md` — as 35 histórias de usuário na forma original e as decisões de teste.
- `tickets.md` — as 16 fatias verticais, dependências e o racional de cada decisão tomada.
- `ml/README.md` e `resultado_18_08.md` — a trilha de ML, a contestação da meta de 80% e o achado
  do detector de bocejo.
- `.wize/knowledge/document-project/architecture-snapshot.md` — componentes, endpoints e o fluxo
  de dados ponta a ponta (diagramas moram aqui, por regra).
- `.wize/knowledge/document-project/conventions.md` — as convenções que o código pratica.
- `.wize/knowledge/document-project/risk-spots.md` — riscos mapeados com confiança.

## Decision log

Ver `.decision-log.md`.
