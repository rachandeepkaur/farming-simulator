import json

from atlas import ndi
from atlas.config import CROPS_SAMPLE_PATH
from atlas.ndi_extract import output_schema

PAGES = [
    {"page": 1, "text": "Safflower overview. Grown in the Sacramento Valley."},
    {"page": 2, "text": "The frost resistan ce of safflower depends on the cultivar,\nand seedlings tolerate light frost."},
    {"page": 3, "text": "WATER USE\nexperience indicates that a total of about 20 to 25 inch-\nes of water is needed for full yield."},
    {"page": 4, "text": "Safflower roots have been found at 10 feet (3 m) in a permeable soil."},
]


def fact(found=True, **kw):
    base = {"found": found, "guide_id": "g1", "page": None, "quote": None}
    base.update(kw)
    return base


def test_select_pages_covers_each_fact():
    pages = [{"page": i, "text": "filler " * 50} for i in range(1, 30)]
    pages[4]["text"] += " evapotranspiration water use " * 3
    pages[20]["text"] += " frost injury frost "
    pages[25]["text"] += " roots reach 6 feet deep "
    got = [p["page"] for p in ndi.select_pages(pages, max_chars=10_000)]
    assert 5 in got and 21 in got and 26 in got
    assert got == sorted(got)
    assert 6 in got  # page after a kept page


def test_locate_quote_tolerates_ocr_spacing_and_hyphenation():
    assert ndi.locate_quote("The frost resistance of safflower depends on the cultivar", PAGES) == 2
    assert ndi.locate_quote("a total of about 20 to 25 inches of water", PAGES) == 3
    assert ndi.locate_quote("safflower needs 40 inches of water each year", PAGES) is None
    assert ndi.locate_quote("short", PAGES) is None


def test_verify_accepts_real_and_rejects_invented_facts():
    extracted = {
        "water_use": fact(low=20, high=25, typical=None, unit="in", page=9,
                          quote="a total of about 20 to 25 inches of water is needed"),
        "frost_tolerance": fact(value="moderate", page=2,
                                quote="The frost resistance of safflower depends on the cultivar"),
        "heat_tolerance": fact(value="high", page=1, quote="Safflower loves heat and thrives in hot summers."),
        "nitrogen_fixing": fact(found=False),
        "root_depth": fact(value=10, unit="ft", page=4,
                           quote="Safflower roots have been found at 10 feet (3 m) in a permeable soil."),
    }
    v = ndi.verify("safflower", extracted, {"g1": PAGES})
    assert v["water_use"]["ok"] and v["water_use"]["pdf_page"] == 3  # real page, not the claimed 9
    assert v["water_use"]["value"] == round(22.5 * 2.54, 1)
    assert v["frost_tolerance"] == {"ok": True, "guide_id": "g1", "pdf_page": 2,
                                    "quote": extracted["frost_tolerance"]["quote"], "value": "moderate"}
    assert not v["heat_tolerance"]["ok"] and "not found" in v["heat_tolerance"]["reason"]
    assert not v["nitrogen_fixing"]["ok"]
    assert v["root_depth"]["value"] == 305


def test_verify_rejects_numbers_missing_from_quote():
    extracted = {"water_use": fact(low=30, high=35, unit="in",
                                   quote="a total of about 20 to 25 inches of water is needed")}
    v = ndi.verify("safflower", extracted, {"g1": PAGES})
    assert not v["water_use"]["ok"] and "numbers" in v["water_use"]["reason"]


def test_verify_rejects_unknown_guide():
    v = ndi.verify("x", {"frost_tolerance": fact(guide_id="nope", value="low", quote="anything long enough")},
                   {"g1": PAGES})
    assert "unknown guide" in v["frost_tolerance"]["reason"]


def test_merge_crops_marks_every_field():
    sample = json.loads(CROPS_SAMPLE_PATH.read_text())
    guides = [{"id": "g1", "title": "Safflower Production", "publisher": "UC ANR", "url": "https://x/y.pdf",
               "crops": ["safflower"]}]
    verified = {"safflower": {
        "water_use": {"ok": True, "guide_id": "g1", "pdf_page": 3, "quote": "q", "value": 57.2,
                      "unit": "cm", "as_written": {"low": 20, "high": 25, "typical": None, "unit": "in"}},
        "frost_tolerance": {"ok": False, "reason": "not stated in the guides"},
    }}
    out = ndi.merge_crops(sample, verified, guides, {"date": "2026-11-14"})
    saff = out["crops"]["safflower"]
    assert saff["water_need_cm"] == 57.2
    assert saff["evidence"]["water_need_cm"]["pdf_page"] == 3
    assert saff["evidence"]["frost_tolerance"]["placeholder"] is True
    assert saff["frost_tolerance"] == sample["crops"]["safflower"]["frost_tolerance"]
    assert saff["source"] == "Safflower Production, p. 3"
    assert out["crops"]["processing_tomato"]["source"] == "PLACEHOLDER"
    assert set(saff["evidence"]) == {"water_need_cm", "frost_tolerance", "heat_tolerance",
                                     "nitrogen_fixing", "root_depth_cm"}
    assert out["strategies"] == sample["strategies"]


def test_pages_from_nace_page_list():
    raw = {"id": "doc_1", "status": "completed",
           "result": {"pages": [{"page_index": 0, "markdown": "# A"}, {"page_index": 1, "markdown": "B"}]}}
    assert ndi.pages_from_nace(raw) == [{"page": 1, "text": "# A"}, {"page": 2, "text": "B"}]


def test_pages_from_nace_markdown_with_markers():
    raw = {"status": "succeeded", "outputs": [{"format": "markdown",
                                               "content": "<!-- page 1 -->\nIntro\n<!-- page 2 -->\nWater"}]}
    assert ndi.pages_from_nace(raw) == [{"page": 1, "text": "\nIntro\n"}, {"page": 2, "text": "\nWater"}]


def test_pages_from_nace_single_blob():
    assert ndi.pages_from_nace({"markdown": "all text"}) == [{"page": None, "text": "all text"}]


def test_extraction_schema_is_strict():
    s = output_schema()
    assert set(s["required"]) == set(ndi.FACTS)
    for f in ndi.FACTS:
        sub = s["properties"][f]
        assert sub["additionalProperties"] is False
        assert set(sub["required"]) == set(sub["properties"])
