# "Engagement not found" — cause and fix (v15)

**330 tests passing · TypeScript clean · build clean.**

## What you saw

The Discovery page showed **"Engagement not found"** in the artifacts panel while
the evidence snapshot immediately below reported **Artifacts: 5** and the
lifecycle showed 2/8. The page contradicted itself.

## What it actually was

`"Engagement not found"` is the literal 404 body the backend returns for an
engagement id it does not have. Reproduced exactly:

```
GET /api/engagements/{live}/artifacts  -> 200
GET /api/engagements/{stale}/artifacts -> 404 {"detail":"Engagement not found"}
```

So the panel was asking for an engagement that no longer existed. Two defects
let that reach the screen:

**1. No request cancellation.** `ArtifactViewer` fired a load per id change with
no generation guard. When the stored id was stale and the context then
auto-selected a live one, two requests were in flight; the slower stale 404
resolved last and overwrote the good result. Requests are now
generation-stamped and a superseded response is discarded.

**2. A stale selection was never cleared.** The app stayed pinned to a dead id,
so every panel 404'd. A "not found" on the selected engagement now drops the
stored id and re-selects from what actually exists.

Verified in the browser: planting your production id
`7677d797-6e08-4487-ac6e-a374689104ed` in `localStorage` and reloading now
recovers to the live engagement with **zero errors** — previously it produced
the error you saw.

## Why the id went stale — the real problem

Your Render service runs on the **Free** instance type, but `render.yaml`
declares a persistent disk:

```yaml
disk:
  name: cinvent-data
  mountPath: /var/data
```

**Render disks require a paid instance.** On Free the disk is never attached, so
`/var/data` is ordinary container storage — and the container runs as root, so
creating that directory *succeeds*. Nothing fails, nothing warns, and the
SQLite database sits there looking healthy.

Free instances also spin down after roughly 15 minutes of inactivity and
restart cold. **Every restart and every deploy wipes the database.** That is why
engagements keep disappearing and why the browser holds ids the server has never
heard of.

### This is now visible instead of silent

A durability check runs before anything opens the database and prints to the
service log:

```
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
  DATA DURABILITY WARNING
  The database is configured at /var/data/cinvent.db, which looks like a
  persistent disk mount but is not actually mounted...
  Attach a persistent disk (paid instance on Render), or point DATABASE_URL
  at a managed PostgreSQL database.
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
```

`GET /health` now carries the same assessment under `storage`, so the UI can
warn before work is lost.

## What to do about it

| Option | Effect |
|---|---|
| **Upgrade the Render instance and keep the disk** | `/var/data` is genuinely mounted; SQLite persists. Smallest change. |
| **Point `DATABASE_URL` at managed PostgreSQL** | Durable, and the v2 core already supports it. Note the legacy engagement store is still raw SQLite, so this alone does not move everything. |
| **Stay on Free** | Workable for demos only. Expect the database to reset; treat every engagement as disposable. |

Until one of the first two is done, the fixes above stop the *symptom* — the
app now recovers cleanly instead of dead-ending — but the underlying data loss
continues.
