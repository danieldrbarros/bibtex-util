import csv
import requests
from bs4 import BeautifulSoup
import time
import re

INPUT_CSV = "input.csv"
OUTPUT_BIB = "output.bib"

HEADERS = {"User-Agent": "Mozilla/5.0"}


# -----------------------------
# Helpers
# -----------------------------
def first_or_none(lst):
    return lst[0] if lst else None


def extract_doi(soup):
    # Try meta tags first
    doi = soup.find("meta", attrs={"name": "citation_doi"})
    if doi:
        return doi.get("content")

    # Regex fallback
    text = soup.get_text()
    match = re.search(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", text, re.I)
    return match.group(0) if match else None


# -----------------------------
# Abstract extraction
# -----------------------------
def extract_abstract(soup):
    # --- Strategy 1: High-quality full abstract containers
    selectors = [
        # Springer / Nature
        {"name": "section", "attrs": {"class": re.compile("Abstract", re.I)}},
        {"name": "div", "attrs": {"class": re.compile("Abstract", re.I)}},

        # IEEE
        {"name": "div", "attrs": {"class": re.compile("abstract-text", re.I)}},

        # ACM
        {"name": "div", "attrs": {"class": re.compile("abstractSection", re.I)}},

        # Generic
        {"name": "section", "attrs": {"id": re.compile("abstract", re.I)}},
        {"name": "div", "attrs": {"id": re.compile("abstract", re.I)}},
    ]

    for sel in selectors:
        tag = soup.find(sel["name"], attrs=sel["attrs"])
        if tag:
            text = tag.get_text(separator=" ", strip=True)

            # Heuristic: avoid truncated abstracts
            if len(text) > 300:
                return clean_text(text)

    # --- Strategy 2: paragraphs inside abstract sections
    abstract_sections = soup.find_all(
        ["section", "div"],
        attrs={"class": re.compile("abstract", re.I)}
    )

    for sec in abstract_sections:
        paragraphs = sec.find_all("p")
        if paragraphs:
            text = " ".join(p.get_text(strip=True) for p in paragraphs)
            if len(text) > 300:
                return clean_text(text)

    # --- Strategy 3: citation_abstract (often truncated)
    tag = soup.find("meta", attrs={"name": "citation_abstract"})
    if tag and tag.get("content"):
        text = tag.get("content")
        if len(text) > 300:
            return clean_text(text)

    # --- Strategy 4: fallback meta
    for name in ["description", "dc.description", "og:description"]:
        tag = soup.find("meta", attrs={"name": name}) or \
              soup.find("meta", attrs={"property": name})
        if tag and tag.get("content"):
            text = tag.get("content")
            if len(text) > 300:
                return clean_text(text)

    return None

def clean_text(text):
    if not text:
        return None
    text = re.sub(r"\s+", " ", text)
    return text.strip()


# -----------------------------
# CrossRef enrichment
# -----------------------------
def fetch_crossref_bibtex(doi):
    try:
        url = f"https://api.crossref.org/works/{doi}/transform/application/x-bibtex"
        r = requests.get(url, headers=HEADERS, timeout=10)
        if r.status_code == 200:
            return r.text
    except:
        pass
    return None


# -----------------------------
# Build BibTeX
# -----------------------------
def build_bibtex_from_meta(meta, url, abstract=None):
    title = first_or_none(meta.get("citation_title", []))
    authors = meta.get("citation_author", [])
    journal = first_or_none(meta.get("citation_journal_title", []))
    booktitle = first_or_none(meta.get("citation_conference_title", []))

    year = None
    date = first_or_none(meta.get("citation_publication_date", []))
    if date:
        year = date[:4]

    volume = first_or_none(meta.get("citation_volume", []))
    number = first_or_none(meta.get("citation_issue", []))
    pages = first_or_none(meta.get("citation_firstpage", []))
    doi = first_or_none(meta.get("citation_doi", []))
    publisher = first_or_none(meta.get("citation_publisher", []))

    entry_type = "article" if journal else "inproceedings" if booktitle else "misc"
    key = f"auto_{abs(hash(url))}"

    fields = {
        "title": title,
        "author": " and ".join(authors) if authors else None,
        "journal": journal,
        "booktitle": booktitle,
        "year": year,
        "volume": volume,
        "number": number,
        "pages": pages,
        "publisher": publisher,
        "doi": doi,
        "url": url,
        "abstract": abstract
    }

    bib = f"@{entry_type}{{{key},\n"
    for k, v in fields.items():
        if v:
            bib += f"  {k} = {{{v}}},\n"
    bib += "}"

    return bib


# -----------------------------
# Main extraction logic
# -----------------------------
def fetch_bibtex(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        if r.status_code != 200:
            return None, f"HTTP {r.status_code}"

        soup = BeautifulSoup(r.text, "html.parser")

        # --- Extract abstract early
        abstract = extract_abstract(soup)

        # --- Strategy 1: direct BibTeX
        for pre in soup.find_all("pre"):
            txt = pre.get_text()
            if "@article" in txt or "@inproceedings" in txt:
                # Inject abstract if missing
                if abstract and "abstract" not in txt.lower():
                    txt = txt.rstrip("}\n") + f",\n  abstract = {{{abstract}}}\n}}"
                return txt.strip(), None

        # --- Strategy 2: DOI → CrossRef
        doi = extract_doi(soup)
        if doi:
            crossref_bib = fetch_crossref_bibtex(doi)
            if crossref_bib:
                if abstract and "abstract" not in crossref_bib.lower():
                    crossref_bib = crossref_bib.rstrip("}\n") + f",\n  abstract = {{{abstract}}}\n}}"
                return crossref_bib.strip(), None

        # --- Strategy 3: meta tags
        meta = {}
        for tag in soup.find_all("meta"):
            name = tag.get("name")
            if name and name.startswith("citation_"):
                meta.setdefault(name, []).append(tag.get("content"))

        if meta:
            return build_bibtex_from_meta(meta, url, abstract), None

        return None, "No metadata found"

    except Exception as e:
        return None, str(e)


# -----------------------------
# Main pipeline
# -----------------------------
def main():
    total = 0
    success = 0
    failures = []
    entries = []

    with open(INPUT_CSV, newline='', encoding="utf-8") as f:
        reader = csv.DictReader(f)

        if "URL" not in reader.fieldnames:
            raise ValueError("CSV must contain a 'URL' column")

        for row in reader:
            total += 1
            url = row["URL"].strip()

            print(f"[{total}] {url}")

            bib, err = fetch_bibtex(url)

            if bib:
                entries.append(bib)
                success += 1
            else:
                failures.append((url, err))

            time.sleep(1)

    # Write output
    with open(OUTPUT_BIB, "w", encoding="utf-8") as f:
        f.write("\n\n".join(entries))

    # Validation
    print("\n=== SUMMARY ===")
    print(f"CSV rows: {total}")
    print(f"BibTeX entries: {success}")
    print(f"Failures: {len(failures)}")

    if total != success:
        print("\n⚠️ Mismatch detected!")

    if failures:
        print("\nFailed entries:")
        for url, err in failures:
            print(f"- {url} | {err}")


if __name__ == "__main__":
    main()