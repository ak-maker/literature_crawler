#!/usr/bin/env python3
"""
Citation Graph Generator
========================

Reads papers.json, queries Semantic Scholar for citation relationships
between high-scoring papers, and generates an interactive HTML graph.

Usage:
    python graph.py output/uav_ugv/papers.json
    python graph.py output/uav_ugv/papers.json --min-score 35
    python graph.py output/uav_ugv/papers.json --min-score 30 --max-nodes 80
"""

import argparse
import json
import logging
import os
import time
import requests
from pyvis.network import Network

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Load .env for S2 API key
_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())


# --- Method category detection (for node coloring) ---

METHOD_COLORS = {
    "Reinforcement Learning": "#e74c3c",
    "Model Predictive Control": "#3498db",
    "Formation Control": "#2ecc71",
    "Path Planning": "#f39c12",
    "Task Allocation": "#9b59b6",
    "SLAM / Mapping": "#1abc9c",
    "Communication": "#e67e22",
    "Consensus": "#34495e",
    "Swarm": "#e91e63",
    "Diffusion": "#00bcd4",
    "GNN": "#ff5722",
    "Other": "#95a5a6",
}

METHOD_KEYWORDS = {
    "Reinforcement Learning": ["reinforcement learning", "rl ", "q-learning", "ppo", "marl", "drl"],
    "Diffusion": ["diffusion model", "diffusion policy", "denoising"],
    "GNN": ["graph neural", "gnn", "graph attention"],
    "Model Predictive Control": ["model predictive control", "mpc"],
    "Formation Control": ["formation control", "formation keeping"],
    "Consensus": ["consensus"],
    "Path Planning": ["path planning", "trajectory planning", "trajectory optimization"],
    "Task Allocation": ["task allocation", "task assignment"],
    "SLAM / Mapping": ["slam", "mapping", "localization"],
    "Communication": ["communication", "message passing", "bandwidth"],
    "Swarm": ["swarm"],
}


def detect_method(paper):
    text = f"{paper['title']} {paper.get('abstract', '')}".lower()
    for method, keywords in METHOD_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return method
    return "Other"


def get_s2_paper_id(paper):
    """Extract a usable Semantic Scholar paper ID."""
    # From S2 URL
    url = paper.get("url", "")
    if "semanticscholar.org/paper/" in url:
        return url.split("/paper/")[-1]
    # From arXiv ID
    arxiv_id = paper.get("arxiv_id", "")
    if arxiv_id:
        # Strip version suffix for S2 lookup
        clean = arxiv_id.split("v")[0] if "v" in arxiv_id else arxiv_id
        return f"ArXiv:{clean}"
    return None


def fetch_citations(papers, api_key=None):
    """
    For each paper, query S2 to get its references.
    Returns dict: paper_title -> set of referenced S2 paper IDs.
    """
    headers = {}
    base_url = "https://api.semanticscholar.org/graph/v1"
    rate_limit = 3.0

    if api_key and api_key.startswith("sk-user-"):
        base_url = "https://ai4scholar.net/graph/v1"
        headers["Authorization"] = f"Bearer {api_key}"
        rate_limit = 0.5
    elif api_key:
        headers["x-api-key"] = api_key
        rate_limit = 0.5

    # Build a set of all S2 IDs in our paper set (for matching)
    our_ids = set()
    id_to_title = {}
    for p in papers:
        sid = get_s2_paper_id(p)
        if sid:
            our_ids.add(sid)
            id_to_title[sid] = p["title"]

    # For each paper, get references and check which ones are in our set
    edges = []  # (source_title, target_title)
    checked = 0

    for p in papers:
        sid = get_s2_paper_id(p)
        if not sid:
            continue

        try:
            resp = requests.get(
                f"{base_url}/paper/{sid}",
                params={"fields": "references,references.externalIds"},
                headers=headers,
                timeout=15,
            )

            if resp.status_code == 429:
                logger.warning("Rate limited, waiting 30s...")
                time.sleep(30)
                resp = requests.get(
                    f"{base_url}/paper/{sid}",
                    params={"fields": "references,references.externalIds"},
                    headers=headers,
                    timeout=15,
                )

            if resp.status_code == 200:
                data = resp.json()
                refs = data.get("references") or []
                for ref in refs:
                    ref_id = ref.get("paperId", "")
                    # Check if this reference's S2 ID or ArXiv ID is in our set
                    if ref_id in our_ids:
                        edges.append((p["title"], id_to_title[ref_id]))
                    else:
                        # Check ArXiv ID
                        ext = ref.get("externalIds") or {}
                        arxiv = ext.get("ArXiv", "")
                        if arxiv:
                            arxiv_key = f"ArXiv:{arxiv}"
                            if arxiv_key in our_ids:
                                edges.append((p["title"], id_to_title[arxiv_key]))

            checked += 1
            if checked % 10 == 0:
                logger.info(f"  Checked {checked}/{len(papers)} papers, found {len(edges)} edges")
            time.sleep(rate_limit)

        except Exception as e:
            logger.warning(f"  Error fetching {sid}: {e}")
            checked += 1
            continue

    logger.info(f"Citation scan done: {len(edges)} edges from {checked} papers")
    return edges


