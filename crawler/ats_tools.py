#!/usr/bin/env python3
"""
Kariyer Atlası – ATS tespit + ilan çekme araçları (yalnızca Python standart kütüphanesi).

Kullanım:
  python ats_tools.py detect companies.csv  -o detected.csv
  python ats_tools.py fetch  detected.csv   -o jobs.jsonl

detect: her şirketin careers_url adresini açar, sayfadaki ATS izlerini arar
        (Workday, Greenhouse, Lever, SmartRecruiters, Ashby, Workable, SuccessFactors, Eightfold,
        Phenom, Taleo, iCIMS, Oracle HCM, TalentLink, Personio, Teamtailor, Avature).
fetch:  tespit edilen ATS için ilgili bağlayıcıyı çalıştırır ve ilanları JSONL olarak yazar.
        Bağlayıcı yoksa site haritası + JSON-LD (JobPosting) yöntemini dener.

Not: Robots.txt ve sitelerin kullanım şartlarına uyun; istek hızını düşük tutun.
"""
import argparse, csv, gzip, html, json, re, sys, time, urllib.error, urllib.parse, urllib.request
from xml.etree import ElementTree as ET

UA = "Mozilla/5.0 (compatible; CareerAtlasBot/0.2; +https://github.com/sc971/career-atlas)"
DELAY = 1.0                                          # istekler arası bekleme (sn)


