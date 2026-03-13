"""
Paper fetchers for arXiv and Semantic Scholar APIs.
"""

import re
import time
import logging
import requests
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class Paper:
    title: str
    abstract: str
    authors: List[str]
    year: Optional[int]
    venue: str = ""
    citation_count: int = 0
    url: str = ""
    arxiv_id: str = ""
    doi: str = ""
    source: str = ""  # "arxiv", "semantic_scholar", "both"
    has_code: bool = False
    code_url: str = ""
    has_demo: bool = False
    pdf_url: str = ""
    fields_of_study: List[str] = field(default_factory=list)
    publication_types: List[str] = field(default_factory=list)
    search_query: str = ""  # which query found this paper
    # Scores (filled by scorer)
    venue_score: float = 0
    relevance_score: float = 0
    impact_score: float = 0
    bonus_score: float = 0
    total_score: float = 0


# --- Utility patterns ---

_CODE_PATTERN = re.compile(
    r'github\.com|gitlab\.com|bitbucket\.org|code\s*(is\s*)?available|open[\-\s]?source',
    re.IGNORECASE,
)
_CODE_URL_PATTERN = re.compile(r'(https?://github\.com/[^\s\)\],]+)')
_DEMO_KEYWORDS = re.compile(
    r'real[\-\s]?world|real robot|hardware experiment|physical experiment|'
    r'field test|outdoor experiment|real[\-\s]?world deployment|physical demo|'
    r'deployed on|onboard experiment|flight experiment|field deployment|'
    r'real[\-\s]?world evaluation|physical platform',
    re.IGNORECASE,
)


def _detect_code(text: str):
    has_code = bool(_CODE_PATTERN.search(text))
    match = _CODE_URL_PATTERN.search(text)
    code_url = match.group(1).rstrip('.,;') if match else ""
    return has_code, code_url


def _detect_demo(text: str) -> bool:
    return bool(_DEMO_KEYWORDS.search(text))


# ============================================================
# arXiv Fetcher
# ============================================================

class ArxivFetcher:
    BASE_URL = "http://export.arxiv.org/api/query"
    RATE_LIMIT = 3  # seconds between requests
    NS = {
        "atom": "http://www.w3.org/2005/Atom",
        "arxiv": "http://arxiv.org/schemas/atom",
    }

    def search(self, query: str, max_results: int = 100,
               categories: List[str] = None) -> List[Paper]:
        papers = []
        batch = 50

        for start in range(0, max_results, batch):
            params = {
                "search_query": self._build_query(query, categories),
                "start": start,
                "max_results": min(batch, max_results - start),
                "sortBy": "relevance",
                "sortOrder": "descending",
            }
            try:
                resp = requests.get(self.BASE_URL, params=params, timeout=30)
                resp.raise_for_status()
                batch_papers = self._parse(resp.text, query)
                papers.extend(batch_papers)
                logger.info(f"  arXiv: {len(papers)} papers (query='{query}')")
                if start + batch < max_results:
                    time.sleep(self.RATE_LIMIT)
            except Exception as e:
                logger.error(f"  arXiv error: {e}")
                break

        return papers

    def _build_query(self, query: str, categories=None) -> str:
        # Connect each word with AND for broader matching
        terms = query.strip().split()
        if len(terms) > 1:
            q = " AND ".join(f"all:{t}" for t in terms)
        else:
            q = f"all:{terms[0]}"
        if categories:
            cat_filter = " OR ".join(f"cat:{c}" for c in categories)
            q = f"({q}) AND ({cat_filter})"
        return q

    def _parse(self, xml_text: str, query: str) -> List[Paper]:
        papers = []
        ns = self.NS
        root = ET.fromstring(xml_text)

        for entry in root.findall("atom:entry", ns):
            title_el = entry.find("atom:title", ns)
            summary_el = entry.find("atom:summary", ns)
            if title_el is None or summary_el is None:
                continue

            title = " ".join(title_el.text.strip().split())
            abstract = " ".join(summary_el.text.strip().split())

            authors = []
            for author_el in entry.findall("atom:author", ns):
                name_el = author_el.find("atom:name", ns)
                if name_el is not None:
                    authors.append(name_el.text)

            published = entry.find("atom:published", ns)
            year = int(published.text[:4]) if published is not None and published.text else None

            id_el = entry.find("atom:id", ns)
            id_url = id_el.text if id_el is not None else ""
            arxiv_id = id_url.split("/abs/")[-1] if "/abs/" in id_url else ""

            # Venue from comment field
            comment_el = entry.find("arxiv:comment", ns)
            comment = comment_el.text if comment_el is not None and comment_el.text else ""

            # PDF link
            pdf_url = ""
            for link in entry.findall("atom:link", ns):
                if link.get("title") == "pdf":
                    pdf_url = link.get("href", "")

            combined_text = f"{abstract} {comment}"
            has_code, code_url = _detect_code(combined_text)
            has_demo = _detect_demo(combined_text)

            papers.append(Paper(
                title=title,
                abstract=abstract,
                authors=authors,
                year=year,
                venue=comment,
                url=id_url,
                arxiv_id=arxiv_id,
                source="arxiv",
                has_code=has_code,
                code_url=code_url,
                has_demo=has_demo,
                pdf_url=pdf_url,
                search_query=query,
            ))

        return papers


