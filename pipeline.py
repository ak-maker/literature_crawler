#!/usr/bin/env python3
"""
Literature Review Pipeline
==========================

Usage:
    python pipeline.py <search_config.yaml>
    python pipeline.py searches/uav_ugv.yaml -o output/uav_ugv
    python pipeline.py searches/uav_ugv.yaml --s2-api-key YOUR_KEY
    python pipeline.py searches/uav_ugv.yaml --arxiv-only
    python pipeline.py searches/uav_ugv.yaml --s2-only

The search config YAML defines:
  - search_queries: keyword groups to search
  - venue_tiers: venue scoring tiers (tier1=30, tier2=20, tier3=10)
  - relevance_keywords: high/medium priority keywords for relevance scoring

Scoring breakdown (total 0-100):
  - Venue    (0-30): ICRA/IROS/RA-L/RSS/CoRL/NeurIPS/ICML/ICLR = 30pts
  - Relevance(0-30): keyword match to your research focus
  - Impact   (0-20): citations per year (percentile within results)
  - Bonus    (0-20): +10 has code, +10 has real-world demo
"""

import argparse
import csv
import json
import logging
import os
import sys

# Load .env file if present (S2_API_KEY)
_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())
from datetime import datetime

import yaml

from fetcher import ArxivFetcher, SemanticScholarFetcher, deduplicate, enrich_with_paperswithcode
from scorer import score_all
from analyzer import (
    extract_keywords, top_authors, method_evolution,
    venue_distribution, year_distribution, method_paper_groups,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def fetch_papers(config: dict, s2_api_key=None,
                 arxiv_only=False, s2_only=False):
    arxiv = ArxivFetcher()
    s2 = SemanticScholarFetcher(api_key=s2_api_key)
    all_papers = []

    for group in config.get("search_queries", []):
        name = group.get("name", "unnamed")
        keywords = group.get("keywords", [])
        max_per = group.get("max_results_per_keyword", 50)
        categories = group.get("arxiv_categories", [])

        logger.info(f"=== Search group: {name} ===")

        for kw in keywords:
            logger.info(f"Searching: '{kw}'")

            if not s2_only:
                papers = arxiv.search(kw, max_results=max_per, categories=categories)
                all_papers.extend(papers)

            if not arxiv_only:
                papers = s2.search(kw, max_results=max_per)
                all_papers.extend(papers)

    before = len(all_papers)
    all_papers = deduplicate(all_papers)
    logger.info(f"Deduplicated: {before} -> {len(all_papers)} unique papers")

    return all_papers


def generate_csv(papers, output_dir):
    path = os.path.join(output_dir, "papers.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "Rank", "Total", "Venue_S", "Relev_S", "Impact_S", "Bonus_S",
            "Title", "Authors", "Year", "Venue", "Citations",
            "Code", "Code_URL", "Demo", "URL", "PDF", "Source",
        ])
        for i, p in enumerate(papers, 1):
            w.writerow([
                i, f"{p.total_score:.0f}",
                f"{p.venue_score:.0f}", f"{p.relevance_score:.0f}",
                f"{p.impact_score:.0f}", f"{p.bonus_score:.0f}",
                p.title, "; ".join(p.authors[:5]),
                p.year, p.venue[:60], p.citation_count,
                "Y" if p.has_code else "", p.code_url,
                "Y" if p.has_demo else "",
                p.url, p.pdf_url, p.source,
            ])
    return path


def generate_json(papers, output_dir):
    path = os.path.join(output_dir, "papers.json")
    data = []
    for p in papers:
        data.append({
            "title": p.title,
            "authors": p.authors,
            "year": p.year,
            "venue": p.venue,
            "citation_count": p.citation_count,
            "has_code": p.has_code,
            "code_url": p.code_url,
            "has_demo": p.has_demo,
            "scores": {
                "venue": p.venue_score,
                "relevance": p.relevance_score,
                "impact": p.impact_score,
                "bonus": p.bonus_score,
                "total": p.total_score,
            },
            "url": p.url,
            "pdf_url": p.pdf_url,
            "arxiv_id": p.arxiv_id,
            "abstract": p.abstract[:500],
            "source": p.source,
        })
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return path


def _paper_line(p, show_score=True):
    """Format a single paper as a markdown list item."""
    parts = []
    if p.url:
        parts.append(f"[{p.title}]({p.url})")
    else:
        parts.append(p.title)
    meta = []
    if p.year:
        meta.append(str(p.year))
    if p.venue:
        meta.append(p.venue[:30])
    if p.citation_count:
        meta.append(f"{p.citation_count} cites")
    if show_score:
        meta.append(f"score={p.total_score:.0f}")
    tags = []
    if p.has_code:
        tags.append("CODE")
    if p.has_demo:
        tags.append("DEMO")
    line = f"- {parts[0]}"
    if meta:
        line += f" ({', '.join(meta)})"
    if tags:
        line += f" **[{', '.join(tags)}]**"
    if p.has_code and p.code_url:
        line += f" | [repo]({p.code_url})"
    return line


