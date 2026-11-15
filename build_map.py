"""Bouwt de koppellijst tussen nederlandwereldwijd.nl en netherlandsworldwide.nl.

Uitvoer:
- docs/map.json          Nederlandse URL -> {en, es, fr, de}, voor de lookup-pagina
- docs/koppellijst.xlsx  Gekoppeld / Geen EN-versie / EN zonder NL-link / Meerdere EN naar 1 NL /
                         Te controleren / Info
- data/state.json        per Engelse URL: lastmod + vertalingen (voor incrementele runs)

Werkwijze:
1. Engelse sitemap -> Engelse pagina's ophalen -> `translations` uit de paginadata
   (alleen de Engelse pagina's bevatten de link naar de Nederlandse versie).
2. Nederlandse sitemaps -> alle Nederlandse pagina's (alleen sitemapbestanden, geen pagina's).
3. Vergelijken. Nederlandse links die niet in de Nederlandse sitemap staan, worden
   los gecontroleerd (verplaatst / niet gevonden / niet in sitemap / onduidelijk).
4. Engelse pagina's zonder NL-link (bijv. ambassadepagina's: geen vertaaldata) worden
   gekoppeld via data/handmatig.json of afgeleid uit de woorden van bestaande koppelingen.

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

# Sub-sitemaps eerst (die bepalen de kolom "sub-sitemap"), daarna de hoofdsitemap als vangnet
# voor sub-sitemaps die later bijkomen.
EN_SITEMAPS = [
    "https://www.netherlandsworldwide.nl/paginas/sitemap.xml",
    "https://www.netherlandsworldwide.nl/contact/embassies-consulates-general/sitemap.xml",
    "https://www.netherlandsworldwide.nl/sitemap.xml",
]
NL_SITEMAPS = [
    "https://www.nederlandwereldwijd.nl/paginas/sitemap.xml",
    "https://www.nederlandwereldwijd.nl/contact/ambassades-consulaten-generaal/sitemap.xml",
    "https://www.nederlandwereldwijd.nl/reisadvies/sitemap.xml",
    "https://www.nederlandwereldwijd.nl/sitemap.xml",
]
EN_BASE = "https://www.netherlandsworldwide.nl"
NL_BASE = "https://www.nederlandwereldwijd.nl"
OUT_MAP = "docs/map.json"
OUT_XLSX = "docs/koppellijst.xlsx"
STATE = "data/state.json"
MANUAL = "data/handmatig.json"
DELAY = float(os.getenv("DELAY", "1.0"))   # seconden tussen requests
FULL = os.getenv("FULL") == "1"
MIN_RATIO = 0.8                     # nieuwe kaart < 80% van de oude -> niet opslaan
MAX_FAIL_RATIO = 0.2                # >20% mislukte fetches -> afbreken
MAX_CHECKS = 500                    # max. aantal losse controles per run

NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
LANG_SUFFIX = re.compile(r"[./](es|fr|de)$")   # .../pagina.es én .../pagina/es
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


def sitemap_label(url: str) -> str:
    """https://…/contact/ambassades-consulaten-generaal/sitemap.xml -> 'contact/ambassades-consulaten-generaal'."""
    path = urlsplit(url).path.strip("/")
    label = path.rsplit("/", 1)[0] if "/" in path else ""
    return label or path or url


def sitemap_urls(url: str, out: dict, seen: set, counts: dict) -> None:
    """Voegt alle <loc> (met lastmod en sub-sitemap) toe aan out; volgt indexen recursief.
    Een URL houdt het label van de eerste sitemap waarin hij gevonden is."""
    if url in seen:
        return
    seen.add(url)
    root = ET.fromstring(get(url).content)
    for sm in root.findall("sm:sitemap", NS):
        sitemap_urls(sm.findtext("sm:loc", namespaces=NS).strip(), out, seen, counts)
    label = sitemap_label(url)
    n = 0
    for u in root.findall("sm:url", NS):
        loc = u.findtext("sm:loc", namespaces=NS).strip()
        if loc in out:
            continue
        lm = (u.findtext("sm:lastmod", default="", namespaces=NS) or "").strip()
        out[loc] = {"lastmod": lm, "source": label}
        n += 1
    if n:
        counts[label] = counts.get(label, 0) + n


