# """
# SigNoz Query Generator — FastAPI backend.

# Reuses the customer/product routing logic and HAR extraction from the
# original CLI script, exposed as a single /generate endpoint the React
# frontend calls.
# """
# import json
# import os
# from datetime import datetime, timedelta, timezone

# import pandas as pd
# from fastapi import FastAPI, UploadFile, File, Form
# from fastapi.middleware.cors import CORSMiddleware
# from typing import Optional

# BASE_DIR = os.path.dirname(__file__)
# K8S_CSV = os.path.join(BASE_DIR, "k8s.csv")
# EC2_CSV = os.path.join(BASE_DIR, "ec2_servers.csv")
# DOCKER_CSV = os.path.join(BASE_DIR, "dockernames.csv")

# app = FastAPI(title="SigNoz Query Generator")

# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["*"],          # tighten in production
#     allow_methods=["*"],
#     allow_headers=["*"],
# )


# # ──────────────────────────────────────────────────────────────────────────
# # Routing helpers
# # ──────────────────────────────────────────────────────────────────────────
# def env_match(server_name: str, envs) -> bool:
#     """Match a server to the chosen environment(s). poc/uat/dev are all
#     treated as non-prod. A server is non-prod if its name contains any
#     non-prod marker; otherwise it's prod."""
#     name = server_name.lower()
#     NONPROD_MARKERS = ("uat", "dev")          # add "stg", "test", "qa" if needed
#     is_nonprod = any(m in name for m in NONPROD_MARKERS)
#     for e in envs:
#         e = e.strip().lower()
#         if e in ("poc", "uat", "dev") and is_nonprod:
#             return True
#         if e == "prod" and not is_nonprod:
#             return True
#     return False


# def find_k8s_row(k8clients, customer, instancetype):
#     cust = customer.strip().lower()
#     envs = [e.strip().lower() for e in instancetype]
#     want_poc = any(e in ("poc", "uat") for e in envs)
#     want_prod = any(e == "prod" for e in envs)

#     col = k8clients["customer name"].str.strip().str.lower()
#     cand = k8clients[(col == cust) | (col == cust + "-uat") | (col == "poc-" + cust)]
#     if cand.empty:
#         return None

#     is_poc = cand["k8s.cluster.name"].str.contains("poc", na=False)
#     if want_poc and not want_prod:
#         sel = cand[is_poc]
#     elif want_prod and not want_poc:
#         sel = cand[~is_poc]
#     else:
#         sel = cand
#     return sel if not sel.empty else None


# def build_base_query(customer, product, instancetype):
#     query = ""
#     k8clients = pd.read_csv(K8S_CSV)
#     k8clients.columns = [c.strip() for c in k8clients.columns]
#     ec2clients = pd.read_csv(EC2_CSV)
#     try:
#         dockerclients = pd.read_csv(DOCKER_CSV)
#     except FileNotFoundError:
#         dockerclients = pd.DataFrame()

#     env_clause = "deployment.environment in [" + ",".join(f"'{i}'" for i in instancetype) + "] "

#     df_ec2 = ec2clients[
#         (ec2clients["Client Name"].str.strip().str.lower() == customer.lower())
#         & (ec2clients["Product"].str.strip().str.lower() == product.lower())
#     ]

#     notes = []

#     if product == "ctix":
#         df1 = find_k8s_row(k8clients, customer, instancetype)
#         df2 = (
#             dockerclients[dockerclients.iloc[:, 0].str.strip().str.lower() == customer.lower()]
#             if not dockerclients.empty
#             else pd.DataFrame()
#         )
#         if df1 is not None:
#             query += env_clause
#             clusters = ", ".join(f"'{c}'" for c in df1["k8s.cluster.name"].tolist())
#             namespaces = ", ".join(f"'{n}'" for n in df1["k8s.namespace.name"].tolist())
#             query += f"k8s.cluster.name in [{clusters}] "
#             query += f"k8s.namespace.name in [{namespaces}] "
#         elif not df2.empty:
#             query += f"ec2.tag.client in ['{df2.iloc[0, 0]}'] "
#         elif not df_ec2.empty:
#             sel = df_ec2[df_ec2["Server Name"].apply(lambda s: env_match(s, instancetype))]
#             if not sel.empty:
#                 quoted = ", ".join(f"'{t}'" for t in sel["Server Name"].tolist())
#                 query += f"ec2.tag.Name in [{quoted}]"
#             else:
#                 notes.append(f"No EC2 servers for {customer}/{product} in env {instancetype}")
#         else:
#             notes.append(f"Customer '{customer}' not found for ctix")

