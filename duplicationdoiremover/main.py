import os
import glob
from datetime import datetime
from collections import defaultdict

from pybtex.database import parse_file, BibliographyData

from pybtex.database.input import bibtex
from pybtex.errors import set_strict_mode


INPUT_DIR = "input"
OUTPUT_BIB = "output.bib"
AUDIT_LOG = "audit.log"


def normalize_doi(doi):
    if not doi:
        return None
    doi = doi.strip().lower()
    doi = doi.replace("https://doi.org/", "").replace("http://doi.org/", "")
    return doi


def extract_doi(entry):
    # Common fields where DOI may appear
    for field in ["doi", "DOI"]:
        if field in entry.fields:
            return normalize_doi(entry.fields[field])
    return None


def clean_outputs():
    # Always recreate files from scratch
    if os.path.exists(OUTPUT_BIB):
        os.remove(OUTPUT_BIB)
    if os.path.exists(AUDIT_LOG):
        os.remove(AUDIT_LOG)


def log(message):
    with open(AUDIT_LOG, "a", encoding="utf-8") as f:
        f.write(message + "\n")


def main():
    clean_outputs()

    log(f"=== Deduplication Run ===")
    log(f"Timestamp: {datetime.now()}\n")

    bib_files = glob.glob(os.path.join(INPUT_DIR, "*.bib"))

    if not bib_files:
        log("No .bib files found in input folder.")
        print("No .bib files found.")
        return

    log(f"Files processed: {len(bib_files)}")
    for bf in bib_files:
        log(f" - {bf}")
    log("")

    all_entries = []
    source_map = {}  # entry_key -> source file

    set_strict_mode(False)
    parser = bibtex.Parser()
    # Step 1: Read all entries
    for bib_file in bib_files:
        bib_data = parser.parse_file(bib_file)
        for key, entry in bib_data.entries.items():
            all_entries.append((key, entry))
            source_map[key] = os.path.basename(bib_file)

    log(f"Total records read: {len(all_entries)}\n")

    # Step 2: Deduplicate by DOI
    doi_index = {}
    duplicates = []
    missing_doi = []

    for key, entry in all_entries:
        doi = extract_doi(entry)

        if not doi:
            missing_doi.append((key, entry))
            continue

        if doi not in doi_index:
            doi_index[doi] = (key, entry)
        else:
            duplicates.append((doi, key, entry))

    # Step 3: Build cleaned dataset
    cleaned_entries = {}

    # Keep unique DOI entries
    for doi, (key, entry) in doi_index.items():
        cleaned_entries[key] = entry

    # Keep entries without DOI (optional — here we KEEP them)
    for key, entry in missing_doi:
        cleaned_entries[key] = entry

    # Step 4: Logging duplicates
    log("=== DUPLICATES REMOVED (by DOI) ===")
    log(f"Total duplicates removed: {len(duplicates)}\n")

    dup_group = defaultdict(list)
    for doi, key, entry in duplicates:
        dup_group[doi].append((key, entry))

    for doi, items in dup_group.items():
        log(f"DOI: {doi}")
        kept_key, _ = doi_index[doi]
        log(f"  KEPT: {kept_key} (source: {source_map.get(kept_key)})")

        for key, entry in items:
            log(f"  REMOVED: {key} (source: {source_map.get(key)})")
        log("")

    # Step 5: Logging missing DOI
    log("\n=== ENTRIES WITHOUT DOI ===")
    log(f"Total without DOI: {len(missing_doi)}")
    for key, entry in missing_doi:
        log(f" - {key} (source: {source_map.get(key)})")

    # Step 6: Write cleaned .bib
    bib_data = BibliographyData(entries=cleaned_entries)

    with open(OUTPUT_BIB, "w", encoding="utf-8") as f:
        f.write(bib_data.to_string("bibtex"))

    # Summary
    log("\n=== SUMMARY ===")
    log(f"Final records: {len(cleaned_entries)}")
    log(f"Duplicates removed: {len(duplicates)}")
    log(f"Missing DOI kept: {len(missing_doi)}")

    print("Done.")
    print(f"Cleaned file: {OUTPUT_BIB}")
    print(f"Audit log: {AUDIT_LOG}")


if __name__ == "__main__":
    main()