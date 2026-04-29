import re
from collections import defaultdict
from typing import List, Dict


# -----------------------------
# CONFIG
# -----------------------------
INPUT_FILE = "input.ris"
OUTPUT_FILE = "output.bib"


# -----------------------------
# RIS → BibTeX TYPE MAPPING
# -----------------------------
RIS_TO_BIBTEX = {
    "JOUR": "article",
    "JFULL": "article",
    "MGZN": "article",
    "BOOK": "book",
    "CHAP": "incollection",
    "CONF": "inproceedings",
    "CPAPER": "inproceedings",
    "THES": "phdthesis",
    "RPRT": "techreport",
    "ELEC": "misc",
    "GEN": "misc",
}


# -----------------------------
# PARSE RIS FILE (ROBUST)
# -----------------------------
def parse_ris(file_path: str) -> List[Dict[str, List[str]]]:
    records = []
    current = defaultdict(list)
    last_tag = None

    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            raw = line.rstrip()

            # blank line → new record
            if not raw.strip():
                if current:
                    records.append(dict(current))
                    current = defaultdict(list)
                last_tag = None
                continue

            # explicit RIS end
            if raw.startswith("ER"):
                if current:
                    records.append(dict(current))
                    current = defaultdict(list)
                last_tag = None
                continue

            match = re.match(r"^([A-Z0-9]{2})\s*-\s*(.*)$", raw)
            if match:
                tag, value = match.groups()
                current[tag].append(value)
                last_tag = tag
            else:
                # continuation line (VERY important for abstracts)
                if last_tag:
                    current[last_tag][-1] += " " + raw.strip()

    if current:
        records.append(dict(current))

    return records


# -----------------------------
# FIELD MAPPING
# -----------------------------
def map_fields(ris: Dict[str, List[str]]) -> Dict[str, str]:
    bib = {}

    # Authors
    authors = []

    for tag in ["AU", "A1", "A2", "A3", "A4"]:
        if tag in ris:
            authors.extend(ris[tag])

    if authors:
        # Normalize "Last, First" → BibTeX expects this format already
        cleaned_authors = []
        for a in authors:
            a = a.strip()

            # remove trailing punctuation
            a = a.rstrip(".,;")

            cleaned_authors.append(a)

        bib["author"] = " and ".join(cleaned_authors)

    # Title
    if "TI" in ris:
        bib["title"] = ris["TI"][0]
    elif "T1" in ris:
        bib["title"] = ris["T1"][0]

    # Journal / Source
    if "JO" in ris:
        bib["journal"] = ris["JO"][0]
    elif "JF" in ris:
        bib["journal"] = ris["JF"][0]
    elif "T2" in ris:
        bib["journal"] = ris["T2"][0]

    # Booktitle (for proceedings)
    if "BT" in ris:
        bib["booktitle"] = ris["BT"][0]

    # Year
    if "PY" in ris:
        match = re.search(r"\d{4}", ris["PY"][0])
        if match:
            bib["year"] = match.group(0)

    # Volume / Issue
    if "VL" in ris:
        bib["volume"] = ris["VL"][0]
    if "IS" in ris:
        bib["number"] = ris["IS"][0]

    # Pages
    if "SP" in ris and "EP" in ris:
        bib["pages"] = f"{ris['SP'][0]}--{ris['EP'][0]}"
    elif "SP" in ris:
        bib["pages"] = ris["SP"][0]

    # Publisher
    if "PB" in ris:
        bib["publisher"] = ris["PB"][0]

    # DOI + URL (normalized)
    doi = None

    if "DO" in ris:
        doi = ris["DO"][0].strip()

        # clean DOI (remove prefixes)
        doi = re.sub(r"^https?://doi\.org/", "", doi, flags=re.IGNORECASE)
        doi = re.sub(r"^doi:\s*", "", doi, flags=re.IGNORECASE)

        bib["doi"] = doi

    # Prefer DOI-based URL (canonical)
    if doi:
        bib["url"] = f"https://doi.org/{doi}"
    elif "UR" in ris:
        bib["url"] = ris["UR"][0]

    # Abstract (AB + N2 + multiline safe)
    abstract_lines = []
    if "AB" in ris:
        abstract_lines.extend(ris["AB"])
    if "N2" in ris:  # Embase / Scopus
        abstract_lines.extend(ris["N2"])
    if abstract_lines:
        bib["abstract"] = " ".join(abstract_lines)

    # Keywords
    if "KW" in ris:
        bib["keywords"] = ", ".join(ris["KW"])

    # Identifiers
    if "SN" in ris:
        bib["issn"] = ris["SN"][0]

    return bib


# -----------------------------
# TYPE RESOLUTION (EMBASE-AWARE)
# -----------------------------
def resolve_entry_type(ris: Dict[str, List[str]]) -> str:
    ty = ris.get("TY", [""])[0]

    # 1. Trust RIS first (Embase usually correct here)
    if ty in RIS_TO_BIBTEX:
        return RIS_TO_BIBTEX[ty]

    # 2. Heuristics
    if "BT" in ris:
        return "inproceedings"

    if "JO" in ris or "JF" in ris:
        return "article"

    if "PB" in ris and "TI" in ris:
        return "book"

    return "misc"


# -----------------------------
# KEY GENERATION
# -----------------------------
def generate_key(entry: Dict[str, str], index: int) -> str:
    author = entry.get("author", "unknown").split(" and ")[0]
    author = re.sub(r"\W+", "", author.split(",")[0])

    year = entry.get("year", "0000")

    return f"{author}{year}_{index}"


# -----------------------------
# BIBTEX FORMATTER
# -----------------------------
def to_bibtex(entry_type: str, fields: Dict[str, str], key: str) -> str:
    lines = [f"@{entry_type}{{{key},"]

    for k, v in fields.items():
        v = v.replace("\n", " ").strip()
        lines.append(f"  {k} = {{{v}}},")

    if lines[-1].endswith(","):
        lines[-1] = lines[-1][:-1]

    lines.append("}\n")
    return "\n".join(lines)


# -----------------------------
# MAIN
# -----------------------------
def main():
    records = parse_ris(INPUT_FILE)

    print(f"Parsed {len(records)} records")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as out:
        for i, ris in enumerate(records):
            entry_type = resolve_entry_type(ris)
            fields = map_fields(ris)

            key = generate_key(fields, i)
            bibtex_entry = to_bibtex(entry_type, fields, key)

            out.write(bibtex_entry)

    print(f"Conversion completed: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()