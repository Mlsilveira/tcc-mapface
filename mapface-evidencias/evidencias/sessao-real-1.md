# Sessão real 1

- Gravação: 12:17:50 → 12:32:40 (duração 14:50, horário local)
- Navegador: `Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36 Edg/157.0.0.0`
- CPU lógicas: 16 · memória declarada: 16 GB · tela: 1536x864@1.25
- Origem: https://d2qm0t6ecgabb2.cloudfront.net
- Build (/health): `f04a533`
- Página no download: `/relatorio/10`

## Captura no cliente

- FPS exibido na tela: média 34.3, mediana 32.0, p5 28.0, mínimo 0, máximo 59 (894 leituras de 1 s)
- Segundos abaixo de 15 FPS: 3 (0.3%)
- CPU: anotar à mão pelo Performance monitor (ver roteiro).

## Cobertura da medição

| Situação | Segundos | % do esperado |
| --- | ---: | ---: |
| Payloads esperados (1 por segundo de gravação) | 891 | 100% |
| Enviados com rosto e captura confiável | 723 | 81.1% |
| Enviados com incerteza (sem valor de índice) | 3 | 0.3% |
| Enviados sem rosto | 165 | 18.5% |
| Não enviados (lacuna de conexão/aba) | 0 | 0.0% |

Motivos de incerteza: reflexo-ocular = 2 s, oclusao = 1 s

## Canal WebSocket (ida e volta medida no navegador)

| Medida | p50 (ms) | p95 (ms) | Máx. (ms) | Média (ms) |
| --- | ---: | ---: | ---: | ---: |
| RTT (navegador) | 160.8 | 310.4 | 819.0 | 178.3 |
| Processamento (backend) | 10.6 | 140.4 | 595.6 | 24.0 |
| Rede + fila (RTT − processamento) | 149.0 | 213.3 | 310.2 | 154.2 |

- 891 respostas de score. O RTT já inclui o processamento; rede = RTT − processamento, sem somar nada duas vezes.
- Meta WebSocket ≤ 200 ms: 765 de 891 respostas
- Meta RNF06 backend ≤ 100 ms: 816 de 891 respostas
- O RTT inclui o tempo até o navegador processar a mensagem; com a aba em segundo plano ele infla.
- Payloads sem resposta registrada: 0

## Eventos de conexão e rede

| Instante | Desde o início | Evento |
| --- | ---: | --- |
| 12:17:49 | -00:01 | WS #0 aberta |
| 12:17:49 | -00:01 | WS #0 autenticada |
| 12:32:41 | 14:51 | WS #0 fechada (código 1005) |

## Calibração

- Calibração inicial concluída em: 01:00
- Não houve volta à calibração depois da inicial.

## O que o servidor devolveu

- IEE médio sobre pontos com valor: 73.4 (888 pontos; 3 pontos nulos por incerteza; cobertura 99.7%)
- Segundos com cada motivo de fadiga ativo: bocejos = 131, olhos-fechados-prolongados = 58
- Leitura de sonolência: média 0.606 em 818 segundos com valor

## Bocejos: marcados × detectados

- MAR com rosto: mediana 0.005, p99 0.955, máximo 1.189
- Regra do backend: MAR médio do segundo > 0.3 por ≥ 2 s. Com 1 leitura por segundo, um bocejo de exatamente 2 leituras fica no limite e pode não contar.
- Detecções lidas de: servidor (fadiga +8 com motivo bocejos)
- Bocejos marcados (tecla B): 6 · detecções do sistema: 3

**Detectados: 2 de 6** · não detectados: 4 · detecções sem bocejo marcado: 1

| Desde o início | Origem | Resultado |
| ---: | --- | --- |
| 03:19 | marcado | detectado +4 s |
| 04:50 | marcado | **não detectado** |
| 06:52 | marcado | **não detectado** |
| 06:55 | marcado | **não detectado** |
| 13:38 | detecção sem marca | sem marca próxima |
| 13:47 | marcado | detectado +6 s |
| 13:52 | marcado | **não detectado** |

Outras marcas: fala × 2, sorriso × 2, livre × 2, comer-beber × 2
- marca livre em 06:57
- marca livre em 07:06

