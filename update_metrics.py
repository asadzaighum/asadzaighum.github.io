#!/usr/bin/env python3
"""
update_metrics.py
-----------------
Fetches research metrics and writes them into index.html by targeting the
elements with id="scopus-docs", "wos-docs", "scopus-h", "wos-h" and the
"Last updated" span (id="metrics-updated").

It ONLY replaces the number inside those specific elements, so the rest of
the page is never touched.

Environment variables (set as GitHub Actions secrets):
  SCOPUS_API_KEY   (required for Scopus)  -> from https://dev.elsevier.com
  SCOPUS_AUTHOR_ID (required for Scopus)  -> your numeric Scopus Author ID: 55507494500
  SCOPUS_INST_TOKEN (optional)            -> institutional token, if your
                                             institution requires one for API access
  WOS_API_KEY      (optional)             -> Web of Science Starter API key
  WOS_AUTHOR_ID    (optional)             -> your WoS ResearcherID / author id

If a source's credentials are missing or the call fails, that source's numbers
are left exactly as they are in the file. The script never crashes the build.
"""

import os
import re
import sys
import json
import datetime
import urllib.request
import urllib.error

HTML_FILE = os.environ.get("HTML_FILE", "index.html")

SCOPUS_API_KEY   = os.environ.get("SCOPUS_API_KEY", "").strip()
SCOPUS_AUTHOR_ID = os.environ.get("SCOPUS_AUTHOR_ID", "").strip()
SCOPUS_INST_TOKEN = os.environ.get("SCOPUS_INST_TOKEN", "").strip()

WOS_API_KEY   = os.environ.get("WOS_API_KEY", "").strip()
WOS_AUTHOR_ID = os.environ.get("WOS_AUTHOR_ID", "").strip()


def log(msg):
    print(f"[update_metrics] {msg}", flush=True)


def http_get_json(url, headers):
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ---------------------------------------------------------------- Scopus ----
def fetch_scopus():
    """Return dict with 'h' and 'docs', or {} on any failure."""
    if not (SCOPUS_API_KEY and SCOPUS_AUTHOR_ID):
        log("Scopus credentials missing -> skipping Scopus.")
        return {}

    url = (
        "https://api.elsevier.com/content/author/author_id/"
        f"{SCOPUS_AUTHOR_ID}?view=METRICS"
    )
    headers = {
        "X-ELS-APIKey": SCOPUS_API_KEY,
        "Accept": "application/json",
    }
    if SCOPUS_INST_TOKEN:
        headers["X-ELS-Insttoken"] = SCOPUS_INST_TOKEN

    try:
        data = http_get_json(url, headers)
    except urllib.error.HTTPError as e:
        log(f"Scopus HTTP {e.code}: {e.read().decode('utf-8', 'ignore')[:300]}")
        return {}
    except Exception as e:  # noqa: BLE001
        log(f"Scopus request failed: {e}")
        return {}

    try:
        core = data["author-retrieval-response"][0]
        h = int(core["h-index"])
        docs = int(core["coredata"]["document-count"])
        log(f"Scopus -> h-index={h}, docs={docs}")
        return {"h": h, "docs": docs}
    except (KeyError, IndexError, ValueError, TypeError) as e:
        log(f"Scopus response parse error: {e}")
        return {}


# ------------------------------------------------------------- Web of Sci ---
def fetch_wos():
    """Return dict with 'h' and 'docs', or {} on any failure.

    Uses the Web of Science Starter API. h-index is not always exposed by the
    Starter tier; if only the document count is available, we return just that.
    """
    if not (WOS_API_KEY and WOS_AUTHOR_ID):
        log("WoS credentials missing -> skipping WoS (numbers left as-is).")
        return {}

    # Documents authored, via the Starter API documents endpoint.
    url = (
        "https://api.clarivate.com/apis/wos-starter/v1/documents"
        f"?q=AI=({WOS_AUTHOR_ID})&limit=1&page=1"
    )
    headers = {"X-ApiKey": WOS_API_KEY, "Accept": "application/json"}

    try:
        data = http_get_json(url, headers)
    except urllib.error.HTTPError as e:
        log(f"WoS HTTP {e.code}: {e.read().decode('utf-8', 'ignore')[:300]}")
        return {}
    except Exception as e:  # noqa: BLE001
        log(f"WoS request failed: {e}")
        return {}

    out = {}
    try:
        out["docs"] = int(data["metadata"]["total"])
        log(f"WoS -> docs={out['docs']}")
    except (KeyError, TypeError, ValueError) as e:
        log(f"WoS docs parse error: {e}")

    # h-index generally requires the Expanded API / Incites; leave to a secret
    # override if you have it precomputed.
    wos_h = os.environ.get("WOS_H_INDEX", "").strip()
    if wos_h.isdigit():
        out["h"] = int(wos_h)
        log(f"WoS -> h-index={out['h']} (from WOS_H_INDEX)")

    return out


# ---------------------------------------------------------- HTML rewrite ----
def replace_metric(html, element_id, new_value):
    """
    Replace the inner text of the FIRST element carrying id="element_id".
    Matches <... id="element_id" ...>OLD</...> and swaps only OLD.
    Returns (html, changed_bool).
    """
    pattern = re.compile(
        r'(id="' + re.escape(element_id) + r'"[^>]*>)(.*?)(</)',
        re.DOTALL,
    )

    def _sub(m):
        return f"{m.group(1)}{new_value}{m.group(3)}"

    new_html, n = pattern.subn(_sub, html, count=1)
    if n == 0:
        log(f"WARNING: id='{element_id}' not found; skipped.")
        return html, False
    return new_html, True


def main():
    if not os.path.exists(HTML_FILE):
        log(f"ERROR: {HTML_FILE} not found.")
        sys.exit(1)

    with open(HTML_FILE, "r", encoding="utf-8") as f:
        html = f.read()

    scopus = fetch_scopus()
    wos = fetch_wos()

    changed = False
    if "docs" in scopus:
        html, c = replace_metric(html, "scopus-docs", scopus["docs"]); changed |= c
    if "h" in scopus:
        html, c = replace_metric(html, "scopus-h", scopus["h"]); changed |= c
    if "docs" in wos:
        html, c = replace_metric(html, "wos-docs", wos["docs"]); changed |= c
    if "h" in wos:
        html, c = replace_metric(html, "wos-h", wos["h"]); changed |= c

    if changed:
        today = datetime.date.today().strftime("%d %b %Y")
        html, _ = replace_metric(html, "metrics-updated", today)
        with open(HTML_FILE, "w", encoding="utf-8") as f:
            f.write(html)
        log(f"index.html updated ({today}).")
    else:
        log("No metrics changed; file left untouched.")


if __name__ == "__main__":
    main()