# ----------------------------------------------------------------- HTTP yardımcıları
def http(url, data=None, headers=None, timeout=30, retries=3):
    h = {"User-Agent": UA, "Accept": "*/*", "Accept-Encoding": "gzip", "Accept-Language": "en-US,en;q=0.9"}
    if headers:
        h.update(headers)
    body = json.dumps(data).encode() if isinstance(data, (dict, list)) else data
    if isinstance(data, (dict, list)):
        h["Content-Type"] = "application/json"
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=body, headers=h, method="POST" if body else "GET")
        time.sleep(DELAY * (1 + attempt * 3))
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return r.geturl(), raw.decode(r.headers.get_content_charset() or "utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code in (429, 502, 503, 504) and attempt < retries:
                wait = int(e.headers.get("Retry-After") or 0) or 10 * (attempt + 1)
                time.sleep(min(wait, 60))
                continue
            raise

def get_json(url, data=None):
    return json.loads(http(url, data=data, headers={"Accept": "application/json"})[1])

def strip_html(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


# ----------------------------------------------------------------- ATS tespiti
SIGNATURES = [
    ("workday",         r"https?://([\w-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([\w-]+)"),
    ("greenhouse",      r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_board\?for=)?([\w-]+)"),
    ("lever",           r"jobs\.(?:eu\.)?lever\.co/([\w.-]+)"),
    ("smartrecruiters", r"(?:careers|jobs)\.smartrecruiters\.com/([\w-]+)"),
    ("ashby",           r"jobs\.ashbyhq\.com/([\w.%-]+)"),
    ("workable",        r"apply\.workable\.com/([\w-]+)"),
    ("personio",        r"([\w-]+)\.jobs\.personio\.(?:de|com)"),
    ("teamtailor",      r"([\w-]+)\.teamtailor\.com"),
    ("talentlink",      r"([\w-]+)\.recruitmentplatform\.com"),
    ("oracle_hcm",      r"([\w-]+)\.fa\.[\w.-]*oraclecloud\.com/hcmUI/CandidateExperience"),
    ("taleo",           r"([\w-]+)\.taleo\.net"),
    ("icims",           r"([\w-]+)\.icims\.com"),
    ("avature",         r"([\w-]+)\.avature\.net"),
    ("eightfold",       r"([\w-]+\.eightfold\.ai)"),
    ("successfactors",  r"(career\d*\.(?:sapsf|successfactors)\.(?:com|eu)|rmkcdn\.successfactors\.com|jobs\.sap\.com)"),
    ("phenom",          r"(cdn\.phenompeople\.com|phenompeople|\"phApp\")"),
]
# SuccessFactors Career Site Builder ilan sayfası kalıbı: /job/<şehir-başlık>/<9 haneli id>/
SF_CSB_PATH = re.compile(r'href="(/job/[^"/]+/\d{6,}/?)"')
JOB_LINK_HINT = re.compile(r'href="([^"]+)"[^>]*>[^<]{0,40}(?:jobs|vacanc|open positions|stellen|açık pozisyon|search jobs|apply)', re.I)

def detect_in_html(page_html):
    for name, pat in SIGNATURES:
        m = re.search(pat, page_html)
        if m:
            return name, "|".join(g for g in m.groups() if g)
    if SF_CSB_PATH.search(page_html) and ("Apply now" in page_html or "Job Segment" in page_html):
        return "successfactors", ""
    if '"JobPosting"' in page_html:
        return "jsonld", ""
    return None, ""

def detect(url):
    """Kariyer sayfasını ve oradaki 'jobs' bağlantılarından birkaçını tarar."""
    seen, queue = set(), [url]
    while queue and len(seen) < 4:
        u = queue.pop(0)
        if u in seen:
            continue
        seen.add(u)
        try:
            final, body = http(u)
        except Exception as e:
            continue
        # yönlendirme ATS adresine gittiyse
        ats, key = detect_in_html(final + " " + body)
        if ats:
            if ats in ("successfactors", "phenom", "jsonld") and not key:
                key = urllib.parse.urlsplit(final).netloc
            return ats, key, final
        for href in JOB_LINK_HINT.findall(body)[:3]:
            queue.append(urllib.parse.urljoin(final, html.unescape(href)))
    return "unknown", "", url


# ----------------------------------------------------------------- bağlayıcılar
def job(company, title, location, url, posted=None, description="", source=""):
    return {"company": company, "title": title, "location": location, "url": url,
            "posted": posted, "description": description, "source": source}

def fetch_workday(company, key, with_description=False):
    """key = 'tenant|wdN|site'  örn. 'dow|wd1|ExternalCareers'"""
    tenant, wd, site = key.split("|")
    base = f"https://{tenant}.{wd}.myworkdayjobs.com"
    api = f"{base}/wday/cxs/{tenant}/{site}"
    offset, limit = 0, 20
    while True:
        _, txt = http(f"{api}/jobs", {"appliedFacets": {}, "limit": limit, "offset": offset, "searchText": ""},
                      headers={"Accept": "application/json", "Origin": base, "Referer": f"{base}/{site}"})
        if not txt.lstrip().startswith("{"):
            raise RuntimeError("Workday returned a non-JSON page (maintenance or blocked): " + strip_html(txt)[:120])
        data = json.loads(txt)
        posts = data.get("jobPostings", [])
        for p in posts:
            desc = ""
            if with_description:
                try:
                    info = get_json(f"{api}{p['externalPath']}").get("jobPostingInfo", {})
                    desc = strip_html(info.get("jobDescription", ""))
                except Exception:
                    pass
            yield job(company, p.get("title"), p.get("locationsText"),
                      f"{base}/{site}{p.get('externalPath', '')}", p.get("postedOn"), desc, "workday")
        offset += limit
        if not posts or offset >= data.get("total", 0):
            break

def fetch_greenhouse(company, key):
    data = get_json(f"https://boards-api.greenhouse.io/v1/boards/{key}/jobs?content=true")
    for j in data.get("jobs", []):
        yield job(company, j.get("title"), (j.get("location") or {}).get("name"), j.get("absolute_url"),
                  j.get("updated_at"), strip_html(html.unescape(j.get("content", ""))), "greenhouse")

def fetch_lever(company, key):
    for j in get_json(f"https://api.lever.co/v0/postings/{key}?mode=json"):
        cat = j.get("categories") or {}
        yield job(company, j.get("text"), cat.get("location"), j.get("hostedUrl"),
                  j.get("createdAt"), j.get("descriptionPlain", ""), "lever")

def fetch_smartrecruiters(company, key):
    offset = 0
    while True:
        data = get_json(f"https://api.smartrecruiters.com/v1/companies/{key}/postings?limit=100&offset={offset}")
        items = data.get("content", [])
        for j in items:
            loc = j.get("location") or {}
            yield job(company, j.get("name"), ", ".join(x for x in [loc.get("city"), loc.get("country")] if x),
                      f"https://jobs.smartrecruiters.com/{key}/{j.get('id')}", j.get("releasedDate"), "", "smartrecruiters")
        offset += len(items)
        if not items or offset >= data.get("totalFound", 0):
            break

def fetch_ashby(company, key):
    data = get_json(f"https://api.ashbyhq.com/posting-api/job-board/{key}?includeCompensation=false")
    for j in data.get("jobs", []):
        yield job(company, j.get("title"), j.get("location"), j.get("jobUrl"),
                  j.get("publishedAt"), j.get("descriptionPlain", ""), "ashby")

def fetch_eightfold(company, key, domain=None):
    """Deneysel. key = 'bayer.eightfold.ai' gibi bir host. domain verilmezse host'tan tahmin edilir."""
    domain = domain or key.split(".")[0] + ".com"
    start = 0
    while True:
        data = get_json(f"https://{key}/api/apply/v2/jobs?domain={domain}&start={start}&num=50")
        items = data.get("positions", [])
        for j in items:
            yield job(company, j.get("name"), j.get("location"),
                      j.get("canonicalPositionUrl") or f"https://{key}/careers?pid={j.get('id')}",
                      j.get("t_create"), strip_html(j.get("job_description", "")), "eightfold")
        start += len(items)
        if not items or start >= data.get("count", 0):
            break

def sitemap_job_urls(host, limit=2000):
    """Site haritasından ilan adreslerini toplar (SuccessFactors CSB, Phenom ve çoğu özel site)."""
    urls, todo, done = [], [f"https://{host}/sitemap.xml"], set()
    while todo and len(urls) < limit:
        sm = todo.pop(0)
        if sm in done:
            continue
        done.add(sm)
        try:
            _, body = http(sm)
            root = ET.fromstring(body.encode())
        except Exception:
            continue
        for loc in root.iter():
            if loc.tag.endswith("loc") and loc.text:
                u = loc.text.strip()
                if u.endswith(".xml"):
                    todo.append(u)
                elif re.search(r"/job/|/jobs/|/stellen|/vacanc|/position", u, re.I):
                    urls.append(u)
    return urls[:limit]

def jsonld_jobs(page_html):
    for block in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', page_html, re.S | re.I):
        try:
            data = json.loads(block.strip())
        except Exception:
            continue
        for d in (data if isinstance(data, list) else data.get("@graph", [data])):
            if isinstance(d, dict) and d.get("@type") == "JobPosting":
                yield d

def csb_category_job_urls(go_url, page_size=25, max_pages=40):
    """SuccessFactors Career Site Builder kategori sayfası (/go/<ad>/<id>) içindeki ilan adresleri.
    Sayfalama: /go/<ad>/<id>/25/, /50/ ... (yeni ilan çıkmayınca durur)."""
    base = go_url.split("?")[0].rstrip("/")
    root = "{0.scheme}://{0.netloc}".format(urllib.parse.urlsplit(base))
    seen, out = set(), []
    for i in range(max_pages):
        url = base + "/" if i == 0 else f"{base}/{i * page_size}/"
        try:
            _, body = http(url)
        except Exception:
            break
        new = [urllib.parse.urljoin(root, html.unescape(h)) for h in re.findall(r'href="([^"]*/job/[^"]+/\d{6,}/?)"', body)]
        new = [u for u in new if u not in seen]
        if not new:
            break
        for u in new:
            seen.add(u); out.append(u)
    return out

def fetch_sitemap_jsonld(company, host, max_pages=500):
    urls = csb_category_job_urls(host) if "/go/" in host else sitemap_job_urls(host)
    for u in urls[:max_pages]:
        try:
            _, body = http(u)
        except Exception:
            continue
        found = False
        for d in jsonld_jobs(body):
            found = True
            loc = d.get("jobLocation")
            loc = loc[0] if isinstance(loc, list) and loc else loc
            addr = (loc or {}).get("address", {}) if isinstance(loc, dict) else {}
            where = ", ".join(x for x in [addr.get("addressLocality"), addr.get("addressCountry") if isinstance(addr.get("addressCountry"), str) else None] if x)
            yield job(company, d.get("title"), where, u, d.get("datePosted"), strip_html(d.get("description", "")), "jsonld")
        if not found:   # JSON-LD yoksa SuccessFactors sayfa alanlarını ya da başlığı al
            t = re.search(r'itemprop="title"[^>]*>(.*?)<', body, re.S) or re.search(r"<title>(.*?)</title>", body, re.S | re.I)
            loc = re.search(r'itemprop="jobLocation"[^>]*>(.*?)</', body, re.S) or re.search(r'Location:\s*</[^>]+>\s*([^<]+)', body)
            date = re.search(r'itemprop="datePosted"[^>]*>(.*?)<', body, re.S) or re.search(r'Date:\s*</[^>]+>\s*([^<]+)', body)
            desc = re.search(r'class="jobdescription"[^>]*>(.*?)</span>', body, re.S)
            yield job(company, strip_html(t.group(1)) if t else None, strip_html(loc.group(1)) if loc else None, u,
                      strip_html(date.group(1)) if date else None, strip_html(desc.group(1)) if desc else "", "successfactors")

CONNECTORS = {
    "workday": fetch_workday, "greenhouse": fetch_greenhouse, "lever": fetch_lever,
    "smartrecruiters": fetch_smartrecruiters, "ashby": fetch_ashby, "eightfold": fetch_eightfold,
    "successfactors": fetch_sitemap_jsonld, "phenom": fetch_sitemap_jsonld, "jsonld": fetch_sitemap_jsonld,
}


# ----------------------------------------------------------------- komutlar
def cmd_detect(args):
    rows = list(csv.DictReader(open(args.input, encoding="utf-8")))
    out = csv.DictWriter(open(args.output, "w", newline="", encoding="utf-8"),
                         fieldnames=list(rows[0].keys()) + ["detected_ats", "detected_key", "final_url"])
    out.writeheader()
    for r in rows:
        ats, key, final = detect(r["careers_url"])
        print(f"{r['company']:<25} {ats:<16} {key}", file=sys.stderr)
        out.writerow({**r, "detected_ats": ats, "detected_key": key, "final_url": final})

def cmd_fetch(args):
    rows = list(csv.DictReader(open(args.input, encoding="utf-8")))
    n_total = 0
    with open(args.output, "w", encoding="utf-8") as f:
        for r in rows:
            ats = r.get("detected_ats") or ""
            key = r.get("ats_key") if (r.get("ats_key") or "").startswith("http") else (r.get("detected_key") or r.get("ats_key") or "")
            if not ats and "successfactors" in (r.get("ats") or "").lower():
                ats = "successfactors"
            fn = CONNECTORS.get(ats)
            if not fn or not key:
                print(f"{r['company']:<25} atlandı (ats={ats or '?'})", file=sys.stderr)
                continue
            n = 0
            try:
                for j in fn(r["company"], key):
                    j["sector"] = r.get("sector")
                    f.write(json.dumps(j, ensure_ascii=False) + "\n")
                    n += 1
            except Exception as e:
                print(f"{r['company']:<25} HATA: {e}", file=sys.stderr)
            print(f"{r['company']:<25} {ats:<16} {n} ilan", file=sys.stderr)
            n_total += n
    print(f"Toplam {n_total} ilan -> {args.output}", file=sys.stderr)

if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("detect"); d.add_argument("input"); d.add_argument("-o", "--output", default="detected.csv")
    g = sub.add_parser("fetch");  g.add_argument("input"); g.add_argument("-o", "--output", default="jobs.jsonl")
    a = p.parse_args()
    {"detect": cmd_detect, "fetch": cmd_fetch}[a.cmd](a)
