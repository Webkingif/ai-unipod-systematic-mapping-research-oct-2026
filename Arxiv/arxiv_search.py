#!/usr/bin/env python3
"""
arXiv search for the Workstream A mapping study, via the public arXiv API.
Standard library only.

Query logic (same as the protocol string):
 (cat:cs.CL OR cat:eess.AS)
 AND (language/resource terms)
 AND (speech-technology terms)

Outputs:
    hits.csv        one row per paper with custom mapping study schema
    hits.bib        BibTeX file of all retrieved records
    search_log.json exact query, URL, run date, API total vs retrieved count
    raw/            raw Atom XML pages (keep these as evidence of the search)

arXiv API etiquette: at most one request every 3.5 seconds (enforced below).
"""

import argparse
import csv
import json
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

API = "http://export.arxiv.org/api/query"
CATEGORIES = ["cs.CL", "eess.AS"]
GROUP_1 = ["Yoruba", "Yorùbá", "Hausa", "Igbo", "Nigerian Pidgin", "Naija",
           "Nigerian-accented English", "AfriSpeech", "NaijaVoices", "YORULECT",
           "YarnGPT", "IroyinSpeech", "BibleTTS", "FLEURS", "GlobalPhone"]
GROUP_2 = ["speech", "ASR", "TTS", "telephony", "acoustic", "narrowband",
           "8 kHz", "codec", "language identification", "code-switching", "model","corpora", "dataset","benchmark"]

NS = {"a": "http://www.w3.org/2005/Atom",
      "os": "http://a9.com/-/spec/opensearch/1.1/",
      "ax": "http://arxiv.org/schemas/atom"}
PAGE = 100
DELAY = 3.5  # seconds between requests

CSV_COLUMNS = [
    "key", "year", "venue", "title", "abstract", "url", "doi",
    "group1_matches", "group2_matches", "afrispeech_flag",
    "screener1", "screener2", "decision", "notes"
]


def field_or(terms):
    parts = []
    for t in terms:
        parts.append(f'ti:"{t}"')
        parts.append(f'abs:"{t}"')
    return "(" + " OR ".join(parts) + ")"


def build_query(date_from=None, date_to=None):
    cats = "(" + " OR ".join(f"cat:{c}" for c in CATEGORIES) + ")"
    q = f"{cats} AND {field_or(GROUP_1)} AND {field_or(GROUP_2)}"
    if date_from or date_to:
        d1 = (date_from or "1991-01-01").replace("-", "") + "0000"
        d2 = (date_to or date.today().isoformat()).replace("-", "") + "2359"
        q += f" AND submittedDate:[{d1} TO {d2}]"
    return q


def fetch(query, start, raw_dir):
    params = urllib.parse.urlencode({
        "search_query": query, "start": start, "max_results": PAGE,
        "sortBy": "submittedDate", "sortOrder": "ascending",
    }, quote_via=urllib.parse.quote)
    url = f"{API}?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "mapping-study-search/1.0"})
    
    # Create a standard library SSL context that bypasses local cert verification issues
    context = ssl._create_unverified_context()
    
    with urllib.request.urlopen(req, timeout=60, context=context) as r:
        data = r.read()
    (raw_dir / f"page_{start:05d}.xml").write_bytes(data)
    return url, data


def text(el, path):
    x = el.find(path, NS)
    return re.sub(r"\s+", " ", x.text).strip() if x is not None and x.text else ""


def find_matches(title, abstract, terms):
    blob = f"{title} {abstract}"
    matched = []
    for t in terms:
        # Case-insensitive substring/word check
        if t.lower() in blob.lower():
            matched.append(t)
    return "; ".join(sorted(list(set(matched))))


def make_key(authors, year, arxiv_id):
    first_author = authors.split(";")[0].strip() if authors else "Unknown"
    last_name = first_author.split()[-1] if first_author else "Unknown"
    last_name_clean = re.sub(r'[^a-zA-Z]', '', last_name)
    clean_id = arxiv_id.replace("/", "_").replace(".", "_")
    return f"{last_name_clean}{year}_{clean_id}"


