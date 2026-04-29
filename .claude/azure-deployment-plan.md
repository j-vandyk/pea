# Azure Deployment Plan — PEA Drone Events (Africa Continental)

**Date:** April 2026  
**Scope:** Single data scientist implementing the PEA pipeline in an existing Azure workspace, running the `drone_events_codebook` domain across continental Africa  
**Estimate:** Infrastructure live in 1 working day; continental results in 5–8 days

---

## Summary

The pipeline is implementation-ready. All code, codebooks, Docker images, and infra scripts exist. A single data scientist familiar with Azure CLI and Python can have the daily job running and a continental backfill in progress within one working day. The primary ceiling on result quality is GDELT's incomplete drone-event indexing — not the pipeline itself.

---

## Phase 1 — Installation and First Run
**Estimated time: 4–6 hours (single working day)**

| Step | Task | Time |
|------|------|------|
| 1 | Clone repo, `cp .env.example .env`, fill `AZURE_FOUNDRY_API_KEY` and `AZURE_OPENAI_ENDPOINT` | 20 min |
| 2 | `pip install -r requirements-core.txt` — DeBERTa relevance model downloads (~184 MB) | 15 min |
| 3 | `az login && az account set --subscription <id>` | 5 min |
| 4 | `chmod +x infra/setup.sh && ./infra/setup.sh` — creates resource group (`pea-rg`), ACR, ADLS Gen2 with `pea-outputs` filesystem | 30–45 min |
| 5 | Configure 5 GitHub Secrets (`ACR_LOGIN_SERVER`, `ACR_USERNAME`, `ACR_PASSWORD`, `AZURE_CREDENTIALS`, `AZURE_RESOURCE_GROUP`) | 10 min |
| 6 | `git push origin main` — GitHub Actions builds both Docker images and pushes to ACR | 20–30 min |
| 7 | `chmod +x infra/deploy.sh && ./infra/deploy.sh` — creates Container Apps Jobs (`pea-daily`, `pea-backfill`), Key Vault, managed identity, Azure Monitor alert | 30–45 min |
| 8 | Smoke test: `az containerapp job start --name pea-daily --resource-group pea-rg` and watch logs | 30 min |

**Checkpoint:** `pea-daily` is live and running `--stage all --countries NG,ZA,UG,DZ --days 2` every morning at 06:00 UTC. First real drone events visible in ADLS within 8 hours of starting.

---

## Phase 2 — Smoke Test (Day 1, Parallel)

Before triggering the backfill, validate extraction quality with a targeted local test:

```bash
python -m src.acquisition.pipeline \
  --domains drone \
  --countries ZA \
  --days 30 \
  --max-articles 50
```

Review `data/raw/drone/events_*.jsonl` — confirm event types match expected drone codebook categories (`drone_strike_attack`, `isr_reconnaissance`, `counter_drone_response`, etc.) and location fields are geocoded correctly.

**Expected output:** 5–25 drone events from South Africa over 30 days. If zero events are returned, check GDELT discovery keywords in `configs/keywords.yaml` under the `drone` domain entry.

---

## Phase 3 — Continental Backfill (Days 1–8, Unattended)

Trigger the backfill job immediately after smoke test passes. Runs unattended on `pea-backfill` (4 CPU / 8 GB, 24-hour replica timeout).

```bash
az containerapp job start --name pea-backfill --resource-group pea-rg \
  --args "--domains" "drone" \
         "--countries" "NG,ZA,UG,DZ,KE,GH,ET,TZ,SD,EG,SN,ZW,LY,AO,SO,CM,CI,CD" \
         "--backfill-from" "2024-01-01" \
         "--backfill-to" "2026-04-29" \
         "--backfill-window-days" "30" \
         "--workers" "8" \
         "--rpm-limit" "450" \
         "--resume" \
         "--upload-to" "abfss://pea-data/backfill"
```

**Countries covered (20):** Nigeria, South Africa, Uganda, Algeria, Kenya, Ghana, Ethiopia, Tanzania, Sudan, Egypt, Senegal, Zimbabwe, Libya, Angola, Somalia, Cameroon, Ivory Coast, DR Congo

**Compute estimate:**

