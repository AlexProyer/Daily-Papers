#!/usr/bin/env python3
"""
Paper Radar - Daily Research Intelligence
Fetches papers from arXiv, Semantic Scholar, Papers With Code, and HuggingFace.
Scores them with heuristic-based relevance scoring (no API key required).
"""

import json
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from urllib.parse import urlencode, quote_plus
import sys
import os

# ─────────────────────────────────────────────
#  CONFIGURATION — edit this section freely
# ─────────────────────────────────────────────

# Your personal interest topics for the FILTERED report.
# Each group maps a human label -> list of regex patterns (matched with word
# boundaries, case-insensitive). Synonyms/acronyms are grouped so a paper that
# says "agentic" or "multi-agent" still matches "AI agents", etc.
# A paper must hit AT LEAST ONE group to appear in the filtered report at all.
TOPIC_GROUPS = {
    "cybersecurity": [
        r"cyber\s?security", r"\binfosec\b", r"information security",
        r"network security", r"security operations", r"\bSOC\b",
        r"zero[ -]?trust", r"threat intelligence",
    ],
    "vuln & threats": [
        r"vulnerabilit", r"\bCVE\b", r"\bexploit", r"intrusion detection",
        r"\bIDS\b", r"\bSIEM\b", r"\bmalware\b", r"ransomware", r"phishing",
        r"threat detection",
    ],
    "anomaly detection": [
        r"anomaly detection", r"outlier detection", r"novelty detection",
    ],
    "LLM": [
        r"\bLLMs?\b", r"large language model", r"foundation model",
    ],
    "AI agents": [
        r"\bAI agent", r"\bagentic\b", r"autonomous agent", r"\bLLM[ -]?agent",
        r"multi[- ]?agent", r"\btool[- ]use\b",
    ],
    "fintech & payments": [
        r"\bfintech\b", r"financial technology", r"\bpayment", r"\bPCI[\s-]?DSS\b",
        r"open banking", r"digital banking",
    ],
    "fraud detection": [
        r"\bfraud\b", r"money laundering", r"\bAML\b", r"financial crime",
    ],
    "compliance & audit": [
        r"\bcompliance\b", r"regulatory", r"security audit", r"\bGDPR\b", r"\bSOC\s?2\b",
    ],
    "adversarial ML": [
        r"adversarial", r"\bjailbreak", r"prompt injection", r"red[- ]team",
        r"model extraction", r"data poisoning", r"\bbackdoor\b",
    ],
}

# Derived flat list (used only for display in the report footer)
PERSONAL_TOPICS = list(TOPIC_GROUPS.keys())

# arXiv categories to monitor (cs = Computer Science, stat = Statistics)
ARXIV_CATEGORIES = [
    "cs.CR",   # Cryptography and Security
    "cs.AI",   # Artificial Intelligence
    "cs.LG",   # Machine Learning
    "cs.CV",   # Computer Vision
    "cs.NE",   # Neural and Evolutionary Computing
    "cs.SE",   # Software Engineering
    "stat.ML", # Statistics - Machine Learning
    "cs.CL",   # Computation and Language (NLP)
    "cs.RO",   # Robotics
    "econ.GN", # General Economics
]

# Scoring weights — these drive what gets selected
SCORE_WEIGHTS = {
    "recency_bonus":       20,   # published today/yesterday
    "hf_daily_featured":  25,   # curated by HuggingFace community
    "has_code":           15,   # has public code repository
    "high_citations_new": 18,   # high citations for a new paper
    "topic_match":        30,   # matches personal topics (filtered report only)
    "abstract_quality":   10,   # novelty signals in abstract
    "influential_authors":  7,  # from known high-impact venues/institutions
}

