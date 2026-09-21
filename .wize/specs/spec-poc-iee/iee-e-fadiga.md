# IEE e fadiga — definição operacional

Companion de `SPEC.md` (CAP-4, CAP-5, CAP-6). Catálogo de limiares e regras: não cabe no kernel.

## A fórmula

```
IEE(t) = P(t) × [ (0,6 × EAR_norm) + (0,4 × HP_norm) ] − F
```

| Termo | O que é | Por que assim |
|---|---|---|
| `P(t)` | Presença facial binária | Sem rosto não há comportamento observável. Zera o índice em vez de estimar |
| `EAR_norm` | Abertura ocular relativa à baseline | Peso principal (0,6): é o proxy mais direto de fixação visual |
| `HP_norm` | Desvio angular da cabeça (yaw/pitch) relativo à baseline | Peso secundário (0,4) |
| `F` | Penalidade de fadiga | Subtraída, limitada a 40 pontos |

Escala de 0 a 100. O 100 é estabilidade visual máxima em relação à tela; o 0 é ausência facial ou
dispersão total.

## Calibração da baseline

Os primeiros 60 segundos da sessão calibram silenciosamente o padrão neutro do estudante — EAR e
inclinação natural da cabeça.

**Usa a mediana, não a média.** As piscadas do minuto de calibração puxariam o EAR neutro para
baixo e inflariam o score da sessão inteira. A mediana é indiferente a elas.

**Ausência durante a calibração recalibra.** Se o estudante sai do quadro, o sistema espera e
recomeça quando o rosto volta, em vez de fixar uma baseline com dado incompleto.

**A baseline sobrevive à reconexão.** O analista é mantido por sessão entre conexões, para que a
reconexão automática do canal não jogue fora a calibração a cada oscilação de rede.

> Limitação conhecida: esse estado vive em memória de processo. Com mais de uma réplica, trocar de
> instância recomeça a calibração no meio da sessão. Ver `risk-spots.md`.

## As três regras de fadiga

`F` vem de regras diretas sobre a série de EAR e MAR. Os três sinais somam e são limitados a 40.

| Sinal | Regra | Por que existe |
|---|---|---|
| **PERCLOS** | Proporção do último minuto com a pálpebra fechada | A métrica clássica de sonolência |
| **Microssono** | Um fechamento contínuo de 2 s ou mais | A proporção dilui um episódio único e longo; este o pega |
| **Bocejo** | MAR acima do limiar por 2 s | Dois segundos é tempo suficiente para não ser fala |

### Dois limiares que valem a defesa

**Olho fechado é metade da abertura neutra do estudante**, não o 0,20 absoluto da literatura. Quem
tem EAR neutro de 0,18 estaria permanentemente "de olhos fechados" sob um limiar fixo — o mesmo
problema que a calibração individual resolve no score.

**Ausência de rosto não conta como olho fechado** e não entra no denominador do PERCLOS. Sem rosto
não sabemos o que a pálpebra fazia. Contar ausência como fechamento transformaria "saiu para pegar
água" em "cochilou".

## Incerteza de captura (CAP-6)

O julgamento mora no navegador, porque é onde a imagem existe: dos quatro números que sobem por
segundo é impossível separar "aluno de olhos semicerrados" de "sala escura e detector chutando o
contorno da pálpebra". O que atravessa a rede é o veredito, nunca a evidência — a luminância
medida morre no cliente.

Três sinais, com precedência causal (pouca luz *produz* os outros dois, então vem primeiro):

1. Luminância média do quadro
2. Taxa de detecção dentro da janela
3. Assimetria entre os olhos — é o que denuncia reflexo de óculos: as duas pálpebras descem juntas
   ao piscar, mas só uma lente reflete

**Ausência não é incerteza.** Rosto ausente é uma medição verdadeira (o `P(t) = 0`) e zera o score.
Incerteza é a recusa de afirmar qualquer coisa: grava score nulo com o motivo.

**A leitura incerta não entra em lugar nenhum** — não calibra baseline, não conta como pálpebra
fechada no PERCLOS, não vira ponto da série.

## Por que regras e não o Random Forest

O spec original previa `F` vindo de um classificador treinado no DAiSEE. A medição registrada em
`resultado_18_08.md` desfez a premissa: no split de teste o modelo empata com um classificador que
responde sempre "engajado" (0,4753 de precisão macro, ambos). Um `F` derivado dele seria
**constante**, e a penalidade de fadiga seria código morto.

Além disso, o modelo prevê *engajamento* — construto subjetivo, com teto de ~0,72 mesmo partindo de
anotação humana sobre o mesmo clipe. Fadiga é estado físico observável: "a pálpebra ficou fechada
por mais de dois segundos" tem resposta objetiva, verificável e explicável ao estudante.

## Pendência aberta

`LIMIAR_MAR_BOCEJO = 0,30`, escolhido a partir da distribuição observada no DAiSEE (p99,9 = 0,2884).
O valor herdado de 0,60 disparava em 7 clipes de 8570 — bocejo nenhum, em ~24 horas de vídeo.

Duas coisas seguem abertas:

- O 0,30 vem de distribuição, não de bocejos observados. Precisa de recalibração empírica com dados
  reais de teste.
- `ml/esquema.py` ainda usa 0,60 para a mesma grandeza, apesar de `ml/metricas.py` se declarar a
  referência de implementação. Duas fontes de verdade divergentes.
