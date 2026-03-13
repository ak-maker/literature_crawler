"""
Analysis utilities: keyword extraction, top authors, method evolution.
"""

import re
from collections import Counter
from typing import List, Tuple, Dict

from fetcher import Paper

STOPWORDS = {
    'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
    'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'been',
    'be', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
    'should', 'may', 'might', 'shall', 'can', 'that', 'which', 'who', 'whom',
    'this', 'these', 'those', 'it', 'its', 'we', 'our', 'us', 'they', 'their',
    'them', 'he', 'she', 'his', 'her', 'my', 'your', 'also', 'such', 'both',
    'each', 'more', 'most', 'other', 'some', 'no', 'not', 'only', 'same',
    'so', 'than', 'too', 'very', 'just', 'about', 'above', 'after', 'again',
    'all', 'am', 'any', 'because', 'before', 'being', 'below', 'between',
    'during', 'few', 'further', 'here', 'how', 'into', 'itself', 'me',
    'nor', 'once', 'out', 'over', 'own', 'per', 'then', 'there', 'through',
    'under', 'until', 'up', 'what', 'when', 'where', 'while', 'why',
    'however', 'based', 'using', 'proposed', 'method', 'approach', 'paper',
    'show', 'results', 'propose', 'presented', 'problem', 'new', 'two',
    'first', 'one', 'used', 'use', 'different', 'well', 'respectively',
    'achieve', 'achieved', 'performance', 'compared', 'existing', 'methods',
    'approaches', 'thus', 'hence', 'therefore', 'given', 'without', 'within',
    'among', 'across', 'several', 'many', 'much', 'get', 'set', 'let',
    'three', 'four', 'five', 'can', 'demonstrate', 'demonstrates',
    'work', 'number', 'able', 'order', 'provide', 'provides',
    'consider', 'enable', 'enables', 'allow', 'allows', 'address',
    'study', 'aim', 'investigate', 'present', 'introduce', 'develop',
    'large', 'small', 'high', 'low', 'significantly',
}


def extract_keywords(papers: List[Paper], top_n: int = 50) -> List[Tuple[str, int]]:
    """Extract high-frequency bigrams and important unigrams."""
    bigram_counter = Counter()
    unigram_counter = Counter()

    for p in papers:
        text = f"{p.title} {p.abstract}".lower()
        words = re.findall(r'\b[a-z]{3,}\b', text)
        filtered = [w for w in words if w not in STOPWORDS]

        unigram_counter.update(filtered)

        for i in range(len(filtered) - 1):
            bigram_counter[f"{filtered[i]} {filtered[i+1]}"] += 1

    # Prefer bigrams, supplement with unigrams not already covered
    combined = list(bigram_counter.most_common(top_n))
    for w, count in unigram_counter.most_common(top_n * 2):
        if len(combined) >= top_n:
            break
        if not any(w in bg for bg, _ in combined):
            combined.append((w, count))

    combined.sort(key=lambda x: x[1], reverse=True)
    return combined[:top_n]


def top_authors(papers: List[Paper], top_n: int = 20) -> List[Tuple[str, int, float]]:
    """Top authors by paper count, with average paper score."""
    author_papers: Dict[str, List[Paper]] = {}

    for p in papers:
        for a in p.authors:
            author_papers.setdefault(a, []).append(p)

    result = []
    for author, plist in author_papers.items():
        count = len(plist)
        avg_score = sum(p.total_score for p in plist) / count
        result.append((author, count, round(avg_score, 1)))

    result.sort(key=lambda x: (x[1], x[2]), reverse=True)
    return result[:top_n]


