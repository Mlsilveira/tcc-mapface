# Sessão na versão final (sessão 28, build f2b675e)

- Gravação: 21:59:21 → 22:14:25 (duração 15:04, horário local)
- Navegador: `Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36 Edg/157.0.0.0`
- CPU lógicas: 16 · memória declarada: 16 GB · tela: 1536x864@1.25
- Origem: https://d2qm0t6ecgabb2.cloudfront.net
- Build (/health): `f2b675e`
- Página no download: `/relatorio/28`

## Captura no cliente

- FPS exibido na tela: média 46.9, mediana 47.0, p5 40.0, mínimo 0, máximo 60 (907 leituras de 1 s)
- Segundos abaixo de 15 FPS: 11 (1.2%)
- CPU: anotar à mão pelo Performance monitor (ver roteiro).

## Cobertura da medição

| Situação | Segundos | % do esperado |
| --- | ---: | ---: |
| Payloads esperados (1 por segundo de gravação) | 905 | 100% |
| Enviados com rosto e captura confiável | 898 | 99.2% |
| Enviados com incerteza (sem valor de índice) | 0 | 0.0% |
| Enviados sem rosto e sem incerteza (índice zero) | 0 | 0.0% |
| Não enviados (lacuna de conexão/aba) | 7 | 0.8% |

## Canal WebSocket (ida e volta medida no navegador)

| Medida | p50 (ms) | p95 (ms) | Máx. (ms) | Média (ms) |
| --- | ---: | ---: | ---: | ---: |
| RTT (navegador) | 150.1 | 335.8 | 625.6 | 176.2 |
| Processamento (backend) | 10.1 | 189.4 | 402.1 | 28.9 |
| Rede + fila (RTT − processamento) | 138.0 | 205.2 | 541.9 | 147.3 |

- 898 respostas de score. O RTT já inclui o processamento; rede = RTT − processamento, sem somar nada duas vezes.
- Meta WebSocket ≤ 200 ms: 750 de 898 respostas
- Meta RNF06 backend ≤ 100 ms: 810 de 898 respostas
- O RTT inclui o tempo até o navegador processar a mensagem; com a aba em segundo plano ele infla.
- Payloads sem resposta registrada: 0

## Eventos de conexão e rede

| Instante | Desde o início | Evento |
| --- | ---: | --- |
| 21:59:20 | -00:01 | WS #0 aberta |
| 21:59:20 | -00:01 | WS #0 autenticada |
| 22:06:57 | 07:36 | navegador aba-hidden |
| 22:07:07 | 07:46 | navegador aba-visible |
| 22:14:26 | 15:05 | WS #0 fechada (código 1005) |

Lacunas na série (vão > 2.5 s entre payloads):

- 22:06:57 (em 07:36): 3.1 s sem dados
- 22:07:00 (em 07:39): 4.0 s sem dados
- 22:07:04 (em 07:43): 3.2 s sem dados

## Calibração

- Calibração inicial concluída em: 01:01
- Não houve volta à calibração depois da inicial.

## O que o servidor devolveu

- IEE médio sobre pontos com valor: 92.4 (898 pontos; 0 pontos nulos por incerteza; cobertura 100.0%)
- Segundos com cada motivo de fadiga ativo: bocejos = 119
- Leitura de sonolência: média 0.540 em 823 segundos com valor

## Bocejos: marcados × detectados

- MAR com rosto: mediana 0.004, p99 0.041, máximo 1.017
- Regra do backend: MAR médio do segundo > 0.3 por ≥ 2 s. Com 1 leitura por segundo, um bocejo de exatamente 2 leituras fica no limite e pode não contar.
- Detecções lidas de: servidor (fadiga +8 com motivo bocejos)
- Bocejos marcados (tecla B): 0 · detecções do sistema: 2

**Detectados: 0 de 0** · não detectados: 0 · detecções sem bocejo marcado: 2

| Desde o início | Origem | Resultado |
| ---: | --- | --- |
| 09:09 | detecção sem marca | sem marca próxima |
| 13:55 | detecção sem marca | sem marca próxima |