#     elif product in ("csap", "cftr"):
#         sel = df_ec2[df_ec2["Server Name"].apply(lambda s: env_match(s, instancetype))]
#         if not sel.empty:
#             quoted = ", ".join(f"'{t}'" for t in sel["Server Name"].tolist())
#             query += f"ec2.tag.Name in [{quoted}]"
#         else:
#             query += f"k8s.namespace.name in ['{product}'] "
#             query += f"AND body contains '{customer}' "

#     elif product == "csol":
#         sel = df_ec2[df_ec2["Server Name"].apply(lambda s: env_match(s, instancetype))]
#         if not sel.empty:
#             quoted = ", ".join(f"'{t}'" for t in sel["Server Name"].tolist())
#             query += f"ec2.tag.Name in [{quoted}]"
#         else:
#             notes.append(f"No EC2 servers for {customer}/{product} in env {instancetype}")

#     elif product == "co-island":
#         query += f"k8s.namespace.name in ['{product}'] "
#         query += f"AND body contains '{customer}' "

#     elif product == "csap-webapp":
#         query += f"k8s.container.name in ['{product}'] "
#         query += f"AND body contains '{customer}' "

#     return query.strip(), notes


# # ──────────────────────────────────────────────────────────────────────────
# # HAR extraction
# # ──────────────────────────────────────────────────────────────────────────
# def extract_har(har_dict, window_minutes=2):
#     """Pull error endpoint paths, error status codes, and the incident time
#     window from a parsed HAR dict. Only 4xx/5xx entries are used."""
#     from urllib.parse import urlparse

#     paths, statuses, times, seen = [], set(), [], set()
#     for e in har_dict.get("log", {}).get("entries", []):
#         status = e.get("response", {}).get("status", 0)
#         if status < 400:
#             continue
#         path = urlparse(e.get("request", {}).get("url", "")).path
#         if path and path != "/" and path not in seen:
#             seen.add(path)
#             paths.append(path)
#         statuses.add(str(status))
#         if e.get("startedDateTime"):
#             times.append(e["startedDateTime"])

#     start_nano = end_nano = start_str = end_str = None
#     if times:
#         ts = [datetime.fromisoformat(t.replace("Z", "+00:00")) for t in times]
#         lo = min(ts) - timedelta(minutes=window_minutes)
#         hi = max(ts) + timedelta(minutes=window_minutes)
#         start_nano = int(lo.timestamp() * 1_000_000_000)
#         end_nano = int(hi.timestamp() * 1_000_000_000)
#         start_str = lo.strftime("%Y-%m-%d %H:%M:%S")
#         end_str = hi.strftime("%Y-%m-%d %H:%M:%S")

#     return {
#         "paths": paths,
#         "statuses": sorted(statuses),
#         "start_nano": start_nano,
#         "end_nano": end_nano,
#         "start_str": start_str,
#         "end_str": end_str,
#     }


# def group_clause(values):
#     """OR same-kind values into one group: 1 -> bare, 2+ -> (a OR b ...)."""
#     clauses = [f"body contains '{v}'" for v in values]
#     if not clauses:
#         return None
#     if len(clauses) == 1:
#         return clauses[0]
#     return "(" + " OR ".join(clauses) + ")"


# def iso_to_nano(iso_str):
#     """Convert a UTC datetime string (from the absolute picker) to ns epoch."""
#     if not iso_str:
#         return None
#     # datetime-local gives 'YYYY-MM-DDTHH:MM' (no seconds, no tz). Treat as UTC.
#     dt = datetime.fromisoformat(iso_str)
#     if dt.tzinfo is None:
#         dt = dt.replace(tzinfo=timezone.utc)
#     return int(dt.timestamp() * 1_000_000_000)


