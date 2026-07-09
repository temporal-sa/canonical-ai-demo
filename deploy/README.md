# Deploying to the shared EKS cluster (tmprl-demo-cloud-registry)

The registry is a **GitOps platform**, not a plain image registry. You don't write
Kubernetes manifests, push images, or run `kubectl`. You commit **one `DemoProject`
YAML** ([`canonical-ai-demo.yaml`](./canonical-ai-demo.yaml)) and the platform operator
builds the images (CodeBuild → ECR), provisions a Temporal Cloud namespace + API key,
renders the Deployments/Services, syncs secrets, runs a smoke check, and publishes the
route at `https://canonical-ai-demo.tmprl-demo.cloud`.

## What ships (three components, one project)

| Component | What | Exposure |
|---|---|---|
| `app` | FastAPI gateway **+ the web UI**, served same-origin | Public route, **Google-auth gated** |
| `worker` | the agent loop + activities (LLM, tools, DB writes) | internal |
| `postgres` | Chinook, self-seeding, single ephemeral pod | internal (`postgres:5432`) |

The web UI and API are one image on one origin, so there's a single public hostname and
no CORS. The browser gets `BACKEND_URL=""` from the gateway's dynamic `/config.js`.

## Prerequisites (these are on you — org/AWS access)

1. **Push this repo to a `temporal-sa` GitHub repo** matching `spec.source.repo`
   (default `https://github.com/temporal-sa/canonical-ai-demo`). CodeBuild clones it.

2. **Create two AWS Secrets Manager secrets** (region `us-west-1`, account `429214323166`):

   | Secret name | JSON |
   |---|---|
   | `tmprl-dem-cld/canonical-ai-demo/anthropic-credentials` | `{"ANTHROPIC_API_KEY": "sk-ant-..."}` |
   | `tmprl-dem-cld/canonical-ai-demo/db-creds` | `{"POSTGRES_USER": "demo", "POSTGRES_PASSWORD": "<pick one>"}` |

## Deploy

Copy the CR into the registry repo and open a PR:

```bash
cp deploy/canonical-ai-demo.yaml \
   <path-to>/tmprl-demo-cloud-registry/projects/demo/canonical-ai-demo.yaml
# commit + PR in that repo; on merge, Flux + the operator take over.
```

## Auth & LLM-token protection

`ingress.temporalAuthRequired: true` gates the public route behind **Google/Gmail OAuth**
— anonymous internet traffic can't reach the agent, so it can't burn your Anthropic token.
The gate also forwards the verified user's email as `X-Temporal-Auth-Email`, which the
gateway uses as the customer identity — so each demoer is isolated by their real login,
no sign-in step in the app.

> ⚠️ The platform has **no built-in rate limiting**. Auth keeps the public out, but any
> logged-in temporal.io user could still run up tokens. Fine for an internal demo; if you
> want defense-in-depth, add a backend rate-limit keyed on `X-Temporal-Auth-Email`.

## Notes & caveats

- **Data is ephemeral.** The Postgres pod re-seeds if replaced; per-email isolation keeps
  concurrent demoers' orders separate. No scheduled reset (by design).
- **Temporal is Cloud, not in-cluster.** `worker:true` / `temporalAccess:true` inject the
  address/namespace/API-key; `config.py` reads them unchanged.
- **Building locally** (to test images before pushing): the cluster is amd64, so
  `docker buildx build --platform linux/amd64 -f docker/app.Dockerfile .` — but you don't
  push manually; CodeBuild builds on merge.
- **`config.py` is the only env-reader.** Local dev (`make up`) is unchanged; the discrete
  `DB_*` vars here are composed into `DB_URL` only when `DB_URL` isn't set directly.
