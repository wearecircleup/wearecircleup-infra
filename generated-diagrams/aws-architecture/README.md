# Circle Up AWS architecture

Este paquete contiene solo diagramas de infraestructura AWS. No incluye reglas de negocio, formularios, decisiones operativas de UI ni actores humanos.

## Diagramas

- [01-runtime-overview.png](C:/Users/gocir/Documents/wearecircleup-infra/generated-diagrams/aws-architecture/01-runtime-overview.png)
- [02-ingress-and-handlers.png](C:/Users/gocir/Documents/wearecircleup-infra/generated-diagrams/aws-architecture/02-ingress-and-handlers.png)
- [03-async-processing.png](C:/Users/gocir/Documents/wearecircleup-infra/generated-diagrams/aws-architecture/03-async-processing.png)
- [04-data-and-ai.png](C:/Users/gocir/Documents/wearecircleup-infra/generated-diagrams/aws-architecture/04-data-and-ai.png)

## Regla de lectura

- Solo servicios AWS.
- `API Gateway` representa entrypoints HTTP desplegados.
- `Lambda` representa handlers y workers.
- `SQS` y `EventBridge` representan asincronía.
- `DynamoDB`, `S3`, `SES`, `Bedrock`, `Textract`, `Secrets Manager` y `CloudWatch` representan dependencias compartidas.

## Script

- [render-aws-architecture.py](C:/Users/gocir/Documents/wearecircleup-infra/generated-diagrams/aws-architecture/render-aws-architecture.py)
