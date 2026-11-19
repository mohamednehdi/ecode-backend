# Project tracker: eCode barcode platform (PFE)

Working file shared between the student and the "supervisor" role (Claude).
It is the **product backlog** and the **sprint log**. Update it after every work session.

Rules for this file:
- A story is `DONE` only when its acceptance criteria are checked **and** its tests pass.
- Dates are written only when the work really happened on that date. No estimated or back-filled dates.
- Measured numbers go in `docs/PERFORMANCE.md` (or a new study file), never from memory.

Status values: `TODO`, `IN PROGRESS`, `DONE`, `DROPPED`.
Size: story points (1 = a few hours, 2 = one day, 3 = two days, 5 = about a week, 8 = split it).

---

## 1. Vision

A platform that locates and extracts 1D and 2D barcodes (EAN/Code 128/ITF, QR, DataMatrix...) from
multi-page PDFs and images, with:
- a free public web interface;
- a web service for other applications, protected by API keys with quotas, allowed IPs and allowed types;
- an admin back office;
- measured performance (target: under 100 ms per request, 1000 requests per second).

Stack: Angular, Flask, MySQL, zxing-cpp, PyMuPDF.

---

## 2. Cahier des charges: coverage

| Requirement | Status | Where |
|---|---|---|
| Multi-page PDF + image extraction (1D, QR, DataMatrix), JSON output | DONE | `app/scans/` |
| Web service only through tokens | DONE | `app/api/routes.py` |
| Quotas per hour / month / validity period | DONE | `app/api/routes.py`, `ApiToken` |
| Allowed IPs, allowed types per token | DONE | `app/models/api_token.py` |
| Free web interface (PDF/JPG/PNG upload) | DONE | frontend `upload` component, `/public/extract` |
| Admin back office for tokens | DONE | frontend `api-tokens` component |
| Poor-quality scans | DONE | `app/scans/decoder.py` fallback passes |
| Under 100 ms per request | PARTIAL | met up to about 1 Mpx; not for A4 / PDF on the dev laptop |
| 1000 requests per second | NOT DEMONSTRATED | needs several workers / servers (see F1) |
| Stress test | DONE | `stress/`, results in `docs/PERFORMANCE.md` |
| Proposed hardware configuration | DONE | `docs/PERFORMANCE.md` |

To confirm with the academic supervisor: "free web interface" implemented as anonymous access with a per-IP rate limit.

---

## 3. Product backlog (new features)

Ordered by value for the PFE. Each item says why an engineering jury would care.

### F1. Scalable deployment and the 1000 req/s target (priority 1)
Why: closes the only unmet item of the cahier and gives the report a real architecture.
- Docker Compose: Nginx (reverse proxy + load balancing) + several app containers + Redis + MySQL.
- Quota and rate-limit counters in Redis (instead of counting `api_usage` rows).
- Re-run the stress test with 1, 2, 4, 8 app workers and plot the scaling curve.
- Details and what is verified: `docs/DEPLOYMENT.md`.

| Part | What | Status |
|---|---|---|
| F1a | Dockerfile (gunicorn), Nginx config, compose file, `init-db`, `/health`, proxy IP handling | DONE: stack built and run with Docker Desktop (2026-11-19), end-to-end test through Nginx passed |
| F1b | Redis quota counters (hourly window, monthly counter, refund, fallback) | DONE: unit tests with `fakeredis`, and checked on the real Redis container (quota shared by 2 app containers) |
| F1c | Scaling benchmark 1/2/4 containers | DONE: measured 2026-11-19, flat curve on a 4-core laptop (CPU-bound); table in `docs/PERFORMANCE.md` §3. 8 containers skipped (4 cores, 3.8 GB) |

- Acceptance criteria:
  - [x] `docker compose up` starts the whole platform (MySQL, Redis, init-db, 2 app containers, Nginx): all healthy, `/health` answers through Nginx
  - [x] Quotas stay correct across several workers (8 concurrent workers, 50 slots: exactly 50 admitted)
  - [x] Scaling curve (throughput and p95 vs number of workers) in `docs/PERFORMANCE.md`
  - [x] Honest conclusion: 36 to 46 req/s (1200x900) and about 85 req/s (300x300) on a 4-core laptop; 1000 req/s NOT demonstrated, needs more cores/machines
- Found while doing it: the old migrations cannot build an empty database (the `user` table was never created by a
  migration). Fixed with the `init-db` command, tested on an empty MySQL database.
- Lesson from the first attempt: the script pointed at port 8080 (an Oracle listener) and logged 33,000 failures; it now reads HTTP_PORT and checks `/health` before running.
- Size: 8. Status: DONE (target 1000 req/s still to be shown on bigger hardware)

### F2. Decoder comparison study (priority 2)
Why: turns "I chose zxing-cpp" into a measured, defensible engineering decision.
- Build a labelled dataset: clean, blur, noise, JPEG compression, low contrast, skew, perspective, small codes, inverted.
- Compare zxing-cpp, pyzbar, pylibdmtx, OpenCV `BarcodeDetector` (and `wechat_qrcode` for QR) on accuracy and time.
- Acceptance criteria:
  - [ ] Reproducible script `bench/compare_decoders.py` and dataset generator
  - [ ] Result tables and charts per degradation type
  - [ ] Short analysis: strengths, weaknesses, why the final choice
- Size: 5. Status: TODO

