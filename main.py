#!/usr/bin/env python3
"""
Daily sentiment report - single self-contained file (Windows, .py or Jupyter)
============================================================================

Uses the same search and positive/negative logic as Counterparty Search
(crd_collector.py + ui.html), copied into this one file, so nothing else is needed
except:   pip install requests beautifulsoup4

For each keyword it searches Google News, Bing News and GDELT, keeps articles
published in the last 24 hours, reads the article pages it can open, and prints
an HTML report page (opened in your browser) plus a console summary: search key
points, number of NEGATIVE and POSITIVE articles, and the references (links).
Main search: your ResouX API (RESOUX_URL / RESOUX_KEY below), then the news feeds.
Files go to the "reports" folder (.html, .txt, .csv).

Jupyter: paste into a cell and run (or call run_once(["Name 1", "Name 2"])).
Command Prompt:
    python daily_report.py                         run once now
    python daily_report.py --keyword "Some Name"   another keyword
    python daily_report.py --daily 08:00           keep running, report every day at 08:00
    python daily_report.py --install-task 08:00    let Windows run it every day at 08:00
    python daily_report.py --remove-task           remove that task
"""
import argparse
import concurrent.futures as cf
import csv
import datetime as dt
import email.utils
import json
import os
import random
import re
import sys
import time
import urllib.parse
from xml.etree import ElementTree as ET

import html
import webbrowser

import requests
from bs4 import BeautifulSoup

# =================================================================== SETTINGS ===
KEYWORDS = ["Donald Trump"]                            # add more: ["Donald Trump", "Rolls-Royce"]

# Main search: your ResouX API
RESOUX_URL = "https://sourcefolio-resource-desk.olya-chambers.chatgpt.site/api/resoux"
RESOUX_KEY = os.environ.get("RESOUX_KEY", "ceff4ae5bbe86f92750bff38cde58f9c0f846b3e")
RESOUX_SHOW_RAW = False                                # True = print the API's raw answer (for checking)

# ResouX runs first, then these news sources (set to [] to use ResouX only)
SOURCES = ["resoux", "google_news", "bing_news", "duckduckgo_web", "deep_news_sites", "deep_web_sites", "gdelt_news"]

# Deep search: each site is searched separately (site:...) so it is not crowded out by bigger sources
DEEP_NEWS_SITES = ["bloomberg.com", "reuters.com", "ft.com", "wsj.com", "cnbc.com", "bbc.co.uk",
                   "theguardian.com", "apnews.com", "politico.com", "nytimes.com"]   # via Google News (dated)
DEEP_WEB_SITES = ["linkedin.com", "x.com", "reddit.com", "youtube.com"]           # via DuckDuckGo, past day
OPEN_REPORT = True                                     # open the HTML report in your browser when done
FETCH_ARTICLES = True                                  # read article pages for better sentiment
MAX_FETCH = 60                                         # max article pages read per keyword
REPORT_DIR = "reports"                                 # folder for saved .txt / .csv copies
TASK_NAME = "Daily Sentiment Report"                   # name used in Windows Task Scheduler
# ==============================================================================

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/129.0 Safari/537.36")
PAYWALL_HINTS = ("subscribe to read", "subscribers only", "for subscribers", "to continue reading",
                 "sign in to read", "create a free account to", "reached the maximum number of")
try:
    THIS_FILE = os.path.abspath(__file__)
except NameError:          # Jupyter
    THIS_FILE = None
HERE = os.path.dirname(THIS_FILE) if THIS_FILE else os.getcwd()


def log(msg):
    print(f"[{dt.datetime.now():%H:%M:%S}] {msg}", flush=True)


def domain(url):
    try:
        h = (urllib.parse.urlsplit(url).hostname or "").lower()
        return h[4:] if h.startswith("www.") else h
    except ValueError:
        return ""


# ------------------------------------------------ sentiment (from ui.html) ----
NEG_STRONG = ["appointment of administrators", "administrators appointed", "administrator", "administrators", "administration",
    "winding up", "winding-up", "wound up", "liquidation", "liquidator", "liquidators", "receivership", "receivers appointed",
    "strike off", "struck off", "dissolved", "winding up petition", "county court judgment", "ccj", "creditors' voluntary",
    "company voluntary arrangement", "disqualified", "disqualification", "fraud", "fraudulent", "scandal", "bankrupt", "bankruptcy",
    "insolvency", "insolvent", "administration order", "collapse", "collapsed",
    "lawsuit", "class action", "sued", "sues", "indicted", "indictment", "convicted", "guilty", "fined", "penalty", "penalties",
    "sanctioned", "sanctions", "money laundering", "bribery", "bribe", "corruption", "embezzlement", "scam", "data breach",
    "cyberattack", "ransomware", "hacked", "recall", "recalls", "defaulted", "default", "probe", "investigation", "investigated",
    "raid", "raided", "layoffs", "laid off", "job cuts", "axe", "axes", "to cut jobs", "profit warning",
    "misconduct", "harassment", "discrimination", "pollution", "spill", "fatal", "fatalities", "explosion", "whistleblower",
    "wrongdoing", "negligence", "violation", "violations", "ban", "banned", "crisis", "controversy", "boycott", "rip-off", "ripoff",
    "writedown", "write-down", "impairment", "plunge", "plunges", "plummets", "slump", "slumps", "tumble", "tumbles", "downgrade",
    "downgraded", "loss-making", "fake", "deceptive", "misleading", "misled", "accused", "alleged", "allegedly", "allegations"]
NEG = ["loss", "losses", "decline", "declines", "declined", "falls", "fell", "fall", "drop", "drops", "dropped", "slips", "slipped",
    "slides", "slid", "sheds", "shed", "underperforms", "underperform", "lower", "down", "cut", "cuts", "weak", "weaker", "warning",
    "warns", "concern", "concerns", "risk", "risks", "delay", "delays", "delayed", "shortfall", "complaint", "complaints",
    "criticised", "criticized", "criticism", "backlash", "struggle", "struggles", "struggling", "suspended", "suspension",
    "resigns", "resigned", "ousted", "fired", "strike", "strikes", "outage", "disruption", "problems", "problem", "failure",
    "failed", "fails", "poor", "terrible", "awful", "worst", "disappointed", "disappointing", "unreliable", "rude", "refund",
    "cancelled", "canceled", "woes", "hamper", "hampered", "challenges", "challenging", "debt", "deficit", "burning platform"]
POS_STRONG = ["record profit", "record revenue", "award", "awarded", "wins", "won", "breakthrough", "milestone", "acclaimed",
    "outstanding", "excellent", "exonerated", "acquitted", "beats expectations", "beat expectations", "upgraded", "upgrade",
    "turnaround", "surges", "surge", "soars", "soar"]