# # ──────────────────────────────────────────────────────────────────────────
# # Endpoint
# # ──────────────────────────────────────────────────────────────────────────
# @app.post("/generate")
# async def generate(
#     customer: str = Form(...),
#     product: str = Form(...),
#     env: str = Form(...),                       # comma-separated: "poc" or "prod,poc"
#     time_mode: str = Form("none"),              # "none" | "relative" | "absolute"
#     relative: Optional[str] = Form(None),       # e.g. "15m", "1h", "24h"
#     abs_start: Optional[str] = Form(None),      # "YYYY-MM-DDTHH:MM" (UTC)
#     abs_end: Optional[str] = Form(None),
#     har: Optional[UploadFile] = File(None),
# ):
#     instancetype = [e.strip() for e in env.split(",") if e.strip()]
#     base, notes = build_base_query(customer, product, instancetype)

#     # ── HAR (optional) ────────────────────────────────────────────────
#     har_info = None
#     if har is not None:
#         raw = await har.read()
#         try:
#             har_dict = json.loads(raw.decode("utf-8"))
#             har_info = extract_har(har_dict)
#         except Exception as ex:
#             notes.append(f"Could not parse HAR: {ex}")

#     # body clauses from HAR
#     body_parts = []
#     if har_info:
#         g_path = group_clause(har_info["paths"])
#         g_status = group_clause(har_info["statuses"])
#         if g_path:
#             body_parts.append(g_path)
#         if g_status:
#             body_parts.append(g_status)
#         # If the HAR contained any error responses, also restrict to ERROR-level
#         # log lines (cuts the INFO noise). Bare 'ERROR' matches every log format.
#         if har_info["statuses"]:
#             body_parts.append("body contains 'ERROR'")

#     query_no_time = base
#     if body_parts:
#         query_no_time = base + " AND " + " AND ".join(body_parts)

#     # ── Resolve time: HAR wins, else user input ───────────────────────
#     start_nano = end_nano = None
#     time_label = None

#     if har_info and har_info["start_nano"]:
#         start_nano = har_info["start_nano"]
#         end_nano = har_info["end_nano"]
#         time_label = f"{har_info['start_str']} to {har_info['end_str']} UTC (from HAR)"
#     elif time_mode == "absolute" and abs_start and abs_end:
#         start_nano = iso_to_nano(abs_start)
#         end_nano = iso_to_nano(abs_end)
#         time_label = f"{abs_start} to {abs_end} UTC (manual)"
#     elif time_mode == "relative" and relative:
#         unit = relative[-1]
#         amount = int(relative[:-1])
#         mins = {"m": 1, "h": 60, "d": 1440}.get(unit, 1) * amount
#         now = datetime.now(timezone.utc)
#         lo = now - timedelta(minutes=mins)
#         start_nano = int(lo.timestamp() * 1_000_000_000)
#         end_nano = int(now.timestamp() * 1_000_000_000)
#         time_label = f"Last {relative} (relative)"

#     query_with_time = query_no_time
#     if start_nano and end_nano:
#         query_with_time = (
#             query_no_time
#             + f" AND timestamp >= {start_nano} AND timestamp <= {end_nano}"
#         )

#     return {
#         "base_query": base,
#         "query_without_time": query_no_time,
#         "query_with_time": query_with_time,
#         "time_label": time_label,
#         "time_source": (
#             "har" if (har_info and har_info["start_nano"])
#             else time_mode if start_nano else "none"
#         ),
#         "har_summary": (
#             {
#                 "endpoints": har_info["paths"],
#                 "statuses": har_info["statuses"],
#                 "window": time_label if har_info and har_info["start_nano"] else None,
#             }
#             if har_info
#             else None
#         ),
#         "notes": notes,
#     }


# @app.get("/customers")
# def customers():
#     """Return the combined, deduplicated list of known customers from both
#     the k8s and EC2 files, for the search dropdown in the UI."""
#     names = set()
#     try:
#         k8 = pd.read_csv(K8S_CSV)
#         k8.columns = [c.strip() for c in k8.columns]
#         for n in k8["customer name"].dropna():
#             names.add(str(n).strip())
#     except Exception:
#         pass
#     try:
#         ec2 = pd.read_csv(EC2_CSV)
#         for n in ec2["Client Name"].dropna():
#             names.add(str(n).strip())
#     except Exception:
#         pass
#     return {"customers": sorted(names, key=str.lower)}