def build_graph(papers, edges, output_path):
    """Build interactive pyvis graph."""
    net = Network(
        height="900px",
        width="100%",
        bgcolor="#1a1a2e",
        font_color="white",
        directed=True,
        notebook=False,
    )

    # Physics settings for better layout
    net.set_options("""
    {
        "physics": {
            "forceAtlas2Based": {
                "gravitationalConstant": -80,
                "centralGravity": 0.01,
                "springLength": 150,
                "springConstant": 0.02,
                "damping": 0.4
            },
            "solver": "forceAtlas2Based",
            "stabilization": {"iterations": 200}
        },
        "interaction": {
            "hover": true,
            "tooltipDelay": 100,
            "zoomView": true
        },
        "edges": {
            "arrows": {"to": {"enabled": true, "scaleFactor": 0.5}},
            "color": {"color": "#555555", "opacity": 0.6},
            "smooth": {"type": "continuous"}
        }
    }
    """)

    # Add nodes
    title_to_paper = {p["title"]: p for p in papers}
    connected_titles = set()
    for src, tgt in edges:
        connected_titles.add(src)
        connected_titles.add(tgt)

    for p in papers:
        method = detect_method(p)
        color = METHOD_COLORS.get(method, "#95a5a6")
        score = p["scores"]["total"]
        year = p.get("year", "?")

        # Node size proportional to score
        size = 10 + score * 0.5

        # Border for code/demo
        border_width = 1
        border_color = color
        if p.get("has_code") and p.get("has_demo"):
            border_width = 4
            border_color = "#FFD700"  # Gold
        elif p.get("has_code"):
            border_width = 3
            border_color = "#00FF00"  # Green
        elif p.get("has_demo"):
            border_width = 3
            border_color = "#FF69B4"  # Pink

        # Short label
        title_short = p["title"][:40] + "..." if len(p["title"]) > 40 else p["title"]
        label = f"{title_short}\n({year})"

        # Hover tooltip
        tags = []
        if p.get("has_code"):
            tags.append("CODE")
        if p.get("has_demo"):
            tags.append("DEMO")
        tag_str = f" [{', '.join(tags)}]" if tags else ""
        tooltip = (
            f"<b>{p['title']}</b><br>"
            f"Year: {year} | Score: {score:.0f}{tag_str}<br>"
            f"Method: {method}<br>"
            f"Venue: {p.get('venue', 'N/A')}<br>"
            f"Citations: {p.get('citation_count', 0)}<br>"
            f"<a href='{p.get('url', '')}' target='_blank'>Link</a>"
        )
        if p.get("has_code") and p.get("code_url"):
            tooltip += f" | <a href='{p['code_url']}' target='_blank'>Code</a>"

        # Dim unconnected nodes
        opacity = 1.0 if p["title"] in connected_titles else 0.5

        net.add_node(
            p["title"],
            label=label,
            title=tooltip,
            size=size,
            color={
                "background": color,
                "border": border_color,
                "highlight": {"background": "#ffffff", "border": color},
            },
            borderWidth=border_width,
            font={"size": 9, "color": "white"},
            opacity=opacity,
        )

    # Add edges
    for src, tgt in edges:
        if src in title_to_paper and tgt in title_to_paper:
            net.add_edge(src, tgt)

    # Save
    net.save_graph(output_path)

    # Add legend as a manual HTML injection
    _inject_legend(output_path, papers, edges, connected_titles)

    logger.info(f"Graph saved: {output_path}")
    logger.info(f"  Nodes: {len(papers)}, Edges: {len(edges)}, "
                f"Connected: {len(connected_titles)}")