POS = ["growth", "grew", "grows", "grow", "record", "profit", "profits", "profitable", "beat", "beats", "exceeds", "exceeded",
    "rally", "gains", "gain", "rise", "rises", "rose", "climbs", "climbed", "outpaces", "outpaced", "supports", "jumps", "jumped",
    "advances", "advanced", "outperforms", "outperform", "win", "contract", "deal", "order", "orders", "partnership", "partners",
    "expands", "expansion", "expand", "launch", "launches", "launched", "innovative", "innovation", "strong", "robust", "success",
    "successful", "praised", "praise", "great", "recommend", "recommended", "reliable", "best", "leader", "leading", "approval",
    "approved", "investment", "invest", "invests", "boost", "boosts", "boosting", "funding", "dividend", "buyback", "upbeat",
    "optimistic", "recovery", "rebound", "confidence", "demand", "on course", "in line with expectations", "thrived", "thriving",
    "benefited"]
NEGATORS = re.compile(r"\b(not|no|never|without|denies|denied|deny|rejects|rejected|dismissed|cleared of|free of)\b[^.]{0,22}$", re.I)


def _lexicon():
    lex = [(t, -2) for t in NEG_STRONG] + [(t, -1) for t in NEG] + [(t, 2) for t in POS_STRONG] + [(t, 1) for t in POS]
    lex.sort(key=lambda x: -len(x[0]))
    out = []
    for t, w in lex:
        pat = re.escape(t).replace(r"\ ", " ").replace(" ", r"[\s-]+")
        out.append((t, w, re.compile(r"(^|[^a-z0-9])(" + pat + r")(?=$|[^a-z0-9])", re.I)))
    return out


LEX = _lexicon()
SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"“‘(])")


def sentences(text):
    return [s for s in SENT_SPLIT.split(re.sub(r"\s+", " ", text or "")) if len(s) > 3]


def score_text(text, subject_re):
    sents = sentences(text)
    pos = neg = 0.0
    hits = []
    for si, s in enumerate(sents):
        low = s.lower()
        weight = 0.5 if (subject_re and not subject_re.search(s) and len(sents) > 3) else 1
        for term, w, rx in LEX:
            at = 0
            while True:
                m = rx.search(low, at)
                if not m:
                    break
                start, end = m.start(2), m.end(2)
                negated = NEGATORS.search(low[max(0, start - 30):start])
                low = low[:start] + " " * (end - start) + low[end:]  # mask so shorter terms don't re-match
                at = end
                if negated:
                    hits.append({"term": term, "w": 0, "si": si, "negated": True})
                    continue
                ww = w * weight
                if ww > 0:
                    pos += ww
                else:
                    neg += -ww
                hits.append({"term": term, "w": ww, "si": si})
    return pos, neg, hits, sents


def depth_of(r):
    c, s = (r.get("content") or "").strip(), (r.get("snippet") or "").strip()
    if (r.get("content_status") == "full" and len(c) >= 400) or len(c) >= 600:
        return "full"
    if len(c) >= 200:
        return "partial"
    if len(s) >= 50 or len(c) >= 50:
        return "snippet"
    return "headline"


def subject_regex(name):
    words = [w for w in re.split(r"\s+", name.strip()) if w]
    return re.compile(r"[\s\-]+".join(re.escape(w) for w in words), re.I) if words else None


def analyse(r, subject_re):
    text = ". ".join(x for x in (r.get("title"), r.get("snippet"), r.get("content")) if x)
    depth = depth_of(r)
    pos, neg, hits, sents = score_text(text, subject_re)
    total = pos + neg
    if total == 0:
        sentiment = "unclear" if depth == "headline" else "neutral"
    elif pos > 0 and neg > 0 and min(pos, neg) / max(pos, neg) >= 0.45:
        sentiment = "mixed"
    else:
        sentiment = "positive" if pos > neg else "negative"
    margin = abs(pos - neg) / total if total else 0
    conf = "Low"
    if depth == "full":
        conf = "High" if total >= 4 and (margin >= 0.5 or sentiment == "mixed") else "Medium" if total >= 2 else "Low"
    elif depth in ("partial", "snippet"):
        conf = "Medium" if total >= 3 and margin >= 0.6 else "Low"
    if sentiment == "neutral" and depth == "full":
        conf = "Medium"
    uniq = lambda xs: list(dict.fromkeys(xs))  # noqa: E731
    strongest = sorted([h for h in hits if not h.get("negated")], key=lambda h: -abs(h["w"]))
    evidence = sents[strongest[0]["si"]] if strongest else ""
    if len(evidence) > 280:
        evidence = evidence[:277] + "…"
    return {
        "sentiment": sentiment, "confidence": conf, "depth": depth,
        "pos_score": round(pos, 1), "neg_score": round(neg, 1),
        "pos_terms": uniq(h["term"] for h in hits if h["w"] > 0),
        "neg_terms": uniq(h["term"] for h in hits if h["w"] < 0),
        "evidence": evidence,
    }


# ------------------------------------------------ search (from crd_collector) ----
def _rss_items(content):
    return ET.fromstring(content).iter("item")


def _child(el, suffix):
    for c in el:
        if c.tag == suffix or c.tag.endswith("}" + suffix):
            return c
    return None


def _text(el):
    return (el.text or "").strip() if el is not None else ""


def _strip_html(s):
    return BeautifulSoup(s or "", "html.parser").get_text(" ", strip=True)


def google_news(keyword, extra=""):
    query = f'"{keyword}" {extra} when:1d'.replace("  ", " ")
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": query, "hl": "en-GB", "gl": "GB", "ceid": "GB:en"})
    r = requests.get(url, headers={"User-Agent": UA}, timeout=25)
    if r.status_code != 200:
        return query, f"HTTP {r.status_code}", []
    items = []
    for it in _rss_items(r.content):
        title, src = _text(_child(it, "title")), _child(it, "source")
        pub = _text(src)
        if pub and title.endswith(" - " + pub):
            title = title[: -len(pub) - 3].strip()
        desc = _strip_html(_text(_child(it, "description")))
        if desc.startswith(title) or len(desc) < 25:
            desc = ""
        items.append({"url": _text(_child(it, "link")), "title": title, "snippet": desc,
                      "publisher": pub, "date_text": _text(_child(it, "pubDate")),
                      "site": domain(src.get("url", "")) if src is not None else ""})
    return query, "ok", items


