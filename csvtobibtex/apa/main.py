import csv
import requests
from bs4 import BeautifulSoup
import time
import re

INPUT_CSV = "input.csv"
OUTPUT_BIB = "output.bib"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
}


# -----------------------------
# Helpers
# -----------------------------
def first_or_none(lst):
    return lst[0] if lst else None


def normalize_doi(doi):
    if not doi:
        return None
    doi = doi.strip()
    doi = re.sub(r"https?://(dx\.)?doi\.org/", "", doi, flags=re.I)
    return doi


def extract_doi_from_row(row):
    if "DOI" in row and row["DOI"].strip():
        return normalize_doi(row["DOI"])
    return None


def resolve_url(row):
    # Keep compatibility with existing logic
    if "URL" in row and row["URL"].strip():
        return row["URL"].strip()

    if "DOI" in row and row["DOI"].strip():
        raw = row["DOI"].strip()

        if raw.lower().startswith("http"):
            return raw

        doi = normalize_doi(raw)
        return f"https://doi.org/{doi}"

    return None


def extract_doi(soup):
    doi = soup.find("meta", attrs={"name": "citation_doi"})
    if doi:
        return doi.get("content")

    text = soup.get_text()
    match = re.search(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", text, re.I)
    return match.group(0) if match else None


# -----------------------------
# Abstract extraction
# -----------------------------
def extract_abstract(soup):
    selectors = [
        {"name": "section", "attrs": {"class": re.compile("Abstract", re.I)}},
        {"name": "div", "attrs": {"class": re.compile("Abstract", re.I)}},
        {"name": "div", "attrs": {"class": re.compile("abstract-text", re.I)}},
        {"name": "div", "attrs": {"class": re.compile("abstractSection", re.I)}},
        {"name": "section", "attrs": {"id": re.compile("abstract", re.I)}},
        {"name": "div", "attrs": {"id": re.compile("abstract", re.I)}},
    ]

    for sel in selectors:
        tag = soup.find(sel["name"], attrs=sel["attrs"])
        if tag:
            text = tag.get_text(separator=" ", strip=True)
            if len(text) > 300:
                return clean_text(text)

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

    tag = soup.find("meta", attrs={"name": "citation_abstract"})
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
# CrossRef (PRIMARY)
# -----------------------------
def fetch_crossref_bibtex(doi):
    try:
        url = f"https://api.crossref.org/works/{doi}/transform/application/x-bibtex"
        r = requests.get(url, headers=HEADERS, timeout=10)

        if r.status_code == 200:
            return r.text
    except Exception as e:
        print(f"  ⚠️ CrossRef error: {e}")

    return None


# -----------------------------
# Build BibTeX (fallback)
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

    entry_type = "article" if journal else "inproceedings" if booktitle else "misc"
    key = f"auto_{abs(hash(url))}"

    fields = {
        "title": title,
        "author": " and ".join(authors) if authors else None,
        "journal": journal,
        "booktitle": booktitle,
        "year": year,
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
# Scraping fallback
# -----------------------------
def fetch_bibtex(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=10, allow_redirects=True)
        soup = BeautifulSoup(r.text, "html.parser")

        abstract = extract_abstract(soup)

        # Try metadata
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

        for row in reader:
            total += 1
            print(f"[{total}] Processing")

            doi = extract_doi_from_row(row)
            url = resolve_url(row)

            bib = None
            err = None

            # --- PRIMARY: CrossRef
            if doi:
                print(f"  → trying CrossRef (DOI: {doi})")
                bib = fetch_crossref_bibtex(doi)

            # --- FALLBACK: scraping
            if not bib and url:
                print(f"  → fallback scraping: {url}")
                bib, err = fetch_bibtex(url)

            if bib:
                entries.append(bib)
                success += 1
            else:
                failures.append((url or doi, err or "No metadata found"))

            time.sleep(1)

    with open(OUTPUT_BIB, "w", encoding="utf-8") as f:
        f.write("\n\n".join(entries))

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