def generate_report(papers, analysis, output_dir, config):
    path = os.path.join(output_dir, "report.md")
    weights = config.get("scoring_weights", {})

    with open(path, "w", encoding="utf-8") as f:
        f.write("# Literature Review Report\n\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")

        code_count = sum(1 for p in papers if p.has_code)
        demo_count = sum(1 for p in papers if p.has_demo)
        f.write(f"Total: **{len(papers)}** papers | "
                f"**{code_count}** with code | "
                f"**{demo_count}** with real-world demo\n\n")

        # --- Scoring explanation ---
        f.write("## Scoring System (0-100)\n\n")
        f.write("| Component | Max | Description |\n")
        f.write("|-----------|-----|-------------|\n")
        f.write(f"| Relevance | {weights.get('relevance_max', 45)} "
                f"| critical(+8/+4) high(+5/+2) medium(+2/+1) keyword match |\n")
        f.write(f"| Bonus | {weights.get('bonus_code', 15) + weights.get('bonus_demo', 15)} "
                f"| +{weights.get('bonus_code', 15)} code, "
                f"+{weights.get('bonus_demo', 15)} real-world demo |\n")
        f.write(f"| Venue | {weights.get('venue_max', 15)} "
                f"| Tier1=15 (ICRA/IROS/RA-L/RSS/CoRL/NeurIPS/ICML/ICLR) |\n")
        f.write(f"| Impact | {weights.get('impact_max', 10)} "
                f"| Citations/year percentile |\n\n")

        # --- Top papers table ---
        f.write("## Top 50 Papers\n\n")
        f.write("| # | Total | Rel | Bonus | Venue | Imp | Title | Year | Venue | Cites | Code | Demo |\n")
        f.write("|---|-------|-----|-------|-------|-----|-------|------|-------|-------|------|------|\n")
        for i, p in enumerate(papers[:50], 1):
            code = "Y" if p.has_code else ""
            demo = "Y" if p.has_demo else ""
            t = p.title[:65] + "..." if len(p.title) > 65 else p.title
            v = p.venue[:20] if p.venue else "-"
            link = f"[{t}]({p.url})" if p.url else t
            f.write(
                f"| {i} | **{p.total_score:.0f}** | {p.relevance_score:.0f} | "
                f"{p.bonus_score:.0f} | {p.venue_score:.0f} | "
                f"{p.impact_score:.0f} | {link} | {p.year} | {v} | "
                f"{p.citation_count} | {code} | {demo} |\n"
            )

        # --- Method categories (collapsible with paper links) ---
        f.write("\n## Methods by Category\n\n")
        method_papers = analysis.get("method_papers", {})
        for method_name, method_list in method_papers.items():
            if not method_list:
                continue
            f.write(f"<details>\n<summary><b>{method_name}</b> ({len(method_list)} papers)</summary>\n\n")
            for p in method_list:
                f.write(_paper_line(p) + "\n")
            f.write("\n</details>\n\n")

        # --- Method evolution timeline ---
        f.write("## Method Evolution by Year\n\n")
        evolution = analysis["method_evolution"]
        if evolution:
            all_methods = set()
            for year_data in evolution.values():
                all_methods.update(year_data.keys())

            significant = [
                m for m in all_methods
                if sum(evolution.get(y, {}).get(m, 0) for y in evolution) >= 3
            ]
            significant.sort()
            years = sorted(evolution.keys())
            if len(years) > 12:
                years = years[-12:]

            f.write(f"| Method | {' | '.join(str(y) for y in years)} |\n")
            f.write(f"|--------|{'|'.join(['---'] * len(years))}|\n")
            for method in significant:
                counts = [str(evolution.get(y, {}).get(method, 0)) for y in years]
                f.write(f"| {method} | {' | '.join(counts)} |\n")

        # --- Papers with code (collapsible) ---
        code_papers = [p for p in papers if p.has_code]
        if code_papers:
            f.write(f"\n<details>\n<summary><b>Papers with Code ({len(code_papers)})</b></summary>\n\n")
            for p in code_papers:
                f.write(_paper_line(p) + "\n")
            f.write("\n</details>\n\n")

        # --- Papers with real-world demo (collapsible) ---
        demo_papers = [p for p in papers if p.has_demo]
        if demo_papers:
            f.write(f"<details>\n<summary><b>Papers with Real-World Demo ({len(demo_papers)})</b></summary>\n\n")
            for p in demo_papers:
                f.write(_paper_line(p) + "\n")
            f.write("\n</details>\n\n")

        # --- Year distribution ---
        f.write("## Papers by Year\n\n")
        years_data = analysis["year_dist"]
        if years_data:
            max_count = max(years_data.values()) if years_data else 1
            f.write("```\n")
            for y, c in sorted(years_data.items()):
                bar = "#" * int(c / max_count * 40)
                f.write(f"{y} | {bar} {c}\n")
            f.write("```\n")

        # --- Top keywords ---
        f.write("\n## High-Frequency Keywords\n\n")
        for kw, count in analysis["keywords"][:30]:
            f.write(f"- **{kw}** ({count})\n")

        # --- Top authors ---
        f.write("\n## Top Authors\n\n")
        f.write("| Author | Papers | Avg Score |\n")
        f.write("|--------|--------|-----------|\n")
        for author, count, avg in analysis["top_authors"]:
            f.write(f"| {author} | {count} | {avg} |\n")

        # --- Venue distribution ---
        f.write("\n## Venue Distribution\n\n")
        f.write("| Venue | Count |\n|-------|-------|\n")
        for venue, count in analysis["venue_dist"][:20]:
            f.write(f"| {venue[:50]} | {count} |\n")

    return path


