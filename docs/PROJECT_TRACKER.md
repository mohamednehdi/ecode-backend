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
- Dataset of 704 labelled images: 4 code types x 22 degradation conditions x 8 contents, fixed seeds.
- Compared: eCode pipeline, zxing-cpp, pyzbar, pylibdmtx, OpenCV QRCodeDetector / QRCodeDetectorAruco / BarcodeDetector.
- Acceptance criteria:
  - [x] Reproducible scripts `bench/make_dataset.py`, `bench/run_benchmark.py`, `bench/analyze.py`
  - [x] Result tables and charts per condition and per code type (`bench/results/summary.md`, `bench/figures/`)
  - [x] Analysis: strengths, weaknesses, limits of the study, why the final choice (`docs/DECODER_STUDY.md`)
- Findings: zxing-cpp is the best 2D reader (DataMatrix 100 % vs 94 % for pylibdmtx, 4.4x faster); the clean-up passes add
  +24 / +27 points on Code 128 / EAN-13; every decoder fails on 1D codes after blur sigma >= 2.
- Lesson: the first dataset had 1 to 2 px bars (many cells at 0 % for everybody); recalibrated to about 3 px per module
  before drawing conclusions, all measurements redone.
- Size: 5. Status: DONE

### F2b. Fix the weaknesses found by F2 (new)
- Misreads: on EAN-13 at 30 degrees, zxing-cpp and our pipeline return another valid EAN-13 (2 of 176 images, 1.1 %);
  they come from the quick read itself. Idea: check an inclined 1D read against the straightened region (F3b makes this possible).
- Gap between 20 and 30 degrees for Code 128: FIXED by F3b (regions are straightened before decoding).
- Rule: tune on NEW seeds (a separate tuning set), and keep the F2 dataset only for the final score.
- Acceptance criteria:
  - [ ] Separate tuning dataset (different seeds)
  - [ ] Misread rate on EAN-13 down to 0 on the F2 dataset, without losing more than 2 points of correct reads
  - [ ] Code 128 read at 20 to 30 degrees; F2 table re-run and compared before/after
- Size: 3. Status: TODO

### F3. Barcode localisation stage (priority 3)
Why: the project title says "localisation et extraction"; localisation is currently only a by-product of decoding.

| Part | What | Status |
|---|---|---|
| F3a | Localiser (`app/scans/localizer.py`): finds code regions without decoding; true boxes added to the datasets; realistic document pages; scoring model trained on tuning sets only; final exam on untouched sets | DONE: documents recall 80.6 %, precision 73.1 %, 64 ms (`docs/LOCALIZER_STUDY.md`) |
| F3b | Use the regions: decode each region (crop, deskew, enlarge), report unreadable regions in the JSON and show them in another colour on the public page, decode the other codes of a page when only some were read | DONE: default mode reads +1.1 to +1.9 points and cuts p95 by 1.7-2.4x; thorough mode +16.7 points on multi-code pages (`docs/REGIONS_DECODING.md`) |

- Acceptance criteria:
  - [x] Detection recall and precision measured on a dataset with true boxes (80.6 % / 73.1 % on document pages)
  - [x] Tests for the localiser (blank pages, large scans, model loaded)
  - [x] Improvement on poor scans vs the current fallback passes, measured on the final sets (documents 76.7 -> 78.6 % default, 93.4 % thorough; tilted 30 degrees 68.8 -> 93.8 %)
  - [x] Public page shows undecoded regions in another colour (orange) - but only 18-24 % of the reported regions are real unread codes
- Lessons: the single-code pages were far too easy (first detector: 100 % there, 36 % on realistic pages); tuning and final
  sets use different seeds and the final sets were scored once; limits (synthetic fonts and codes, no real scans) are in the study.
- Not achieved: misreads did not go to 0 on the final set (3 and 3): they come from the quick read, which never reaches the region stage -> F2b.
- Size: 8. Status: DONE

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
| 2026-11-19 | F2 decoder study: dataset of 704 images, 7 decoders compared, tables + charts + study document. First dataset recalibrated (1D bars too thin: everybody at 0 %). Found 2 weaknesses of our own decoder (EAN-13 misreads at 30 degrees, gap at 20-30 degrees) -> F2b. | F2b or F3 (localisation) |
| 2026-11-20 | F3a: true boxes in the datasets, 240 realistic document pages, density-based localiser + 12-weight logistic scoring, trimming, speed-ups (296 ms -> 64 ms), 4 new tests (33 pass). Final exam run once on untouched sets: documents recall 80.6 % / precision 73.1 %. Honest limits written in docs/LOCALIZER_STUDY.md. | F3b: use the regions to decode better and show unreadable codes |
| 2026-11-20 | F3b: region decoding (crop, straighten, enlarge, 5 variants), thorough mode, unread regions in the JSON and in orange on the public page (Angular), API `?thorough=1`. 5 strategies compared; final exam run once. 38 tests pass. Misreads NOT fixed (come from the quick read). | F4 admin dashboard, or F2b |
| 2026-11-20 | Looked at the public page: 1D codes had thin/partial boxes (zxing reports only the scanned line). Fixed: every code has its real outline (`polygon`), 1D codes get the located region's box in thorough mode, page draws polygons. Orange image frame made neutral grey (orange now means unreadable region). Speed test made robust (best of 15). 39 tests pass. | F4 or F2b |
