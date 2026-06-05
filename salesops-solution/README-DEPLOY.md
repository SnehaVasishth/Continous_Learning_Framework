# Deploy

Single container image (FastAPI + bundled React SPA) deployable to any cloud container platform.

## Environment

All runtime knobs are read from environment variables. See [`.env.example`](.env.example) for the full list. The most important ones for production:

| Var | Purpose |
| --- | --- |
| `APP_AUTH_ENABLED` | `true` to enforce bearer-token auth on every `/api/*` route |
| `APP_AUTH_TOKEN` | 32+ char random string clients send as `Authorization: Bearer <token>` |
| `APP_CORS_ORIGINS` | Comma-separated list of allowed browser origins |
| `APP_BASE_URL` | Public URL the app is reachable at |
| `APP_LOG_FORMAT` | `json` (production) or `text` (dev) |
| `DATABASE_URL` | `postgresql://user:pass@host:5432/db` — blank falls back to local SQLite |
| `EMAIL_SECRET_KEY` | Fernet key for at-rest secret encryption (must persist across restarts) |

Liveness: `GET /api/health` → `{"ok": true}`
Readiness: `GET /api/ready` → DB ping + connector status

## Local

```bash
cp .env.example .env
# fill in APP_AUTH_TOKEN and EMAIL_SECRET_KEY
docker-compose up --build
```

App at <http://localhost:8000>. The compose file ships a Postgres 16 sidecar; the app container talks to it via `DATABASE_URL`.

## Google Cloud Run

```bash
# 1. Build & push
gcloud builds submit --tag gcr.io/PROJECT_ID/keysight-salesops:latest

# 2. Deploy with env vars (use --set-secrets for the sensitive ones)
gcloud run deploy keysight-salesops \
  --image gcr.io/PROJECT_ID/keysight-salesops:latest \
  --region us-central1 --platform managed --allow-unauthenticated \
  --set-env-vars APP_AUTH_ENABLED=true,APP_LOG_FORMAT=json,APP_CORS_ORIGINS=https://app.example.com \
  --set-secrets APP_AUTH_TOKEN=app-auth-token:latest,EMAIL_SECRET_KEY=email-secret-key:latest,DATABASE_URL=database-url:latest

# 3. Verify
curl https://YOUR-CLOUDRUN-URL/api/ready
```

Use Cloud SQL (Postgres) connector for `DATABASE_URL`. Mount `backend/data/uploads` and `backend/data/outputs` to a GCS bucket via `gcsfuse` or migrate to `STORAGE_BACKEND=s3`/`azure_blob` in phase-2.

## Azure App Service (containers)

```bash
# 1. ACR push
az acr build --registry MYREGISTRY --image keysight-salesops:latest .

# 2. App Service config
az webapp config container set --name keysight-salesops --resource-group RG \
  --docker-custom-image-name MYREGISTRY.azurecr.io/keysight-salesops:latest
az webapp config appsettings set --name keysight-salesops --resource-group RG --settings \
  APP_AUTH_ENABLED=true APP_LOG_FORMAT=json \
  APP_AUTH_TOKEN=@Microsoft.KeyVault(SecretUri=...) \
  EMAIL_SECRET_KEY=@Microsoft.KeyVault(SecretUri=...) \
  DATABASE_URL=@Microsoft.KeyVault(SecretUri=...) \
  WEBSITES_PORT=8000

# 3. Restart
az webapp restart --name keysight-salesops --resource-group RG
```

Pair with Azure Database for PostgreSQL Flexible Server.

## AWS ECS (Fargate)

```bash
# 1. ECR push
aws ecr get-login-password | docker login --username AWS --password-stdin ACCOUNT.dkr.ecr.REGION.amazonaws.com
docker build -t keysight-salesops .
docker tag keysight-salesops:latest ACCOUNT.dkr.ecr.REGION.amazonaws.com/keysight-salesops:latest
docker push ACCOUNT.dkr.ecr.REGION.amazonaws.com/keysight-salesops:latest

# 2. Task definition (relevant container snippet)
{
  "name": "app",
  "image": "ACCOUNT.dkr.ecr.REGION.amazonaws.com/keysight-salesops:latest",
  "portMappings": [{"containerPort": 8000, "protocol": "tcp"}],
  "environment": [
    {"name": "APP_AUTH_ENABLED", "value": "true"},
    {"name": "APP_LOG_FORMAT", "value": "json"},
    {"name": "APP_CORS_ORIGINS", "value": "https://app.example.com"}
  ],
  "secrets": [
    {"name": "APP_AUTH_TOKEN", "valueFrom": "arn:aws:secretsmanager:...:app-auth-token"},
    {"name": "EMAIL_SECRET_KEY", "valueFrom": "arn:aws:secretsmanager:...:email-secret-key"},
    {"name": "DATABASE_URL", "valueFrom": "arn:aws:secretsmanager:...:database-url"}
  ],
  "healthCheck": {"command": ["CMD-SHELL", "curl -f http://localhost:8000/api/health || exit 1"]}
}

# 3. Service
aws ecs create-service --cluster CLUSTER --service-name keysight-salesops \
  --task-definition keysight-salesops:1 --desired-count 1 --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[...],securityGroups=[...],assignPublicIp=ENABLED}" \
  --load-balancers targetGroupArn=...,containerName=app,containerPort=8000
```

Pair with RDS Postgres for `DATABASE_URL`.

## Hardening checklist (before real customer traffic)

- [ ] Rotate `EMAIL_SECRET_KEY` (and re-enrol email accounts — old ciphertext becomes unreadable)
- [ ] Set `APP_AUTH_ENABLED=true` and ship `APP_AUTH_TOKEN` via your secret manager
- [ ] Switch `DATABASE_URL` to managed Postgres (Cloud SQL / Azure Flexible / RDS)
- [ ] Lock down `APP_CORS_ORIGINS` to your real frontend domain only
- [ ] Set `APP_LOG_FORMAT=json` and pipe logs to your aggregator (Cloud Logging / App Insights / CloudWatch)
- [ ] Wire `/api/ready` to the platform's readiness probe; `/api/health` to liveness
- [ ] Move `STORAGE_BACKEND` from `local` to `s3` or `azure_blob` (phase-2) so uploads survive container churn
- [ ] Set up monitoring & alerting (out of scope for this scaffolding)
- [ ] Replace bearer-token auth with SSO (phase-2)
