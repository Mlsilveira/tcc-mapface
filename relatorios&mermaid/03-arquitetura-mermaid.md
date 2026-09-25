# Arquitetura em Mermaid — duas versões

Duas leituras do mesmo sistema, no formato enxuto do diagrama original. Sem a
camada de pesquisa offline: aqui está só o que roda.

A versão longa, com a trilha de ML e as divergências em relação ao pré-projeto,
está em [`arquitetura.md`](../arquitetura.md) na raiz.

---

## Versão 1 — completa

Abrange a arquitetura inteira: as quatro camadas do desenho original, mais a
borda HTTPS que o produto exige para existir.

```mermaid
graph TD
    subgraph Interface["Interface (Client/Browser)"]
        A["Angular"]
        B["MediaPipe FaceLandmarker"]
    end

    subgraph Borda["Borda (HTTPS, origem unica)"]
        CF["AWS CloudFront"]
        LB["AWS ALB"]
    end

    subgraph Processamento["Processamento (AWS Cloud)"]
        D["FastAPI (AWS ECS Fargate)"]
        AN["AnalistaEngajamento<br/>baseline + formula do IEE"]
        FA["DetectorDeFadiga<br/>PERCLOS, fechamento, bocejo"]
        SO["ClassificadorDeSonolencia<br/>ExtraTrees, 39 features"]
        H["AWS ECR"]
    end

    subgraph Dados["Inteligencia e Dados"]
        G["AWS S3<br/>build do Angular"]
        F["PostgreSQL (AWS RDS)<br/>AES-256 em repouso"]
        SM["AWS Secrets Manager"]
    end

    subgraph DevOps["Gerenciamento (IaC)"]
        T["Terraform"]
    end

    T -.->|Provisiona| Borda
    T -.->|Provisiona| Processamento
    T -.->|Provisiona| Dados
    G -.->|Origem do site| CF
    H -.->|Entrega imagem Docker| D
    SM -.->|Senha do banco| D

    CF -->|SPA em HTTPS| A
    A -->|Video, nunca sai da maquina| B
    B -->|"9 numeros/s, wss"| CF
    CF -->|"/auth /sessoes /telemetria"| LB
    LB --> D
    D --> AN
    AN -->|"F entra no indice"| FA
    D -->|"janela de 10s"| SO
    SO -.->|"leitura paralela"| D
    D <-->|Persistencia| F
    D -->|"Score + sonolencia, 1 Hz"| CF
    CF -->|Feedback em tempo real| A

    classDef pendente stroke-dasharray: 5 5
    class D,LB pendente
```

**Como ler as setas.** Linha cheia é caminho de requisição; tracejada é
provisionamento ou leitura que não entra na conta. Nó com contorno tracejado
ainda não foi construído (ticket 15).

**As três coisas que o diagrama afirma:**

1. O vídeo para no navegador. Do `MediaPipe` para fora saem nove números.
2. O CloudFront é caminho obrigatório, não otimização — é ele que entrega o
   HTTPS sem o qual a webcam não liga.
3. O `ClassificadorDeSonolencia` tem seta tracejada de volta: ele **não** entra
   na fórmula do índice.

---

## Versão 2 — resumida

O sistema em seis caixas, para slide e para abertura de capítulo.

```mermaid
graph LR
    A["Navegador<br/>Angular + MediaPipe"]
    CF["CloudFront<br/>HTTPS"]
    D["FastAPI<br/>ECS Fargate"]
    ML["IEE + fadiga<br/>+ sonolencia"]
    F["PostgreSQL<br/>RDS"]
    T["Terraform"]

    A -->|"9 numeros/s"| CF
    CF --> D
    D --> ML
    ML --> F
    D -->|"score"| CF
    CF --> A
    T -.->|Provisiona| CF
    T -.->|Provisiona| D
    T -.->|Provisiona| F
```

**A frase que acompanha este slide:** *o rosto é processado no navegador, o
servidor recebe só números, e a infraestrutura inteira sobe com um comando.*

---

## Nota de renderização

Os dois blocos foram renderizados com Mermaid 11 antes de entrar aqui. O GitHub
e o Mermaid Live Editor aceitam os dois como estão; para exportar em alta
resolução para a monografia, use o [Mermaid Live Editor](https://mermaid.live)
com fundo transparente e formato SVG.
