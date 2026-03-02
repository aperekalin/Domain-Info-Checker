#!/usr/bin/env python3
"""
Domain Info Checker
- Reads a CSV file whose first column contains domains/URLs.
- Validates that each row looks like a domain (label + TLD), tolerant of:
  - https:// / http:// prefixes
  - leading www.
  - URLs with paths/query fragments
- Queries WhoisXML API Domain Info API for valid domains.
- Extracts and writes back into the SAME CSV these columns:
    createdDate
    registrarName
    Registrant_name
    Registrant_country

Auth:
  Export your API key as WHOISXMLAPI_API_KEY .

Usage:
  python3 domain_info_checker.py input.csv
"""

from __future__ import annotations

import csv
import os
import re
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests


DOMAIN_INFO_ENDPOINT = "https://domain-info.whoisxmlapi.com/api/v1"  # :contentReference[oaicite:3]{index=3}

OUT_COLUMNS = [
    "createdDate",
    "registrarName",
    "Registrant_name",
    "Registrant_email",   # ← new column (placed after name)
    "Registrant_country",
]


# ---- Domain parsing / validation ----

_LABEL_RE = re.compile(r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)$")


def _to_ascii_idna(host: str) -> Optional[str]:
    """
    Convert Unicode domain to ASCII (punycode) via IDNA.
    Returns None if conversion fails.
    """
    host = host.strip().strip(".")
    if not host:
        return None
    try:
        # Python has built-in 'idna' codec in most distributions.
        return host.encode("idna").decode("ascii")
    except Exception:
        return None


