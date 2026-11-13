"""Bouwt de koppellijst tussen nederlandwereldwijd.nl en netherlandsworldwide.nl.

Uitvoer:
- docs/map.json          Nederlandse URL -> {en, es, fr, de}, voor de lookup-pagina
- docs/koppellijst.xlsx  Gekoppeld / Geen EN-versie / Te controleren / Info
- data/state.json        per Engelse URL: lastmod + vertalingen (voor incrementele runs)

Werkwijze:
1. Engelse sitemap -> Engelse pagina's ophalen -> `translations` uit de paginadata
   (alleen de Engelse pagina's bevatten de link naar de Nederlandse versie).
2. Nederlandse sitemap -> alle Nederlandse pagina's (alleen sitemapbestanden, geen pagina's).
3. Vergelijken. Nederlandse links die niet in de Nederlandse sitemap staan, worden
   los gecontroleerd (verplaatst / niet gevonden / niet in sitemap / onduidelijk).

Incrementeel: alleen Engelse pagina's waarvan <lastmod> veranderd is worden opnieuw
opgehaald. Zet FULL=1 voor een volledige run.
"""
import html as htmllib
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit

import requests

EN_SITEMAP = "https://www.netherlandsworldwide.nl/sitemap.xml"
NL_SITEMAP = "https://www.nederlandwereldwijd.nl/sitemap.xml"
EN_BASE = "https://www.netherlandsworldwide.nl"
NL_BASE = "https://www.nederlandwereldwijd.nl"
OUT_MAP = "docs/map.json"
OUT_XLSX = "docs/koppellijst.xlsx"
STATE = "data/state.json"
DELAY = float(os.getenv("DELAY", "1.0"))   # seconden tussen requests
FULL = os.getenv("FULL") == "1"
MIN_RATIO = 0.8                     # nieuwe kaart < 80% van de oude -> niet opslaan
MAX_FAIL_RATIO = 0.2                # >20% mislukte fetches -> afbreken
MAX_CHECKS = 500                    # max. aantal losse controles per run

NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
LANG_SUFFIX = re.compile(r"\.(es|fr|de)$")
TRANSLATIONS = re.compile(r'translations\\?":(\[.*?\])')
CANONICAL = re.compile(r'<link[^>]+rel="canonical"[^>]+href="([^"]+)"', re.I)
META_REFRESH = re.compile(r'<meta[^>]+http-equiv="refresh"[^>]+content="[^"]*url=([^"]+)"', re.I)
NEXT_REDIRECT = re.compile(r'NEXT_REDIRECT;[a-z]+;([^;"\\]+);')
NOT_FOUND = "pagina-niet-gevonden"

session = requests.Session()
session.headers["User-Agent"] = "Mozilla/5.0 (nww-taalwissel; editor tool)"


def norm(url: str) -> str:
    """Zelfde normalisatie als in docs/index.html."""
    p = urlsplit(url.strip())
    host = p.netloc.lower().removeprefix("www.")
    path = p.path.rstrip("/") or "/"
    return f"{host}{path}"


def get(url: str) -> requests.Response:
    for attempt in range(3):
        try:
            r = session.get(url, timeout=30)
            if r.status_code in (429, 503):
                time.sleep(10 * (attempt + 1))
                continue
            return r
        except requests.RequestException:
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"fetch mislukt: {url}")


def sitemap_urls(url: str, source: str = "") -> dict[str, dict]:
    """Alle <loc> met lastmod en de sub-sitemap waar ze in staan; volgt indexen recursief."""
    root = ET.fromstring(get(url).content)
    out = {}
    for sm in root.findall("sm:sitemap", NS):
        loc = sm.findtext("sm:loc", namespaces=NS).strip()
        out.update(sitemap_urls(loc, urlsplit(loc).path.rsplit("/", 1)[-1]))
    for u in root.findall("sm:url", NS):
        loc = u.findtext("sm:loc", namespaces=NS).strip()
        lm = (u.findtext("sm:lastmod", default="", namespaces=NS) or "").strip()
        out[loc] = {"lastmod": lm, "source": source or urlsplit(url).path.rsplit("/", 1)[-1]}
    return out