| Variable | Estimate |
|----------|----------|
| Monthly windows × 20 countries | ~580 GDELT queries |
| Articles passing drone relevance filter (~10–20%) | 50–200 per window |
| Throughput at 8 workers, 450 RPM limit | ~1,500–3,000 articles/day |
| **Wall-clock time for Jan 2024 – Apr 2026** | **3–5 days unattended** |
| Human time to monitor | **< 1 hour total** |

Monitor with:

```bash
az containerapp job execution list \
  --name pea-backfill --resource-group pea-rg --output table
```

---

## Phase 4 — Post-Backfill Processing (Day 8, ~2 hours)

Once the backfill job completes, run the process stage to deduplicate and quality-control the full dataset:

```bash
python -m src.acquisition.pipeline \
  --stage process \
  --domains drone \
  --countries NG,ZA,UG,DZ,KE,GH,ET,TZ,SD,EG,SN,ZW,LY,AO,SO,CM,CI,CD
```

**Outputs:**
- `data/processed/events_consolidated.jsonl` — deduplicated, QC-passed drone events
- `data/processed/quality_report.json` — confidence distribution, schema validity
- `data/processed/duplicates_log.jsonl` — audit trail

---

## Milestones and Timeline

| Day | Milestone | What you have |
|-----|-----------|---------------|
| Day 1, hour 2 | Smoke test passes | Validated extraction on ZA, 30 days |
| Day 1, end of day | Infrastructure live | `pea-daily` running; fresh events every 06:00 UTC |
| Day 1, afternoon | Backfill triggered | Unattended 3–5 day compute job running |
| Day 5–8 | Backfill complete | 20-country drone event dataset, Jan 2024–present |
| Day 8, +2 hours | Process stage complete | Clean, deduplicated continental dataset ready for analysis |

**Fastest path to first meaningful results:** Run the ZA smoke test on Day 1. This alone produces usable drone events within 2 hours of installation, before any Azure infrastructure is provisioned.

---

## Known Limitations and Mitigations

| Limitation | Severity | Mitigation |
|------------|----------|------------|
| GDELT drone recall ceiling — drone events often tagged `ATTACK` or `MILITARY_ACTION`, not a drone-specific theme; events where "drone" doesn't appear in the headline are missed | **High** | Add `--source worldnews` (requires `WORLDNEWS_API_KEY`, free tier) or supply a pre-scraped OSINT corpus via `--source file --file-path <path>` |
| Somalia / Sudan / Libya: GDELT English-language bias misses Arabic and Somali reporting | **Medium** | Pipeline translates via Google Translate; BBC Monitoring (`--source bbc`) covers these markets in English |
| No drone-domain recall benchmark yet | **Medium** | ACLED has an `air/drone strike` sub-event type; register at acleddata.com for a free research token, then build `acled_validator.py` (stub exists at `src/validation/`) |
| Azure AI Foundry RPM quota | **Low–Medium** | Default `--rpm-limit 450` leaves 10% headroom under a 500 RPM deployment. Request quota increase via Azure Portal if running >8 workers |
| First-run geocoding is slow (Nominatim 1 req/sec) | **Low** | Subsequent runs hit disk cache (`data/cache/geocode_cache.json`). Use `--no-geocode` if lat/lon not needed immediately |

---

## Optional Enhancements (Post-Initial Deployment)

These are not required for first results but improve coverage and quality:

1. **Add World News API** (`WORLDNEWS_API_KEY` in Key Vault) — a second discovery source that indexes articles GDELT misses. Free tier: 50 points/day, suitable for targeted daily runs.

2. **Add BBC Monitoring** (`BBC_MONITORING_USER_NAME` / `BBC_MONITORING_USER_PASSWORD`) — highest-quality source for Africa; uses `Civil_unrest` topic + ISO3 country codes. Run with `--source both` or `--source all`.

3. **Build ACLED validator** — `src/validation/acled_validator.py` stub exists; blocked on ACLED API token. Once built, run against `data/processed/events_consolidated.jsonl` for recall-by-country and recall-by-event-type diagnostics.

4. **Expand country list** — add remaining African countries (`target: false` entries in `configs/countries.yaml`) once the 20-country baseline is validated.

5. **Dashboard** — `pea-dashboard` Container App is already deployed by `infra/deploy.sh`. Accessible at the Container App FQDN. Shows live event counts, map, and turmoil levels.