### F3. Barcode localisation stage (priority 3)
Why: the project title says "localisation et extraction"; localisation is currently only a by-product of decoding.
- Detect candidate barcode regions first (gradient/morphology for 1D, finder patterns or contours for 2D), then decode crops.
- Return the region even when the content cannot be decoded (`decoded: false`) so the user sees where a code was found.
- Acceptance criteria:
  - [ ] Detection rate measured on the F2 dataset (precision/recall of regions)
  - [ ] Improvement on poor scans vs the current fallback passes, measured
  - [ ] Public page shows undecoded regions in another colour
- Size: 8 (split). Status: TODO

### F4. Admin statistics dashboard (priority 4)
Why: makes the back office more than a CRUD screen; needs per-request latency data.
- Store per request: status code, duration in ms, number of codes, file type and size.
- Pages: requests per day, error rate, average and p95 latency, top tokens, types found; CSV export.
- Acceptance criteria:
  - [ ] New columns + migration, written without slowing the request (measured)
  - [ ] Dashboard page with at least 4 charts
  - [ ] Filter by token and by period
- Size: 5. Status: TODO

### F5. API documentation (priority 5)
- OpenAPI/Swagger page for `/api/v1/extract` (parameters, errors, examples), README for API users.
- Acceptance criteria:
  - [ ] Swagger UI reachable and the "Try it" call works with a key
  - [ ] Examples in curl, Python and JavaScript
- Size: 2. Status: TODO

### F6. Observability (priority 6)
- Structured JSON logs with a request id, Prometheus `/metrics` endpoint (latency histogram, quota rejections), Grafana dashboard.
- Acceptance criteria:
  - [ ] Dashboard screenshot during a stress run
  - [ ] Alert rule example (error rate or p95 above a threshold)
- Size: 3. Status: TODO

### F7. CI pipeline and test quality (priority 7)
- GitHub Actions: backend tests, frontend build and unit tests, lint.
- Frontend unit tests for the services and the token form; one end-to-end test (Playwright): upload, login, create a key.
- Backend coverage report.
- Acceptance criteria:
  - [ ] Pipeline green on every push
  - [ ] Coverage figure in the README
- Size: 3. Status: TODO

### F8. Asynchronous jobs for large documents (priority 8)
- `POST /api/v1/jobs` returns a job id; `GET /api/v1/jobs/<id>` returns progress and result; optional webhook on completion.
- Needs a queue (Redis + RQ or Celery).
- Acceptance criteria:
  - [ ] A 100-page PDF is processed without blocking a web worker
  - [ ] Webhook is signed (HMAC) and retried on failure
- Size: 8 (split). Status: TODO

### F9. Security hardening (priority 9)
- Admin audit log (who created/edited/deleted which token), key rotation, login brute-force protection, HTTPS in the compose setup, security headers.
- A short threat-model section in the report (assets, threats, mitigations).
- Size: 3. Status: TODO

---

## 4. Suggested minimum for the PFE

Items F1, F2 and F4 are the minimum worth adding: one scalability result, one scientific comparison and one
visible product feature. F3 is the best "engineer" feature if time allows. F5 to F9 are polish: pick by time left.

---

## 5. Definition of Done

- Code merged, no failing test.
- Acceptance criteria checked in this file.
- Relevant numbers measured and written down.
- Short entry added to the sprint log (section 6).

---

## 6. Sprint log

Scrum setup to use: sprints of 2 weeks, one sprint goal each, a review (demo) and a retrospective at the end.
Fill each row only with what really happened and the real dates.

| Sprint | Real dates | Sprint goal | Stories finished | Demo | Retrospective (what to keep / change) |
|---|---|---|---|---|---|
| _to fill_ | | | | | |

### Work already in the project (to place in sprints by the student, with the real dates from the student's own records)

| Area | What exists |
|---|---|
| Authentication | Login, JWT sessions with revocation, 3-step password reset, admin-only access |
| Upload | Public upload page, PDF page navigation, boxes drawn on the codes |
| Decoding | zxing-cpp decoder with fallback passes for poor scans |
| Web service | `/api/v1/extract`, API keys (hashed), quotas, IP and type rules |
| Back office | API Tokens admin page |
| Performance | Profiling, decoder replacement, waitress server, Locust stress test, hardware proposal |

The dates for each of these must come from the student. They are not guessed here.

---

## 7. Journal

Short notes after each work session (date, what was done, what was learned, what is next).

| Date | Done | Next |
|---|---|---|
| 2026-11-19 | Tracker created. F1a/F1b written: Redis quota counters (29 tests pass), Docker/Nginx/compose files, `init-db` (fixes fresh-database setup), `/health`, trusted-proxy IP handling. | Install Docker Desktop, run `docker compose up`, fix what breaks, then F1c measurements |
| 2026-11-19 | Docker Desktop installed (WSL updated). `docker compose up -d --build` works. End-to-end through Nginx: admin login, key creation, PDF with 5 codes read, quota 2 -> 200/200/429 with both app containers serving (Redis key holds the count), wrong key 401. | F1c: scaling measurements, then F2 |
| 2026-11-19 | F1c benchmark: 1/2/4 containers, two workloads, 0 failures; throughput flat (CPU-bound on 4 cores). First run invalid (wrong port) and discarded; script now checks `/health`. Results in `docs/PERFORMANCE.md`. | F2: decoder comparison study |