def read_sitemaps(urls: list[str]) -> tuple[dict, dict]:
    """Leest de sub-sitemaps en als laatste de hoofdsitemap. Een ontbrekende sub-sitemap
    geeft een waarschuwing (de hoofdsitemap vangt dat op); een fout in de hoofdsitemap breekt af."""
    out, seen, counts = {}, set(), {}
    for i, url in enumerate(urls):
        try:
            sitemap_urls(url, out, seen, counts)
        except (ET.ParseError, RuntimeError) as e:
            if i == len(urls) - 1:
                raise
            print(f"  WAARSCHUWING: sitemap {url} niet leesbaar ({e}); hoofdsitemap vangt dit op")
    return out, counts


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


def path_of(url: str) -> str:
    return urlsplit(url).path.strip("/")


def segment_dictionary(cms_pairs: list[tuple[str, str]]) -> dict[str, str]:
    """EN-padsegment -> meest gebruikte NL-padsegment, geleerd uit CMS-koppelingen met even diepe paden."""
    counts: dict[str, dict[str, int]] = {}
    for en, nl in cms_pairs:
        a, b = path_of(en).split("/"), path_of(nl).split("/")
        if len(a) != len(b):
            continue
        for x, y in zip(a, b):
            counts.setdefault(x, {})
            counts[x][y] = counts[x].get(y, 0) + 1
    return {x: max(c, key=c.get) for x, c in counts.items()}


def derive(en_path: str, seg: dict, folders: dict) -> str:
    """Vertaalt een EN-pad naar een vermoedelijk NL-pad (map-vertalingen eerst, dan per segment)."""
    for en_dir, nl_dir in sorted(folders.items(), key=lambda kv: -len(kv[0])):
        if en_path == en_dir or en_path.startswith(en_dir + "/"):
            rest = en_path[len(en_dir):].strip("/")
            tail = "/".join(seg.get(x, x) for x in rest.split("/")) if rest else ""
            return f"{nl_dir}/{tail}".strip("/")
    return "/".join(seg.get(x, x) for x in en_path.split("/"))


def link(state: dict, nl_by_norm: dict, manual: dict) -> dict:
    """Koppelt Engelse aan Nederlandse pagina's.

    1. CMS: de NL-link uit de vertaaldata van de Engelse pagina.
    2. Voor Engelse pagina's zonder NL-link: handmatig (data/handmatig.json), anders afgeleid
       (pad vertaald met woorden uit de CMS-koppelingen). Alleen als de NL-pagina in de sitemap
       staat, nog niet via het CMS gekoppeld is, en precies één Engelse pagina erop uitkomt.
    """
    cms, missing = [], []
    for en_url in sorted(state):
        tr = state[en_url]["translations"]
        langs = {t["lang"]: t["link"] for t in tr if t.get("lang") and t.get("link")}
        nl = langs.pop("nl", None)
        langs.setdefault("en", en_url)
        if nl:
            cms.append((en_url, nl, langs))
        else:
            missing.append((en_url, "geen vertaaldata" if not tr else "geen NL-link in vertaaldata", langs))

    seg = segment_dictionary([(e, n) for e, n, _ in cms])
    folders = manual.get("mappen", {})
    pages = {k.strip("/"): v.strip("/") for k, v in manual.get("paginas", {}).items()}
    nl_host = urlsplit(NL_BASE).netloc.removeprefix("www.")
    cms_keys = {norm(n) for _, n, _ in cms}

    proposals = []                      # [en_url, reden, voorstel_url, bron, langs]
    for en_url, reason, langs in missing:
        p = path_of(en_url)
        target, src = (pages[p], "handmatig") if p in pages else (derive(p, seg, folders), "afgeleid")
        key = f"{nl_host}/{target}".rstrip("/") if target else f"{nl_host}/"
        if key in nl_by_norm and key not in cms_keys:
            proposals.append([en_url, reason, nl_by_norm[key][0], src, langs])
        else:
            proposals.append([en_url, reason, "", "", langs])

    claimed: dict[str, int] = {}
    for pr in proposals:
        if pr[2]:
            claimed[norm(pr[2])] = claimed.get(norm(pr[2]), 0) + 1
    for pr in proposals:                # twee EN-pagina's op dezelfde NL-pagina -> geen van beide
        if pr[2] and claimed[norm(pr[2])] > 1:
            pr[2], pr[3] = "", "dubbel, niet gekoppeld"

    links = [(e, n, l, "CMS") for e, n, l in cms]
    links += [(pr[0], pr[2], pr[4], pr[3]) for pr in proposals if pr[2]]
    return {"links": links, "proposals": proposals}