# GENERAL report = high-POTENTIAL papers regardless of topic (original design).
# Kept at 30 so strong arXiv papers (which only earn recency + abstract signals,
# no code/citation/HF bonus) can still surface. Noise is controlled by the
# trimmed novelty keyword lists, not by a high threshold.
MIN_SCORE_GENERAL  = 30   # minimum score for general report
# FILTERED report = your topics, "few but excellent": high threshold PLUS a hard
# topic-match requirement (see generate_report).
MIN_SCORE_FILTERED = 50
MAX_PAPERS_PER_SOURCE = 8 # max top papers shown per source

# ─────────────────────────────────────────────
#  NOVELTY SIGNAL KEYWORDS (abstract analysis)
# ─────────────────────────────────────────────

# Kept deliberately small: only STRONG novelty/impact signals. Generic academic
# filler ("we propose", "we present", "benchmark") was removed because it appears
# in nearly every paper and was inflating scores past the threshold.
NOVELTY_POSITIVE = [
    "state-of-the-art", "sota", "outperform", "surpass", "breakthrough",
    "significant improvement", "outperforms previous", "first to",
    "open source", "open-source",
]

NOVELTY_NEGATIVE = [
    "survey", "review", "overview", "tutorial", "summary of", "we survey",
    "literature review", "systematic review"
]

IMPACT_SIGNALS = [
    "large-scale", "trillion", "billion parameters", "100B", "GPT-4", "Claude",
    "Gemini", "Llama", "foundation model", "multimodal", "autonomous",
    "zero-shot", "few-shot", "instruction tuning", "RLHF", "alignment",
    "safety", "attack", "defense", "adversarial", "jailbreak", "red team"
]

# ─────────────────────────────────────────────
#  UTILITIES
# ─────────────────────────────────────────────

def safe_get(url, headers=None, timeout=15):
    """HTTP GET with retry logic."""
    default_headers = {
        "User-Agent": "PaperRadar/1.0 (research aggregator; contact via GitHub)"
    }
    if headers:
        default_headers.update(headers)
    for attempt in range(3):
        try:
            req = Request(url, headers=default_headers)
            with urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except (URLError, HTTPError) as e:
            if attempt == 2:
                print(f"    ⚠ Failed to fetch {url[:80]}... ({e})", file=sys.stderr)
                return None
            time.sleep(2 ** attempt)
    return None

def today_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")