def parse_translations(page: str) -> list[dict] | None:
    """Leest de translations-lijst uit de paginadata. None = niet gevonden."""
    m = TRANSLATIONS.search(page)
    if not m:
        return None
    try:
        items = json.loads(m.group(1).replace('\\"', '"'))
    except json.JSONDecodeError:
        return None
    out = []
    for it in items:
        link = it.get("link", "")
        if link.startswith("/"):
            link = EN_BASE + link
        out.append({"lang": it.get("lang"), "link": link})
    return out


def check_url(url: str) -> tuple[str, str]:
    """Wat doet de site met deze URL? -> (status, nieuwe URL of '')."""
    try:
        r = get(url)
    except RuntimeError:
        return "onduidelijk", ""
    final = r.url
    page = r.text if "html" in r.headers.get("content-type", "html") else ""
    canon = CANONICAL.search(page)
    canon = htmllib.unescape(canon.group(1)) if canon else ""

    if r.status_code == 404 or NOT_FOUND in final or NOT_FOUND in canon:
        return "niet gevonden", ""
    if r.history and norm(final) != norm(url):
        return "verplaatst", final
    for rx in (META_REFRESH, NEXT_REDIRECT):
        m = rx.search(page)
        if m:
            target = urljoin(url, htmllib.unescape(m.group(1).strip()))
            if NOT_FOUND in target:
                return "niet gevonden", ""
            return "verplaatst", target
    if r.status_code == 200 and canon and norm(canon) != norm(url):
        return "verplaatst", canon
    if r.status_code == 200:
        return "niet in sitemap", ""
    return "onduidelijk", f"HTTP {r.status_code}"


def self_test():
    """Laat in het log zien hoe de site een niet-bestaande pagina afhandelt."""
    test = NL_BASE + "/bestaat-niet-taalwissel-test-123"
    try:
        r = get(test)
        canon = CANONICAL.search(r.text)
        print(f"Zelftest niet-bestaande pagina: HTTP {r.status_code}, eind-URL {r.url}, "
              f"canonical {canon.group(1) if canon else '-'} -> {check_url(test)[0]}")
    except RuntimeError as e:
        print(f"Zelftest mislukt: {e}")


def load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def write_xlsx(pairs, gaps, checks, info):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    head_font = Font(bold=True, color="FFFFFF")
    head_fill = PatternFill("solid", fgColor="154273")
    link_font = Font(color="01689B", underline="single")

    def sheet(ws, title, headers, rows, widths):
        ws.title = title
        ws.append(headers)
        for c in ws[1]:
            c.font, c.fill = head_font, head_fill
        for row in rows:
            ws.append(row)
        for row in ws.iter_rows(min_row=2):
            for c in row:
                if isinstance(c.value, str) and c.value.startswith("http"):
                    c.hyperlink, c.font = c.value, link_font
        for i, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = w
        ws.freeze_panes = "A2"
        if rows:
            ws.auto_filter.ref = ws.dimensions

    sheet(wb.active, "Gekoppeld",
          ["NL-pagina", "EN", "ES", "FR", "DE", "NL sub-sitemap"], pairs, [60, 60, 45, 45, 45, 28])
    sheet(wb.create_sheet(), "Geen EN-versie",
          ["NL-pagina", "NL sub-sitemap", "Laatst gewijzigd (sitemap)"], gaps, [70, 28, 26])
    sheet(wb.create_sheet(), "Te controleren",
          ["EN-pagina", "NL-link op EN-pagina", "Status", "Nieuwe NL-URL"], checks, [60, 60, 16, 60])
    sheet(wb.create_sheet(), "Info", ["Onderdeel", "Waarde"], info, [40, 60])
    wb.save(OUT_XLSX)


