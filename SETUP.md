# Setup — push to GitHub and run

## The large-file problem, and why it happened

The folder is **569 MB**, but only **1 MB is source**:

| Path | Size | Belongs in git? |
|---|---|---|
| `frontend/node_modules/` | 378 MB | No — `npm install` rebuilds it |
| `frontend/.next/` | 188 MB | No — `npm run build` regenerates it |
| `*.db` | 2 MB | No — runtime state |
| **Everything else (source)** | **1 MB** | **Yes** |

There was no root `.gitignore`, so git tried to commit all 569 MB. GitHub rejects
any single file over 100 MB and warns above 50 MB.

A `.gitignore` is now in place. Verified result: **147 files, 608 KB, largest
file 64 KB.**

> **Important:** `.gitignore` only prevents *future* commits. If you already
> committed the large files, see "Already committed?" at the bottom.

---

## 1. Push to GitHub

```bash
cd eliteintelia-factory
git init
git add -A
git status --short | wc -l     # expect ~147, not thousands
git commit -m "EliteInteliA Intelligence Factory"
git branch -M main
git remote add origin https://github.com/<you>/eliteintelia-factory.git
git push -u origin main
```

Sanity check before pushing — this must print nothing:

```bash
git ls-files | xargs ls -l | awk '$5 > 10485760 {print $5, $9}'
```

## 2. Run the backend

```bash
cd backend
python3.11 -m venv .venv
./.venv/bin/pip install -r requirements.txt
./.venv/bin/uvicorn api_server:app --reload --port 8000
```

Check it: <http://127.0.0.1:8000/health> and <http://127.0.0.1:8000/docs>

## 3. Run the frontend

```bash
cd frontend
npm install
echo "NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000" > .env.local
npm run dev
```

Open <http://localhost:3000>.

## 4. Run the tests

```bash
cd backend && ./.venv/bin/python -m pytest tests -q     # 171 passing
```

---

## Deploy

**Backend → Render.** New → Blueprint → point at the repo (`render.yaml` is at
the root). Set `CORS_ORIGINS` to your exact Vercel URL (no trailing slash), plus
your LLM variables. The persistent disk in `render.yaml` needs a paid instance;
on the free tier delete the `disk:` block and set `CINVENT_DB_PATH=data/cinvent.db`
(data will not survive restarts).

**Frontend → Vercel.** Import the repo, **Root Directory: `frontend`**, set
`NEXT_PUBLIC_API_BASE_URL` to the Render URL, deploy.

> `NEXT_PUBLIC_*` variables are inlined at **build** time. After changing one you
> must **redeploy**, not restart.

Copy `.env.example` to `.env` for local configuration. Never commit `.env`.

---

## Already committed the large files?

`.gitignore` will not remove what is already in history. If your push was
rejected, the simplest reliable fix is a clean history:

```bash
rm -rf .git          # discards local history only, not your files
git init
git add -A           # .gitignore now applies
git commit -m "EliteInteliA Intelligence Factory"
git branch -M main
git remote add origin https://github.com/<you>/<repo>.git
git push -u origin main --force
```

To keep history instead, untrack the offenders and rewrite:

```bash
git rm -r --cached frontend/node_modules frontend/.next
git commit -m "Remove build output from tracking"
# history rewrite still required if they exist in earlier commits:
pip install git-filter-repo
git filter-repo --path frontend/node_modules --path frontend/.next --invert-paths
git push --force
```