# @app.get("/health")
# def health():
#     return {"status": "ok"}

"""
SigNoz Query Generator — FastAPI backend.

Reuses the customer/product routing logic and HAR extraction from the
original CLI script, exposed as a single /generate endpoint the React
frontend calls.
"""
"""
SigNoz Query Generator — FastAPI backend.

Reuses the customer/product routing logic and HAR extraction from the
original CLI script, exposed as a single /generate endpoint the React
frontend calls.
"""
import json
import os
from datetime import datetime, timedelta, timezone

import pandas as pd
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional

BASE_DIR = os.path.dirname(__file__)
K8S_CSV = os.path.join(BASE_DIR, "k8s.csv")
EC2_CSV = os.path.join(BASE_DIR, "ec2_servers.csv")
DOCKER_CSV = os.path.join(BASE_DIR, "dockernames.csv")
ALIASES_CSV = os.path.join(BASE_DIR, "customer_aliases.csv")

app = FastAPI(title="SigNoz Query Generator")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # tighten in production
    allow_methods=["*"],
    allow_headers=["*"],
)


# ──────────────────────────────────────────────────────────────────────────
# Customer alias resolution
# ──────────────────────────────────────────────────────────────────────────
def load_aliases():
    """alias (lowercase, as typed) -> {'code': internal short code used in
    k8s.csv/ec2_servers.csv, 'display': pretty name for the UI}."""
    try:
        df = pd.read_csv(ALIASES_CSV)
        df.columns = [c.strip() for c in df.columns]
        out = {}
        for _, row in df.iterrows():
            alias = str(row["alias"]).strip().lower()
            out[alias] = {
                "code": str(row["customer_code"]).strip(),
                "display": str(row["display_name"]).strip(),
            }
        return out
    except Exception:
        return {}


def resolve_customer(raw_customer: str):
    """Turn whatever the person typed/selected (e.g. 'PayPal', 'Unicredit',
    'UCG') into (internal_code, display_name). Falls back to the raw text
    itself if it's not in the alias table yet -- so unaliased customers keep
    working exactly as before."""
    norm = raw_customer.strip().lower()
    aliases = load_aliases()
    if norm in aliases:
        return aliases[norm]["code"], aliases[norm]["display"]
    return norm, raw_customer.strip()


def format_display_name(raw_code: str) -> str:
    """Best-effort readable formatting for customers that have no explicit
    alias entry yet. Short alphabetic codes (<=4 chars, e.g. 'idbi', 'vii')
    are treated as acronyms and uppercased; anything longer is title-cased
    (e.g. 'nexus' -> 'Nexus'). This is DISPLAY-ONLY -- matching is already
    case-insensitive everywhere, so this never changes query behavior.
    If a guess here is wrong for a real customer, add one row to
    customer_aliases.csv to override it permanently."""
    raw = raw_code.strip()
    if not raw:
        return raw
    if len(raw) <= 4 and raw.isalpha():
        return raw.upper()
    return raw.title()


# ──────────────────────────────────────────────────────────────────────────
# Routing helpers
# ──────────────────────────────────────────────────────────────────────────
def env_match(server_name: str, envs) -> bool:
    """Match a server to the chosen environment(s). poc/uat/dev are all
    treated as non-prod. A server is non-prod if its name contains any
    non-prod marker; otherwise it's prod."""
    name = server_name.lower()
    NONPROD_MARKERS = ("uat", "dev")          # add "stg", "test", "qa" if needed
    is_nonprod = any(m in name for m in NONPROD_MARKERS)
    for e in envs:
        e = e.strip().lower()
        if e in ("poc", "uat", "dev") and is_nonprod:
            return True
        if e == "prod" and not is_nonprod:
            return True
    return False


