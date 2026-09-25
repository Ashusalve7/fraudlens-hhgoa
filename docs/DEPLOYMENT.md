# FraudLens deployment: Cloudflare Pages + Render

This repository is configured for a split deployment:

- **Cloudflare Pages:** React/Vite frontend from `fraudlens/dashboard/dist`
- **Render:** FastAPI backend from `fraudlens/dashboard/app.py`

The checked-in `wrangler.toml` and `render.yaml` contain no credentials.

## Before either deploy

1. Rotate the TigerGraph credential that was pasted into chat. Do not reuse it.
2. Create a new dedicated runtime credential in TigerGraph/Savanna.
3. Keep the new secret only in Render environment variables. Never put it in `.env`, a command transcript, a screenshot, a Git commit, or a Cloudflare environment variable.
4. Confirm the old credential is rejected from a clean process.

## Render backend

### Blueprint deployment

1. Push the final commit to the GitHub repository connected to Render.
2. In Render, choose **New → Blueprint** and select the repository.
3. Render reads [`render.yaml`](../render.yaml). Set the prompted variables in Render:

   - `TG_HOST`: the dedicated TigerGraph runtime host
   - `TG_SECRET`: the newly rotated dedicated secret
   - `TG_GRAPHNAME`: `FraudGraph`
   - `FRAUDLENS_ALLOWED_ORIGINS`: the exact Cloudflare Pages origin, for example `https://fraudlens-hhgoa.pages.dev`
   - `FRAUDLENS_API_TOKEN`: leave unset for the public read-only demo; if set, use a server-side proxy rather than embedding it in the frontend

4. Deploy the service and wait for the health check:

```text
https://<render-service-name>.onrender.com/health
```

A healthy response has JSON with `ready: true` when the graph is reachable. The Render free plan can sleep; the dashboard displays retry/unavailable states instead of pretending the graph is live.

## Cloudflare Pages frontend

### One-time project creation

Install/login with Wrangler without writing credentials into the repository:

```powershell
npx.cmd wrangler login
npx.cmd wrangler whoami
npx.cmd wrangler pages project create fraudlens-hhgoa
```

If the project already exists, skip the create command.

### Build and deploy

Set the Render URL as a build-time variable. The frontend uses it for `/api` calls; do not use `localhost` in a public build.

```powershell
$env:VITE_API_BASE_URL = "https://<render-service-name>.onrender.com"
npm.cmd run build --prefix fraudlens/dashboard
npx.cmd wrangler pages deploy fraudlens/dashboard/dist --project-name fraudlens-hhgoa --branch main
Remove-Item Env:VITE_API_BASE_URL
```

The `public/_redirects` file makes direct visits to `/cases/HHG-014` and `/analytics` load the React app instead of returning a Pages 404.

After Cloudflare gives the Pages URL, set that exact origin in Render's `FRAUDLENS_ALLOWED_ORIGINS` and redeploy/restart Render. If a custom domain is added later, add that origin as a second comma-separated value.

## Verification

Run these checks without printing any secret:

```powershell
Invoke-WebRequest https://<render-service-name>.onrender.com/health
Invoke-WebRequest https://<render-service-name>.onrender.com/api/cases
Invoke-WebRequest https://fraudlens-hhgoa.pages.dev/
Invoke-WebRequest https://fraudlens-hhgoa.pages.dev/cases/HHG-014
Invoke-WebRequest https://fraudlens-hhgoa.pages.dev/analytics
```

In the browser, verify:

- the queue loads 20 cases;
- HHG-014 shows the bounded graph and SAR draft;
- HHG-002 shows the simulated evidence label and action diff;
- `/analytics` loads through the direct SPA route; and
- no `.env`, raw CSV, or cloud-admin screen appears in the recording.

## Rollback

- Render: use the previous successful deploy from the service's deploy history.
- Cloudflare Pages: redeploy the previous known-good commit with Wrangler or use the Pages rollback control.
- Do not roll back the TigerGraph credential rotation; rotate forward if a secret is exposed again.