def yesterday_utc():
    return (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")

def is_recent(date_str):
    """Returns True if date is today or yesterday (UTC)."""
    if not date_str:
        return False
    ds = date_str[:10]
    return ds in (today_utc(), yesterday_utc())

def clean_text(text):
    if not text:
        return ""
    text = re.sub(r'\s+', ' ', text).strip()
    return text

# ─────────────────────────────────────────────
#  SCORING ENGINE
# ─────────────────────────────────────────────

def match_topics(text):
    """Return the list of TOPIC_GROUPS labels whose patterns match `text`.

    Uses word-boundary, case-insensitive regex (not naive substring) so that
    'agentic' matches 'AI agents' but 'llm' does NOT match inside other words.
    """
    matched = []
    for label, patterns in TOPIC_GROUPS.items():
        if any(re.search(p, text, re.IGNORECASE) for p in patterns):
            matched.append(label)
    return matched

def score_paper(paper, personal_filter=False):
    """
    Score a paper 0–100 using heuristic signals.
    paper dict keys: title, abstract, date, has_code, citations,
                     hf_featured, url, authors, venue
    Returns (score, reasons, topic_matches).
    """
    score = 0
    reasons = []

    # 1. Recency
    if is_recent(paper.get("date", "")):
        score += SCORE_WEIGHTS["recency_bonus"]
        reasons.append("📅 paper reciente (24-48h)")

    # 2. HuggingFace daily featured
    if paper.get("hf_featured"):
        score += SCORE_WEIGHTS["hf_daily_featured"]
        reasons.append("🤗 destacado en HF Daily Papers")

    # 3. Has public code
    if paper.get("has_code"):
        score += SCORE_WEIGHTS["has_code"]
        reasons.append("💻 código público disponible")

    # 4. Citation velocity (impressive for a new paper)
    cites = paper.get("citations", 0) or 0
    if cites >= 50:
        score += SCORE_WEIGHTS["high_citations_new"]
        reasons.append(f"📈 {cites} citas (alto para paper nuevo)")
    elif cites >= 20:
        score += int(SCORE_WEIGHTS["high_citations_new"] * 0.6)
        reasons.append(f"📈 {cites} citas")
    elif cites >= 5:
        score += int(SCORE_WEIGHTS["high_citations_new"] * 0.3)

    # 5. Abstract quality — novelty signals
    abstract = (paper.get("abstract", "") or "").lower()
    title    = (paper.get("title",    "") or "").lower()
    combined = abstract + " " + title

    pos_hits = sum(1 for kw in NOVELTY_POSITIVE if kw.lower() in combined)
    neg_hits = sum(1 for kw in NOVELTY_NEGATIVE if kw.lower() in combined)
    impact_hits = sum(1 for kw in IMPACT_SIGNALS if kw.lower() in combined)

    abstract_score = min(pos_hits * 2 + impact_hits * 3 - neg_hits * 4, SCORE_WEIGHTS["abstract_quality"])
    if abstract_score > 0:
        score += abstract_score
        reasons.append(f"🔬 señales de novedad en abstract (+{abstract_score})")

    # 6. Personal topic match (only for filtered report)
    topic_matches = match_topics(combined)
    if personal_filter and topic_matches:
        topic_score = min(len(topic_matches) * 12, SCORE_WEIGHTS["topic_match"])
        score += topic_score
        reasons.append(f"🎯 temas: {', '.join(topic_matches[:3])}")

    return min(score, 100), reasons, topic_matches

# ─────────────────────────────────────────────
#  SOURCE: arXiv
# ─────────────────────────────────────────────

def fetch_arxiv():
    """Fetch recent papers from arXiv API across configured categories."""
    print("  📥 Fetching arXiv...", file=sys.stderr)
    papers = []
    seen_ids = set()

    for cat in ARXIV_CATEGORIES:
        params = urlencode({
            "search_query": f"cat:{cat}",
            "start": 0,
            "max_results": 25,
            "sortBy": "submittedDate",
            "sortOrder": "descending"
        })
        url = f"https://export.arxiv.org/api/query?{params}"
        raw = safe_get(url)
        if not raw:
            continue

        try:
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            root = ET.fromstring(raw)
            for entry in root.findall("atom:entry", ns):
                arxiv_id = (entry.findtext("atom:id", "", ns) or "").split("/abs/")[-1]
                if arxiv_id in seen_ids:
                    continue
                seen_ids.add(arxiv_id)

                published = (entry.findtext("atom:published", "", ns) or "")[:10]
                if not is_recent(published):
                    continue

                authors = [
                    a.findtext("atom:name", "", ns)
                    for a in entry.findall("atom:author", ns)
                ]
                pdf_url = ""
                for link in entry.findall("atom:link", ns):
                    if link.get("type") == "application/pdf":
                        pdf_url = link.get("href", "")

                papers.append({
                    "source": "arXiv",
                    "id": arxiv_id,
                    "title": clean_text(entry.findtext("atom:title", "", ns)),
                    "abstract": clean_text(entry.findtext("atom:summary", "", ns)),
                    "authors": authors[:4],
                    "date": published,
                    "url": f"https://arxiv.org/abs/{arxiv_id}",
                    "pdf_url": pdf_url or f"https://arxiv.org/pdf/{arxiv_id}",
                    "venue": f"arXiv [{cat}]",
                    "has_code": False,
                    "citations": 0,
                    "hf_featured": False,
                })
        except ET.ParseError as e:
            print(f"    ⚠ XML parse error for {cat}: {e}", file=sys.stderr)

        time.sleep(0.5)  # respect arXiv rate limits

    print(f"    ✓ {len(papers)} recent arXiv papers found", file=sys.stderr)
    return papers

# ─────────────────────────────────────────────
#  SOURCE: Semantic Scholar
# ─────────────────────────────────────────────

def fetch_semantic_scholar():
    """Fetch trending/recent papers from Semantic Scholar API."""
    print("  📥 Fetching Semantic Scholar...", file=sys.stderr)
    papers = []

    # Use the recommendations API and paper search for recent high-impact papers
    fields = "paperId,title,abstract,authors,year,publicationDate,citationCount,openAccessPdf,externalIds,venue"

    # Strategy: search for papers published in last 2 days across key fields
    queries = [
        "machine learning security",
        "large language model",
        "neural network optimization",
        "adversarial attack defense",
        "AI safety alignment",
    ]
    seen_ids = set()
    date_from = yesterday_utc()

    for q in queries:
        url = (
            f"https://api.semanticscholar.org/graph/v1/paper/search"
            f"?query={quote_plus(q)}"
            f"&fields={fields}"
            f"&publicationDateOrYear={date_from}:"
            f"&limit=10"
        )
        raw = safe_get(url)
        if not raw:
            continue
        try:
            data = json.loads(raw)
            for p in data.get("data", []):
                pid = p.get("paperId", "")
                if pid in seen_ids:
                    continue
                seen_ids.add(pid)

                # Precision over recall: only keep papers we can confirm are
                # from the last 24-48h. Unknown/old publication dates are dropped.
                pub_date = p.get("publicationDate", "") or ""
                if not is_recent(pub_date):
                    continue

                authors = [a.get("name", "") for a in p.get("authors", [])[:4]]
                pdf_url = ""
                oap = p.get("openAccessPdf")
                if oap and isinstance(oap, dict):
                    pdf_url = oap.get("url", "")

                arxiv_id = p.get("externalIds", {}).get("ArXiv", "")
                paper_url = (
                    f"https://arxiv.org/abs/{arxiv_id}"
                    if arxiv_id
                    else f"https://www.semanticscholar.org/paper/{pid}"
                )

                papers.append({
                    "source": "Semantic Scholar",
                    "id": pid,
                    "title": clean_text(p.get("title", "")),
                    "abstract": clean_text(p.get("abstract", "")),
                    "authors": authors,
                    "date": pub_date[:10] if pub_date else "",
                    "url": paper_url,
                    "pdf_url": pdf_url,
                    "venue": clean_text(p.get("venue", "Semantic Scholar")),
                    "has_code": False,
                    "citations": p.get("citationCount", 0),
                    "hf_featured": False,
                })
        except (json.JSONDecodeError, KeyError, ValueError):
            pass
        time.sleep(1)

    print(f"    ✓ {len(papers)} Semantic Scholar papers found", file=sys.stderr)
    return papers

# ─────────────────────────────────────────────
#  SOURCE: Papers With Code
# ─────────────────────────────────────────────

def fetch_papers_with_code():
    """Fetch latest papers from Papers With Code API."""
    print("  📥 Fetching Papers With Code...", file=sys.stderr)
    papers = []
    seen_ids = set()

    url = (
        "https://paperswithcode.com/api/v1/papers/"
        "?ordering=-published&items_per_page=50"
    )
    raw = safe_get(url)
    if not raw:
        return papers

    try:
        data = json.loads(raw)
        for p in data.get("results", []):
            pub_date = (p.get("published", "") or "")[:10]
            if not is_recent(pub_date):
                continue

            pid = str(p.get("id", ""))
            if pid in seen_ids:
                continue
            seen_ids.add(pid)

            arxiv_id = p.get("arxiv_id", "")
            paper_url = (
                f"https://arxiv.org/abs/{arxiv_id}"
                if arxiv_id
                else f"https://paperswithcode.com/paper/{p.get('paper_page', pid)}"
            )

            papers.append({
                "source": "Papers With Code",
                "id": pid,
                "title": clean_text(p.get("title", "")),
                "abstract": clean_text(p.get("abstract", "")),
                "authors": (p.get("authors", []) or [])[:4],
                "date": pub_date,
                "url": paper_url,
                "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}" if arxiv_id else "",
                "venue": "Papers With Code",
                "has_code": True,  # by definition — they have code
                "citations": 0,
                "hf_featured": False,
            })
    except (json.JSONDecodeError, KeyError):
        pass

    print(f"    ✓ {len(papers)} Papers With Code papers found", file=sys.stderr)
    return papers

# ─────────────────────────────────────────────
#  SOURCE: HuggingFace Daily Papers
# ─────────────────────────────────────────────

def fetch_huggingface():
    """Fetch HuggingFace daily papers (community-curated)."""
    print("  📥 Fetching HuggingFace Daily Papers...", file=sys.stderr)
    papers = []

    url = f"https://huggingface.co/api/daily_papers?date={today_utc()}&limit=30"
    raw = safe_get(url)

    if not raw:
        # Fallback: yesterday
        url = f"https://huggingface.co/api/daily_papers?date={yesterday_utc()}&limit=30"
        raw = safe_get(url)

    if not raw:
        return papers

    try:
        data = json.loads(raw)
        items = data if isinstance(data, list) else data.get("papers", [])

        for item in items:
            paper = item.get("paper", item)
            pid = paper.get("id", "") or paper.get("arxiv_id", "")
            if not pid:
                continue

            # HF papers often use arxiv IDs
            arxiv_id = paper.get("arxiv_id", pid)
            authors_raw = paper.get("authors", []) or []
            if authors_raw and isinstance(authors_raw[0], dict):
                authors = [a.get("name", a.get("user", {}).get("fullname", "")) for a in authors_raw[:4]]
            else:
                authors = authors_raw[:4]

            pub_date = (paper.get("publishedAt", "") or "")[:10]

            papers.append({
                "source": "HuggingFace Daily Papers",
                "id": pid,
                "title": clean_text(paper.get("title", "")),
                "abstract": clean_text(paper.get("summary", paper.get("abstract", ""))),
                "authors": authors,
                "date": pub_date,
                "url": f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else f"https://huggingface.co/papers/{pid}",
                "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}" if arxiv_id else "",
                "venue": "HuggingFace Daily Papers",
                "has_code": False,
                "citations": item.get("numComments", 0),  # use HF engagement as proxy
                "hf_featured": True,  # ALL HF daily papers are community-curated
            })
    except (json.JSONDecodeError, KeyError, TypeError):
        pass

    print(f"    ✓ {len(papers)} HuggingFace papers found", file=sys.stderr)
    return papers

# ─────────────────────────────────────────────
#  DEDUPLICATION
# ─────────────────────────────────────────────

def deduplicate(papers):
    """Remove duplicates by title similarity."""
    seen_titles = {}
    unique = []
    for p in papers:
        title_key = re.sub(r'[^a-z0-9]', '', (p.get("title") or "").lower())[:60]
        if title_key and title_key not in seen_titles:
            seen_titles[title_key] = True
            unique.append(p)
    return unique

# ─────────────────────────────────────────────
#  REPORT GENERATION
# ─────────────────────────────────────────────

def truncate_abstract(text, max_words=80):
    """Truncate abstract to a readable length."""
    if not text:
        return "_Sin abstract disponible._"
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + "..."

def build_paper_block(paper, score, reasons, rank):
    """Format a single paper entry for the Markdown report."""
    authors_str = ", ".join(paper.get("authors", []) or [])
    if not authors_str:
        authors_str = "_Autores no disponibles_"

    abstract = truncate_abstract(paper.get("abstract", ""))
    date = paper.get("date", "—")
    venue = paper.get("venue", "—")
    url = paper.get("url", "")
    pdf = paper.get("pdf_url", "")

    links = []
    if url:
        links.append(f"[🔗 Ver paper]({url})")
    if pdf:
        links.append(f"[📄 PDF]({pdf})")
    links_str = " · ".join(links) if links else ""

    reasons_str = " · ".join(reasons) if reasons else "señales generales de relevancia"
    score_bar = "█" * (score // 10) + "░" * (10 - score // 10)

    return f"""
### {rank}. {paper.get('title', 'Sin título')}

> **Score:** `{score}/100` `{score_bar}`  
> **Por qué es relevante:** {reasons_str}

**Autores:** {authors_str}  
**Fuente:** {venue} · **Fecha:** {date}  
{links_str}

**Resumen:**  
{abstract}

---"""

def generate_report(all_papers, today_str):
    """Generate both the general and filtered Markdown reports."""

    # ── Score all papers ──────────────────────────
    scored_general  = []
    scored_filtered = []

    for p in all_papers:
        sg, rg, _ = score_paper(p, personal_filter=False)
        sf, rf, topic_matches = score_paper(p, personal_filter=True)
        if sg >= MIN_SCORE_GENERAL:
            scored_general.append((sg, rg, p))
        # Filtered report = HARD requirement of at least one topic match
        # AND a high score. This is what kills off-topic false positives.
        if topic_matches and sf >= MIN_SCORE_FILTERED:
            scored_filtered.append((sf, rf, p))

    # Sort by score desc
    scored_general.sort(key=lambda x: x[0], reverse=True)
    scored_filtered.sort(key=lambda x: x[0], reverse=True)

    # ── Group by source ────────────────────────────
    sources = ["arXiv", "Semantic Scholar", "Papers With Code", "HuggingFace Daily Papers"]

    def group_by_source(scored_list):
        groups = {s: [] for s in sources}
        for score, reasons, paper in scored_list:
            src = paper.get("source", "Other")
            if src in groups:
                groups[src].append((score, reasons, paper))
        return groups

    gen_groups  = group_by_source(scored_general)
    filt_groups = group_by_source(scored_filtered)

    total_gen  = sum(len(v) for v in gen_groups.values())
    total_filt = sum(len(v) for v in filt_groups.values())

    # ── GENERAL REPORT ─────────────────────────────
    gen_lines = [
        f"# 📡 Paper Radar — Reporte General",
        f"**Fecha:** {today_str} · **Papers evaluados:** {len(all_papers)} · **Seleccionados:** {total_gen}",
        f"",
        f"> Este reporte incluye los papers con mayor potencial de todas las fuentes,",
        f"> sin filtro temático. Ordenados por score de relevancia.",
        f"",
        f"---",
        f"",
    ]

    for src in sources:
        items = gen_groups[src][:MAX_PAPERS_PER_SOURCE]
        if not items:
            gen_lines.append(f"## 🔵 {src}\n\n_No hay papers con score suficiente hoy en esta fuente._\n\n---\n")
            continue
        gen_lines.append(f"## 🔵 {src}\n")
        gen_lines.append(f"_{len(items)} papers seleccionados de esta fuente_\n")
        for i, (score, reasons, paper) in enumerate(items, 1):
            gen_lines.append(build_paper_block(paper, score, reasons, i))
        gen_lines.append("")

    gen_lines += [
        "---",
        "",
        f"*Generado automáticamente por Paper Radar · {today_str}*",
        "*Criterios: recencia (24-48h), señales de novedad en abstract, código disponible, citas, featured en HF*",
    ]

    # ── FILTERED REPORT ────────────────────────────
    topics_preview = ", ".join(PERSONAL_TOPICS[:6]) + "..."
    filt_lines = [
        f"# 🎯 Paper Radar — Reporte Filtrado (Mis Temas)",
        f"**Fecha:** {today_str} · **Papers evaluados:** {len(all_papers)} · **Seleccionados:** {total_filt}",
        f"",
        f"> Filtrado por temas de interés personal: _{topics_preview}_",
        f"> Umbral de score más alto ({MIN_SCORE_FILTERED}/100) para máxima precisión.",
        f"",
        f"---",
        f"",
    ]

    if total_filt == 0:
        filt_lines.append(
            "> ⚠️ No se encontraron papers que superen el umbral en tus temas hoy. "
            "Revisa el reporte general para ver todos los papers seleccionados.\n"
        )
    else:
        for src in sources:
            items = filt_groups[src][:MAX_PAPERS_PER_SOURCE]
            if not items:
                continue
            filt_lines.append(f"## 🎯 {src}\n")
            filt_lines.append(f"_{len(items)} papers relevantes a tus temas_\n")
            for i, (score, reasons, paper) in enumerate(items, 1):
                filt_lines.append(build_paper_block(paper, score, reasons, i))
            filt_lines.append("")

    filt_lines += [
        "---",
        "",
        f"*Generado automáticamente por Paper Radar · {today_str}*",
        f"*Temas configurados: {', '.join(PERSONAL_TOPICS)}*",
    ]

    return "\n".join(gen_lines), "\n".join(filt_lines)

# ─────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────

def main():
    today_str = today_utc()
    print(f"\n🚀 Paper Radar starting — {today_str}", file=sys.stderr)
    print("=" * 50, file=sys.stderr)

    # Fetch from all sources
    all_papers = []
    all_papers += fetch_arxiv()
    all_papers += fetch_semantic_scholar()
    all_papers += fetch_papers_with_code()
    all_papers += fetch_huggingface()

    # Deduplicate
    all_papers = deduplicate(all_papers)
    print(f"\n📊 Total unique papers after dedup: {len(all_papers)}", file=sys.stderr)

    # Generate reports
    print("✍️  Generating reports...", file=sys.stderr)
    general_md, filtered_md = generate_report(all_papers, today_str)

    # Output directory
    out_dir = os.environ.get("REPORTS_DIR", "reports")
    os.makedirs(out_dir, exist_ok=True)

    gen_path  = os.path.join(out_dir, f"{today_str}_general.md")
    filt_path = os.path.join(out_dir, f"{today_str}_filtrado.md")

    with open(gen_path, "w", encoding="utf-8") as f:
        f.write(general_md)
    with open(filt_path, "w", encoding="utf-8") as f:
        f.write(filtered_md)

    # Update index
    index_path = os.path.join(out_dir, "README.md")
    update_index(index_path, today_str, out_dir)

    print(f"\n✅ Done!", file=sys.stderr)
    print(f"   General:  {gen_path}", file=sys.stderr)
    print(f"   Filtered: {filt_path}", file=sys.stderr)

def update_index(index_path, today_str, out_dir):
    """Maintain a rolling index of all reports."""
    # Read existing entries
    existing = []
    if os.path.exists(index_path):
        with open(index_path, encoding="utf-8") as f:
            for line in f:
                if line.startswith("| 202"):
                    existing.append(line.strip())

    new_entry = f"| {today_str} | [Reporte General]({today_str}_general.md) | [Reporte Filtrado]({today_str}_filtrado.md) |"
    # Remove today if already exists
    existing = [l for l in existing if not l.startswith(f"| {today_str}")]
    existing.insert(0, new_entry)
    # Keep last 30 days
    existing = existing[:30]

    index_content = f"""# 📡 Paper Radar — Índice de Reportes

Reportes diarios de papers científicos seleccionados por relevancia e impacto potencial.

**Fuentes:** arXiv · Semantic Scholar · Papers With Code · HuggingFace Daily Papers  
**Actualización:** diaria automática vía GitHub Actions (7:00 AM hora Colombia)

---

| Fecha | Reporte General | Reporte Filtrado |
|-------|----------------|-----------------|
{chr(10).join(existing)}

---

*Paper Radar — sistema de inteligencia de investigación científica*
"""
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(index_content)

if __name__ == "__main__":
    main()
