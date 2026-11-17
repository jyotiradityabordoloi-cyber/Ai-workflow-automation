# Deploying SupportFlow AI for free

A public demo on free plans only. About 30 minutes, all in web dashboards; nothing to install.

| Part | Service (free plan) | What runs there |
|---|---|---|
| Dashboard | **Vercel** | `supportflow/frontend` (Next.js) |
| API | **Render** | `supportflow/backend` (FastAPI), defined in `render.yaml` |
| Tickets, audit trail, customer history | **Neon** | PostgreSQL |
| Knowledge and agent corrections | **Qdrant Cloud** | Vector search; its free Cloud Inference computes the embeddings (all-MiniLM-L6-v2) |
| Nightly demo reset | **GitHub Actions** | `.github/workflows/supportflow-demo-reset.yml` |

**What "free" means here**
- **Cold starts:** Render's free API sleeps after 15 idle minutes, so the first visit after that takes up to a minute (the dashboard says so while it waits).
- **Rate limits:** each visitor gets 15 AI actions and 60 changes per 10 minutes, so the shared Groq quota lasts.
- **Nightly reset:** demo data resets every night at 03:00 UTC.
- **Qdrant's inactivity rule:** a free Qdrant cluster is suspended after a week without use. The nightly reset uses it every day, and if the vector store is ever wiped the API rebuilds it from PostgreSQL on its next start, so nothing learned is lost.

Never put real customer data in the public demo.

---

## 1. Neon (database)

1. Sign in at **neon.com** (GitHub login works) and create a project. Pick the region closest to your Render region.
2. On the project dashboard, open **Connect**, turn **off** "Connection pooling", and copy the connection string
   (`postgresql://…neon.tech/neondb?sslmode=require`). This is `DATABASE_URL`. Use it as-is; the app adds the driver name itself.

## 2. Qdrant Cloud (vector memory)

1. Sign in at **cloud.qdrant.io** and create a **Free** cluster.
2. Copy the cluster **URL** (`https://….cloud.qdrant.io`). This is `QDRANT_URL`.
3. Under the cluster's **API Keys**, create a key. This is `QDRANT_API_KEY` (shown once, so keep it safe).
4. Make sure **Inference** is enabled for the cluster (the free model `sentence-transformers/all-minilm-l6-v2` is used).

## 3. Render (API)

1. Sign in at **render.com** with GitHub. Choose **New → Blueprint** and pick this repository. Render reads `render.yaml`.
2. Fill in the secrets it asks for:
   - `DATABASE_URL`: from step 1
   - `GROQ_API_KEY`: the key in your local `.env`
   - `QDRANT_URL` and `QDRANT_API_KEY`: from step 2
   - `CORS_ORIGINS`: for now `["http://localhost:3000"]`; it gets the Vercel address in step 6
3. Click **Apply**. The first build takes a few minutes.
4. Open `https://<your-service>.onrender.com/api/health`. You should see `"ok": true` and `"database": true`.
   The first start creates the tables and loads the 21 knowledge articles into Qdrant.

## 4. Demo data (GitHub Actions)

1. On GitHub, open the repository, then **Settings → Secrets and variables → Actions → New repository secret**, and add
   `DATABASE_URL`, `GROQ_API_KEY`, `QDRANT_URL` and `QDRANT_API_KEY` (the same values).
2. Open **Actions → SupportFlow demo reset → Run workflow**. It loads the 28 demo tickets and classifies them with
   the real model (about 3–5 minutes). The same job then runs every night.

## 5. Vercel (dashboard)

1. Sign in at **vercel.com** with GitHub. Choose **Add New → Project** and import this repository.
2. Set **Root Directory** to `supportflow/frontend`. Vercel detects Next.js.
3. Add these environment variables:
   - `NEXT_PUBLIC_API_MODE` = `live`
   - `NEXT_PUBLIC_API_URL` = `https://<your-service>.onrender.com`
   - `NEXT_PUBLIC_PUBLIC_DEMO` = `true`
4. Click **Deploy** and copy the address (`https://<project>.vercel.app`).

## 6. Connect the two

In Render, open the service, then **Environment**. Set `CORS_ORIGINS` to `["https://<project>.vercel.app"]` and save; Render redeploys.
Open the Vercel address: the dashboard wakes the API and loads the demo.

## 7. Optional: the landing page

Create a second Vercel project from the same repository with **Root Directory** `supportflow/site` (static, no build).
In `site/index.html`, change the "Try the live workspace" link from `http://localhost:3000/` to your Vercel address.

---

## Settings reference (API)

| Variable | Live value | Local default |
|---|---|---|
| `DATABASE_URL` | Neon string | `postgresql+psycopg://…localhost:5433/supportflow` |
| `MEMORY_BACKEND` | `qdrant` | `chroma` (folder `backend/.memory`) |
| `EMBEDDING_PROVIDER` | `qdrant-cloud` | `onnx` (model runs in-process) |
| `QDRANT_URL`, `QDRANT_API_KEY` | from Qdrant Cloud | unset |
| `CORS_ORIGINS` | `["https://<project>.vercel.app"]` | `["http://localhost:3000"]` |
| `RATE_LIMIT_AI_PER_10MIN`, `RATE_LIMIT_WRITES_PER_10MIN` | `15`, `60` | `0` (off) |

Rebuild the vector memory from PostgreSQL by hand at any time with `python -m app.memory.rebuild`.

## If something goes wrong

- **Render build says the Python version isn't available:** change `PYTHON_VERSION` in Render's Environment
  (or in `render.yaml`) to the newest 3.14.x or 3.13.x that Render lists.
- **Health shows `"database": false`:** check `DATABASE_URL` ends with `?sslmode=require` and pooling was off.
- **Dashboard says it can't reach the server:** check `NEXT_PUBLIC_API_URL` has no trailing slash, and that
  `CORS_ORIGINS` contains the exact Vercel address. Vercel preview deployments have different addresses; add them if needed.
- **Similar tickets are empty and the logs say "semantic memory unavailable":** check the Qdrant URL and key, and that the
  cluster isn't suspended (resume it in the Qdrant dashboard; the API restores memory from PostgreSQL on its next start).
- **"This public demo allows a limited number of actions":** the rate limit; raise it in Render's Environment if needed.