def main():
    parser = argparse.ArgumentParser(
        description="Literature Review Pipeline - Fetch, score, and analyze papers",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("config", help="Path to search config YAML file")
    parser.add_argument("-o", "--output", default=None,
                        help="Output directory (default: output/<config_name>)")
    parser.add_argument("--s2-api-key", default=os.environ.get("S2_API_KEY"),
                        help="Semantic Scholar API key (default: from .env or S2_API_KEY env var)")
    parser.add_argument("--arxiv-only", action="store_true",
                        help="Only search arXiv")
    parser.add_argument("--s2-only", action="store_true",
                        help="Only search Semantic Scholar")
    args = parser.parse_args()

    # Load config
    config = load_config(args.config)
    config_name = os.path.splitext(os.path.basename(args.config))[0]

    # Output dir
    output_dir = args.output or os.path.join("output", config_name)
    os.makedirs(output_dir, exist_ok=True)

    logger.info(f"Config: {args.config}")
    logger.info(f"Output: {output_dir}")

    # 1. Fetch
    logger.info("=" * 50)
    logger.info("STEP 1: Fetching papers...")
    papers = fetch_papers(
        config,
        s2_api_key=args.s2_api_key,
        arxiv_only=args.arxiv_only,
        s2_only=args.s2_only,
    )

    if not papers:
        logger.error("No papers found. Check your search queries.")
        sys.exit(1)

    # 1.5. Enrich code info via PapersWithCode
    logger.info("=" * 50)
    logger.info("STEP 1.5: Enriching code info via PapersWithCode...")
    papers = enrich_with_paperswithcode(papers)

    # 2. Score
    logger.info("=" * 50)
    logger.info("STEP 2: Scoring papers...")
    papers = score_all(papers, config)

    # 3. Analyze
    logger.info("=" * 50)
    logger.info("STEP 3: Analyzing...")
    analysis = {
        "keywords": extract_keywords(papers),
        "top_authors": top_authors(papers),
        "method_evolution": method_evolution(papers),
        "method_papers": method_paper_groups(papers),
        "venue_dist": venue_distribution(papers),
        "year_dist": year_distribution(papers),
    }

    # 4. Generate outputs
    logger.info("=" * 50)
    logger.info("STEP 4: Generating reports...")

    csv_path = generate_csv(papers, output_dir)
    json_path = generate_json(papers, output_dir)
    md_path = generate_report(papers, analysis, output_dir, config)

    # Save raw config for reproducibility
    with open(os.path.join(output_dir, "config_used.yaml"), "w") as f:
        yaml.dump(config, f, default_flow_style=False)

    logger.info("=" * 50)
    logger.info("DONE!")
    logger.info(f"  {csv_path}  ({len(papers)} papers)")
    logger.info(f"  {json_path}")
    logger.info(f"  {md_path}")
    logger.info(f"\nTop 10 papers:")
    for i, p in enumerate(papers[:10], 1):
        code = " [CODE]" if p.has_code else ""
        demo = " [DEMO]" if p.has_demo else ""
        logger.info(
            f"  {i:2d}. [{p.total_score:5.0f}] {p.title[:70]}"
            f" ({p.year}, {p.citation_count} cites){code}{demo}"
        )


if __name__ == "__main__":
    main()
