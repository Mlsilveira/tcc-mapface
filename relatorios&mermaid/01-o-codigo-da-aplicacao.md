# O código do MapFace, explicado

Guia de leitura do repositório: o que cada arquivo faz, por que ele existe onde
está, quais trechos carregam decisão de verdade, e em que ordem estudar tudo
isso sem se perder.

Escrito para quem vai **defender** este código, não só rodá-lo.

---

## Sumário

1. [Por onde começar](#1-por-onde-começar)
2. [O mapa de três camadas](#2-o-mapa-de-três-camadas)
3. [Frontend — o que roda no navegador](#3-frontend--o-que-roda-no-navegador)
4. [Backend — o que roda no servidor](#4-backend--o-que-roda-no-servidor)
5. [Trilha de ML — o que roda offline](#5-trilha-de-ml--o-que-roda-offline)
6. [Infraestrutura](#6-infraestrutura)
7. [Os dez trechos que mais importam](#7-os-dez-trechos-que-mais-importam)
8. [As ferramentas, e por que cada uma](#8-as-ferramentas-e-por-que-cada-uma)
9. [Roteiro de estudo em cinco sessões](#9-roteiro-de-estudo-em-cinco-sessões)

---

## 1. Por onde começar

**Não comece pelo `main.py`.** Ele tem 52 linhas e não explica nada.

Comece por **`backend/app/analista.py`**. É o coração do produto: a fórmula do
IEE, a calibração do aluno e o detector de fadiga moram ali, em 702 linhas de
Python puro que não sabem o que é HTTP, banco ou navegador. Se você entender
esse arquivo, entendeu o que o sistema mede.

Depois leia **`frontend/src/app/core/visao/metricas.ts`** (240 linhas): é a
aritmética que transforma 478 pontos de um rosto em três números. Os dois
arquivos juntos são o TCC inteiro; o resto é encanamento — bom encanamento, mas
encanamento.

> **A regra que organiza o repositório:** regra de negócio não conhece
> framework. `analista.py`, `sessoes.py`, `relatorio.py`, `presenca.py`,
> `criterios.py` e `blocos.py` não importam FastAPI nem SQLModel. É por isso
> que a suíte roda em 60 segundos e que os testes falam de comportamento em vez
> de falarem de requisições.

---

## 2. O mapa de três camadas

```
frontend/   Angular 18    o que o aluno vê, e onde o rosto é processado
backend/    FastAPI       o que decide, calcula e guarda
ml/         scikit-learn  o que treina os modelos, offline, fora da aplicação
infra/      Terraform     onde tudo isso vai rodar
```

Tamanhos, para calibrar expectativa:

| Camada | Código | Testes |
| --- | --- | --- |
| Backend | 5.828 linhas | 6.591 linhas, 426 testes |
| Frontend | 3.963 linhas | 5.815 linhas, 326 testes |
| ML | 5.056 linhas | 3.523 linhas, 244 testes |
| Infra | ~600 linhas de HCL | validado com `terraform validate` |

**Há mais teste que código em todas as camadas.** Isso é intencional e é
material de defesa: boa parte dos testes existe para travar uma decisão, não
para cobrir uma linha.

---

## 3. Frontend — o que roda no navegador

### 3.1 O caminho do rosto até o número

Quatro arquivos, em ordem de execução:

**`core/services/camera.service.ts`** (244 linhas) — pede a webcam, trata cada
tipo de falha com mensagem própria e, quando o dispositivo escolhido não abre,
**tenta os outros**. Esse fallback nasceu de um caso real: três câmeras
listadas, duas respondendo `NotReadableError`, e a sessão morrendo sem
explicação.

**`core/visao/landmarks.service.ts`** (410 linhas) — a única peça que conhece o
MediaPipe. Carrega o `FaceLandmarker`, roda o laço de captura e publica
leituras. Trocar a biblioteca de visão computacional mexe **neste arquivo e em
nenhum outro**.

**`core/visao/metricas.ts`** (240 linhas) — aritmética pura sobre pontos:

```ts
EAR = (|p2-p6| + |p3-p5|) / (2 · |p1-p4|)
MAR = (|13-14| + |81-178| + |311-402|) / (3 · |61-291|)
```

Não importa MediaPipe, não importa Angular. É testável com um array de pontos
inventado — e é assim que está testado.

**`core/visao/qualidade.ts`** (121 linhas) — decide se a leitura é confiável.
Luz baixa, reflexo no óculos, oclusão parcial. É o coração da história 17: o
sistema **se abstém** em vez de emitir um número enganoso.

### 3.2 O canal de telemetria

**`core/telemetria/agregacao.ts`** (156 linhas) — junta as amostras de 250 ms
numa leitura por segundo. Duas decisões escritas ali valem a leitura:

- quadros **sem rosto ficam fora da média** (contá-los como zero puxaria o EAR
  para baixo e viraria "sonolência" no score);
- o MAR vai pela **média**, não pelo pico — um único quadro em que o MediaPipe
  errou o contorno do lábio viraria bocejo fantasma.

**`core/telemetria/telemetria.service.ts`** (333 linhas) — o WebSocket, com
reconexão exponencial e autenticação **pela primeira mensagem**. Token em query
string vazaria para log de servidor e histórico do navegador; o WebSocket do
navegador não permite header `Authorization`; a primeira mensagem é o único
lugar limpo.

### 3.3 As telas

**`pages/home/home.component.ts`** (672 linhas — o maior arquivo do frontend) —
declara método e assunto, conduz o ciclo de blocos, mostra o cronômetro e o
preview. É grande porque orquestra muita coisa; a lógica do ciclo está separada
em `pages/home/ciclo.ts` (93 linhas), que é puro.

**`pages/relatorio/relatorio.component.ts`** (143 linhas) + o HTML — o relatório
de autopercepção: curva, indicadores, sinais e recomendações.

**`core/api.ts`** (56 linhas) — pequeno e importante: deriva o endereço do
backend de **onde a própria página está**. Sem ele, o bundle do Angular
carregaria uma URL fixa e o mesmo build não serviria para local e nuvem.

---

## 4. Backend — o que roda no servidor

### 4.1 O núcleo: `analista.py` (702 linhas)

O arquivo mais importante do repositório. Quatro peças:

**`Baseline`** — o padrão neutro do aluno, calibrado na mediana dos primeiros
60 segundos. Mediana e não média: um único quadro com landmark mal detectado
desloca a média e não move a mediana.

**`calcular_iee`** — a fórmula:

```
IEE(t) = P(t) × [0,6 · EAR_norm + 0,4 · HP_norm] − F
```

`P(t)` é presença binária: sem rosto, o índice zera (história 18). `EAR_norm` e
`HP_norm` são medidos **contra a baseline do próprio aluno**, que é o que a
história 13 protege — quem tem EAR neutro de 0,18 não é penalizado por um
limiar fixo de 0,20.

**`DetectorDeFadiga`** — o fator `F`, de regras, sobre uma janela de 60 s:

| Sinal | O que mede | Penalidade |
| --- | --- | --- |
| PERCLOS | proporção do minuto com pálpebra fechada | até 25 pontos |
| Microssono | fechamento contínuo ≥ 2 s | 15 pontos |
| Bocejo | MAR acima do limiar por ≥ 2 s | 10 por episódio |

Duas decisões de defesa: o limiar de olho fechado é **metade da abertura neutra
do aluno**, não o 0,20 absoluto da literatura; e **ausência de rosto não conta
como olho fechado** nem entra no denominador do PERCLOS — contar ausência como
fechamento transformaria "saiu pegar água" em "cochilou".

**`RegistroDeAnalistas`** — um analista por sessão, entre conexões. Sem ele,
cada queda de rede jogaria a baseline fora. Limpeza preguiçosa, sem processo de
fundo.

### 4.2 O ciclo de vida da sessão

**`sessoes.py`** (442 linhas) — regras puras: iniciar, encerrar, varredura de
inativas. **`metodos.py`** (177) — o catálogo de métodos de estudo, que é quem
define a pausa máxima tolerada. **`blocos.py`** (220) — o vocabulário de foco e
pausa. **`presenca.py`** (111) — a distinção que sustenta o relatório: *duração
total* (aba aberta) versus *duração presente* (captura de fato).

> **O bug que a ticket 17 matou.** A atividade da sessão era renovada a cada
> payload recebido — e o navegador manda payload válido mesmo sem rosto. Cadeira
> vazia com a janela aberta renovava a sessão indefinidamente, e o relatório
> contava a tarde inteira como estudo. Hoje quem mantém a sessão viva é **rosto
> na câmera**, com o limite vindo do método declarado.

### 4.3 Relatório e retenção

**`relatorio.py`** (267) — `resumir(sessao, serie)` é função pura: série entra,
indicadores saem. **`recomendacoes.py`** (236) — os nomes dos alertas e os
textos de autorregulação. **`criterios.py`** (615) — a avaliação por blocos e
todas as frases dela. **`sumarizacao.py`** (225) — congela os indicadores no
encerramento e, passadas 24 horas, troca os pontos por segundo por médias por
minuto (história 25).

> **Por que congelar.** Média de médias não é média. Recalcular os indicadores
> sobre a série já colapsada daria números *parecidos* com os originais, e
> parecido é a pior categoria de errado num relatório que o aluno vai comparar
> com o da semana passada.

### 4.4 O classificador de sonolência

**`janela.py`** (276) — monta as 39 features a partir da telemetria de 1 Hz,
com a mesma calibração de 60 segundos do IEE. Código puro, sem scikit-learn.

**`sonolencia.py`** (166) — a única peça do backend que conhece scikit-learn.
Carrega o `.joblib`, recusa artefato incompatível e devolve `None` quando não
há modelo — a aplicação inteira funciona sem ele.

> **A separação inteira desta parte, em uma frase:** o `F` que desconta do IEE
> vem das regras; a leitura do modelo é registrada e mostrada **ao lado**. Há
> teste travando isso — com e sem modelo, o score sai idêntico.

### 4.5 Infraestrutura do próprio código

**`database.py`** (301) — engine e **migração leve**: acrescenta colunas que os
modelos ganharam, preenche obrigatórias, afrouxa as que viraram opcionais e
destrava as órfãs. Tem um cadeado consultivo para o rolling update do ECS não
rodar dois `ALTER TABLE` ao mesmo tempo.

**`security.py`** (205) — bcrypt e JWT com **janela deslizante e teto
absoluto**: o token renova enquanto o aluno usa, mas nenhuma credencial vive
mais de 12 horas depois do login.

**`routers/`** — três arquivos finos. Eles validam entrada, chamam as regras e
serializam saída. Nenhuma decisão de produto mora ali.

---

## 5. Trilha de ML — o que roda offline

Ambiente próprio (`ml/.venv`), porque MediaPipe e OpenCV somam centenas de MB e
não entram na imagem do backend.

**Extração** — `daisee.py` e `rldd.py` leem cada dataset do disco;
`extracao.py` roda o MediaPipe frame a frame; `metricas.py` faz a matemática;
`agregacao.py` resume em janelas; **`agregacao_producao.py`** refaz a agregação
como o backend a veria (médias por segundo, e não frames a 6 fps).

**Treino** — `treino.py` (engajamento, DAiSEE) e `treino_fadiga.py`
(sonolência, UTA-RLDD). `combinado.py` põe os dois datasets na mesma mesa.

**Relatório** — `relatorio.py` e `relatorio_fadiga.py` formatam; quem mede não
formata.

O detalhe completo está em [`04-o-treinamento-do-random-forest.md`](./04-o-treinamento-do-random-forest.md).

---

## 6. Infraestrutura

`infra/` em Terraform, quatro módulos: `rede` (VPC própria, sem NAT Gateway),
`site` (S3 privado + CloudFront), `registro` (ECR), `banco` (RDS PostgreSQL com
AES-256).

**O CloudFront não é enfeite.** O endpoint de site estático do S3 serve apenas
HTTP, e o navegador só libera `getUserMedia` em contexto seguro. Sem ele, o
produto carrega, faz login, deixa iniciar a sessão e falha na única coisa que
existe para fazer.

---

## 7. Os dez trechos que mais importam

Se o tempo for curto, leia estes:

| # | Onde | O que decide |
| --- | --- | --- |
| 1 | `analista.py` → `calcular_iee` | A fórmula inteira do produto |
| 2 | `analista.py` → `Baseline` | Por que o índice é relativo ao aluno |
| 3 | `analista.py` → `DetectorDeFadiga._avaliar` | Os três sinais de fadiga e seus limiares |
| 4 | `metricas.ts` → `calcularEAR` / `calcularMAR` | De 478 pontos a três números |
| 5 | `agregacao.ts` → `agregar` | O que sai do navegador — a fronteira de privacidade |
| 6 | `relatorio.py` → `_episodios` | Por que "47 bocejos" virou "3 episódios" |
| 7 | `presenca.py` → `duracao_presente` | A diferença entre aba aberta e estudo |
| 8 | `sumarizacao.py` → `congelar` | Por que média de médias não é média |
| 9 | `database.py` → `_relaxar_obrigatoriedade` | Como o banco sobrevive a mudanças de modelo |
| 10 | `treino_fadiga.py` → `normaliza` | Por que a calibração offline imita a de produção |

---

## 8. As ferramentas, e por que cada uma

| Ferramenta | Papel | Por que ela, e não outra |
| --- | --- | --- |
| **Angular 18** | Frontend | Standalone components e signals; o processamento do rosto precisa ficar no cliente, e o framework não atrapalha |
| **MediaPipe FaceLandmarker** | Visão computacional | Roda no navegador via WASM. É o que torna a promessa de privacidade **estrutural**: sem ele, o vídeo teria que subir |
| **FastAPI** | API | Assíncrono de origem — o WebSocket de telemetria a 1 Hz por aluno é o caso de uso central |
| **SQLModel** | ORM | Um tipo serve de modelo de tabela e de schema; menos duplicação entre banco e API |
| **SQLite → PostgreSQL** | Banco | SQLite na PoC, sem servidor; a troca é uma `DATABASE_URL` |
| **bcrypt + JWT** | Autenticação | Hashing com custo ajustável e token sem estado no servidor |
| **scikit-learn** | ML | Random Forest e ExtraTrees sobre vetores tabulares; interpretabilidade via importância de features, inferência em milissegundos |
| **pandas + PyArrow** | Dados | Parquet para os datasets intermediários — 514 mil linhas cabem em 31 MB |
| **Terraform** | Infra | História 34 pede ambiente reproduzível e portátil entre contas |
| **pytest / Karma+Jasmine** | Testes | O padrão de cada ecossistema |

---

## 9. Roteiro de estudo em cinco sessões

**Sessão 1 — o que o sistema mede** *(2 h)*
`analista.py` inteiro, depois `metricas.ts`. Ao final você deve conseguir
explicar a fórmula do IEE de cabeça e dizer por que a baseline existe.

**Sessão 2 — o caminho do dado** *(2 h)*
`landmarks.service.ts` → `agregacao.ts` → `telemetria.service.ts` →
`routers/telemetria.py` → `telemetria.py`. Siga uma leitura da webcam até o
banco. Pergunta-guia: *em que ponto exato o vídeo deixa de existir?*

**Sessão 3 — o ciclo de vida e o relatório** *(2 h)*
`sessoes.py`, `presenca.py`, `metodos.py`, `relatorio.py`, `sumarizacao.py`.
Pergunta-guia: *o que impede uma cadeira vazia de virar três horas de estudo?*

**Sessão 4 — a trilha de ML** *(3 h)*
[`resultado_18_08.md`](../resultado_18_08.md) e
[`resultado_sonolencia.md`](../resultado_sonolencia.md) primeiro, o código
depois. Os relatórios explicam **por que** cada coisa é como é; o código sozinho
não.

**Sessão 5 — nuvem e privacidade** *(1,5 h)*
`infra/README.md`, `infra/modules/site/main.tf`, e os dois testes que travam a
fronteira de privacidade (`test_telemetria.py::test_schema_do_log_...` e
`agregacao.spec.ts`). Pergunta-guia: *o que impede alguém de adicionar um campo
de imagem sem ninguém notar?*

---

### Um conselho final

Os comentários deste repositório não descrevem o que o código faz — isso o
código já diz. Eles registram **o que foi considerado e descartado**, e por quê.
Quando encontrar um comentário longo, ele provavelmente está guardando a
resposta de uma pergunta que a banca vai fazer.