# ============================================================
# Semantic Scholar Fetcher
# ============================================================

class SemanticScholarFetcher:
    OFFICIAL_URL = "https://api.semanticscholar.org/graph/v1"
    AI4SCHOLAR_URL = "https://ai4scholar.net/graph/v1"
    FIELDS = (
        "title,abstract,authors,year,venue,externalIds,"
        "citationCount,openAccessPdf,url,publicationTypes,fieldsOfStudy"
    )

    def __init__(self, api_key: str = None, base_url: str = None):
        self.headers = {}

        if api_key and api_key.startswith("sk-user-"):
            # ai4scholar.net proxy key
            self.base_url = base_url or self.AI4SCHOLAR_URL
            self.headers["Authorization"] = f"Bearer {api_key}"
            self.rate_limit = 0.5
            logger.info(f"S2 via ai4scholar.net proxy")
        elif api_key:
            # Official Semantic Scholar API key
            self.base_url = base_url or self.OFFICIAL_URL
            self.headers["x-api-key"] = api_key
            self.rate_limit = 0.5
        else:
            # No key: official API, conservative rate limit
            self.base_url = base_url or self.OFFICIAL_URL
            self.rate_limit = 3.0

    def search(self, query: str, max_results: int = 100) -> List[Paper]:
        papers = []
        batch = 100  # S2 max per request

        for offset in range(0, max_results, batch):
            limit = min(batch, max_results - offset)
            params = {
                "query": query,
                "offset": offset,
                "limit": limit,
                "fields": self.FIELDS,
            }

            try:
                resp = requests.get(
                    f"{self.base_url}/paper/search",
                    params=params,
                    headers=self.headers,
                    timeout=30,
                )

                # Rate limit handling
                if resp.status_code == 429:
                    wait = int(resp.headers.get("Retry-After", 60))
                    logger.warning(f"  S2 rate limited, waiting {wait}s...")
                    time.sleep(wait)
                    resp = requests.get(
                        f"{self.base_url}/paper/search",
                        params=params, headers=self.headers, timeout=30,
                    )

                resp.raise_for_status()
                data = resp.json()

                if "data" not in data:
                    break

                for item in data["data"]:
                    paper = self._parse_paper(item, query)
                    if paper:
                        papers.append(paper)

                total = data.get("total", 0)
                logger.info(f"  S2: {len(papers)}/{min(total, max_results)} papers (query='{query}')")

                if offset + limit >= total:
                    break
                time.sleep(self.rate_limit)

            except Exception as e:
                logger.error(f"  S2 error: {e}")
                break

        return papers

    def _parse_paper(self, item: dict, query: str) -> Optional[Paper]:
        title = item.get("title")
        if not title:
            return None

        abstract = item.get("abstract") or ""
        ext_ids = item.get("externalIds") or {}
        authors = [a.get("name", "") for a in (item.get("authors") or [])]

        combined_text = abstract
        has_code, code_url = _detect_code(combined_text)
        has_demo = _detect_demo(combined_text)

        pdf_info = item.get("openAccessPdf") or {}

        return Paper(
            title=title,
            abstract=abstract,
            authors=authors,
            year=item.get("year"),
            venue=item.get("venue") or "",
            citation_count=item.get("citationCount") or 0,
            url=item.get("url") or "",
            arxiv_id=ext_ids.get("ArXiv", ""),
            doi=ext_ids.get("DOI", ""),
            source="semantic_scholar",
            has_code=has_code,
            code_url=code_url,
            has_demo=has_demo,
            pdf_url=pdf_info.get("url", ""),
            fields_of_study=item.get("fieldsOfStudy") or [],
            publication_types=item.get("publicationTypes") or [],
            search_query=query,
        )