def bing_news(keyword):
    query = f'"{keyword}"'
    params = {"q": query, "format": "rss", "count": "50", "setlang": "en", "qft": 'interval="7"'}
    r = requests.get("https://www.bing.com/news/search?" + urllib.parse.urlencode(params),
                     headers={"User-Agent": UA}, timeout=25)
    if r.status_code != 200:
        return query, f"HTTP {r.status_code}", []
    if b"<rss" not in r.content[:2000]:
        return query, "no RSS feed returned (consent or verification page)", []
    items = []
    for it in _rss_items(r.content):
        link = _text(_child(it, "link"))
        if "apiclick.aspx" in link:
            link = urllib.parse.parse_qs(urllib.parse.urlsplit(link).query).get("url", [link])[0]
        items.append({"url": link, "title": _text(_child(it, "title")),
                      "snippet": _strip_html(_text(_child(it, "description"))),
                      "publisher": _text(_child(it, "Source")) or domain(link),
                      "date_text": _text(_child(it, "pubDate"))})
    return query, "ok", items


def gdelt_news(keyword):
    query = f'"{keyword}" sourcelang:english'
    end = dt.datetime.now(dt.timezone.utc)
    params = {"query": query, "mode": "ArtList", "maxrecords": "75", "format": "json", "sort": "DateDesc",
              "startdatetime": (end - dt.timedelta(hours=24)).strftime("%Y%m%d%H%M%S"),
              "enddatetime": end.strftime("%Y%m%d%H%M%S")}
    global GDELT_BLOCKED
    if GDELT_BLOCKED:
        return query, "skipped (GDELT rate-limited earlier in this run)", []
    for attempt in range(2):  # GDELT allows about one request every 5 seconds: one short retry, then move on
        r = requests.get("https://api.gdeltproject.org/api/v2/doc/doc", params=params,
                         headers={"User-Agent": UA}, timeout=20)
        if r.status_code != 429:
            break
        if attempt == 0:
            log("GDELT is busy (HTTP 429), trying once more in 6 s")
            time.sleep(6)
    if r.status_code == 429:
        GDELT_BLOCKED = True
        log("GDELT is still rate-limiting - skipped for this run, continuing with the other sources")
        return query, "HTTP 429 (GDELT rate-limited this computer - skipped; it usually clears within an hour)", []
    if r.status_code != 200:
        return query, f"HTTP {r.status_code}", []
    txt = r.text.strip()
    if not txt.startswith("{"):
        return query, "GDELT: " + txt[:120], []
    items = []
    for a in json.loads(txt).get("articles", []):
        sd = a.get("seendate", "")  # e.g. 20261014T153000Z
        when = ""
        if len(sd) >= 15:
            when = email.utils.format_datetime(dt.datetime.strptime(sd[:15], "%Y%m%dT%H%M%S")
                                               .replace(tzinfo=dt.timezone.utc))
        if a.get("url", "").startswith("http"):
            items.append({"url": a["url"], "title": a.get("title", ""), "snippet": "",
                          "publisher": a.get("domain", ""), "date_text": when})
    return query, "ok", items


# ------------------------------------------------------------ deep search ----
def website(r):
    """The real website of a result (Google News links point to news.google.com)."""
    return r.get("site") or domain(r["url"])


def site_name(d):
    """bloomberg.com -> Bloomberg, linkedin.com -> LinkedIn"""
    special = {"linkedin.com": "LinkedIn", "x.com": "X (Twitter)", "youtube.com": "YouTube", "ft.com": "Financial Times",
               "wsj.com": "Wall Street Journal", "cnbc.com": "CNBC", "bbc.co.uk": "BBC", "apnews.com": "AP News",
               "nytimes.com": "New York Times", "theguardian.com": "The Guardian", "reddit.com": "Reddit"}
    return special.get(d, d.split(".")[0].capitalize())


def deep_news_sites(keyword):
    """Google News feed restricted to each chosen news site (site:bloomberg.com ...), last 24 hours."""
    queries, items, counts = [], [], []
    for site in DEEP_NEWS_SITES:
        try:
            q_, status, found = google_news(keyword, f"site:{site}")
        except (requests.RequestException, ET.ParseError) as e:
            q_, status, found = f'"{keyword}" site:{site} when:1d', f"failed ({type(e).__name__})", []
        queries.append(q_)
        for it in found:
            it["found_via"] = f"{site_name(site)} (deep search)"
        items += found
        counts.append(f"{site_name(site)} {len(found) if status == 'ok' else status}")
        time.sleep(1)
    return queries, "ok", items, ", ".join(counts)


def _ddg(query):
    """DuckDuckGo web results limited to the past day (df=d). Returns (status, items)."""
    r = requests.post("https://html.duckduckgo.com/html/", data={"q": query, "kl": "wt-wt", "df": "d"},
                      headers={"User-Agent": UA, "Referer": "https://html.duckduckgo.com/"}, timeout=25)
    if r.status_code != 200:
        return f"HTTP {r.status_code}", []
    if "anomaly-modal" in r.text or "challenge-form" in r.text:
        return "blocked (DuckDuckGo asked for a verification check)", []
    soup = BeautifulSoup(r.text, "html.parser")
    items = []
    for a in soup.select("a.result__a"):
        href = a.get("href", "")
        if "duckduckgo.com/l/" in href:
            href = urllib.parse.parse_qs(urllib.parse.urlsplit(href).query).get("uddg", [href])[0]
        if href.startswith("//"):
            href = "https:" + href
        if not href.startswith("http") or "duckduckgo.com/y.js" in href:
            continue
        box = a.find_parent(class_="result") or a.parent
        sn = box.select_one(".result__snippet") if box else None
        items.append({"url": href, "title": a.get_text(" ", strip=True),
                      "snippet": sn.get_text(" ", strip=True) if sn else ""})
    return "ok", items


def duckduckgo_web(keyword):
    """General DuckDuckGo web search (all websites), past day only."""
    q_ = f'"{keyword}"'
    status, found = _ddg(q_)
    today = dt.date.today().isoformat()
    for it in found:
        it.update(publisher=domain(it["url"]), date_text="", published=today,
                  date_note="within past day, per search engine")
    time.sleep(random.uniform(2, 4))  # pause before the next DuckDuckGo search
    return q_ + "  (past day)", status, found


def deep_web_sites(keyword):
    """Web search on LinkedIn, X, Reddit, YouTube... via DuckDuckGo, past day only."""
    queries, items, counts = [], [], []
    today = dt.date.today().isoformat()
    for site in DEEP_WEB_SITES:
        q_ = f'"{keyword}" site:{site}'
        queries.append(q_ + "  (past day)")
        try:
            status, found = _ddg(q_)
        except requests.RequestException as e:
            status, found = f"failed ({type(e).__name__})", []
        found = [f for f in found if domain(f["url"]).endswith(site)]
        for it in found:
            it.update(publisher=site_name(site), date_text="", published=today,
                      date_note="within past day, per search engine", found_via=f"{site_name(site)} (deep search)")
        items += found
        counts.append(f"{site_name(site)} {len(found) if status == 'ok' else status}")
        if status.startswith("blocked"):
            break
        time.sleep(random.uniform(2, 4))
    return queries, "ok", items, ", ".join(counts)


