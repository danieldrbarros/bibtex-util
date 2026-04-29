import re
import requests
from bs4 import BeautifulSoup
import time
import random

INPUT_BIB = "input.bib"
OUTPUT_BIB = "output_enriched.bib"

HEADERS = {"User-Agent": "Mozilla/5.0"}


# -----------------------------
# Utilities
# -----------------------------
def clean_text(text):
    if not text:
        return None
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def split_bibtex_entries(content):
    entries = re.split(r'\n@', content)
    entries = [e if e.startswith('@') else '@' + e for e in entries if e.strip()]
    return entries


def extract_field(entry, field):
    match = re.search(rf'{field}\s*=\s*\{{(.*?)\}}', entry, re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else None


def has_abstract(entry):
    abstract = extract_field(entry, "abstract")
    return abstract and len(abstract) > 100


# -----------------------------
# Semantic Scholar (BEST SOURCE)
# -----------------------------
def fetch_semantic_scholar_abstract(doi):
    try:
        url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}?fields=abstract"
        r = requests.get(url, headers=HEADERS, timeout=10)

        if r.status_code == 200:
            data = r.json()
            abstract = data.get("abstract")

            if abstract and len(abstract) > 50:
                return clean_text(abstract)

    except Exception as e:
        print(f"  ⚠️ Semantic Scholar error: {e}")

    return None


# Optional fallback by title (useful if DOI missing)
def fetch_semantic_scholar_by_title(title):
    try:
        url = f"https://api.semanticscholar.org/graph/v1/paper/search?query={title}&fields=abstract&limit=1"
        r = requests.get(url, headers=HEADERS, timeout=10)

        if r.status_code == 200:
            data = r.json()
            if data.get("data"):
                abstract = data["data"][0].get("abstract")
                if abstract:
                    return clean_text(abstract)

    except Exception as e:
        print(f"  ⚠️ Semantic Scholar title error: {e}")

    return None


# -----------------------------
# CrossRef fallback
# -----------------------------
def fetch_crossref_abstract(doi):
    try:
        url = f"https://api.crossref.org/works/{doi}"
        r = requests.get(url, headers=HEADERS, timeout=10)

        if r.status_code == 200:
            data = r.json()
            abstract = data["message"].get("abstract")

            if abstract:
                abstract = re.sub(r"<.*?>", "", abstract)  # remove XML
                return clean_text(abstract)

    except Exception as e:
        print(f"  ⚠️ CrossRef error: {e}")

    return None


# -----------------------------
# Scraping fallback
# -----------------------------
def extract_abstract_from_url(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, "html.parser")

        sections = soup.find_all(
            ["section", "div"],
            attrs={"class": re.compile("abstract", re.I)}
        )

        for sec in sections:
            text = sec.get_text(separator=" ", strip=True)
            if len(text) > 300:
                return clean_text(text)

        # fallback meta
        tag = soup.find("meta", attrs={"name": "citation_abstract"})
        if tag and tag.get("content"):
            return clean_text(tag.get("content"))

    except Exception as e:
        print(f"  ⚠️ Scraping error: {e}")

    return None


# -----------------------------
# Inject abstract into BibTeX
# -----------------------------
def add_abstract_to_entry(entry, abstract):
    if not abstract:
        return entry

    entry = entry.rstrip().rstrip("}")
    entry += f",\n  abstract = {{{abstract}}}\n}}"
    return entry


# -----------------------------
# Main pipeline
# -----------------------------
def main():
    with open(INPUT_BIB, "r", encoding="utf-8") as f:
        content = f.read()

    entries = split_bibtex_entries(content)

    total = len(entries)
    already_has = 0
    enriched = 0

    new_entries = []

    for i, entry in enumerate(entries, 1):
        print(f"[{i}/{total}] Processing entry")

        if has_abstract(entry):
            already_has += 1
            new_entries.append(entry)
            continue

        doi = extract_field(entry, "doi")
        url = extract_field(entry, "url")
        title = extract_field(entry, "title")

        abstract = None

        # --- Strategy 1: Semantic Scholar (BEST)
        if doi:
            abstract = fetch_semantic_scholar_abstract(doi)
            if abstract:
                print("  → abstract from Semantic Scholar (DOI)")

        # --- Strategy 2: CrossRef
        if not abstract and doi:
            abstract = fetch_crossref_abstract(doi)
            if abstract:
                print("  → abstract from CrossRef")

        # --- Strategy 3: Semantic Scholar by title
        if not abstract and title:
            abstract = fetch_semantic_scholar_by_title(title)
            if abstract:
                print("  → abstract from Semantic Scholar (title)")

        # --- Strategy 4: scraping
        if not abstract and url:
            abstract = extract_abstract_from_url(url)
            if abstract:
                print("  → abstract from scraping")

        if abstract:
            entry = add_abstract_to_entry(entry, abstract)
            enriched += 1

        new_entries.append(entry)

        time.sleep(random.uniform(1.5, 3.0))  # reduce blocking risk

    # Write output
    with open(OUTPUT_BIB, "w", encoding="utf-8") as f:
        f.write("\n\n".join(new_entries))

    # Summary
    print("\n=== SUMMARY ===")
    print(f"Total entries: {total}")
    print(f"Already had abstract: {already_has}")
    print(f"Newly enriched: {enriched}")
    print(f"Still missing: {total - (already_has + enriched)}")


if __name__ == "__main__":
    main()