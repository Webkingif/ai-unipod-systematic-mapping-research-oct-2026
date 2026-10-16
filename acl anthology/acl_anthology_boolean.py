#!/usr/bin/env python3
"""
ACL Anthology search: single Boolean string, Workstream A mapping study.

Implements exactly:
 ("Yoruba" OR "Yorùbá" OR "Hausa" OR "Igbo" OR "Pidgin" OR "Naija" OR
  "Nigerian" OR "AfriSpeech" OR "NaijaVoices" OR "IroyinSpeech" OR "YORÙLECT")
 AND
 ("speech" OR "ASR" OR "TTS" OR "speech recognition" OR "speech synthesis" OR
  "language identification" OR "code-switching" OR "narrowband" OR "8 kHz" OR
  "telephony")

applied to title + abstract of the Anthology BibTeX export WITH abstracts
(.bib or .bib.gz). Case-insensitive; diacritics ignored (Yorùbá = Yoruba).
Terms match as whole words/phrases. Standard library only.

Usage:
    python acl_anthology_boolean.py --bib anthology+abstracts.bib.gz \
        --out results --year-min 2015 --year-max 2026 [--seed seed.txt]

Outputs: hits.csv (with abstract + doi + blank double-screening columns),
search_log.json (hash, date, exact terms, counts), seed_check.txt (optional).
"""

import argparse
import csv
import gzip
import hashlib
import json
import re
import sys
import unicodedata
from datetime import date
from pathlib import Path

GROUP_1 = ["Yoruba", "Yorùbá", "Hausa", "Igbo", "Pidgin", "Naija", "Nigeria","Nigerian",
           "AfriSpeech", "NaijaVoices", "IroyinSpeech", "YORÙLECT"]
GROUP_2 = ["speech", "ASR", "TTS", "speech recognition", "speech synthesis",
           "language identification", "code-switching", "narrowband", "8 kHz",
           "telephony", "dataset","model", "corpora", "benchmark"]

_ACCENT_CMDS = re.compile(r"""\\[`'^"~=.]""")
_COMBINING = re.compile(r"[\u0300-\u036f]")
FIELD_RE = re.compile(r'(?ms)^\s*(\w+)\s*=\s*"(.*?)"\s*,?\s*$')


def norm(s):
    s = _ACCENT_CMDS.sub("", s)
    s = re.sub(r"[{}\\]", "", s)
    s = unicodedata.normalize("NFKD", s)
    s = _COMBINING.sub("", s).lower()
    return re.sub(r"\s+", " ", s).strip()


def term_regex(terms):
    """One compiled regex per term, whole-word, on normalised text."""
    out = {}
    for t in terms:
        pat = r"(?<![a-z0-9])" + re.escape(norm(t)) + r"(?![a-z0-9])"
        out[t] = re.compile(pat)
    return out


def parse_bib(text):
    entries = []
    for chunk in re.split(r"(?m)^@", text)[1:]:
        head, _, body = chunk.partition("\n")
        m = re.match(r"(\w+)\s*\{\s*([^,\s]+)", head)
        if not m or m.group(1).lower() in ("string", "comment", "preamble"):
            continue
        f = {fm.group(1).lower(): fm.group(2) for fm in FIELD_RE.finditer(body)}
        f["_key"] = m.group(2)
        f["_raw"] = "@" + chunk
        entries.append(f)
    return entries


def year_of(e):
    m = re.search(r"\d{4}", e.get("year", ""))
    return int(m.group()) if m else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bib", required=True)
    ap.add_argument("--out", default="results")
    ap.add_argument("--year-min", type=int)
    ap.add_argument("--year-max", type=int)
    ap.add_argument("--seed")
    a = ap.parse_args()

    p = Path(a.bib)
    file_bytes = p.read_bytes()
    raw = gzip.decompress(file_bytes) if p.suffix == ".gz" else file_bytes
    entries = parse_bib(raw.decode("utf-8", errors="replace"))
    if not entries:
        sys.exit("No entries parsed. Check the BibTeX file.")

    def in_range(e):
        y = year_of(e)
        return y is None or (
            (a.year_min is None or y >= a.year_min)
            and (a.year_max is None or y <= a.year_max)
        )

    pool = [e for e in entries if in_range(e)]
    g1, g2 = term_regex(GROUP_1), term_regex(GROUP_2)

    rows = []
    for e in pool:
        text = norm(e.get("title", "") + " . " + e.get("abstract", ""))
        m1 = [t for t, r in g1.items() if r.search(text)]
        if not m1:
            continue
        m2 = [t for t, r in g2.items() if r.search(text)]
        if not m2:
            continue
        rows.append({
            "key": e["_key"],
            "year": e.get("year", ""),
            "venue": e.get("booktitle") or e.get("journal", ""),
            "title": re.sub(r"[{}]", "", e.get("title", "")),
            "abstract": re.sub(r"[{}]", "", e.get("abstract", "")),
            "url": e.get("url", ""),
            "doi": re.sub(r"[{}]", "", e.get("doi", "")),
            "group1_matches": "; ".join(m1),
            "group2_matches": "; ".join(m2),
            "afrispeech_flag": "yes" if "AfriSpeech" in m1 else "",
            "screener1": "", "screener2": "", "decision": "", "notes": "",
        })

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    cols = list(rows[0].keys()) if rows else [
        "key", "year", "venue", "title", "abstract", "url", "doi", "group1_matches",
        "group2_matches", "afrispeech_flag", "screener1", "screener2",
        "decision", "notes"]
    with open(out / "hits.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)

    matched_keys = {r["key"] for r in rows}
    with open(out / "hits.bib", "w", encoding="utf-8") as f:
        for e in pool:
            if e["_key"] in matched_keys and "_raw" in e:
                f.write(e["_raw"].strip() + "\n\n")

    counts = {
        "records_in_file": len(entries),
        "records_with_abstract": sum(1 for e in entries if e.get("abstract")),
        "records_after_date_filter": len(pool),
        "records_matching_search": len(rows),
    }
    log = {
        "run_date": date.today().isoformat(),
        "bib_file": p.name,
        "bib_file_sha256": hashlib.sha256(file_bytes).hexdigest(),
        "year_min": a.year_min, "year_max": a.year_max,
        "group_1_terms": GROUP_1, "group_2_terms": GROUP_2,
        "logic": "(any of group_1) AND (any of group_2) on title + abstract",
        "counts": counts,
    }
    (out / "search_log.json").write_text(json.dumps(log, indent=2, ensure_ascii=False), encoding="utf-8")

    if a.seed:
        keys = {r["key"] for r in rows}
        titles = [norm(r["title"]) for r in rows]
        seeds = [s.strip() for s in Path(a.seed).read_text(encoding="utf-8").splitlines() if s.strip()]
        lines, n = [], 0
        for s in seeds:
            ok = s in keys or any(norm(s) in t for t in titles)
            n += ok
            lines.append(("FOUND   " if ok else "MISSED  ") + s)
        lines.append(f"\nSeed recall: {n}/{len(seeds)}")
        (out / "seed_check.txt").write_text("\n".join(lines), encoding="utf-8")
        print(lines[-1])

    print(json.dumps(counts, indent=2))


if __name__ == "__main__":
    main()