# ------------------------------------------------------------ ResouX API ----
_URL_KEYS = ("url", "link", "href", "source_url", "sourceUrl", "web_url", "permalink")
_TITLE_KEYS = ("title", "headline", "name", "label")
_TEXT_KEYS = ("snippet", "description", "summary", "excerpt", "abstract", "content", "text", "body", "notes")
_DATE_KEYS = ("published", "published_at", "publishedAt", "pubDate", "date", "datetime", "created_at",
              "createdAt", "updated_at", "time", "timestamp", "seendate")
_PUB_KEYS = ("publisher", "source", "site", "domain", "outlet", "source_name", "author")


def _first(d, keys):
    for k in keys:
        v = d.get(k)
        if isinstance(v, dict):
            v = v.get("name") or v.get("title") or v.get("url")
        if v not in (None, "", []):
            return v
    return None


def _find_records(data, depth=0):
    """Find the list of result records anywhere in the JSON answer."""
    if isinstance(data, list) and data and all(isinstance(x, dict) for x in data[:5]):
        if any(_first(x, _URL_KEYS) for x in data[:10]):
            return data
    if depth < 4:
        children = data.values() if isinstance(data, dict) else data if isinstance(data, list) else []
        for v in children:
            if isinstance(v, (list, dict)):
                found = _find_records(v, depth + 1)
                if found:
                    return found
    return None


def _to_iso(v):
    if v is None:
        return ""
    if isinstance(v, (int, float)):  # unix time (seconds or milliseconds)
        return dt.datetime.fromtimestamp(v / 1000 if v > 1e11 else v, dt.timezone.utc).isoformat()
    return str(v).strip()


def resoux(keyword):
    """Search your ResouX API. Tries the usual request styles and reports exactly what happened."""
    headers = {"User-Agent": UA, "Accept": "application/json",
               "Authorization": f"Bearer {RESOUX_KEY}", "X-API-Key": RESOUX_KEY}
    params = {"q": keyword, "query": keyword, "keyword": keyword, "period": "24h", "hours": "24"}
    attempts = [("GET", dict(params=params)),
                ("POST", dict(json=params)),
                ("GET", dict(params=dict(params, key=RESOUX_KEY, api_key=RESOUX_KEY)))]
    shown = f"{RESOUX_URL}  q={keyword!r}, period=24h"
    last = "no answer"
    for method, kw in attempts:
        try:
            r = requests.request(method, RESOUX_URL, headers=headers, timeout=40, **kw)
        except requests.RequestException as e:
            return shown, f"connection failed: {type(e).__name__}: {e}", []
        if RESOUX_SHOW_RAW:
            print(f"--- ResouX {method} -> HTTP {r.status_code}\n{r.text[:1500]}\n---", flush=True)
        if r.status_code in (401, 403):
            last = f"HTTP {r.status_code}: key refused ({method})"
            continue
        if r.status_code in (404, 405, 400):
            last = f"HTTP {r.status_code} on {method}: {r.text[:120].strip()}"
            continue
        if r.status_code != 200:
            return shown, f"HTTP {r.status_code}: {r.text[:120].strip()}", []
        try:
            data = r.json()
        except ValueError:
            m = re.search(r"<title[^>]*>(.*?)</title>", r.text, re.I | re.S)
            page = f" titled '{m.group(1).strip()[:60]}'" if m else ""
            last = (f"answer is a web page{page}, not data - this address is not a data API "
                    "(or it needs a login)")
            continue
        records = _find_records(data)
        if records is None:
            keys = list(data)[:8] if isinstance(data, dict) else type(data).__name__
            return shown, f"ok (HTTP 200) but no result list found; answer keys: {keys}", []
        items = []
        for rec in records:
            url = _first(rec, _URL_KEYS)
            if not url or not str(url).startswith("http"):
                continue
            pub = _first(rec, _PUB_KEYS)
            items.append({"url": str(url), "title": str(_first(rec, _TITLE_KEYS) or url),
                          "snippet": str(_first(rec, _TEXT_KEYS) or "")[:3000],
                          "publisher": str(pub) if pub else domain(str(url)),
                          "date_text": "", "iso": _to_iso(_first(rec, _DATE_KEYS))})
        return shown + f"  [{method}]", "ok", items
    return shown, last, []


GDELT_BLOCKED = False

SEARCHERS = {"resoux": resoux, "google_news": google_news, "bing_news": bing_news, "gdelt_news": gdelt_news,
             "duckduckgo_web": duckduckgo_web, "deep_news_sites": deep_news_sites, "deep_web_sites": deep_web_sites}
SOURCE_LABELS = {"resoux": "ResouX", "google_news": "Google News", "bing_news": "Bing News", "gdelt_news": "GDELT",
                 "duckduckgo_web": "DuckDuckGo", "deep_news_sites": "Deep search: news sites", "deep_web_sites": "Deep search: LinkedIn / social"}


def extract_article(html_text):
    """Readable article text + publish date (same approach as crd_collector.extract_article)."""
    soup = BeautifulSoup(html_text, "html.parser")
    published = None
    for prop in ("article:published_time", "og:published_time", "datePublished", "pubdate"):
        tag = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
        if tag and tag.get("content"):
            published = tag["content"]
            break
    for t in soup(["script", "style", "noscript", "nav", "header", "footer", "aside", "form", "svg"]):
        t.decompose()
    box = soup.find("article") or soup.find("main") or soup.body or soup
    paras = [p.get_text(" ", strip=True) for p in box.find_all(["p", "h2", "li"])]
    text = "\n".join(p for p in paras if len(p) > 40)
    if len(text) < 300:
        text = re.sub(r"\s+", " ", box.get_text(" ", strip=True))
    return text[:8000], published


def fetch_one(r):
    try:
        resp = requests.get(r["url"], headers={"User-Agent": UA, "Accept-Language": "en-GB,en;q=0.8"},
                            timeout=15, allow_redirects=True)
        if resp.status_code >= 400 or "html" not in resp.headers.get("content-type", "html"):
            r["content_status"] = f"http_{resp.status_code}"
            return
        text, published = extract_article(resp.text[:3_000_000])
        low = text.lower()
        if any(h in low for h in PAYWALL_HINTS) and len(text) < 2500:
            r["content_status"] = "paywall_or_login"
        else:
            r["content_status"] = "full" if len(text) >= 400 else "too_short"
        r["content"] = text
        if published and not r.get("date_text") and not r.get("iso"):
            r["published"] = published[:10]
            r.pop("date_note", None)  # real date from the page replaces the search-engine estimate
    except requests.RequestException as e:
        r["content_status"] = f"error_{type(e).__name__}"


