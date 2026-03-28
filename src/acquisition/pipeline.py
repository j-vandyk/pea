"""
Protest Event Analysis Pipeline
================================
End-to-end pipeline for Global South / non-Western protest event data collection,
full-text retrieval, and LLM-based structured extraction.

Stages:
  1. DISCOVERY   — query GDELT DOC API for candidate article URLs
  2. SCRAPING    — fetch full article text from source URLs
  3. TRANSLATION — detect and translate non-English text (optional)
  4. EXTRACTION  — Claude (Anthropic API) extracts structured protest event fields
  5. STORAGE     — save results to data/raw/ as JSONL + CSV

Codebook version: 2.1

Usage (from repo root):
    python -m src.acquisition.pipeline
    python -m src.acquisition.pipeline --query "protest strike" --countries NG,ZA,UG,DZ --days 7
    python -m src.acquisition.pipeline --help

Requires:
    ANTHROPIC_API_KEY environment variable (or pass --claude-api-key)
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional

from src.acquisition.gdelt_discovery import discover_articles
from src.acquisition.scraper import scrape_articles
from src.acquisition.translator import translate_articles
from src.acquisition.extractor import extract_events
from src.acquisition.storage import save_results

class _JsonFormatter(logging.Formatter):
    def format(self, record):
        entry = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry)

_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(_JsonFormatter())
logging.basicConfig(level=logging.INFO, handlers=[_handler])
log = logging.getLogger("pipeline")

# Default output dir — aligns with project data structure
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[2] / "data" / "raw"


def _load_checkpoint(output_dir: Path) -> set[str]:
    """Return set of URLs already processed in a previous run."""
    cp = output_dir / "checkpoint.txt"
    return set(cp.read_text().splitlines()) if cp.exists() else set()


def _save_checkpoint(output_dir: Path, url: str) -> None:
    """Append a processed URL to the checkpoint file."""
    with open(output_dir / "checkpoint.txt", "a") as f:
        f.write(url + "\n")


def run_pipeline(
    query: str,
    countries: list,
    days: int,
    output_dir: Path,
    max_articles: int = 100,
    translate: bool = True,
    provider: str = "claude",
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    upload_to: Optional[str] = None,
):
    log.info("=== Protest Event Analysis Pipeline (codebook v2.2) ===")
    log.info(f"Query: '{query}' | Countries: {countries} | Days back: {days}")
    log.info(f"LLM provider: {provider} | model: {model or 'default'}")

    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    # Stage 1: Discovery
    log.info("--- Stage 1: GDELT Discovery ---")
    articles = discover_articles(
        query=query, countries=countries, days=days, max_results=max_articles
    )
    log.info(f"Discovered {len(articles)} candidate articles")

    if not articles:
        log.warning("No articles found. Try broadening your query or country list.")
        return []

    # Stage 2: Full-text scraping
    log.info("--- Stage 2: Full-text Scraping ---")
    articles = scrape_articles(articles)
    scraped = [a for a in articles if a.get("text")]
    log.info(f"Successfully scraped {len(scraped)}/{len(articles)} articles")

    if not scraped:
        log.warning("No articles could be scraped. Check network access.")
        return []

    # Stage 3: Translation (optional)
    if translate:
        log.info("--- Stage 3: Translation ---")
        scraped = translate_articles(scraped)
    else:
        for a in scraped:
            a["text_en"] = a.get("text")
            a["text_lang"] = "unknown"

    # Stage 4: LLM Extraction via Claude
    log.info("--- Stage 4: LLM Event Extraction (Claude API) ---")
    checkpoint_path = str(output_dir / "checkpoint.txt")
    events, failures = extract_events(
        scraped,
        model=model,
        api_key=api_key,
        provider=provider,
        checkpoint_path=checkpoint_path,
    )
    log.info(f"Extracted {len(events)} protest events ({len(failures)} extraction failures)")

    # Stage 5: Storage
    log.info("--- Stage 5: Saving Results ---")
    out_path = save_results(events, output_dir=output_dir, run_id=run_id, failures=failures, upload_to=upload_to)
    log.info(f"Results saved to {out_path}")

    log.info("=== Pipeline complete ===")
    return events


def main():
    from dotenv import load_dotenv
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Protest Event Analysis Pipeline — Global South focus (codebook v2.1)"
    )
    parser.add_argument(
        "--query", default="protest demonstration strike rally march",
        help="Keywords to search in GDELT (space-separated)"
    )
    parser.add_argument(
        "--countries", default="NG,ZA,UG,DZ",
        help="Comma-separated ISO2 country codes"
    )
    parser.add_argument("--days", type=int, default=7,
                        help="How many days back to search")
    parser.add_argument("--max-articles", type=int, default=50,
                        help="Max articles to process")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR),
                        help="Directory to write results (default: data/raw/)")
    parser.add_argument("--no-translate", action="store_true",
                        help="Skip translation step")
    parser.add_argument("--provider", default="claude", choices=["claude", "openai", "azure"],
                        help="LLM provider: 'claude' (default), 'openai', or 'azure' (Azure AI Foundry)")
    parser.add_argument("--model", default=None,
                        help="Model ID — defaults to claude-sonnet-4-6 (claude) or gpt-4o-mini (openai)")
    parser.add_argument("--api-key", default=None,
                        help="API key — defaults to ANTHROPIC_API_KEY or OPENAI_API_KEY env var")
    parser.add_argument("--resume", action="store_true",
                        help="Resume from checkpoint.txt — skip already-processed URLs")
    parser.add_argument("--upload-to", default=None,
                        help="Upload outputs after run: 's3://bucket/prefix' or 'az://container/prefix'")
    args = parser.parse_args()

    # Clear checkpoint on fresh run
    output_dir = Path(args.output_dir)
    checkpoint = output_dir / "checkpoint.txt"
    if not args.resume and checkpoint.exists():
        checkpoint.unlink()
        log.info("Fresh run — cleared existing checkpoint")

    run_pipeline(
        query=args.query,
        countries=args.countries.split(","),
        days=args.days,
        output_dir=Path(args.output_dir),
        max_articles=args.max_articles,
        translate=not args.no_translate,
        provider=args.provider,
        model=args.model,
        api_key=args.api_key,
        upload_to=args.upload_to,
    )


if __name__ == "__main__":
    main()
