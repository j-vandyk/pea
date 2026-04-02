# Improving Codebook, Keywords, and Extraction Quality

Three layers to improve, in order of bang-for-your-buck.

---

## Layer 1 — Codebook YAML (your primary workspace, no code needed)

**File:** `configs/protest_codebook.yaml`

This is the single most impactful place for domain expert work. The LLM receives everything in this file at extraction time — once codebook injection is wired in (see Layer 2 below), every example and rule you add directly improves output.

### What to add for each of the 8 event types

**Negative examples** — the most common boundary confusions:

| Type | Common false positives to add as negatives |
|------|--------------------------------------------|
| `riot` | "Police fired rubber bullets at an otherwise peaceful crowd" |
| `strike_boycott` | "Union announces it is considering a strike next month" |
| `demonstration_march` | "A town hall meeting where residents discussed policy" |
| `occupation_seizure` | "A brief 20-minute sit-down blockade of an entrance" |
| `vigil` | "A religious ceremony commemorating a historical event" |
| `petition_signature` | "An online poll or social media hashtag campaign" |
| `confrontation` | "Security guards remove a single trespasser" |
| `hunger_strike` | "An individual refuses hospital food out of frustration" |

**Decision rules** — especially for confusable pairs:
- `demonstration_march` vs. `confrontation`: confrontation requires intentional obstruction/interruption; a march that passes by a building without blocking it is a march
- `occupation_seizure` vs. `confrontation`: occupation requires ≥2 hours of sustained physical presence; a brief blockade is a confrontation
- `vigil` vs. `demonstration_march`: if participants begin moving through public space with chants/banners, recode as march; a static candlelit assembly remains a vigil
- `riot` escalation rule: a peaceful march where a small sub-group breaks off to throw stones = TWO events (march + riot), not one riot

### Expand the non-events disqualifier list

Add more specific patterns to the `disqualify_immediately` section:
- "Parliamentary march or official delegation visiting a site" (institutional representation)
- "Police/military parade or official ceremony"
- "Private company shareholder meeting disruption by investors" (business grievance, not political)
- "NGO or civil society organisation conference/seminar"
- "Religious service, prayer meeting, or church gathering without explicit political demand"
- "Academic sit-in lasting under 1 hour with no stated demands"

### Add African-context non-event patterns

Under `african_context`, add:
- "AU, SADC, ECOWAS, IGAD, COMESA ministerial or summit meetings"
- "State-organised national day celebrations or independence parades"
- "Traditional chieftaincy ceremonies or royal investitures"
- "Sports celebrations or victory parades after international matches"

---

## Layer 2 — Inject Codebook into the Extractor (~5 lines of code)

**File:** `src/acquisition/extractor.py`

The `CodebookManager.get_prompt_context()` method in `src/utils/codebook_manager.py` already generates a clean, LLM-readable version of all 8 event types (definitions, positive/negative examples, decision rules). It is used by the *alternative* `LLMClassifier` pipeline but **not** by the main extractor.

### Change

Split the existing `SYSTEM_PROMPT` constant into a base string, then dynamically append the codebook at module load:

```python
# Near the top of src/acquisition/extractor.py, after imports:
from src.utils.codebook_manager import CodebookManager as _CM
import os as _os

_codebook_path = _os.path.join(
    _os.path.dirname(_os.path.dirname(_os.path.dirname(__file__))),
    "configs", "protest_codebook.yaml"
)
_CODEBOOK_CONTEXT = _CM(_codebook_path).get_prompt_context()

# Then at the end of the SYSTEM_PROMPT string definition:
SYSTEM_PROMPT = SYSTEM_PROMPT + "\n\n" + _CODEBOOK_CONTEXT
```

This gives the LLM the full codebook on every extraction call — definitions, positive/negative examples, and decision rules — without any structural changes to the pipeline.

---

## Layer 3 — Few-Shot Extraction Examples (~10 lines of code)

**Files:** `configs/extraction_examples.yaml` (new), `src/acquisition/extractor.py`

### Step 1: Curate examples (content work, no code)

Create `configs/extraction_examples.yaml` with 3 gold-standard cases:

```yaml
examples:
  - description: "Clean single event"
    article_snippet: >
      About 500 workers gathered outside the Shoprite distribution centre in
      Johannesburg on Tuesday demanding a 12% wage increase. The South African
      Commercial, Catering and Allied Workers Union organised the march, which
      dispersed peacefully after three hours.
    extracted_events:
      - event_type: demonstration_march
        event_date: "2026-03-18"
        country: "South Africa"
        city: "Johannesburg"
        organizer: "South African Commercial, Catering and Allied Workers Union"
        crowd_size: "500"
        claims: ["12% wage increase"]
        state_response: "none"
        outcome: "dispersed"
        confidence: "high"

  - description: "Correct empty result — summit, not protest"
    article_snippet: >
      African Union heads of state convened in Addis Ababa for the 38th
      ordinary session of the Assembly to discuss climate finance and
      regional security cooperation.
    extracted_events: []

  - description: "Multi-event article"
    article_snippet: >
      University students occupied the administration building demanding
      free education, while outside a separate group of workers on a
      general strike blocked the campus entrance.
    extracted_events:
      - event_type: occupation_seizure
        claims: ["free education"]
        participant_groups: ["university students"]
        confidence: "high"
      - event_type: strike_boycott
        claims: ["workers' demands"]
        participant_groups: ["workers"]
        confidence: "medium"
```

### Step 2: Load and inject (code change)

In `src/acquisition/extractor.py`, load the examples at module start and prepend them to the user prompt template.

---

## Layer 4 — Discovery / Keywords (mechanical, lower priority)

**File:** `src/acquisition/gdelt_discovery.py`

### Move keywords to config

`PROTEST_THEMES` and the filter keywords are hardcoded. Move them to `configs/keywords.yaml` so you can tune without touching Python.

### Fix multi-country noise

Currently `--countries NG,ZA` appends country names as keywords, which returns US articles mentioning South Africa. Fix: run one GDELT query per country (using the `sourcecountry` FIPS filter), then deduplicate results. Adds ~N API calls but eliminates cross-country noise.

---

## Recommended Engagement Order

| Step | Where | What | Code? |
|------|-------|------|-------|
| 1 | `configs/protest_codebook.yaml` | Add negative examples + decision rules for all 8 types | No |
| 2 | `src/acquisition/extractor.py` | Inject codebook context into SYSTEM_PROMPT | ~5 lines |
| 3 | `configs/protest_codebook.yaml` | Expand non-events + African-context disqualifiers | No |
| 4 | `configs/extraction_examples.yaml` | Curate 3 few-shot examples | No (new YAML) |
| 5 | `src/acquisition/extractor.py` | Load + inject few-shot examples into USER_PROMPT | ~10 lines |
| 6 | `configs/keywords.yaml` | Move + expand keywords config | Mechanical refactor |
| 7 | `src/acquisition/gdelt_discovery.py` | Sequential per-country queries | ~15 lines |

---

## Verifying Improvements

After each set of codebook changes, run a small test:

```bash
venv/bin/python -m src.acquisition.pipeline \
  --provider azure --countries ZA --days 14 --max-articles 30
```

Compare `data/raw/summary_*.json` between runs:
- **Events extracted** — should increase if you improved recall
- **"No events found" count** — should increase if you improved disqualification
- **Turmoil level distribution** — should shift if riot/state_response classification improved

For the codebook injection change specifically, add a temporary debug line before the first LLM call to confirm the full codebook is being sent:
```python
print(SYSTEM_PROMPT[-500:])  # Should show event type definitions
```