def published_at(r):
    """(aware datetime or None, exact time known?)"""
    if r.get("date_text"):
        try:
            d = email.utils.parsedate_to_datetime(r["date_text"])
            return (d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)), True
        except (TypeError, ValueError):
            pass
    if r.get("iso"):
        v = r["iso"].replace("Z", "+00:00")
        try:
            if len(v) <= 10:
                d = dt.date.fromisoformat(v)
                return dt.datetime(d.year, d.month, d.day, tzinfo=dt.timezone.utc), False
            d = dt.datetime.fromisoformat(v)
            return (d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)), True
        except ValueError:
            try:
                d = email.utils.parsedate_to_datetime(r["iso"])
                return (d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)), True
            except (TypeError, ValueError):
                pass
    if r.get("published"):
        try:
            d = dt.date.fromisoformat(r["published"])
            return dt.datetime(d.year, d.month, d.day, tzinfo=dt.timezone.utc), False
        except ValueError:
            pass
    return None, False


def _key(text):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower())).strip()[:90]


def collect(keyword, now):
    providers, results, seen, dupes = [], [], {}, 0
    for name in SOURCES:
        fn = SEARCHERS.get(name)
        if not fn:
            log(f"Unknown source '{name}' - skipped")
            continue
        log(f"{name}: searching '{keyword}'")
        try:
            out = fn(keyword)
        except (requests.RequestException, ET.ParseError, ValueError) as e:
            out = ("", f"failed: {type(e).__name__}", [])
        query, status, items = out[:3]
        message = out[3] if len(out) > 3 else ""
        queries = query if isinstance(query, list) else [query] if query else []
        label = SOURCE_LABELS.get(name, name)
        providers.append({"name": label, "status": status if status != "ok" or items else "no results",
                          "count": len(items), "queries": queries, "message": message})
        for it in items:
            via = it.get("found_via") or label
            k1 = it["url"].split("?")[0].rstrip("/")
            tk = _key(it["title"])
            k2 = tk + "|" + _key(it.get("publisher") or it.get("site") or domain(it["url"])) if len(tk) >= 20 else ""
            old = seen.get(k1) or (seen.get(k2) if k2 else None)
            if old is not None:
                dupes += 1
                if via not in old["found_by"]:
                    old["found_by"].append(via)
                continue
            it.update(provider=label, found_by=[via], content="", content_status="not_attempted")
            seen[k1] = it
            if k2:
                seen[k2] = it
            results.append(it)
        if name == "gdelt_news" and not GDELT_BLOCKED:
            time.sleep(5)  # GDELT asks for one request every 5 seconds

    if FETCH_ARTICLES:
        targets = [r for r in results if "news.google." not in r["url"]][:MAX_FETCH]
        log(f"Reading {len(targets)} article page(s)")
        with cf.ThreadPoolExecutor(max_workers=6) as ex:
            list(ex.map(fetch_one, targets))

    cutoff = now - dt.timedelta(hours=24)
    subj = subject_regex(keyword)
    kept, skipped = [], {"older_than_24h": 0, "no_date": 0, "keyword_not_found": 0}
    for r in results:
        when, exact = published_at(r)
        if when is None:
            skipped["no_date"] += 1
            continue
        if (exact and when < cutoff) or (not exact and when.date() < cutoff.date()):
            skipped["older_than_24h"] += 1
            continue
        if subj and not subj.search(" ".join((r["title"], r["snippet"], r["content"]))):
            skipped["keyword_not_found"] += 1
            continue
        r["when"], r["when_exact"] = when, exact
        r.update(analyse(r, subj))
        kept.append(r)
    kept.sort(key=lambda r: r["when"], reverse=True)
    return kept, providers, dupes, skipped


# ------------------------------------------------------ console report ----
def fmt_when(r):
    if not r.get("when"):
        return "date unknown"
    if r.get("when_exact"):
        return r["when"].astimezone().strftime("%d %b %Y %H:%M")
    return r["when"].strftime("%d %b %Y") + (f" – {r['date_note']}" if r.get("date_note") else "")



def console_report(all_results, now):
    """Plain-text report: what was searched, how each source answered, counts and references."""
    L = []
    line = "=" * 78
    since = (now - dt.timedelta(hours=24)).astimezone().strftime("%d %b %Y %H:%M")
    until = now.astimezone().strftime("%d %b %Y %H:%M")
    L += [line, "DAILY SENTIMENT REPORT", f"Period: {since}  ->  {until} (last 24 hours, local time)", line, ""]

    L.append("SUMMARY")
    L.append(f"  {'Keyword':<30}{'Negative':>10}{'Positive':>10}{'Mixed/neutral':>15}{'Total':>8}")
    for kw, (items, *_r) in all_results.items():
        n = sum(r["sentiment"] == "negative" for r in items)
        p = sum(r["sentiment"] == "positive" for r in items)
        L.append(f"  {kw[:29]:<30}{n:>10}{p:>10}{len(items) - n - p:>15}{len(items):>8}")
    L.append("")

    for kw, (items, providers, dupes, skipped) in all_results.items():
        L += [line, f"KEYWORD: {kw}", line, "", "Search key points:"]
        for p in providers:
            L.append(f"  - {p['name']}: {p['status']}, {p['count']} result(s)")
            for q_ in p.get("queries", []):
                L.append(f"      query:   {q_}")
            if p.get("message"):
                L.append(f"      per site: {p['message']}" if "deep" in p["name"].lower() else f"      message: {p['message']}")
        found = len(items) + sum(skipped.values())
        L += [f"  Results found (after removing {dupes} duplicates): {found}",
              f"  Left out: {skipped['older_than_24h']} older than 24h, {skipped['no_date']} without a date, "
              f"{skipped['keyword_not_found']} not mentioning '{kw}'",
              f"  Analysed: {len(items)}", ""]

        groups = {k: [r for r in items if r["sentiment"] == k] for k in ("negative", "positive")}
        other = len(items) - len(groups["negative"]) - len(groups["positive"])
        L += ["Result:",
              f"  NEGATIVE: {len(groups['negative'])}",
              f"  POSITIVE: {len(groups['positive'])}",
              f"  Mixed / neutral / unclear: {other}", ""]

        for key in ("negative", "positive"):
            L.append(f"{key.upper()} REFERENCES ({len(groups[key])})")
            if not groups[key]:
                L += ["  None.", ""]
                continue
            for i, r in enumerate(groups[key], 1):
                L.append(f"  [{i}] {r.get('title') or '(no title)'}")
                L.append(f"      found by: {', '.join(r['found_by'])}   |   website: {website(r)}")
                L.append(f"      {r.get('publisher') or domain(r['url'])} | {fmt_when(r)} | "
                         f"confidence {r['confidence']} | based on {r['depth']} text")
                if r["neg_terms"]:
                    L.append(f"      negative words: {', '.join(r['neg_terms'][:6])}")
                if r["pos_terms"]:
                    L.append(f"      positive words: {', '.join(r['pos_terms'][:6])}")
                if r.get("evidence"):
                    L.append(f"      key sentence:   {r['evidence']}")
                L.append(f"      {r['url']}")
                L.append("")
    L += [line, "Sentiment is marked automatically by wording rules; it is a first pass, not a judgement.", line]
    return "\n".join(L)