def _inject_legend(html_path, papers, edges, connected_titles):
    """Inject a legend + stats panel into the HTML."""
    legend_html = """
    <div id="legend" style="position:fixed; top:10px; right:10px; background:rgba(0,0,0,0.85);
         padding:15px; border-radius:8px; color:white; font-family:monospace; font-size:12px;
         max-width:280px; z-index:1000; border:1px solid #333;">
      <div style="font-size:14px; font-weight:bold; margin-bottom:8px;">Citation Graph</div>
      <div style="margin-bottom:8px;">
        Papers: {n_papers} | Edges: {n_edges} | Connected: {n_connected}
      </div>
      <div style="font-size:11px; margin-bottom:6px;"><b>Method Colors:</b></div>
      {color_items}
      <div style="font-size:11px; margin-top:8px;"><b>Borders:</b></div>
      <div><span style="color:#FFD700;">&#9632;</span> Code + Demo</div>
      <div><span style="color:#00FF00;">&#9632;</span> Code only</div>
      <div><span style="color:#FF69B4;">&#9632;</span> Demo only</div>
      <div style="font-size:10px; margin-top:8px; color:#888;">
        Node size = score | Arrow = cites<br>
        Hover for details | Scroll to zoom
      </div>
    </div>
    """

    # Build color items for methods that actually appear
    method_counts = {}
    for p in papers:
        m = detect_method(p)
        method_counts[m] = method_counts.get(m, 0) + 1

    color_items = ""
    for method, count in sorted(method_counts.items(), key=lambda x: -x[1]):
        c = METHOD_COLORS.get(method, "#95a5a6")
        color_items += f'<div><span style="color:{c};">&#9679;</span> {method} ({count})</div>\n'

    legend_html = legend_html.format(
        n_papers=len(papers),
        n_edges=len(edges),
        n_connected=len(connected_titles),
        color_items=color_items,
    )

    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    html = html.replace("</body>", legend_html + "\n</body>")

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)


def main():
    parser = argparse.ArgumentParser(description="Generate citation graph from papers.json")
    parser.add_argument("papers_json", help="Path to papers.json")
    parser.add_argument("--min-score", type=float, default=30,
                        help="Minimum score to include (default: 30)")
    parser.add_argument("--max-nodes", type=int, default=100,
                        help="Maximum number of papers to include (default: 100)")
    parser.add_argument("-o", "--output", default=None,
                        help="Output HTML path (default: same dir as papers.json)")
    parser.add_argument("--s2-api-key", default=os.environ.get("S2_API_KEY"),
                        help="Semantic Scholar API key")
    args = parser.parse_args()

    # Load papers
    with open(args.papers_json, "r", encoding="utf-8") as f:
        all_papers = json.load(f)

    # Filter
    papers = [p for p in all_papers if p["scores"]["total"] >= args.min_score]
    papers = papers[:args.max_nodes]
    logger.info(f"Selected {len(papers)} papers (score >= {args.min_score}, max {args.max_nodes})")

    if len(papers) < 2:
        logger.error("Need at least 2 papers to build a graph.")
        return

    # Fetch citation relationships
    logger.info("Fetching citation relationships from Semantic Scholar...")
    edges = fetch_citations(papers, api_key=args.s2_api_key)

    # Build graph
    output_path = args.output or os.path.join(
        os.path.dirname(args.papers_json), "citation_graph.html"
    )
    build_graph(papers, edges, output_path)

    print(f"\nOpen in browser: {os.path.abspath(output_path)}")


if __name__ == "__main__":
    main()
