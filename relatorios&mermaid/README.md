# Relatórios e diagramas

Material de apoio para a monografia e para a defesa. Quatro documentos, cada um
respondendo a uma pergunta diferente.

| Documento | Pergunta que responde | Para quem |
| --- | --- | --- |
| [01 — O código da aplicação](./01-o-codigo-da-aplicacao.md) | O que cada arquivo faz, e por onde começar a estudar | Quem vai mexer ou defender o código |
| [02 — O projeto e a banca](./02-o-projeto-e-a-banca.md) | Para que serve, o que dá para medir, o que perguntam e como responder | Quem vai escrever a monografia e apresentar |
| [03 — Arquitetura em Mermaid](./03-arquitetura-mermaid.md) | Como o sistema se organiza, em duas versões | Slides e capítulo de arquitetura |
| [04 — O treinamento do Random Forest](./04-o-treinamento-do-random-forest.md) | O que foi tentado no ML, o que falhou, e por quê | Capítulo de metodologia e resultados |
| [05 — Linha do tempo](./05-linha-do-tempo.md) | Que feature entrou quando, o que ela quebrou e o que a quebra ensinou | Capítulo de desenvolvimento e cronograma |

## Ordem sugerida de leitura

Para **entender o projeto**: 05 → 02 → 03 → 04 → 01. A linha do tempo primeiro dá
o contexto de *por que* o sistema é como é antes de você ver *o que* ele é.

Para **mexer no código**: 01 → 03, e depois 04 se for tocar na trilha de ML.

Para **preparar a defesa**: 02 inteiro, depois a seção 7 do 04 (as armadilhas) e as
dez descobertas do 05 — é de lá que saem as melhores respostas sobre rigor
metodológico.

## Documentos relacionados, fora desta pasta

- [`../spec-poc-iee.md`](../spec-poc-iee.md) — o problema, as 35 histórias de
  usuário e as decisões de arquitetura originais
- [`../tickets.md`](../tickets.md) — as 17 fatias verticais, com o que foi
  decidido em cada uma
- [`../arquitetura.md`](../arquitetura.md) — o diagrama completo, incluindo a
  trilha offline e as divergências em relação ao pré-projeto
- [`../resultado_18_08.md`](../resultado_18_08.md) — a investigação do DAiSEE
- [`../resultado_sonolencia.md`](../resultado_sonolencia.md) — a grade completa
  do UTA-RLDD

## Uma observação sobre os números

Toda métrica citada nestes relatórios vem de um artefato gerado por script e
versionado — não de memória nem de estimativa. Onde um número é uma projeção ou
uma estimativa por proxy, isso está dito na mesma frase.