# ---------------------------------------------------------- HTML report ----
CSS = """
:root{--bg:#fff;--fg:#1d2433;--muted:#5d6678;--line:#e3e6ec;--card:#f6f7f9;--pos:#1f7a4d;--pos-bg:#e3f3ea;
--neg:#b42318;--neg-bg:#fbe9e7;--link:#1a4fa0;--mono:Consolas,Menlo,monospace}
@media (prefers-color-scheme:dark){:root{--bg:#14171c;--fg:#e6e8ec;--muted:#9aa3b2;--line:#2b313b;--card:#1b1f26;
--pos:#5cc98e;--pos-bg:#173326;--neg:#ff8a7e;--neg-bg:#3a1a18;--link:#8ab4ff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 "Segoe UI",system-ui,Arial,sans-serif}
main{max-width:1000px;margin:0 auto;padding:28px 18px 70px}
h1{font-size:26px;margin:0 0 2px}h2{font-size:21px;margin:42px 0 12px;padding-bottom:6px;border-bottom:2px solid var(--line)}
h3{font-size:16px;margin:24px 0 8px}.muted{color:var(--muted);font-size:13px}
.wrap{overflow-x:auto}table{border-collapse:collapse;width:100%;margin:12px 0}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}th{font-size:13px;color:var(--muted)}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
.counts{display:flex;gap:12px;flex-wrap:wrap;margin:12px 0}
.box{border-radius:10px;padding:12px 20px;min-width:140px;background:var(--card);border:1px solid var(--line)}
.box b{display:block;font-size:32px;line-height:1.1}
.box.neg{background:var(--neg-bg);color:var(--neg);border-color:transparent}
.box.pos{background:var(--pos-bg);color:var(--pos);border-color:transparent}
.kp{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 14px;font-size:13px}
.kp code{font-family:var(--mono);font-size:12px;overflow-wrap:anywhere}.kp td:nth-child(4){width:42%}.kp td:nth-child(2){width:34%}.kp .muted{font-weight:400}
.st-ok{color:var(--pos);font-weight:600}.st-bad{color:var(--neg);font-weight:600}
ol{padding-left:26px}li{margin:0 0 14px}a{color:var(--link)}
.ev{font-size:13px;color:var(--muted);border-left:3px solid var(--line);padding-left:9px;margin-top:4px}
.t-neg{color:var(--neg)}.t-pos{color:var(--pos)}
.src{display:inline-block;font-size:12px;font-weight:600;padding:1px 8px;margin:3px 4px 2px 0;border-radius:99px;
background:#1f3a68;color:#fff}.src.deep{background:#6b3fa0}
.site{font-size:12px;color:var(--muted)}
details summary{cursor:pointer;font-weight:600;margin:18px 0 8px}
.foot{margin-top:46px;font-size:12px;color:var(--muted)}
.top{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;flex-wrap:wrap}.top>div{flex:1 1 420px}.top .btn{margin-top:4px}
.btn{font:inherit;font-size:14px;font-weight:600;padding:8px 14px;border-radius:8px;cursor:pointer;
border:1px solid var(--line);background:var(--card);color:var(--fg)}.btn:hover{border-color:var(--link);color:var(--link)}
dialog{max-width:760px;width:calc(100% - 24px);max-height:88vh;border:1px solid var(--line);border-radius:12px;
padding:0;background:var(--bg);color:var(--fg)}dialog::backdrop{background:rgba(0,0,0,.45)}
.dlg-head{position:sticky;top:0;display:flex;justify-content:space-between;align-items:center;padding:14px 20px;
background:var(--bg);border-bottom:1px solid var(--line)}.dlg-head h2{margin:0;border:0;padding:0;font-size:19px}
.dlg-body{padding:4px 20px 20px}.dlg-body h3{margin-top:20px}.dlg-body li{margin:0 0 6px}
.tag{display:inline-block;font-size:12px;font-weight:600;padding:1px 8px;border-radius:99px;background:var(--card);border:1px solid var(--line)}
.tag.no{color:var(--pos)}.tag.yes{color:var(--neg)}
"""