def normalize_domain(raw: str) -> Optional[str]:
    """
    Extract and normalize a domain name from a raw CSV cell.
    Accepts plain domains and URLs.
    Returns normalized ASCII (punycode) domain, or None if it doesn't look like a domain.
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None

    # If it's a URL (or looks like one), use urlparse.
    # urlparse("example.com/path") treats it as path, so add scheme if needed.
    candidate = s
    if "://" not in candidate and ("/" in candidate or "?" in candidate or "#" in candidate):
        candidate = "http://" + candidate

    parsed = urlparse(candidate)
    host = parsed.netloc or parsed.path  # if no scheme, netloc can be empty
    host = host.strip()

    # Remove credentials, port
    if "@" in host:
        host = host.split("@", 1)[1]
    if ":" in host:
        host = host.split(":", 1)[0]

    host = host.strip().strip(".").lower()
    if host.startswith("www."):
        host = host[4:]

    # Basic sanity
    if not host or "." not in host:
        return None
    if len(host) > 253:
        return None
    if "_" in host:
        return None

    # IDNA normalize
    ascii_host = _to_ascii_idna(host)
    if not ascii_host:
        return None

    # Validate labels + TLD
    labels = ascii_host.split(".")
    if len(labels) < 2:
        return None

    tld = labels[-1]
    # Allow punycode TLDs (xn--) or alpha TLDs 2..63
    if not (tld.startswith("xn--") or re.fullmatch(r"[a-z]{2,63}", tld)):
        return None

    for lab in labels:
        # Allow punycode labels
        if lab.startswith("xn--"):
            if len(lab) > 63:
                return None
            continue
        if not _LABEL_RE.fullmatch(lab):
            return None

    return ascii_host


# ---- Domain Info API parsing helpers ----

def _index_field_list(items: Any) -> Dict[str, Any]:
    """
    Convert a list of {"fieldName": ..., "fieldValue": ...} into a dict.
    If duplicates exist, last one wins.
    """
    out: Dict[str, Any] = {}
    if not isinstance(items, list):
        return out
    for it in items:
        if not isinstance(it, dict):
            continue
        k = it.get("fieldName")
        v = it.get("fieldValue")
        if isinstance(k, str):
            out[k] = v
    return out


def _pick_first(fields: Dict[str, Any], candidates: List[str]) -> Optional[Any]:
    for c in candidates:
        if c in fields and fields[c] not in (None, "", []):
            return fields[c]
    return None


@dataclass
class DomainInfoResult:
    created_date: Optional[str]
    registrar_name: Optional[str]
    registrant_name: Optional[str]
    registrant_email: Optional[str]   # ← new
    registrant_country: Optional[str]


def extract_requested_fields(payload: Dict[str, Any]) -> DomainInfoResult:
    """
    Domain Info API response sections:
      - data: list of core WHOIS fields (creation date, registrarName, etc.)
      - registrantContact: list of registrant contact fields (name, country, etc.)
    Each item is {fieldName, fieldValue, auditDate, isEmptyOrRedactedNow}. :contentReference[oaicite:4]{index=4}
    """
    data_map = _index_field_list(payload.get("data"))
    reg_map = _index_field_list(payload.get("registrantContact"))

    created = _pick_first(
        data_map,
        # Prefer ISO8601 if present; fall back to other common names if they appear
        ["createdDateISO8601", "createdDate", "createdDateNormalized"],
    )

    registrar = _pick_first(data_map, ["registrarName"])

    registrant_name = _pick_first(reg_map, ["name"])
    registrant_email = _pick_first(reg_map, ["email"])
    registrant_country = _pick_first(reg_map, ["country", "countryCode"])

    # Cast to strings for CSV friendliness
    def _to_str(x: Any) -> Optional[str]:
        if x is None:
            return None
        if isinstance(x, (dict, list)):
            return str(x)
        s = str(x).strip()
        return s if s else None

    return DomainInfoResult(
        created_date=_to_str(created),
        registrar_name=_to_str(registrar),
        registrant_name=_to_str(registrant_name),
        registrant_email=_to_str(registrant_email),   # ← new
        registrant_country=_to_str(registrant_country),
    )


# ---- CSV helpers ----

def detect_dialect(path: str) -> csv.Dialect:
    """
    Robust dialect detection:
    - Only allow common CSV delimiters: comma, tab, semicolon, pipe.
    - If none are present, default to comma.
    """
    allowed_delims = [",", "\t", ";", "|"]

    with open(path, "r", newline="", encoding="utf-8-sig") as f:
        sample = f.read(8192)

    # If the file doesn't appear to contain any common delimiter, it's likely a 1-column file.
    if not any(d in sample for d in allowed_delims):
        return csv.get_dialect("excel")  # comma

    # Try Sniffer but restrict delimiters to safe ones
    sniffer = csv.Sniffer()
    try:
        dialect = sniffer.sniff(sample, delimiters=allowed_delims)
        return dialect
    except Exception:
        return csv.get_dialect("excel")  # comma fallback


def looks_like_header(first_cell: str) -> bool:
    s = (first_cell or "").strip().lower()
    return s in {"domain", "domains", "domain_name", "domain name", "url", "urls"}


def ensure_columns(header: List[str], wanted: List[str]) -> Tuple[List[str], Dict[str, int]]:
    header_out = list(header)
    for col in wanted:
        if col not in header_out:
            header_out.append(col)
    idx = {name: i for i, name in enumerate(header_out)}
    return header_out, idx


# ---- API call ----

def call_domain_info(api_key: str, domain: str, timeout_s: int = 30) -> Tuple[bool, Any]:
    """
    GET https://domain-info.whoisxmlapi.com/api/v1?apiKey=...&domainName=... :contentReference[oaicite:5]{index=5}
    """
    params = {
        "apiKey": api_key,
        "domainName": domain,
        "outputFormat": "JSON",
    }
    try:
        r = requests.get(DOMAIN_INFO_ENDPOINT, params=params, timeout=timeout_s)
    except requests.RequestException as e:
        return False, f"Request error: {e}"

    # Try JSON first
    try:
        data = r.json()
    except ValueError:
        data = None

    if r.ok and isinstance(data, dict):
        return True, data

    # Error: build a useful message
    if isinstance(data, dict):
        # best-effort extraction
        for k in ("error", "message", "errorMessage", "errorCode", "description", "details"):
            if k in data and data[k]:
                return False, f"HTTP {r.status_code}: {k}={data[k]}"
        return False, f"HTTP {r.status_code}: {data}"
    else:
        txt = (r.text or "").strip()
        if txt:
            return False, f"HTTP {r.status_code}: {txt[:500]}"
        return False, f"HTTP {r.status_code}: (no response body)"


# ---- Main ----

def main(argv: List[str]) -> int:
    if len(argv) != 2:
        print("Usage: python3 domain_info_checker.py <input.csv>", file=sys.stderr)
        return 2

    csv_path = argv[1]
    if not os.path.isfile(csv_path):
        print(f"Error: file not found: {csv_path}", file=sys.stderr)
        return 2

    api_key = os.environ.get("WHOISXMLAPI_API_KEY")
    if not api_key:
        print(
            "Error: WHOISXMLAPI_API_KEY is not set.\n"
            "Run like:\n"
            "  WHOISXMLAPI_API_KEY=\"your_key\" ./run-domain-info-checker.sh file.csv",
            file=sys.stderr,
        )
        return 2

    dialect = detect_dialect(csv_path)

    with open(csv_path, "r", newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f, dialect)
        rows = list(reader)

    if not rows:
        print("CSV is empty; nothing to do.")
        return 0

    header_present = looks_like_header(rows[0][0] if rows[0] else "")
    if header_present:
        header_in = rows[0]
        data_rows = rows[1:]
    else:
        # Create a header if none exists
        ncols = max(len(r) for r in rows)
        header_in = [f"col{i+1}" for i in range(ncols)]
        data_rows = rows

    header_out, col_idx = ensure_columns(header_in, OUT_COLUMNS)

    # Ensure every row has enough columns
    def pad_row(r: List[str], n: int) -> List[str]:
        rr = list(r)
        if len(rr) < n:
            rr.extend([""] * (n - len(rr)))
        return rr

    updated_rows: List[List[str]] = []
    updated_rows.append(header_out)

    # Process each row (first column is domain input)
    for i, row in enumerate(data_rows, start=1 if header_present else 0):
        row = pad_row(row, len(header_out))
        raw_domain = row[0] if row else ""
        domain = normalize_domain(raw_domain)

        if not domain:
            print(f"[row {i}] SKIP (not a domain): {raw_domain}")
            updated_rows.append(row)
            continue

        ok, resp = call_domain_info(api_key, domain)
        if not ok:
            print(f"[{domain}] ERROR: {resp}")
            updated_rows.append(row)
            continue

        # Success
        result = extract_requested_fields(resp)

        row[col_idx["createdDate"]] = result.created_date or ""
        row[col_idx["Registrant_name"]] = result.registrant_name or ""
        row[col_idx["Registrant_email"]] = result.registrant_email or ""
        row[col_idx["Registrant_country"]] = result.registrant_country or ""

        print(
            f"[{domain}] OK | createdDate={row[col_idx['createdDate']]} | "
            f"registrarName={row[col_idx['registrarName']]} | "
            f"Registrant_name={row[col_idx['Registrant_name']]} | "
            f"Registrant_email={row[col_idx['Registrant_email']]} | "
            f"Registrant_country={row[col_idx['Registrant_country']]}"
)

        updated_rows.append(row)

    # Write back to same file
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
      writer = csv.writer(f, delimiter=",")
      writer.writerows(updated_rows)

    print(f"Completed. Updated CSV saved: {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))