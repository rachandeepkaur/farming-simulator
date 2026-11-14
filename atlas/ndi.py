"""Task 5: crop guides -> structured crop facts, each with its source page.

Pipeline, per guide in data/guides.json:

1. Parse. NDI (Nace `POST /v1/documents/parse`, markdown output) by default;
   `local` uses pypdf on the downloaded PDF and needs no key. Raw Nace
   responses are saved under data/ndi/nace/ so the response shape can be
   checked on the first real run.
2. Select. Keep the pages that mention water use, frost, heat, nitrogen
   fixing or roots, so the extractor reads tens of pages, not hundreds.
3. Extract. One Claude call per crop over all its guides, with structured
   output: for each fact a value, the guide, the page and a verbatim quote.
4. Verify. Every quote must appear in the PDF's own text (pypdf, whitespace
   and hyphenation ignored), and every number must appear in its quote.
   The page we report is the PDF page where the quote was found, not the
   page the model claimed. Facts that fail are dropped, never guessed.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

import httpx

from .config import DATA_DIR

NDI_DIR = DATA_DIR / "ndi"
GUIDES_PATH = DATA_DIR / "guides.json"
NACE_PARSE_URL = "https://console.nace.ai/v1/documents/parse"
NACE_CLIENT = "rotation-atlas/0.1"
USER_AGENT = "Mozilla/5.0 (rotation-atlas crop-guide fetcher)"

FACTS = ("water_use", "frost_tolerance", "heat_tolerance", "nitrogen_fixing", "root_depth")

FACT_KEYWORDS = {
    "water_use": r"evapotranspiration|\bETc?\b|water use|water requirement|inches of water|acre-inch|consumptive use",
    "frost_tolerance": r"frost|freez|cold toleran|winter hard|winterkill|low temperature",
    "heat_tolerance": r"heat|high temperature|hot weather|tolerates high",
    "nitrogen_fixing": r"nitrogen fixation|fixes nitrogen|fix nitrogen|legume|rhizobi|nodul",
    "root_depth": r"\broots?\b.*\b(feet|ft|inches|cm|m)\b|rooting depth|taproot|deep-rooted|deepest-rooted",
}


class NDIError(RuntimeError):
    pass


def load_guides(path: Path = GUIDES_PATH) -> list[dict]:
    return json.loads(path.read_text())["guides"]


# --- 1. Parse -------------------------------------------------------------------

def download_pdf(guide: dict, client: httpx.Client) -> Path:
    path = NDI_DIR / "pdf" / f"{guide['id']}.pdf"
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    r = client.get(guide["url"], follow_redirects=True, timeout=120, headers={"User-Agent": USER_AGENT})
    if r.status_code == 200 and r.content.startswith(b"%PDF"):
        path.write_bytes(r.content)
        return path
    # Some UC sites block non-browser HTTP clients by connection fingerprint
    # but accept curl, so fall back to it.
    import shutil
    import subprocess

    if shutil.which("curl"):
        tmp = path.with_suffix(".part")
        subprocess.run(["curl", "-sSL", "--fail", "-m", "120", "-o", str(tmp), guide["url"]],
                       check=False, capture_output=True)
        if tmp.exists() and tmp.read_bytes()[:4] == b"%PDF":
            tmp.rename(path)
            return path
        tmp.unlink(missing_ok=True)
    raise NDIError(f"{guide['id']}: could not download a PDF from {guide['url']} (HTTP {r.status_code})")


def local_pages(pdf_path: Path) -> list[dict]:
    """1-based PDF pages as text, via pypdf. Cached next to the PDF."""
    cache = pdf_path.with_suffix(".pages.json")
    if cache.exists():
        return json.loads(cache.read_text())
    from pypdf import PdfReader

    reader = PdfReader(str(pdf_path))
    pages = [{"page": i, "text": p.extract_text() or ""} for i, p in enumerate(reader.pages, 1)]
    cache.write_text(json.dumps(pages))
    return pages


_PENDING = {"queued", "pending", "processing", "running", "in_progress", "started", "submitted"}
_FAILED = {"failed", "error", "errored", "cancelled", "canceled"}


def _find_status(raw: dict) -> str | None:
    for key in ("status", "state"):
        v = raw.get(key)
        if isinstance(v, str):
            return v.lower()
        if isinstance(v, dict) and isinstance(v.get("status"), str):
            return v["status"].lower()
    return None


def _find_poll_url(raw) -> str | None:
    """A console.nace.ai/v1 link in the response (e.g. a status or self URL)."""
    if isinstance(raw, dict):
        for k, v in raw.items():
            if isinstance(v, str) and v.startswith("https://console.nace.ai/v1/") and (
                "url" in k.lower() or k.lower() in ("self", "href", "status")
            ):
                return v
            found = _find_poll_url(v)
            if found:
                return found
    elif isinstance(raw, list):
        for v in raw:
            found = _find_poll_url(v)
            if found:
                return found
    return None


def nace_parse(guide: dict, client: httpx.Client, api_key: str, wait_seconds: int = 60,
               polls: int = 10) -> dict:
    """Send one guide to Nace and return the raw JSON response (cached)."""
    path = NDI_DIR / "nace" / f"{guide['id']}.json"
    if path.exists():
        raw = json.loads(path.read_text())
        if _find_status(raw) not in _PENDING:
            return raw
    path.parent.mkdir(parents=True, exist_ok=True)
    headers = {"Authorization": f"Bearer {api_key}", "X-Nace-Client": NACE_CLIENT,
               "Content-Type": "application/json"}
    body = {
        "source": {"type": "url", "url": guide["url"], "file_name": f"{guide['id']}.pdf"},
        "output": {"formats": ["markdown"]},
    }
    r = client.post(NACE_PARSE_URL, params={"wait_seconds": wait_seconds}, headers=headers,
                    json=body, timeout=wait_seconds + 60)
    if r.status_code >= 400:
        raise NDIError(f"{guide['id']}: Nace HTTP {r.status_code}: {r.text[:500]}")
    raw = r.json()
    path.write_text(json.dumps(raw, indent=1))

    for _ in range(polls):
        status = _find_status(raw)
        if status in _FAILED:
            raise NDIError(f"{guide['id']}: Nace job {status}; raw response in {path}")
        if status not in _PENDING:
            return raw
        poll = _find_poll_url(raw)
        if not poll:
            raise NDIError(
                f"{guide['id']}: Nace job still '{status}' after {wait_seconds}s and the response has no "
                f"status URL to poll. Raw response saved to {path}; rerun later or raise wait_seconds."
            )
        time.sleep(5)
        r = client.get(poll, headers=headers, timeout=60)
        r.raise_for_status()
        raw = r.json()
        path.write_text(json.dumps(raw, indent=1))
    raise NDIError(f"{guide['id']}: Nace job not finished after polling; raw response in {path}")


_TEXT_KEYS = ("markdown", "md", "text", "content")
_PAGE_KEYS = ("page", "page_number", "pageNumber", "page_num", "number", "page_index", "index")
_PAGE_MARKER = re.compile(r"<!--\s*page[\s:_#-]*(\d+)\s*-->|\f|^\s*\[?page[\s:_#-]*(\d+)\]?\s*$",
                          re.I | re.M)


def _page_list(obj, under_pages_key: bool = False) -> list[dict] | None:
    """A list of page-like dicts anywhere in the response: items with text and
    either a page-number field or the list itself stored under a "pages" key."""
    if isinstance(obj, list) and obj and all(isinstance(x, dict) for x in obj):
        text_key = next((k for k in _TEXT_KEYS if all(isinstance(x.get(k), str) for x in obj)), None)
        numbered = all(any(isinstance(x.get(k), int) for k in _PAGE_KEYS) for x in obj)
        if text_key and (numbered or under_pages_key):
            pages = []
            for i, x in enumerate(obj):
                num_key = next((k for k in _PAGE_KEYS if isinstance(x.get(k), int)), None)
                n = x[num_key] + (1 if num_key and "index" in num_key.lower() else 0) if num_key else i + 1
                pages.append({"page": n, "text": x[text_key]})
            return pages
    if isinstance(obj, dict):
        for k, v in obj.items():
            found = _page_list(v, under_pages_key="page" in k.lower())
            if found:
                return found
    if isinstance(obj, list):
        for v in obj:
            found = _page_list(v)
            if found:
                return found
    return None


def _markdown_blob(obj) -> str | None:
    if isinstance(obj, dict):
        if obj.get("format") == "markdown" and isinstance(obj.get("content"), str):
            return obj["content"]
        for k, v in obj.items():
            if "markdown" in k.lower() and isinstance(v, str):
                return v
        for v in obj.values():
            found = _markdown_blob(v)
            if found:
                return found
    if isinstance(obj, list):
        for v in obj:
            found = _markdown_blob(v)
            if found:
                return found
    return None


def pages_from_nace(raw: dict) -> list[dict]:
    """Normalise a Nace parse response to [{"page": int|None, "text": str}].

    The response format isn't documented to us, so this accepts a per-page
    list, or one markdown document split on page markers, or (last resort)
    the whole document as one page with page=None. Quote verification against
    the PDF assigns real page numbers either way.
    """
    pages = _page_list(raw)
    if pages:
        return pages
    blob = _markdown_blob(raw)
    if blob is None:
        raise NDIError("no markdown found in Nace response")
    parts, last, n = [], 0, 1
    for m in _PAGE_MARKER.finditer(blob):
        chunk = blob[last:m.start()]
        if chunk.strip():
            parts.append({"page": n, "text": chunk})
        num = m.group(1) or m.group(2)
        n = int(num) if num else n + 1
        last = m.end()
    tail = blob[last:]
    if parts:
        if tail.strip():
            parts.append({"page": n, "text": tail})
        return parts
    return [{"page": None, "text": blob}]


# --- 2. Select ------------------------------------------------------------------

def select_pages(pages: list[dict], max_chars: int = 60_000, per_fact: int = 3) -> list[dict]:
    """For each fact, its pages ranked by keyword matches; take them round-robin
    (every fact's best page, then every fact's second-best, ...) within the
    character budget, so one fact's pages can't crowd out another's.
    Returned in page order."""
    ranked = {}
    for fact, pat in FACT_KEYWORDS.items():
        counts = [(len(re.findall(pat, p["text"], re.I)), i) for i, p in enumerate(pages)]
        ranked[fact] = [i for n, i in sorted(counts, key=lambda x: -x[0]) if n > 0][:per_fact]
    keep, total = [], 0
    for r in range(per_fact):
        for fact in FACTS:
            if r < len(ranked[fact]):
                i = ranked[fact][r]
                if i in keep or total + len(pages[i]["text"]) > max_chars:
                    continue
                keep.append(i)
                total += len(pages[i]["text"])
    # Facts often run over a page break: add the page after each kept page.
    for i in list(keep):
        j = i + 1
        if j < len(pages) and j not in keep and total + len(pages[j]["text"]) <= max_chars:
            keep.append(j)
            total += len(pages[j]["text"])
    return sorted((pages[i] for i in keep), key=lambda p: (p["page"] is None, p["page"] or 0))


def render_guides(docs: list[tuple[dict, list[dict]]]) -> str:
    out = []
    for guide, pages in docs:
        out.append(f'<guide id="{guide["id"]}" title="{guide["title"]}">')
        for p in pages:
            out.append(f'<page n="{p["page"] if p["page"] is not None else "?"}">\n{p["text"].strip()}\n</page>')
        out.append("</guide>")
    return "\n".join(out)


# --- 4. Verify ------------------------------------------------------------------

def _norm(s: str) -> str:
    """Lowercase with whitespace, soft hyphens and hyphens removed, so OCR
    breaks like 'resistan ce' or 'inch- es' still match."""
    return re.sub(r"[\s­\-‐‑‒–]+", "", s.lower())


def _num_str(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else str(v)


def locate_quote(quote: str, pages: list[dict], claimed_page: int | None = None) -> int | None:
    """PDF page whose text contains the quote, preferring the claimed page."""
    q = _norm(quote)
    if len(q) < 12:
        return None
    order = sorted(pages, key=lambda p: p["page"] != claimed_page)
    for p in order:
        if q in _norm(p["text"]):
            return p["page"]
    return None


def numbers_in_quote(values: list[float], quote: str) -> bool:
    q = _norm(quote)
    return all(_num_str(v) in q for v in values)


_TO_CM = {"in": 2.54, "inch": 2.54, "inches": 2.54, "ft": 30.48, "feet": 30.48, "cm": 1.0, "mm": 0.1, "m": 100.0}


def verify(crop_key: str, extracted: dict, guide_pages: dict[str, list[dict]]) -> dict:
    """Keep only facts whose quote is in the guide's PDF text and whose
    numbers are in the quote. Returns {fact: verified_record | rejected_record}."""
    out = {}
    for fact in FACTS:
        e = extracted.get(fact) or {}
        if not e.get("found"):
            out[fact] = {"ok": False, "reason": "not stated in the guides"}
            continue
        gid, quote = e.get("guide_id"), e.get("quote") or ""
        if gid not in guide_pages:
            out[fact] = {"ok": False, "reason": f"unknown guide {gid!r}"}
            continue
        page = locate_quote(quote, guide_pages[gid], e.get("page"))
        if page is None:
            out[fact] = {"ok": False, "reason": "quote not found in the guide's text", "quote": quote}
            continue

        rec = {"ok": True, "guide_id": gid, "pdf_page": page, "quote": quote}
        if fact == "water_use":
            nums = [v for v in (e.get("low"), e.get("high"), e.get("typical")) if v is not None]
            unit = (e.get("unit") or "").lower()
            if not nums or unit not in _TO_CM or not numbers_in_quote(nums, quote):
                out[fact] = {"ok": False, "reason": "numbers or unit not in the quote", "quote": quote}
                continue
            typical = e.get("typical")
            if typical is None:
                lo, hi = e.get("low"), e.get("high")
                typical = (lo + hi) / 2 if lo is not None and hi is not None else (lo if lo is not None else hi)
            rec.update(value=round(typical * _TO_CM[unit], 1), unit="cm",
                       as_written={"low": e.get("low"), "high": e.get("high"),
                                   "typical": e.get("typical"), "unit": unit})
        elif fact == "root_depth":
            v, unit = e.get("value"), (e.get("unit") or "").lower()
            if v is None or unit not in _TO_CM or not numbers_in_quote([v], quote):
                out[fact] = {"ok": False, "reason": "number or unit not in the quote", "quote": quote}
                continue
            rec.update(value=round(v * _TO_CM[unit]), unit="cm", as_written={"value": v, "unit": unit})
        else:
            if e.get("value") is None:
                out[fact] = {"ok": False, "reason": "no value given", "quote": quote}
                continue
            rec["value"] = e["value"]
        out[fact] = rec
    return out


# --- Build crops.json -----------------------------------------------------------

_FIELD = {"water_use": "water_need_cm", "frost_tolerance": "frost_tolerance",
          "heat_tolerance": "heat_tolerance", "nitrogen_fixing": "nitrogen_fixing",
          "root_depth": "root_depth_cm"}


def merge_crops(sample: dict, verified: dict[str, dict], guides: list[dict], meta: dict) -> dict:
    """Sample crops + verified facts. Every field gets an `evidence` entry:
    a guide, PDF page and quote, or `placeholder: true` with the reason."""
    by_id = {g["id"]: g for g in guides}
    out = {"_note": (
        "Built by scripts/build_crops.py from the guides in data/guides.json. Each crop's `evidence` "
        "gives the guide, PDF page (1-based page of the PDF file, not the printed page number) and a "
        "verbatim quote for every fact. Facts the guides don't state keep the placeholder value from "
        "data/crops.sample.json and are marked placeholder: true."
    ), "generated": meta, "crops": {}, "strategies": sample["strategies"]}

    for key, crop in sample["crops"].items():
        c = {k: v for k, v in crop.items() if k != "source"}
        evidence, cited = {}, []
        for fact, field in _FIELD.items():
            rec = verified.get(key, {}).get(fact)
            if rec and rec.get("ok"):
                g = by_id[rec["guide_id"]]
                c[field] = rec["value"]
                evidence[field] = {"guide": g["title"], "publisher": g["publisher"], "url": g["url"],
                                   "pdf_page": rec["pdf_page"], "quote": rec["quote"],
                                   **({"as_written": rec["as_written"]} if "as_written" in rec else {})}
                cited.append(f"{g['title']}, p. {rec['pdf_page']}")
            else:
                evidence[field] = {"placeholder": True,
                                   "reason": (rec or {}).get("reason", "crop has no guides")}
        c["evidence"] = evidence
        c["source"] = "; ".join(dict.fromkeys(cited)) or "PLACEHOLDER"
        out["crops"][key] = c
    return out