def _logic_dialog():
    """'How this research works' panel shown by the info button."""
    e = html.escape
    desc = {
        "resoux": ("ResouX (your API)", "Calls your ResouX address with your key and reads the result list it returns.", False),
        "google_news": ("Google News", "Reads Google's public RSS news feed for the exact name, limited to the last day "
                        "(when:1d). Gives headline, publisher, time and link. Returns up to 100 items.", False),
        "bing_news": ("Bing News", "Reads Bing's public RSS news feed for the exact name, newest first.", False),
        "duckduckgo_web": ("DuckDuckGo", "General DuckDuckGo web search for the exact name across all websites "
                           "(news, blogs, company pages, forums), limited to the past day. Reads DuckDuckGo's results "
                           "page (about 30 results). Dates come from DuckDuckGo's past-day filter, or from the article "
                           "page when it can be read.", True),
        "deep_news_sites": ("Deep search: news sites", "Searches each of these sites separately through the Google News "
                            "feed (site:...), last 24 hours: " + ", ".join(DEEP_NEWS_SITES) + ". Paywalled sites "
                            "(Bloomberg, FT, WSJ) are judged on the headline.", False),
        "deep_web_sites": ("Deep search: LinkedIn / social", "Searches each of these sites separately with DuckDuckGo "
                           "web search limited to the past day: " + ", ".join(DEEP_WEB_SITES) + ". Reads DuckDuckGo's "
                           "results page. LinkedIn and X need a login to read posts, so they are judged on the "
                           "search snippet. Dates come from DuckDuckGo's past-day filter, not an exact time.", True),
        "gdelt_news": ("GDELT", "GDELT's free global news API (JSON), English-language sources, last 24 hours. "
                       "Allows about one request every 5 seconds, so the program waits and retries if it is busy.", False),
    }
    rows = []
    for name in SOURCES:
        label, text, scr = desc.get(name, (name, "Additional source.", False))
        rows.append(f"<tr><td><b>{e(label)}</b></td><td>{e(text)}</td>"
                    f'<td><span class="tag {"yes" if scr else "no"}">{"Search results page" if scr else "No"}</span></td></tr>')
    if FETCH_ARTICLES:
        rows.append('<tr><td><b>Article reading</b></td><td>Opens each article link once, like a browser, and extracts '
                    f'the article text (up to {MAX_FETCH} per keyword) so sentiment is judged on the full article, '
                    'not just the headline. Logins and paywalls are not bypassed; those articles are judged on the '
                    'headline or snippet only. Google News links cannot be opened this way, so they are always '
                    'judged on the headline.</td><td><span class="tag yes">Light scraping</span></td></tr>')
    return f"""<dialog id="logic"><div class="dlg-head"><h2>How this research works</h2>
<button class="btn" onclick="document.getElementById('logic').close()">Close</button></div><div class="dlg-body">
<h3>1. Where the results come from</h3>
<p class="muted">Mostly official feeds and APIs that sources provide for programs to read, not scraping of search pages.
No paid services are used.</p>
<div class="wrap"><table><tr><th>Source</th><th>How it is searched</th><th>Scraping?</th></tr>{"".join(rows)}</table></div>
<h3>2. Steps for each keyword</h3>
<ol>
<li><b>Search</b> every source above for the exact keyword (in quotes).</li>
<li><b>Remove duplicates</b>: the same link, or the same headline found by two sources, is kept once. Every source
that found it is shown on the result as a "Found by" label (purple = deep search).</li>
<li><b>Read articles</b>{" (if enabled)" if FETCH_ARTICLES else " (switched off in settings)"}: download the article text and its publish date.</li>
<li><b>Keep the last 24 hours</b>: results published before the 24-hour window are left out. Results with no
publish date are left out, because their age cannot be checked.</li>
<li><b>Check relevance</b>: the keyword must appear in the headline, snippet or article text.</li>
<li><b>Mark sentiment</b> (next section) and list the result under Negative, Positive or Mixed / neutral.</li>
</ol>
<h3>3. How positive and negative are decided</h3>
<ul>
<li>The text (headline + snippet + article) is checked against the same word lists as the Counterparty Search app.
Strong negative words such as <i>fraud, lawsuit, investigation, bankruptcy, scandal</i> count 2 points; milder ones such
as <i>decline, concern, criticism</i> count 1. Positive words work the same way (<i>award, breakthrough, wins</i> = 2;
<i>growth, success, strong</i> = 1).</li>
<li><b>Negation</b> is handled: "not guilty", "denied fraud", "cleared of" are ignored rather than counted.</li>
<li>Sentences that do not mention the keyword count half, so the score focuses on the subject.</li>
<li>Result: <b>negative</b> or <b>positive</b> if one side clearly wins; <b>mixed</b> if both sides are close
(the smaller is at least 45% of the larger); <b>neutral</b> if no rated words are found; <b>unclear</b> if only a
headline was available and it had no rated words.</li>
<li><b>Confidence</b> is High only when the full article was read and the wording is clear; snippet or headline-only
results are Low or Medium.</li>
</ul>
<h3>4. Limits</h3>
<ul>
<li>Word rules are a fast first pass, not a judgement. They were built for company research, so in politics a word like
"rally" counts as positive and "investigation" as negative even if it concerns someone else. Each reference shows the
words that decided it, so you can check.</li>
<li>Only English text is rated reliably.</li>
<li>Coverage is limited to the sources listed; news feeds return a limited number of items per search.</li>
<li>Allegations reported by sources are not established facts.</li>
</ul></div></dialog>"""


def _ref_item(r):
    e = html.escape
    words = []
    if r["neg_terms"]:
        words.append('<span class="t-neg">negative: ' + e(", ".join(r["neg_terms"][:6])) + "</span>")
    if r["pos_terms"]:
        words.append('<span class="t-pos">positive: ' + e(", ".join(r["pos_terms"][:6])) + "</span>")
    ev = f'<div class="ev">{e(r["evidence"])}</div>' if r.get("evidence") else ""
    badges = "".join(f'<span class="src{" deep" if "deep" in f else ""}">{e(f)}</span>' for f in r["found_by"])
    return (f'<li><a href="{e(r["url"])}" target="_blank" rel="noopener">{e(r.get("title") or r["url"])}</a><br>'
            f'<span class="muted">Found by:</span> {badges}<span class="site">website: {e(website(r))}</span><br>'
            f'<span class="muted">{e(r.get("publisher") or domain(r["url"]))} · {e(fmt_when(r))} · '
            f'confidence {e(r["confidence"])} · based on {e(r["depth"])} text</span><br>'
            f'<span class="muted">{" · ".join(words)}</span>{ev}</li>')