def find_k8s_row(k8clients, customer, instancetype):
    cust = customer.strip().lower()
    envs = [e.strip().lower() for e in instancetype]
    want_poc = any(e in ("poc", "uat") for e in envs)
    want_prod = any(e == "prod" for e in envs)

    col = k8clients["customer name"].str.strip().str.lower()
    cand = k8clients[(col == cust) | (col == cust + "-uat") | (col == "poc-" + cust)]
    if cand.empty:
        return None

    is_poc = cand["k8s.cluster.name"].str.contains("poc", na=False)
    if want_poc and not want_prod:
        sel = cand[is_poc]
    elif want_prod and not want_poc:
        sel = cand[~is_poc]
    else:
        sel = cand
    return sel if not sel.empty else None


def build_base_query(customer, product, instancetype):
    query = ""
    k8clients = pd.read_csv(K8S_CSV)
    k8clients.columns = [c.strip() for c in k8clients.columns]
    ec2clients = pd.read_csv(EC2_CSV)
    try:
        dockerclients = pd.read_csv(DOCKER_CSV)
    except FileNotFoundError:
        dockerclients = pd.DataFrame()

    env_clause = "deployment.environment in [" + ",".join(f"'{i}'" for i in instancetype) + "] "

    df_ec2 = ec2clients[
        (ec2clients["Client Name"].str.strip().str.lower() == customer.lower())
        & (ec2clients["Product"].str.strip().str.lower() == product.lower())
    ]

    notes = []

    if product == "ctix":
        df1 = find_k8s_row(k8clients, customer, instancetype)
        df2 = (
            dockerclients[dockerclients.iloc[:, 0].str.strip().str.lower() == customer.lower()]
            if not dockerclients.empty
            else pd.DataFrame()
        )
        if df1 is not None:
            query += env_clause
            clusters = ", ".join(f"'{c}'" for c in df1["k8s.cluster.name"].tolist())
            namespaces = ", ".join(f"'{n}'" for n in df1["k8s.namespace.name"].tolist())
            query += f"k8s.cluster.name in [{clusters}] "
            query += f"k8s.namespace.name in [{namespaces}] "
        elif not df2.empty:
            query += f"ec2.tag.client in ['{df2.iloc[0, 0]}'] "
        elif not df_ec2.empty:
            sel = df_ec2[df_ec2["Server Name"].apply(lambda s: env_match(s, instancetype))]
            if not sel.empty:
                quoted = ", ".join(f"'{t}'" for t in sel["Server Name"].tolist())
                query += f"ec2.tag.Name in [{quoted}]"
            else:
                notes.append(f"No EC2 servers for {customer}/{product} in env {instancetype}")
        else:
            notes.append(f"Customer '{customer}' not found for ctix")

    elif product in ("csap", "cftr"):
        sel = df_ec2[df_ec2["Server Name"].apply(lambda s: env_match(s, instancetype))]
        if not sel.empty:
            quoted = ", ".join(f"'{t}'" for t in sel["Server Name"].tolist())
            query += f"ec2.tag.Name in [{quoted}]"
        else:
            query += f"k8s.namespace.name in ['{product}'] "
            query += f"AND body contains '{customer}' "

    elif product == "csol":
        sel = df_ec2[df_ec2["Server Name"].apply(lambda s: env_match(s, instancetype))]
        if not sel.empty:
            quoted = ", ".join(f"'{t}'" for t in sel["Server Name"].tolist())
            query += f"ec2.tag.Name in [{quoted}]"
        else:
            notes.append(f"No EC2 servers for {customer}/{product} in env {instancetype}")

    elif product == "co-island":
        query += f"k8s.namespace.name in ['{product}'] "
        query += f"AND body contains '{customer}' "

    elif product == "csap-webapp":
        query += f"k8s.container.name in ['{product}'] "
        query += f"AND body contains '{customer}' "

    return query.strip(), notes


# ──────────────────────────────────────────────────────────────────────────
# HAR extraction
# ──────────────────────────────────────────────────────────────────────────
import re

ID_SEGMENT_RE = re.compile(
    r"^("
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"  # UUID
    r"|\d+"                                                                          # pure digits
    r"|[0-9a-fA-F]{16,}"                                                             # long hex hash
    r")$"
)
STATIC_ASSET_RE = re.compile(
    r"\.(js|css|png|jpe?g|gif|svg|woff2?|ttf|ico|map|json)$", re.IGNORECASE
)
BACKEND_RESOURCE_TYPES = {"xhr", "fetch", "document"}