def method_evolution(papers: List[Paper]) -> Dict[int, Dict[str, int]]:
    """Track method/topic keywords by year."""
    method_keywords = [
        'reinforcement learning', 'deep learning', 'neural network',
        'diffusion', 'transformer', 'graph neural', 'attention mechanism',
        'model predictive control', 'mpc', 'pid control',
        'optimal control', 'lyapunov',
        'potential field', 'voronoi', 'formation control',
        'consensus', 'swarm', 'multi-agent', 'decentralized',
        'centralized', 'distributed control',
        'imitation learning', 'inverse reinforcement',
        'sim-to-real', 'transfer learning',
        'lidar', 'visual', 'slam', 'mapping',
        'task allocation', 'path planning', 'trajectory optimization',
        'cooperative', 'collaborative', 'heterogeneous',
        'communication', 'synchronization',
        'coverage', 'exploration', 'search and rescue',
    ]

    yearly: Dict[int, Counter] = {}
    for p in papers:
        if not p.year:
            continue
        if p.year not in yearly:
            yearly[p.year] = Counter()

        text = f"{p.title} {p.abstract}".lower()
        for kw in method_keywords:
            if kw in text:
                yearly[p.year][kw] += 1

    return {y: dict(c) for y, c in sorted(yearly.items())}


def venue_distribution(papers: List[Paper]) -> List[Tuple[str, int]]:
    """Count papers per venue."""
    counter = Counter()
    for p in papers:
        venue = p.venue.strip() if p.venue.strip() else ("arXiv preprint" if p.arxiv_id else "Unknown")
        # Normalize short venue names
        counter[venue] += 1
    return counter.most_common(30)


def year_distribution(papers: List[Paper]) -> Dict[int, int]:
    """Count papers per year."""
    counter = Counter()
    for p in papers:
        if p.year:
            counter[p.year] += 1
    return dict(sorted(counter.items()))


# Method categories for collapsible report sections
METHOD_CATEGORIES = {
    "Reinforcement Learning": ["reinforcement learning", "rl ", "q-learning", "policy gradient", "ppo", "sac", "marl"],
    "Diffusion Models": ["diffusion model", "diffusion policy", "denoising", "score-based"],
    "Graph Neural Networks": ["graph neural", "gnn", "graph attention", "graph convolution"],
    "Transformer / Attention": ["transformer", "attention mechanism", "self-attention"],
    "Imitation / Inverse RL": ["imitation learning", "inverse reinforcement", "learning from demonstration"],
    "Model Predictive Control": ["model predictive control", "mpc", "receding horizon"],
    "Optimal / Lyapunov Control": ["optimal control", "lyapunov", "control barrier", "cbf"],
    "PID / Classical Control": ["pid control", "pid controller", "proportional integral"],
    "Potential Field": ["potential field", "artificial potential", "apf"],
    "Formation Control": ["formation control", "formation keeping", "formation flight"],
    "Consensus Methods": ["consensus", "consensus protocol", "consensus-based"],
    "Path Planning / Trajectory": ["path planning", "trajectory planning", "trajectory optimization", "rrt", "a*", "prm"],
    "Task Allocation": ["task allocation", "task assignment", "task scheduling"],
    "SLAM / Mapping": ["slam", "simultaneous localization", "mapping", "exploration"],
    "Communication": ["communication", "bandwidth", "latency", "message passing"],
    "Sim-to-Real / Transfer": ["sim-to-real", "sim2real", "transfer learning", "domain adaptation"],
    "Swarm Intelligence": ["swarm intelligence", "swarm robotics", "particle swarm", "ant colony"],
    "Coverage / Search": ["coverage", "search and rescue", "area coverage", "surveillance"],
}


def method_paper_groups(papers: List[Paper]) -> Dict[str, List]:
    """Group papers by method category, sorted by score within each group."""
    groups = {cat: [] for cat in METHOD_CATEGORIES}

    for p in papers:
        text = f"{p.title} {p.abstract}".lower()
        for cat, keywords in METHOD_CATEGORIES.items():
            if any(kw in text for kw in keywords):
                groups[cat].append(p)

    # Sort each group by score, remove empty groups
    return {
        cat: sorted(plist, key=lambda x: x.total_score, reverse=True)
        for cat, plist in groups.items()
        if plist
    }