def load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def write_xlsx(pairs, gaps, en_missing, multi, checks, info):
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
          ["NL-pagina", "EN", "ES", "FR", "DE", "NL sub-sitemap", "Koppeling"], pairs,
          [60, 60, 45, 45, 45, 34, 12])
    sheet(wb.create_sheet(), "Geen EN-versie",
          ["NL-pagina", "NL sub-sitemap", "Laatst gewijzigd (sitemap)"], gaps, [70, 34, 26])
    sheet(wb.create_sheet(), "EN zonder NL-link",
          ["EN-pagina", "EN sub-sitemap", "Probleem", "Vermoedelijke NL-pagina", "Gevonden via"],
          en_missing, [70, 34, 26, 70, 22])
    sheet(wb.create_sheet(), "Meerdere EN naar 1 NL",
          ["NL-pagina", "Aantal EN-pagina's", "EN-pagina's"], multi, [60, 12, 120])
    sheet(wb.create_sheet(), "Te controleren",
          ["EN-pagina", "NL-link op EN-pagina", "Status", "Nieuwe NL-URL"], checks, [60, 60, 16, 60])
    sheet(wb.create_sheet(), "Info", ["Onderdeel", "Waarde"], info, [40, 60])
    wb.save(OUT_XLSX)


def main():
    state = load(STATE, {})
    old_map = load(OUT_MAP, {})
    manual = load(MANUAL, {})

    # 1. Engelse kant
    en_all, en_counts = read_sitemaps(EN_SITEMAPS)
    en_urls = {u: v for u, v in en_all.items() if not LANG_SUFFIX.search(urlsplit(u).path)}
    print(f"EN-sitemaps: {len(en_all)} URL's, waarvan {len(en_urls)} Engels; per sitemap {en_counts}")
    if not en_urls:
        sys.exit("Geen Engelse URL's in de sitemap gevonden - afgebroken.")

    # 2. Nederlandse kant (alleen sitemap)
    nl_all, nl_counts = read_sitemaps(NL_SITEMAPS)
    nl_by_norm = {norm(u): (u, v) for u, v in nl_all.items()}
    print(f"NL-sitemaps: {len(nl_all)} URL's; per sitemap {nl_counts}")
    if not nl_all:
        sys.exit("Geen Nederlandse URL's in de sitemap gevonden - afgebroken.")

    self_test()

    todo = [u for u, v in en_urls.items()
            if FULL or u not in state or state[u].get("lastmod") != v["lastmod"] or not v["lastmod"]]
    print(f"Op te halen: {len(todo)}")

    # Pagina's die vorige keer ook al geen vertaaldata hadden (o.a. de ambassadepagina's, die
    # zonder lastmod elke run opnieuw opgehaald worden) tellen niet mee voor de structuurcheck.
    known_empty = {u for u in todo if u in state and not state[u].get("translations")}
    fails = no_data = no_data_new = 0
    for i, u in enumerate(todo, 1):
        try:
            r = get(u)
            if r.status_code != 200:
                raise RuntimeError(r.status_code)
            tr = parse_translations(r.text)
            if tr is None:
                no_data += 1
                no_data_new += u not in known_empty
            state[u] = {"lastmod": en_urls[u]["lastmod"], "translations": tr or []}
        except Exception as e:  # noqa: BLE001
            fails += 1
            print(f"  FOUT {u}: {e}")
        if i % 100 == 0:
            print(f"  {i}/{len(todo)} (fouten: {fails}, zonder vertaaldata: {no_data})")
        time.sleep(DELAY)

    if todo and fails / len(todo) > MAX_FAIL_RATIO:
        sys.exit(f"{fails}/{len(todo)} fetches mislukt - mogelijk geblokkeerd. Niets opgeslagen.")
    n_check = len(todo) - len(known_empty)
    if n_check >= 20 and no_data_new / n_check > 0.9:
        sys.exit(f"Bij {no_data_new}/{n_check} pagina's geen vertaaldata gevonden - "
                 "paginastructuur veranderd? Niets opgeslagen.")

    state = {u: v for u, v in state.items() if u in en_urls}

    # 3. Koppelen en controleren
    result = link(state, nl_by_norm, manual)
    new_map, pairs, checks = {}, [], []
    by_nl: dict[str, list[str]] = {}
    n_checked = 0
    for en_url, nl, langs, how in result["links"]:
        key = norm(nl)
        new_map[key] = langs
        nl_url = nl
        if key not in nl_by_norm:               # alleen mogelijk bij CMS-links
            if n_checked < MAX_CHECKS:
                status, target = check_url(nl)
                n_checked += 1
                time.sleep(DELAY)
            else:
                status, target = "onduidelijk", "niet gecontroleerd (limiet)"
            checks.append([en_url, nl, status, target])
            if status == "niet gevonden":
                del new_map[key]                # geen geldige koppeling; staat alleen bij Te controleren
                continue
            if status == "verplaatst" and target:
                new_map[norm(target)] = langs   # nieuwe URL werkt ook in de bookmarklet
                nl_url = target
        by_nl.setdefault(norm(nl_url), []).append(en_url)
        src = nl_by_norm.get(norm(nl_url), (None, {}))[1].get("source", "")
        pairs.append([nl_url, langs.get("en", ""), langs.get("es", ""),
                      langs.get("fr", ""), langs.get("de", ""), src, how])

    if old_map and len(new_map) < MIN_RATIO * len(old_map):
        sys.exit(f"Nieuwe kaart ({len(new_map)}) veel kleiner dan oude ({len(old_map)}) - niets opgeslagen.")

    gaps = [[u, v["source"], v["lastmod"]]
            for k, (u, v) in sorted(nl_by_norm.items()) if k not in new_map]
    en_missing = [[en, en_urls[en]["source"], reason, nl or "geen NL-pagina gevonden", how]
                  for en, reason, nl, how, _ in result["proposals"]]
    multi = [[nl_by_norm.get(k, (k, {}))[0], len(v), "\n".join(sorted(v))]
             for k, v in sorted(by_nl.items()) if len(v) > 1]
    hows = {}
    for p in pairs:
        hows[p[6]] = hows.get(p[6], 0) + 1

    now = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M %Z")
    info = [
        ["Bijgewerkt", now],
        ["Engelse pagina's in sitemaps (alleen EN, zonder ES/FR/DE)", len(en_urls)],
        *[[f"  EN sub-sitemap: {k}", v] for k, v in sorted(en_counts.items())],
        ["Nederlandse pagina's in sitemaps", len(nl_all)],
        *[[f"  NL sub-sitemap: {k}", v] for k, v in sorted(nl_counts.items())],
        ["Gekoppeld (rijen)", len(pairs)],
        *[[f"  koppeling: {k}", v] for k, v in sorted(hows.items())],
        ["Geen EN-versie", len(gaps)],
        ["EN zonder NL-link in CMS", len(en_missing)],
        ["NL-pagina's met meerdere EN-pagina's", len(multi)],
        ["Te controleren", len(checks)],
        ["Opgehaald deze run", len(todo)],
        ["Mislukt deze run", fails],
        ["Let op", "'Geen EN-versie' = geen Engelse pagina in de sitemap die naar deze "
                   "pagina linkt. Pagina's met alleen ES/FR/DE vallen hier ook onder."],
        ["Koppeling", "CMS = NL-link staat op de Engelse pagina. afgeleid/handmatig = de Engelse "
                      "pagina mist de NL-link; koppeling vermoed (zie tabblad 'EN zonder NL-link')."],
    ]

    os.makedirs("data", exist_ok=True)
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=0, sort_keys=True)
    with open(OUT_MAP, "w", encoding="utf-8") as f:
        json.dump(new_map, f, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    write_xlsx(pairs, gaps, en_missing, multi, checks, info)

    counts = {}
    for c in checks:
        counts[c[2]] = counts.get(c[2], 0) + 1
    print(f"Klaar: {len(pairs)} gekoppeld {hows}, {len(gaps)} zonder EN-versie, "
          f"{len(en_missing)} EN zonder NL-link, {len(checks)} te controleren {counts} "
          f"(fouten: {fails}, zonder vertaaldata: {no_data})")


if __name__ == "__main__":
    main()