def main():
    state = load(STATE, {})
    old_map = load(OUT_MAP, {})

    # 1. Engelse kant
    en_all = sitemap_urls(EN_SITEMAP)
    en_urls = {u: v for u, v in en_all.items() if not LANG_SUFFIX.search(urlsplit(u).path)}
    print(f"EN-sitemap: {len(en_all)} URL's, waarvan {len(en_urls)} Engels")
    if not en_urls:
        sys.exit("Geen Engelse URL's in de sitemap gevonden - afgebroken.")

    # 2. Nederlandse kant (alleen sitemap)
    nl_all = sitemap_urls(NL_SITEMAP)
    nl_by_norm = {norm(u): (u, v) for u, v in nl_all.items()}
    print(f"NL-sitemap: {len(nl_all)} URL's")
    if not nl_all:
        sys.exit("Geen Nederlandse URL's in de sitemap gevonden - afgebroken.")

    self_test()

    todo = [u for u, v in en_urls.items()
            if FULL or u not in state or state[u].get("lastmod") != v["lastmod"] or not v["lastmod"]]
    print(f"Op te halen: {len(todo)}")

    fails = no_data = 0
    for i, u in enumerate(todo, 1):
        try:
            r = get(u)
            if r.status_code != 200:
                raise RuntimeError(r.status_code)
            tr = parse_translations(r.text)
            if tr is None:
                no_data += 1
            state[u] = {"lastmod": en_urls[u]["lastmod"], "translations": tr or []}
        except Exception as e:  # noqa: BLE001
            fails += 1
            print(f"  FOUT {u}: {e}")
        if i % 100 == 0:
            print(f"  {i}/{len(todo)} (fouten: {fails}, zonder vertaaldata: {no_data})")
        time.sleep(DELAY)

    if todo and fails / len(todo) > MAX_FAIL_RATIO:
        sys.exit(f"{fails}/{len(todo)} fetches mislukt - mogelijk geblokkeerd. Niets opgeslagen.")
    if len(todo) >= 20 and no_data / len(todo) > 0.9:
        sys.exit(f"Bij {no_data}/{len(todo)} pagina's geen vertaaldata gevonden - "
                 "paginastructuur veranderd? Niets opgeslagen.")

    state = {u: v for u, v in state.items() if u in en_urls}

    # 3. Koppelen en controleren
    new_map, pairs, checks = {}, [], []
    n_checked = 0
    for en_url in sorted(state):
        langs = {t["lang"]: t["link"] for t in state[en_url]["translations"]
                 if t.get("lang") and t.get("link")}
        nl = langs.pop("nl", None)
        if not nl:
            continue
        langs.setdefault("en", en_url)
        key = norm(nl)
        new_map[key] = langs
        nl_url = nl
        if key not in nl_by_norm:
            if n_checked < MAX_CHECKS:
                status, target = check_url(nl)
                n_checked += 1
                time.sleep(DELAY)
            else:
                status, target = "onduidelijk", "niet gecontroleerd (limiet)"
            checks.append([en_url, nl, status, target])
            if status == "niet gevonden":
                continue                        # geen geldige koppeling; staat alleen bij Te controleren
            if status == "verplaatst" and target:
                new_map[norm(target)] = langs   # nieuwe URL werkt ook in de bookmarklet
                nl_url = target
        src = nl_by_norm.get(norm(nl_url), (None, {}))[1].get("source", "")
        pairs.append([nl_url, langs.get("en", ""), langs.get("es", ""),
                      langs.get("fr", ""), langs.get("de", ""), src])

    if old_map and len(new_map) < MIN_RATIO * len(old_map):
        sys.exit(f"Nieuwe kaart ({len(new_map)}) veel kleiner dan oude ({len(old_map)}) - niets opgeslagen.")

    gaps = [[u, v["source"], v["lastmod"]]
            for k, (u, v) in sorted(nl_by_norm.items()) if k not in new_map]

    now = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M %Z")
    info = [
        ["Bijgewerkt", now],
        ["Engelse pagina's in sitemap", len(en_urls)],
        ["Nederlandse pagina's in sitemap", len(nl_all)],
        ["Gekoppeld", len(pairs)],
        ["Geen EN-versie", len(gaps)],
        ["Te controleren", len(checks)],
        ["Opgehaald deze run", len(todo)],
        ["Mislukt deze run", fails],
        ["Let op", "'Geen EN-versie' = geen Engelse pagina in de sitemap die naar deze "
                   "pagina linkt. Pagina's met alleen ES/FR/DE vallen hier ook onder."],
    ]

    os.makedirs("data", exist_ok=True)
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=0, sort_keys=True)
    with open(OUT_MAP, "w", encoding="utf-8") as f:
        json.dump(new_map, f, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    write_xlsx(pairs, gaps, checks, info)

    counts = {}
    for c in checks:
        counts[c[2]] = counts.get(c[2], 0) + 1
    print(f"Klaar: {len(pairs)} gekoppeld, {len(gaps)} zonder EN-versie, "
          f"{len(checks)} te controleren {counts} (fouten: {fails}, zonder vertaaldata: {no_data})")


if __name__ == "__main__":
    main()