def html_report(all_results, now):
    e = html.escape
    since = (now - dt.timedelta(hours=24)).astimezone().strftime("%d %b %Y %H:%M")
    until = now.astimezone().strftime("%d %b %Y %H:%M")
    rows, sections = [], []
    for kw, (items, providers, dupes, skipped) in all_results.items():
        by = {k: [r for r in items if r["sentiment"] == k] for k in ("negative", "positive", "mixed", "neutral", "unclear")}
        rest = by["mixed"] + by["neutral"] + by["unclear"]
        anchor = "kw-" + re.sub(r"[^a-z0-9]+", "-", kw.lower())
        rows.append(f'<tr><td><a href="#{anchor}">{e(kw)}</a></td><td class="n t-neg"><b>{len(by["negative"])}</b></td>'
                    f'<td class="n t-pos"><b>{len(by["positive"])}</b></td><td class="n">{len(rest)}</td>'
                    f'<td class="n">{len(items)}</td></tr>')
        kp = []
        for p in providers:
            ok = p["status"] == "ok"
            q = "".join(f"<br>query: <code>{e(x)}</code>" for x in p.get("queries", []))
            msg = f'<br><span class="muted">per site: {e(p["message"])}</span>' if p.get("message") else ""
            kp.append(f'<tr><td>{e(p["name"])}</td><td class="{"st-ok" if ok else "st-bad"}">{e(p["status"])}{msg}</td>'
                      f'<td class="n">{p["count"]}</td><td>{q[4:] if q else ""}</td></tr>')
        found = len(items) + sum(skipped.values())
        sec = [f'<h2 id="{anchor}">{e(kw)}</h2>',
               '<h3>Search key points</h3><div class="kp"><div class="wrap"><table>'
               '<tr><th>Source</th><th>Status</th><th class="n">Results</th><th>Query sent</th></tr>'
               + "".join(kp) + "</table></div>"
               f'<div>Results found: <b>{found}</b> (after removing {dupes} duplicates) · '
               f'left out: {skipped["older_than_24h"]} older than 24h, {skipped["no_date"]} without a date, '
               f'{skipped["keyword_not_found"]} not mentioning the keyword · analysed: <b>{len(items)}</b></div></div>',
               '<h3>Result</h3><div class="counts">'
               f'<div class="box neg"><b>{len(by["negative"])}</b>negative</div>'
               f'<div class="box pos"><b>{len(by["positive"])}</b>positive</div>'
               f'<div class="box"><b>{len(rest)}</b>mixed / neutral</div></div>']
        for label, key in (("Negative references", "negative"), ("Positive references", "positive")):
            sec.append(f'<h3 class="t-{key[:3]}">{label} ({len(by[key])})</h3>')
            sec.append("<ol>" + "".join(_ref_item(r) for r in by[key]) + "</ol>" if by[key] else '<p class="muted">None.</p>')
        if rest:
            sec.append(f"<details><summary>Mixed / neutral / unclear ({len(rest)})</summary><ol>"
                       + "".join(_ref_item(r) for r in rest) + "</ol></details>")
        sections.append("\n".join(sec))
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sentiment report {e(until)}</title><style>{CSS}</style></head><body><main>
<div class="top"><div><h1>Daily sentiment report</h1>
<p class="muted">Articles published {e(since)} – {e(until)} (last 24 hours, local time) · generated {e(until)}</p></div>
<button class="btn" onclick="document.getElementById('logic').showModal()">&#9432; How this research works</button></div>
{_logic_dialog()}
<div class="wrap"><table><thead><tr><th>Keyword</th><th class="n">Negative</th><th class="n">Positive</th>
<th class="n">Mixed / neutral</th><th class="n">Total</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>
{"".join(sections)}
<p class="foot">Sentiment is marked automatically by wording rules (the same rules as Counterparty Search); it is a
first pass, not a judgement. Results based on snippet or headline text were judged without the full article.
Allegations reported by sources are not established facts. Coverage is limited to the sources listed.</p>
</main></body></html>"""


# --------------------------------------------------------------- run ----
def run_once(keywords=None, open_html=None):
    keywords = keywords or KEYWORDS
    open_html = OPEN_REPORT if open_html is None else open_html
    global GDELT_BLOCKED
    GDELT_BLOCKED = False
    now = dt.datetime.now(dt.timezone.utc)
    all_results = {}
    for kw in keywords:
        log(f"=== Searching: {kw} ===")
        try:
            all_results[kw] = collect(kw, now)
        except Exception as ex:  # one failing keyword should not stop the others
            log(f"Search for '{kw}' failed: {type(ex).__name__}: {ex}")
            all_results[kw] = ([], [], 0, {"older_than_24h": 0, "no_date": 0, "keyword_not_found": 0})
    text = console_report(all_results, now)
    print("\n" + text)

    out_dir = os.path.join(HERE, REPORT_DIR)
    os.makedirs(out_dir, exist_ok=True)
    stamp = now.astimezone().strftime("%Y-%m-%d_%H%M")
    html_path = os.path.join(out_dir, f"report_{stamp}.html")
    with open(html_path, "w", encoding="utf-8") as fh:
        fh.write(html_report(all_results, now))
    txt_path = os.path.join(out_dir, f"report_{stamp}.txt")
    csv_path = os.path.join(out_dir, f"report_{stamp}.csv")
    with open(txt_path, "w", encoding="utf-8") as fh:
        fh.write(text)
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["keyword", "sentiment", "confidence", "published", "publisher", "title", "url",
                    "negative_words", "positive_words", "based_on", "found_by", "website"])
        for kw, (items, *_r) in all_results.items():
            for r in items:
                w.writerow([kw, r["sentiment"], r["confidence"], fmt_when(r), r["publisher"], r["title"], r["url"],
                            "; ".join(r["neg_terms"]), "; ".join(r["pos_terms"]), r["depth"],
                            "; ".join(r["found_by"]), website(r)])
    print(f"\nHTML report: {html_path}\nAlso saved:  {txt_path}\n             {csv_path}\n", flush=True)
    if open_html:
        webbrowser.open("file:///" + html_path.replace(os.sep, "/").lstrip("/"))
    return html_path


def parse_hhmm(value):
    try:
        h, m = (int(x) for x in value.split(":"))
        return dt.time(h, m)
    except ValueError:
        sys.exit(f"Time must be HH:MM, for example 08:00 (got '{value}')")


def run_daily(at, keywords=None):
    """Stay running and make the report every day at the given time."""
    while True:
        now = dt.datetime.now()
        nxt = dt.datetime.combine(now.date(), at)
        if nxt <= now:
            nxt += dt.timedelta(days=1)
        print(f"Next report at {nxt:%d %b %Y %H:%M}. Keep this running (Ctrl+C / Interrupt to stop).", flush=True)
        time.sleep((nxt - now).total_seconds())
        try:
            run_once(keywords, open_html=False)
        except Exception as ex:
            log(f"Report failed: {type(ex).__name__}: {ex}")


def install_task(at):
    import subprocess
    if not THIS_FILE:
        print("Windows Task Scheduler needs a .py file: save this code as daily_report.py and run\n"
              "    python daily_report.py --install-task " + at.strftime("%H:%M"))
        return
    py = sys.executable
    pyw = os.path.join(os.path.dirname(py), "pythonw.exe")
    if os.path.exists(pyw):
        py = pyw
    r = subprocess.run(["schtasks", "/Create", "/F", "/SC", "DAILY", "/ST", at.strftime("%H:%M"), "/TN", TASK_NAME,
                        "/TR", f'"{py}" "{THIS_FILE}"'], capture_output=True, text=True)
    print((r.stdout or r.stderr).strip())
    if r.returncode == 0:
        print(f"Windows will run the report every day at {at:%H:%M}. Reports: {os.path.join(HERE, REPORT_DIR)}")


def remove_task():
    import subprocess
    r = subprocess.run(["schtasks", "/Delete", "/F", "/TN", TASK_NAME], capture_output=True, text=True)
    print((r.stdout or r.stderr).strip())


def main():
    ap = argparse.ArgumentParser(description="Daily positive/negative news report (last 24 hours)")
    ap.add_argument("--keyword", action="append", help="keyword to search (repeatable); overrides KEYWORDS")
    ap.add_argument("--daily", metavar="HH:MM", help="keep running and make the report every day at this time")
    ap.add_argument("--install-task", metavar="HH:MM", help="create a Windows scheduled task for this time")
    ap.add_argument("--remove-task", action="store_true", help="remove the Windows scheduled task")
    a, _unknown = ap.parse_known_args()  # ignores the extra arguments Jupyter passes
    if sys.stdout is None:               # started by pythonw (scheduled task): files only
        sys.stdout = open(os.devnull, "w")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    if a.install_task:
        install_task(parse_hhmm(a.install_task))
    elif a.remove_task:
        remove_task()
    elif a.daily:
        run_daily(parse_hhmm(a.daily), a.keyword)
    else:
        run_once(a.keyword)


if __name__ == "__main__":
    main()
