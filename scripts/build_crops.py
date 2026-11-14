"""Task 5: build data/crops.json from the crop guides in data/guides.json.

    export NACE_API_KEY=...        # NDI parse
    export ANTHROPIC_API_KEY=...   # fact extraction
    uv run python scripts/build_crops.py --yes

    uv run python scripts/build_crops.py --parser local --dry-run   # no keys: parse + page selection only

Steps: parse each guide (NDI or local), keep the pages about water use,
frost, heat, nitrogen and roots, extract facts per crop with Claude, verify
every quote against the PDF text, write data/crops.json and a report.
"""

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from atlas import ndi  # noqa: E402
from atlas.config import CROPS_PATH, CROPS_SAMPLE_PATH  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--parser", choices=["nace", "local"], default="nace")
    ap.add_argument("--wait-seconds", type=int, default=60)
    ap.add_argument("--max-chars", type=int, default=90_000, help="page text per crop sent to the extractor")
    ap.add_argument("--no-fallback-local", dest="fallback_local", action="store_false",
                    help="fail instead of parsing a guide locally when NDI can't")
    ap.add_argument("--dry-run", action="store_true", help="parse and select pages only; no extraction")
    ap.add_argument("--yes", action="store_true", help="confirm the paid extraction calls")
    args = ap.parse_args()

    guides = ndi.load_guides()
    sample = json.loads(CROPS_SAMPLE_PATH.read_text())
    nace_key = os.environ.get("NACE_API_KEY")
    if args.parser == "nace" and not nace_key:
        sys.exit("NACE_API_KEY is not set (or pass --parser local to parse PDFs without NDI)")

    pdf_pages, parsed, parser_used = {}, {}, {}
    with httpx.Client() as client:
        for g in guides:
            pdf = ndi.download_pdf(g, client)
            pdf_pages[g["id"]] = ndi.local_pages(pdf)
            if args.parser == "nace":
                try:
                    raw = ndi.nace_parse(g, client, nace_key, args.wait_seconds)
                    parsed[g["id"]] = ndi.pages_from_nace(raw)
                    parser_used[g["id"]] = "nace"
                    numbered = all(p["page"] is not None for p in parsed[g["id"]])
                    print(f"{g['id']}: NDI returned {len(parsed[g['id']])} page(s)"
                          f"{'' if numbered else ' without page numbers (quotes are matched to PDF pages)'}")
                    continue
                except ndi.NDIError as e:
                    if not args.fallback_local:
                        raise
                    print(f"{g['id']}: NDI failed ({e}); using local text for this guide")
            parsed[g["id"]] = pdf_pages[g["id"]]
            parser_used[g["id"]] = "local"
            print(f"{g['id']}: {len(parsed[g['id']])} pages (local pypdf)")

    crops_with_guides = {}
    for g in guides:
        for c in g["crops"]:
            crops_with_guides.setdefault(c, []).append(g)

    per_crop_text = {}
    for crop, gs in crops_with_guides.items():
        budget = args.max_chars // len(gs)
        docs = [(g, ndi.select_pages(parsed[g["id"]], budget)) for g in gs]
        per_crop_text[crop] = ndi.render_guides(docs)
        pages = ", ".join(f"{g['id']} {[p['page'] for p in ps]}" for g, ps in docs)
        print(f"{crop}: {len(per_crop_text[crop]):,} chars from {pages}")

    if args.dry_run:
        print("dry run: stopping before extraction")
        return
    est_tokens = sum(len(t) for t in per_crop_text.values()) // 4
    if not args.yes:
        sys.exit(f"Extraction = {len(per_crop_text)} Claude calls, ~{est_tokens:,} input tokens. "
                 "Re-run with --yes.")

    from atlas.ndi_extract import MODEL, ClaudeExtractor

    extractor = ClaudeExtractor()
    verified, raw_extractions = {}, {}
    for crop, text in per_crop_text.items():
        name = sample["crops"][crop]["name"]
        print(f"extracting {crop}...")
        raw_extractions[crop] = extractor(crop, name, text)
        verified[crop] = ndi.verify(crop, raw_extractions[crop],
                                    {g["id"]: pdf_pages[g["id"]] for g in crops_with_guides[crop]})

    meta = {"date": date.today().isoformat(), "parser_by_guide": parser_used,
            "extractor": MODEL, "guides": [g["id"] for g in guides]}
    crops = ndi.merge_crops(sample, verified, guides, meta)
    CROPS_PATH.write_text(json.dumps(crops, indent=1) + "\n")
    report = ndi.NDI_DIR / "extraction_report.json"
    report.write_text(json.dumps({"raw": raw_extractions, "verified": verified}, indent=1))

    print(f"\nwrote {CROPS_PATH}")
    for crop, facts in verified.items():
        for fact, rec in facts.items():
            if rec.get("ok"):
                print(f"  {crop:18s} {fact:16s} {rec['value']!s:>8}  ({rec['guide_id']} p.{rec['pdf_page']})")
            else:
                print(f"  {crop:18s} {fact:16s} {'—':>8}  placeholder: {rec['reason']}")
    print(f"full extraction report: {report}")


if __name__ == "__main__":
    main()
