import os
import re
import pandas as pd
from datetime import datetime

INPUT_CSV = "input.csv"
OUTPUT_BIB = "output.bib"


# -----------------------------
# Helpers
# -----------------------------

def clean_text(value):
    if pd.isna(value):
        return None
    value = str(value).strip()
    return value if value else None


def normalize_field_name(name):
    name = name.lower()
    name = re.sub(r'[^a-z0-9]+', '_', name)
    return name.strip("_")


def parse_authors(authors_raw):
    if not authors_raw:
        return None

    authors_raw = str(authors_raw)

    if ";" in authors_raw:
        authors = authors_raw.split(";")
    elif "|" in authors_raw:
        authors = authors_raw.split("|")
    elif "," in authors_raw:
        authors = authors_raw.split(",")
    else:
        authors = re.findall(r'[A-Z][a-z]+(?:\s[A-Z][a-z]+)*', authors_raw)

    authors = [a.strip() for a in authors if a.strip()]
    return " and ".join(authors) if authors else authors_raw


def extract_first(row, keywords):
    for col in row.index:
        for kw in keywords:
            if kw in col.lower():
                val = clean_text(row[col])
                if val:
                    return val
    return None


def extract_doi(row):
    doi = extract_first(row, ["doi"])
    if doi:
        doi = doi.replace("https://doi.org/", "").replace("http://doi.org/", "")
    return doi


def build_url(doi, row):
    url = extract_first(row, ["url", "link"])
    if url:
        return url
    if doi:
        return f"https://doi.org/{doi}"
    return None


def detect_entry_type(row):
    ct = extract_first(row, ["content type", "type"])
    if not ct:
        return "misc"

    ct = ct.lower()

    if "article" in ct:
        return "article"
    elif "chapter" in ct:
        return "incollection"
    elif "conference" in ct:
        return "inproceedings"
    elif "book" in ct:
        return "book"
    return "misc"


def generate_key(title, year, idx):
    if title:
        base = re.sub(r'\W+', '', title.lower())[:25]
        return f"{base}{year}_{idx}"
    return f"entry_{idx}"


# -----------------------------
# Main
# -----------------------------

def main():
    if not os.path.exists(INPUT_CSV):
        raise FileNotFoundError(f"{INPUT_CSV} not found.")

    df = pd.read_csv(INPUT_CSV)

    entries = []

    for idx, row in df.iterrows():

        # -----------------------------
        # Extract canonical fields
        # -----------------------------
        title = extract_first(row, ["title"])
        authors = extract_first(row, ["author"])
        year = extract_first(row, ["year"])
        journal = extract_first(row, ["journal", "publication title"])
        volume = extract_first(row, ["volume"])
        number = extract_first(row, ["issue", "number"])
        abstract = extract_first(row, ["abstract", "summary"])
        doi = extract_doi(row)
        url = build_url(doi, row)

        entry_type = detect_entry_type(row)
        key = generate_key(title, year, idx)

        fields = {}

        # -----------------------------
        # Standard BibTeX fields
        # -----------------------------
        if title:
            fields["title"] = title

        if authors:
            parsed = parse_authors(authors)
            if parsed:
                fields["author"] = parsed

        if year:
            fields["year"] = year

        if journal:
            fields["journal"] = journal

        if volume:
            fields["volume"] = volume

        if number:
            fields["number"] = number

        if doi:
            fields["doi"] = doi

        if url:
            fields["url"] = url

        if abstract:
            fields["abstract"] = abstract

        # -----------------------------
        # GREEDY: keep ALL remaining fields
        # -----------------------------
        for col in row.index:
            value = clean_text(row[col])
            if not value:
                continue

            field_name = normalize_field_name(col)

            # skip if already mapped
            if field_name in fields:
                continue

            # avoid overriding canonical fields
            if field_name in ["title", "author", "year", "journal"]:
                field_name = f"original_{field_name}"

            fields[field_name] = value

        # -----------------------------
        # Build BibTeX
        # -----------------------------
        bib_entry = f"@{entry_type}{{{key},\n"

        for k, v in fields.items():
            v = v.replace("{", "\\{").replace("}", "\\}")
            bib_entry += f"  {k} = {{{v}}},\n"

        bib_entry = bib_entry.rstrip(",\n") + "\n}\n"

        entries.append(bib_entry)

    # -----------------------------
    # Write file
    # -----------------------------
    with open(OUTPUT_BIB, "w", encoding="utf-8") as f:
        f.write(f"% Generated on {datetime.now()}\n\n")
        for entry in entries:
            f.write(entry + "\n")

    print(f"✅ Generated: {OUTPUT_BIB}")
    print(f"Total entries: {len(entries)}")


if __name__ == "__main__":
    main()