def is_id_segment(segment: str) -> bool:
    if ID_SEGMENT_RE.match(segment):
        return True
    # Generic catch-all: real route words are essentially never 12+ chars of
    # pure alphanumerics mixing letters AND digits (e.g. ULIDs like
    # '01KWC3TMZN4V197QV0Z7CDXXBY', nanoids, random tokens) -- but legitimate
    # short segments like 'v3', 'api', 'ctix' stay untouched since they're
    # either too short or don't mix letters+digits.
    if segment.isalnum() and len(segment) >= 12:
        has_digit = any(c.isdigit() for c in segment)
        has_alpha = any(c.isalpha() for c in segment)
        if has_digit and has_alpha:
            return True
    return False


def meaningful_endpoint(path: str) -> str:
    """Strip resource-ID path segments (UUIDs, numeric IDs, hashes) so the
    remaining path reads like the *route*, not one specific request -- e.g.
    '/ctix/threatdata/report/239fda18-.../basic-details' -> 'report/basic-details'.
    Falls back to the full path if nothing meaningful is left. This is a
    best-effort heuristic -- verify against real log samples if precision
    here matters for a given customer/product."""
    segments = [s for s in path.split("/") if s]
    kept = [s for s in segments if not is_id_segment(s)]
    if not kept:
        return path
    return "/".join(kept[-2:])


def extract_har(har_dict, window_minutes=2):
    """Pull error endpoint paths, error status codes, and the incident time
    window from a parsed HAR dict. Only 4xx/5xx entries from real API calls
    are used -- fonts, images, analytics beacons, etc. that happen to 404
    are ignored even though they technically errored, since Chrome tags
    every HAR entry with a _resourceType we can filter on."""
    from urllib.parse import urlparse

    paths, endpoint_hints = [], []
    statuses, times = set(), []
    seen_paths, seen_hints = set(), set()

    for e in har_dict.get("log", {}).get("entries", []):
        status = e.get("response", {}).get("status", 0)
        if status < 400:
            continue

        resource_type = e.get("_resourceType")
        if resource_type is not None and resource_type not in BACKEND_RESOURCE_TYPES:
            continue  # skip fonts/images/analytics beacons etc.

        url = e.get("request", {}).get("url", "")
        path = urlparse(url).path
        if not path or path == "/":
            continue
        if STATIC_ASSET_RE.search(path):
            continue  # safety net if _resourceType wasn't present on this entry

        if path not in seen_paths:
            seen_paths.add(path)
            paths.append(path)

        hint = meaningful_endpoint(path)
        if hint not in seen_hints:
            seen_hints.add(hint)
            endpoint_hints.append(hint)

        statuses.add(str(status))
        if e.get("startedDateTime"):
            times.append(e["startedDateTime"])

    start_nano = end_nano = start_str = end_str = None
    if times:
        ts = [datetime.fromisoformat(t.replace("Z", "+00:00")) for t in times]
        lo = min(ts) - timedelta(minutes=window_minutes)
        hi = max(ts) + timedelta(minutes=window_minutes)
        start_nano = int(lo.timestamp() * 1_000_000_000)
        end_nano = int(hi.timestamp() * 1_000_000_000)
        start_str = lo.strftime("%Y-%m-%d %H:%M:%S")
        end_str = hi.strftime("%Y-%m-%d %H:%M:%S")

    return {
        "paths": paths,
        "endpoint_hints": endpoint_hints,
        "statuses": sorted(statuses),
        "start_nano": start_nano,
        "end_nano": end_nano,
        "start_str": start_str,
        "end_str": end_str,
    }


def group_clause(values):
    """OR same-kind values into one group: 1 -> bare, 2+ -> (a OR b ...)."""
    clauses = [f"body contains '{v}'" for v in values]
    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return "(" + " OR ".join(clauses) + ")"


def iso_to_nano(iso_str):
    """Convert a UTC datetime string (from the absolute picker) to ns epoch."""
    if not iso_str:
        return None
    # datetime-local gives 'YYYY-MM-DDTHH:MM' (no seconds, no tz). Treat as UTC.
    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1_000_000_000)


