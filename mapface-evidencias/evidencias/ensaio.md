# Ensaio 07/11

- Gravação: 22:58:42 → 23:01:58 (duração 03:16, horário local)
- Navegador: `Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36 Edg/156.0.0.0`
- CPU lógicas: 16 · memória declarada: 16 GB · tela: 1536x864@1.25
- Origem: https://d2qm0t6ecgabb2.cloudfront.net
- Build (/health): `f04a533`
- Página no download: `/relatorio/9`

## Captura no cliente

- FPS exibido na tela: média 47.4, mediana 49.0, p5 41.0, mínimo 0, máximo 63 (201 leituras de 1 s)
- Segundos abaixo de 15 FPS: 3 (1.5%)
- CPU: anotar à mão pelo Performance monitor (ver roteiro).

## Cobertura da medição

| Situação | Segundos | % do esperado |
| --- | ---: | ---: |
| Payloads esperados (1 por segundo de gravação) | 197 | 100% |
| Enviados com rosto e captura confiável | 177 | 89.8% |
| Enviados com incerteza (sem valor de índice) | 12 | 6.1% |
| Enviados sem rosto | 8 | 4.1% |
| Não enviados (lacuna de conexão/aba) | 0 | 0.0% |

Motivos de incerteza: reflexo-ocular = 9 s, oclusao = 3 s

## Canal WebSocket (ida e volta medida no navegador)

| Medida | p50 (ms) | p95 (ms) | Máx. (ms) | Média (ms) |
| --- | ---: | ---: | ---: | ---: |
| RTT (navegador) | 141.6 | 285.2 | 737.2 | 157.7 |
| Processamento (backend) | 11.1 | 151.6 | 606.3 | 28.1 |
| Rede + fila (RTT − processamento) | 129.0 | 138.4 | 144.6 | 129.7 |

- 197 respostas de score. O RTT já inclui o processamento; rede = RTT − processamento, sem somar nada duas vezes.
- Meta WebSocket ≤ 200 ms: 179 de 197 respostas
- Meta RNF06 backend ≤ 100 ms: 182 de 197 respostas
- O RTT inclui o tempo até o navegador processar a mensagem; com a aba em segundo plano ele infla.
- Payloads sem resposta registrada: 0

## Eventos de conexão e rede

| Instante | Desde o início | Evento |
| --- | ---: | --- |
| 22:58:40 | -00:02 | WS #0 aberta |
| 22:58:41 | -00:01 | WS #0 autenticada |
| 23:01:58 | 03:17 | WS #0 fechada (código 1005) |

## Calibração

- Calibração inicial concluída em: 01:38
- Não houve volta à calibração depois da inicial.

## O que o servidor devolveu

- IEE médio sobre pontos com valor: 86.7 (185 pontos; 12 pontos nulos por incerteza; cobertura 93.9%)
- Leitura de sonolência: média 0.579 em 123 segundos com valor

## Bocejos: marcados × detectados

- MAR com rosto: mediana 0.005, p99 0.153, máximo 0.165
- Regra reaplicada: MAR médio do segundo > 0.3 por ≥ 2 s (na prática, 2 payloads seguidos acima do limiar; a contagem acontece quando chega o payload seguinte)
- Bocejos marcados (tecla B): 1 · detecções do sistema: 0

**Detectados: 0 de 1** · não detectados: 1 · detecções sem bocejo marcado: 0

| Desde o início | Origem | Resultado |
| ---: | --- | --- |
| 03:07 | marcado | **não detectado** |

