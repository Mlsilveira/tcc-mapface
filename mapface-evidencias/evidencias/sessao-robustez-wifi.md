# Robustez Wi-Fi

- Gravação: 14:03:50 → 14:08:25 (duração 04:35, horário local)
- Navegador: `Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36 Edg/157.0.0.0`
- CPU lógicas: 16 · memória declarada: 16 GB · tela: 1536x864@1.25
- Origem: https://d2qm0t6ecgabb2.cloudfront.net
- Build (/health): `f04a533`
- Página no download: `/relatorio/13`

## Captura no cliente

- FPS exibido na tela: média 31.3, mediana 32.0, p5 26.0, mínimo 0, máximo 37 (278 leituras de 1 s)
- Segundos abaixo de 15 FPS: 1 (0.4%)
- CPU: anotar à mão pelo Performance monitor (ver roteiro).

## Cobertura da medição

| Situação | Segundos | % do esperado |
| --- | ---: | ---: |
| Payloads esperados (1 por segundo de gravação) | 277 | 100% |
| Enviados com rosto e captura confiável | 235 | 84.8% |
| Enviados com incerteza (sem valor de índice) | 0 | 0.0% |
| Enviados sem rosto e sem incerteza (índice zero) | 0 | 0.0% |
| Não enviados (lacuna de conexão/aba) | 42 | 15.2% |

## Canal WebSocket (ida e volta medida no navegador)

| Medida | p50 (ms) | p95 (ms) | Máx. (ms) | Média (ms) |
| --- | ---: | ---: | ---: | ---: |
| RTT (navegador) | 173.4 | 6097.1 | 10093.6 | 780.0 |
| Processamento (backend) | 10.9 | 128.2 | 222.3 | 22.5 |
| Rede + fila (RTT − processamento) | 158.3 | 6087.9 | 9913.3 | 757.5 |

- 185 respostas de score. O RTT já inclui o processamento; rede = RTT − processamento, sem somar nada duas vezes.
- Meta WebSocket ≤ 200 ms: 133 de 185 respostas
- Meta RNF06 backend ≤ 100 ms: 175 de 185 respostas
- O RTT inclui o tempo até o navegador processar a mensagem; com a aba em segundo plano ele infla.
- Payloads sem resposta registrada: 50

## Eventos de conexão e rede

| Instante | Desde o início | Evento |
| --- | ---: | --- |
| 14:03:49 | -00:01 | WS #0 aberta |
| 14:03:49 | -00:01 | WS #0 autenticada |
| 14:05:24 | 01:34 | navegador offline |
| 14:05:43 | 01:53 | WS #0 fechada (código 1006) |
| 14:06:09 | 02:19 | navegador online |
| 14:06:19 | 02:29 | WS #1 aberta |
| 14:06:19 | 02:30 | WS #1 autenticada |
| 14:06:51 | 03:01 | navegador offline |
| 14:06:57 | 03:07 | navegador online |
| 14:07:10 | 03:20 | navegador offline |
| 14:07:39 | 03:49 | WS #1 fechada (código 1006) |
| 14:07:41 | 03:51 | navegador online |
| 14:07:43 | 03:53 | WS #2 aberta |
| 14:07:43 | 03:53 | WS #2 autenticada |
| 14:08:16 | 04:26 | navegador offline |
| 14:08:20 | 04:30 | navegador online |
| 14:08:26 | 04:36 | WS #2 fechada (código 1005) |

Lacunas na série (vão > 2.5 s entre payloads):

- 14:05:43 (em 01:53): 37.5 s sem dados
- 14:07:38 (em 03:49): 5.9 s sem dados

## Calibração

- Calibração inicial concluída em: 01:01
- Não houve volta à calibração depois da inicial.

## O que o servidor devolveu

- IEE médio sobre pontos com valor: 96.9 (185 pontos; 0 pontos nulos por incerteza; cobertura 100.0%)
- Leitura de sonolência: média 0.444 em 109 segundos com valor

## Bocejos: marcados × detectados

- MAR com rosto: mediana 0.005, p99 0.052, máximo 0.085
- Regra do backend: MAR médio do segundo > 0.3 por ≥ 2 s. Com 1 leitura por segundo, um bocejo de exatamente 2 leituras fica no limite e pode não contar.
- Detecções lidas de: servidor (fadiga +8 com motivo bocejos)
- Bocejos marcados (tecla B): 0 · detecções do sistema: 0