def parse(data):
    root = ET.fromstring(data)
    total = root.find("os:totalResults", NS)
    total = int(total.text) if total is not None else 0
    rows = []
    for e in root.findall("a:entry", NS):
        full_id = text(e, "a:id")
        m = re.search(r"abs/(.+?)(v\d+)?$", full_id)
        arxiv_id = m.group(1) if m else full_id
        
        title = text(e, "a:title")
        abstract = text(e, "a:summary")
        authors = "; ".join(text(a, "a:name") for a in e.findall("a:author", NS))
        published = text(e, "a:published")
        year = published[:4] if published and len(published) >= 4 else ""
        
        journal_ref = text(e, "ax:journal_ref")
        venue = journal_ref if journal_ref else "arXiv"
        doi = text(e, "ax:doi")
        
        g1_matches = find_matches(title, abstract, GROUP_1)
        g2_matches = find_matches(title, abstract, GROUP_2)
        
        # Check if AfriSpeech is specifically matched
        afrispeech_flag = 1 if any(term.lower() == "afrispeech" for term in g1_matches.split("; ")) else 0
        
        key = make_key(authors, year, arxiv_id)

        rows.append({
            "key": key,
            "year": year,
            "venue": venue,
            "title": title,
            "abstract": abstract,
            "url": full_id,
            "doi": doi,
            "group1_matches": g1_matches,
            "group2_matches": g2_matches,
            "afrispeech_flag": afrispeech_flag,
            "screener1": "",
            "screener2": "",
            "decision": "",
            "notes": "",
            # Keep raw internal metadata for BibTeX generation
            "_authors": authors,
            "_arxiv_id": arxiv_id,
            "_categories": "; ".join(c.get("term", "") for c in e.findall("a:category", NS)),
        })
    return total, rows


def write_bibtex(records, bib_path):
    entries = []
    for r in records:
        authors_bib = r["_authors"].replace(";", " and")
        primary_cat = r["_categories"].split(";")[0].strip() if r["_categories"] else "cs.CL"
        entry = f"""@article{{{r["key"]},
  author = {{{authors_bib}}},
  title = {{{r["title"]}}},
  year = {{{r["year"]}}},
  eprint = {{{r["_arxiv_id"]}}},
  archivePrefix = {{arXiv}},
  primaryClass = {{{primary_cat}}},
  url = {{{r["url"]}}},
  doi = {{{r["doi"]}}},
  journal = {{arXiv preprint arXiv:{r["_arxiv_id"]}}}
}}"""
        entries.append(entry)
    bib_path.write_text("\n\n".join(entries), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="arxiv_results")
    ap.add_argument("--date-from", help="YYYY-MM-DD (submission date)")
    ap.add_argument("--date-to", help="YYYY-MM-DD (submission date)")
    a = ap.parse_args()

    out = Path(a.out)
    raw_dir = out / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    query = build_query(a.date_from, a.date_to)
    rows, start, total, first_url = [], 0, None, None

    while True:
        try:
            url, data = fetch(query, start, raw_dir)
        except Exception as exc:
            sys.exit(f"Request failed at start={start}: {exc}")
        first_url = first_url or url
        total, page_rows = parse(data)
        rows.extend(page_rows)
        print(f"retrieved {len(rows)} / {total}")
        start += PAGE
        if not page_rows or start >= total:
            break
        time.sleep(DELAY)

    # Dedupe on arXiv ID
    seen, unique = set(), []
    for r in rows:
        if r["_arxiv_id"] not in seen:
            seen.add(r["_arxiv_id"])
            unique.append(r)

    # Write CSV
    with open(out / "hits.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        w.writeheader()
        for r in unique:
            # Filter dictionary to only include CSV columns
            row_data = {col: r[col] for col in CSV_COLUMNS}
            w.writerow(row_data)

    # Write BibTeX
    write_bibtex(unique, out / "hits.bib")

    log = {
        "run_date": date.today().isoformat(),
        "api_endpoint": API,
        "first_request_url": first_url,
        "search_query": query,
        "date_from": a.date_from, "date_to": a.date_to,
        "categories": CATEGORIES,
        "group_1_terms": GROUP_1, "group_2_terms": GROUP_2,
        "api_total_results": total,
        "records_retrieved": len(rows),
        "unique_records": len(unique),
        "with_doi": sum(1 for r in unique if r["doi"]),
    }
    (out / "search_log.json").write_text(
        json.dumps(log, indent=2, ensure_ascii=False), encoding="utf-8")
    
    print(json.dumps({k: log[k] for k in
          ("api_total_results", "unique_records", "with_doi")}, indent=2))
    print(f"Outputs successfully saved to: {out}/ (hits.csv, hits.bib, search_log.json)")


if __name__ == "__main__":
    main()
