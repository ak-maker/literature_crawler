"""
Paper scoring system.

Redesigned weights (total 0-100):
  - Relevance (0-45): Fine-grained keyword match (critical/high/medium tiers)
  - Bonus     (0-30): +15 code released, +15 real-world demo
  - Venue     (0-15): Publication venue tier
  - Impact    (0-10): Citations normalized by paper age
"""

import re
import logging
from datetime import datetime
from typing import List, Dict

from fetcher import Paper

logger = logging.getLogger(__name__)

CURRENT_YEAR = datetime.now().year


def score_venue(paper: Paper, venue_tiers: Dict) -> float:
    """Match venue against tier patterns."""
    venue_text = f"{paper.venue} {paper.url}"

    for _tier_name, tier_info in venue_tiers.items():
        for pattern in tier_info.get("patterns", []):
            if re.search(pattern, venue_text, re.IGNORECASE):
                return tier_info["score"]

    # Fallback: known arXiv preprint
    if paper.arxiv_id or "arxiv" in paper.url.lower():
        return 2
    return 0


def score_relevance(paper: Paper, keywords_config: Dict) -> float:
    """
    Fine-grained relevance scoring with 3 tiers:
      - critical: +8 title / +4 abstract  (must-have UAV-UGV anchor terms)
      - high:     +5 title / +2 abstract  (core topic terms)
      - medium:   +2 title / +1 abstract  (supporting terms)
    """
    title = paper.title.lower()
    text = f"{title} {paper.abstract.lower()}"
    max_score = keywords_config.get("max_score", 45)
    score = 0.0

    for kw in keywords_config.get("critical", []):
        kw_lower = kw.lower()
        if kw_lower in title:
            score += 8
        elif kw_lower in text:
            score += 4

    for kw in keywords_config.get("high", []):
        kw_lower = kw.lower()
        if kw_lower in title:
            score += 5
        elif kw_lower in text:
            score += 2

    for kw in keywords_config.get("medium", []):
        kw_lower = kw.lower()
        if kw_lower in title:
            score += 2
        elif kw_lower in text:
            score += 1

    return min(score, max_score)


def score_impact(paper: Paper, all_papers: List[Paper],
                 max_score: float = 10) -> float:
    """Citation-based score normalized by paper age (percentile)."""
    if not all_papers:
        return 0

    def _rate(p):
        age = max(1, CURRENT_YEAR - (p.year or CURRENT_YEAR))
        return p.citation_count / age

    paper_rate = _rate(paper)
    all_rates = sorted(_rate(p) for p in all_papers)

    rank = sum(1 for r in all_rates if r <= paper_rate)
    percentile = rank / len(all_rates)

    return round(percentile * max_score, 1)


def score_bonus(paper: Paper, code_pts: float = 15,
                demo_pts: float = 15) -> float:
    """Bonus for code availability and real-world demo."""
    score = 0.0
    if paper.has_code:
        score += code_pts
    if paper.has_demo:
        score += demo_pts
    return score


def score_all(papers: List[Paper], config: Dict) -> List[Paper]:
    """Score every paper and sort descending by total score."""
    venue_tiers = config.get("venue_tiers", {})
    keywords_config = config.get("relevance_keywords", {})
    weights = config.get("scoring_weights", {})

    impact_max = weights.get("impact_max", 10)
    code_pts = weights.get("bonus_code", 15)
    demo_pts = weights.get("bonus_demo", 15)

    for p in papers:
        p.venue_score = score_venue(p, venue_tiers)
        p.relevance_score = score_relevance(p, keywords_config)
        p.impact_score = score_impact(p, papers, max_score=impact_max)
        p.bonus_score = score_bonus(p, code_pts=code_pts, demo_pts=demo_pts)
        p.total_score = (
            p.venue_score + p.relevance_score +
            p.impact_score + p.bonus_score
        )

    papers.sort(key=lambda p: p.total_score, reverse=True)
    if papers:
        logger.info(f"Scored {len(papers)} papers. "
                     f"Top={papers[0].total_score:.0f}, "
                     f"Median={papers[len(papers)//2].total_score:.0f}, "
                     f"Min={papers[-1].total_score:.0f}")
    return papers