# ──────────────────────────────────────────────────────────────────────────
# Endpoint
# ──────────────────────────────────────────────────────────────────────────
@app.post("/generate")
async def generate(
    customer: str = Form(...),
    product: str = Form(...),
    env: str = Form(...),                       # comma-separated: "poc" or "prod,poc"
    time_mode: str = Form("none"),              # "none" | "relative" | "absolute"
    relative: Optional[str] = Form(None),       # e.g. "15m", "1h", "24h"
    abs_start: Optional[str] = Form(None),      # "YYYY-MM-DDTHH:MM" (UTC)
    abs_end: Optional[str] = Form(None),
    har: Optional[UploadFile] = File(None),
    ticket_keywords: Optional[str] = Form(None),  # comma-separated, e.g. from an LLM keyword-extraction step
):
    instancetype = [e.strip() for e in env.split(",") if e.strip()]

    resolved_customer, display_name = resolve_customer(customer)
    base, notes = build_base_query(resolved_customer, product, instancetype)
    if resolved_customer != customer.strip().lower():
        notes.insert(0, f"Resolved customer '{customer}' -> '{resolved_customer}' ({display_name})")

    # ── HAR (optional) ────────────────────────────────────────────────
    har_info = None
    if har is not None:
        raw = await har.read()
        try:
            har_dict = json.loads(raw.decode("utf-8"))
            har_info = extract_har(har_dict)
        except Exception as ex:
            notes.append(f"Could not parse HAR: {ex}")

    # ── Resolve time: HAR wins, else user input ───────────────────────
    start_nano = end_nano = None
    time_label = None

    if har_info and har_info["start_nano"]:
        start_nano = har_info["start_nano"]
        end_nano = har_info["end_nano"]
        time_label = f"{har_info['start_str']} to {har_info['end_str']} UTC (from HAR)"
    elif time_mode == "absolute" and abs_start and abs_end:
        start_nano = iso_to_nano(abs_start)
        end_nano = iso_to_nano(abs_end)
        time_label = f"{abs_start} to {abs_end} UTC (manual)"
    elif time_mode == "relative" and relative:
        unit = relative[-1]
        amount = int(relative[:-1])
        mins = {"m": 1, "h": 60, "d": 1440}.get(unit, 1) * amount
        now = datetime.now(timezone.utc)
        lo = now - timedelta(minutes=mins)
        start_nano = int(lo.timestamp() * 1_000_000_000)
        end_nano = int(now.timestamp() * 1_000_000_000)
        time_label = f"Last {relative} (relative)"

    def with_time(query_body: str) -> str:
        if start_nano and end_nano:
            return query_body + f" AND timestamp >= {start_nano} AND timestamp <= {end_nano}"
        return query_body

    # ── Build candidate queries ────────────────────────────────────────
    # Rather than betting everything on one "best guess" query, generate
    # several narrower/wider variants. Each gets run independently against
    # SigNoz downstream, and whichever actually returns logs relevant to the
    # ticket wins -- so a wrong guess here just means that candidate finds
    # nothing, not that the whole request fails.
    candidates = [
        {
            "strategy": "base",
            "description": "Customer/product/environment only, no narrowing",
            "query_without_time": base,
            "query_with_time": with_time(base),
        }
    ]

    if har_info:
        # Each HAR-derived signal becomes its OWN candidate rather than one
        # big AND'd clause. Real-world testing showed why this matters: a
        # request path may simply never be echoed into the log body (giving
        # 0 results and poisoning a combined AND clause), while a bare
        # status-code match can produce false positives (matching an
        # unrelated coincidental '500' elsewhere in the log). Keeping them
        # independent means one bad assumption doesn't take out the others,
        # and the relevance-scoring step downstream judges each on its own.
        har_path_candidates = list(dict.fromkeys(har_info["paths"] + har_info["endpoint_hints"]))
        g_path = group_clause(har_path_candidates)
        if g_path:
            path_query = base + " AND " + g_path
            candidates.append({
                "strategy": "har_endpoint",
                "description": "Narrowed using error endpoint(s) from the HAR file",
                "query_without_time": path_query,
                "query_with_time": with_time(path_query),
            })

        g_status = group_clause(har_info["statuses"])
        if g_status:
            status_query = base + " AND " + g_status
            candidates.append({
                "strategy": "har_status",
                "description": "Narrowed using HTTP status code(s) from the HAR file -- "
                                "note: a bare status-code string can false-positive-match "
                                "unrelated numbers in log content, verify relevance carefully",
                "query_without_time": status_query,
                "query_with_time": with_time(status_query),
            })

        if har_info["statuses"]:
            error_query = base + " AND body contains 'ERROR'"
            candidates.append({
                "strategy": "har_error_marker",
                "description": "Narrowed to ERROR-level log lines only, since the HAR contained error responses",
                "query_without_time": error_query,
                "query_with_time": with_time(error_query),
            })

    keyword_list = [k.strip() for k in (ticket_keywords or "").split(",") if k.strip()]
    if keyword_list:
        kw_group = group_clause(keyword_list)
        kw_query = base + " AND " + kw_group
        candidates.append({
            "strategy": "ticket_keywords",
            "description": f"Narrowed using keywords extracted from the ticket: {', '.join(keyword_list)}",
            "query_without_time": kw_query,
            "query_with_time": with_time(kw_query),
        })

    # "Best guess" single query for backward compatibility with callers that
    # only look at the top-level fields. Priority: error-marker (most
    # reliable per real-world testing) > endpoint > status (least reliable,
    # prone to false positives) > ticket keywords > base.
    best = (
        next((c for c in candidates if c["strategy"] == "har_error_marker"), None)
        or next((c for c in candidates if c["strategy"] == "har_endpoint"), None)
        or next((c for c in candidates if c["strategy"] == "har_status"), None)
        or next((c for c in candidates if c["strategy"] == "ticket_keywords"), None)
        or candidates[0]
    )

    return {
        "base_query": base,
        "query_without_time": best["query_without_time"],
        "query_with_time": best["query_with_time"],
        "candidates": candidates,
        "time_label": time_label,
        "time_source": (
            "har" if (har_info and har_info["start_nano"])
            else time_mode if start_nano else "none"
        ),
        "har_summary": (
            {
                "endpoints": har_info["paths"],
                "endpoint_hints": har_info["endpoint_hints"],
                "statuses": har_info["statuses"],
                "window": time_label if har_info and har_info["start_nano"] else None,
            }
            if har_info
            else None
        ),
        "notes": notes,
    }


