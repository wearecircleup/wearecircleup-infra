# Wearecircleup Infra

Repositorio dedicado a infraestructura y despliegue cloud de Circle Up.

Incluye:

- `infra/`: Terraform para `prod`
- `eventbrite_api/`: API de Eventbrite desplegada en Lambda + API Gateway
- `.github/workflows/`: flujos de `plan/apply` y `destroy`

## Importante

El role OIDC de AWS debe confiar en este repo, no en el repo frontend anterior.

El `sub` esperado en la trust policy debe quedar asi:

```json
"token.actions.githubusercontent.com:sub": "repo:wearecircleup/wearecircleup-infra:ref:refs/heads/main"
```

## Estructura

- [infra/README.md](infra/README.md)
- [eventbrite_api/README.md](eventbrite_api/README.md)