# ============================================================
# Deduplication
# ============================================================

def deduplicate(papers: List[Paper]) -> List[Paper]:
    """Deduplicate by normalized title, merging metadata."""
    seen = {}
    result = []

    for p in papers:
        key = re.sub(r'[^a-z0-9]', '', p.title.lower())
        if key in seen:
            existing = seen[key]
            # Merge: keep richer metadata
            if p.citation_count > existing.citation_count:
                existing.citation_count = p.citation_count
            if p.venue and not existing.venue:
                existing.venue = p.venue
            if p.has_code and not existing.has_code:
                existing.has_code = True
                existing.code_url = p.code_url or existing.code_url
            if p.has_demo and not existing.has_demo:
                existing.has_demo = True
            if p.doi and not existing.doi:
                existing.doi = p.doi
            if p.arxiv_id and not existing.arxiv_id:
                existing.arxiv_id = p.arxiv_id
            existing.source = "both"
        else:
            seen[key] = p
            result.append(p)

    return result


# ============================================================
# Code/Demo enrichment
# ============================================================

def enrich_with_paperswithcode(papers: List[Paper]) -> List[Paper]:
    """
    Two-stage enrichment:
    1. Scrape each arXiv abstract page for GitHub links (more reliable than
       checking just the API abstract, which is often truncated)
    2. Fallback: try PapersWithCode API if available
    """
    to_check = [p for p in papers if p.arxiv_id and not p.has_code]
    if not to_check:
        logger.info("No papers to enrich (all already have code info or no arXiv ID)")
        return papers

    logger.info(f"Enriching code/demo info for {len(to_check)} papers via arXiv pages...")
    checked = 0
    code_found = 0
    demo_found = 0

    for p in to_check:
        try:
            # Fetch the arXiv abstract page (has full text + links)
            abs_url = f"https://arxiv.org/abs/{p.arxiv_id}"
            resp = requests.get(abs_url, timeout=10)
            if resp.status_code == 200:
                html = resp.text

                # Code detection: GitHub/GitLab links anywhere on the page
                code_match = re.search(
                    r'(https?://github\.com/[a-zA-Z0-9_\-]+/[a-zA-Z0-9_\-]+)',
                    html
                )
                if code_match:
                    p.has_code = True
                    p.code_url = code_match.group(1)
                    code_found += 1
                elif re.search(r'gitlab\.com/[a-zA-Z0-9_\-]+/[a-zA-Z0-9_\-]+', html):
                    p.has_code = True
                    code_found += 1

                # Demo detection: check full abstract + supplementary text
                if not p.has_demo and _detect_demo(html):
                    p.has_demo = True
                    demo_found += 1

            checked += 1
            if checked % 30 == 0:
                logger.info(f"  Enriched {checked}/{len(to_check)}: "
                            f"+{code_found} code, +{demo_found} demo")
            time.sleep(0.3)
        except Exception:
            checked += 1
            continue

    logger.info(f"  Enrichment done: +{code_found} code, +{demo_found} demo "
                f"(checked {checked}/{len(to_check)} papers)")
    return papers
