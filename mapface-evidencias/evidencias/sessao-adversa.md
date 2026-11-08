# Sessão adversa

- Gravação: 13:34:46 → 13:46:51 (duração 12:05, horário local)
- Navegador: `Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36 Edg/157.0.0.0`
- CPU lógicas: 16 · memória declarada: 16 GB · tela: 1536x864@1.25
- Origem: https://d2qm0t6ecgabb2.cloudfront.net
- Build (/health): `f04a533`
- Página no download: `/relatorio/12`

## Captura no cliente

- FPS exibido na tela: média 36.9, mediana 34.0, p5 29.0, mínimo 0, máximo 62 (728 leituras de 1 s)
- Segundos abaixo de 15 FPS: 2 (0.3%)
- CPU: anotar à mão pelo Performance monitor (ver roteiro).

## Cobertura da medição

| Situação | Segundos | % do esperado |
| --- | ---: | ---: |
| Payloads esperados (1 por segundo de gravação) | 725 | 100% |
| Enviados com rosto e captura confiável | 579 | 79.9% |
| Enviados com incerteza (sem valor de índice) | 118 | 16.3% |
| Enviados sem rosto e sem incerteza (índice zero) | 28 | 3.9% |
| Não enviados (lacuna de conexão/aba) | 0 | 0.0% |

Motivos de incerteza: baixa-luz = 118 s

Dos 118 s com incerteza, 115 também não tinham rosto: o servidor os grava como incertos, não como ausência.

## Canal WebSocket (ida e volta medida no navegador)

| Medida | p50 (ms) | p95 (ms) | Máx. (ms) | Média (ms) |
| --- | ---: | ---: | ---: | ---: |
| RTT (navegador) | 161.0 | 365.5 | 649.6 | 182.6 |
| Processamento (backend) | 10.5 | 184.7 | 490.6 | 27.8 |
| Rede + fila (RTT − processamento) | 147.8 | 217.2 | 409.5 | 154.8 |

- 725 respostas de score. O RTT já inclui o processamento; rede = RTT − processamento, sem somar nada duas vezes.
- Meta WebSocket ≤ 200 ms: 616 de 725 respostas
- Meta RNF06 backend ≤ 100 ms: 663 de 725 respostas
- O RTT inclui o tempo até o navegador processar a mensagem; com a aba em segundo plano ele infla.
- Payloads sem resposta registrada: 0

## Eventos de conexão e rede

| Instante | Desde o início | Evento |
| --- | ---: | --- |
| 13:34:45 | -00:01 | WS #0 aberta |
| 13:34:45 | -00:01 | WS #0 autenticada |
| 13:46:52 | 12:06 | WS #0 fechada (código 1005) |

## Calibração

- Calibração inicial concluída em: 01:00
- Não houve volta à calibração depois da inicial.

## O que o servidor devolveu

- IEE médio sobre pontos com valor: 87.8 (607 pontos; 118 pontos nulos por incerteza; cobertura 83.7%)
- Leitura de sonolência: média 0.520 em 651 segundos com valor

## Bocejos: marcados × detectados

- MAR com rosto: mediana 0.004, p99 0.019, máximo 0.108
- Regra do backend: MAR médio do segundo > 0.3 por ≥ 2 s. Com 1 leitura por segundo, um bocejo de exatamente 2 leituras fica no limite e pode não contar.
- Detecções lidas de: servidor (fadiga +8 com motivo bocejos)
- Bocejos marcados (tecla B): 0 · detecções do sistema: 0

## Cobertura por condição (teclas 1 a 9)

| Condição | Início | Duração (s) | Confiável (%) | Incerta (%) | Sem rosto (%) | Não enviado (%) | Motivo de incerteza dominante | Calibrando no trecho? |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| 1 — Luz normal | 00:00 | 128 | 100.0% | 0.0% | 0.0% | 0.0% | — | sim |
| 2 — Pouca luz | 02:08 | 296 | 99.3% | 0.7% | 0.0% | 0.0% | baixa-luz (2 s) | não |
| 3 — Mão no rosto inteiro | 07:04 | 29 | 6.9% | 0.0% | 93.1% | 0.0% | — | não |
| 4 — Mão em metade do rosto | 07:33 | 30 | 100.0% | 0.0% | 0.0% | 0.0% | — | não |
| 5 — Reflexo nos óculos | 08:04 | 60 | 100.0% | 0.0% | 0.0% | 0.0% | — | não |
| 6 — Fora da câmera | 09:03 | 119 | 1.7% | 97.5% | 0.8% | 0.0% | baixa-luz (116 s) | não |
| 7 — Volta com luz normal | 11:02 | 64 | 98.4% | 0.0% | 0.0% | 1.6% | — | não |

Percentuais sobre a duração do trecho; uma tecla de condição apertada duas vezes abre dois trechos.