@app.get("/customers")
def customers():
    """Return the combined, deduplicated list of known customers for the
    search dropdown in the UI. Prefers the friendly display_name from the
    alias table; anything not yet aliased falls back to its raw CSV value,
    deduplicated case-insensitively so casing differences between k8s.csv
    and ec2_servers.csv (e.g. 'Unicredit' vs 'UniCredit') don't show twice."""
    aliases = load_aliases()
    aliased_codes = {a["code"].lower() for a in aliases.values()}
    aliased_display_names = {a["display"] for a in aliases.values()}

    raw_names = {}  # lowercase -> first-seen original casing
    try:
        k8 = pd.read_csv(K8S_CSV)
        k8.columns = [c.strip() for c in k8.columns]
        for n in k8["customer name"].dropna():
            n = str(n).strip()
            raw_names.setdefault(n.lower(), n)
    except Exception:
        pass
    try:
        ec2 = pd.read_csv(EC2_CSV)
        for n in ec2["Client Name"].dropna():
            n = str(n).strip()
            raw_names.setdefault(n.lower(), n)
    except Exception:
        pass

    # drop raw entries already represented by an alias's internal code,
    # then auto-format the rest for nicer display (acronym-case or title-case)
    unaliased = [
        format_display_name(v) for k, v in raw_names.items() if k not in aliased_codes
    ]

    combined = aliased_display_names.union(unaliased)
    return {"customers": sorted(combined, key=str.lower)}


@app.get("/resolve-customer")
def resolve_customer_endpoint(name: str):
    """Quick lookup to check what a given customer name resolves to --
    useful for debugging alias entries or wiring up automation."""
    code, display = resolve_customer(name)
    return {"input": name, "resolved_code": code, "display_name": display}


@app.get("/health")
def health():
    return {"status": "ok"}
