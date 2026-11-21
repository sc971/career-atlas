#!/usr/bin/env python3
"""
Career Atlas nightly crawler.
Reads companies.csv, fetches the newest jobs of every company that has a connector,
extracts language requirements + keywords from descriptions, and writes:
  data/jobs.json    -> {sector: [[company, initials, hq, rank, color, jobs, careers_url, note]]}
                       job = [title, location, country_code, required_languages, url, keywords]
  data/status.json  -> per-company result (ok / error / no connector)
Usage: python crawler/crawl.py [--max 50] [--only "Dow,Google"] [--detect 40]
"""
import argparse, csv, itertools, json, os, re, sys, time, traceback
sys.path.insert(0, os.path.dirname(__file__))
import ats_tools
from ats_tools import CONNECTORS, detect
from extra import EXTRA

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALL = {**CONNECTORS, **EXTRA}

LANGS = {"EN": r"english|englisch|anglais|ingl[eé]s", "TR": r"turkish|t[uü]rk[cç]e|t[uü]rkisch", "DE": r"german|deutsch|deutschkenntnisse",
         "FR": r"french|fran[cç]ais|franz[oö]sisch", "ES": r"spanish|espa[nñ]ol", "IT": r"italian|italiano", "PT": r"portuguese|portugu[eê]s",
         "NL": r"dutch|nederlands", "AR": r"arabic|arabisch", "ZH": r"chinese|mandarin|cantonese", "JA": r"japanese", "KO": r"korean",
         "RU": r"russian", "PL": r"polish", "HI": r"hindi", "HE": r"hebrew", "SV": r"swedish", "TH": r"thai"}
LANG_CTX = re.compile(r"fluen|proficien|language|speak|written|verbal|native|bilingual|kenntnisse|sprach|langue|idioma", re.I)
VOCAB = ("sap|s/4hana|python|java|javascript|typescript|c\\+\\+|c#|sql|kubernetes|docker|terraform|azure|aws|gcp|linux|power bi|tableau|excel|"
         "salesforce|servicenow|machine learning|llm|generative ai|data science|cybersecurity|security clearance|devops|networking|embedded|firmware|"
         "erp|crm|saas|account executive|account manager|key account|sales|presales|technical sales|business development|customer service|marketing|"
         "finance|accounting|audit|tax|treasury|legal|hr|recruiting|supply chain|procurement|sourcing|logistics|operations|maintenance|reliability|"
         "instrumentation|electrical|commissioning|hse|ehs|safety|process engineering|chemical engineering|mechanical engineering|electrical engineering|"
         "petroleum engineering|drilling|reservoir|subsea|refinery|petrochemical|polymer|catalyst|laboratory|r&d|technical service|"
         "product management|program management|project management|data center|hardware|bachelor|master|phd|mba|internship|graduate|remote|hybrid").split("|")
VOCAB_RE = [(v.replace("\\", ""), re.compile(r"(^|[^a-z])" + v + r"([^a-z]|$)")) for v in VOCAB]

COUNTRY = {"united states": "US", "usa": "US", "us": "US", "united kingdom": "GB", "uk": "GB", "germany": "DE", "deutschland": "DE", "france": "FR",
           "netherlands": "NL", "belgium": "BE", "switzerland": "CH", "austria": "AT", "italy": "IT", "spain": "ES", "portugal": "PT", "ireland": "IE",
           "sweden": "SE", "norway": "NO", "denmark": "DK", "finland": "FI", "poland": "PL", "czech republic": "CZ", "czechia": "CZ", "hungary": "HU",
           "romania": "RO", "bulgaria": "BG", "greece": "GR", "turkey": "TR", "türkiye": "TR", "turkiye": "TR", "united arab emirates": "AE", "uae": "AE",
           "saudi arabia": "SA", "ksa": "SA", "qatar": "QA", "kuwait": "KW", "oman": "OM", "bahrain": "BH", "egypt": "EG", "israel": "IL", "india": "IN",
           "china": "CN", "japan": "JP", "south korea": "KR", "korea": "KR", "taiwan": "TW", "singapore": "SG", "malaysia": "MY", "thailand": "TH",
           "indonesia": "ID", "vietnam": "VN", "philippines": "PH", "australia": "AU", "new zealand": "NZ", "canada": "CA", "mexico": "MX", "brazil": "BR",
           "argentina": "AR", "chile": "CL", "colombia": "CO", "peru": "PE", "south africa": "ZA", "nigeria": "NG", "kenya": "KE", "morocco": "MA",
           "kazakhstan": "KZ", "azerbaijan": "AZ", "pakistan": "PK", "hong kong": "HK"}
ISO3 = {"USA": "US", "GBR": "GB", "DEU": "DE", "FRA": "FR", "NLD": "NL", "IND": "IN", "CAN": "CA", "MEX": "MX", "BRA": "BR", "JPN": "JP", "CHN": "CN",
        "SGP": "SG", "AUS": "AU", "ARE": "AE", "SAU": "SA", "TUR": "TR", "ESP": "ES", "ITA": "IT", "POL": "PL", "IRL": "IE", "CHE": "CH", "KOR": "KR"}

def keywords(text):
    t = text or ""
    tl = t.lower()
    langs = [k for k, p in LANGS.items() if re.search(r"\b(" + p + r")\b", t, re.I)] if LANG_CTX.search(t) else []
    kw = [v for v, r in VOCAB_RE if r.search(tl)]
    y = re.search(r"(\d{1,2})\+?\s*(?:or more\s*)?years", tl)
    if y and int(y.group(1)) < 25:
        kw.append(y.group(1) + "+ years")
    return ",".join(langs), " · ".join(kw)

def country_of(loc, hq):
    parts = [p.strip() for p in re.split(r"[,/|]", re.sub(r"\+\d+ more", "", loc or "")) if p.strip()]
    for p in reversed(parts):
        if re.fullmatch(r"[A-Z]{2}", p) and p not in ("TX", "CA", "WA", "NY", "MI", "LA", "PA", "GA", "KY", "OR", "AZ", "NJ", "VA", "FL", "IL", "MA", "NC", "OH", "CO", "MN", "TN", "IN", "WV", "AL", "OK", "DE", "NV", "UT", "ON", "AB", "BC", "QC"):
            return p
        if p in ISO3: return ISO3[p]
        c = COUNTRY.get(p.lower())
        if c: return c
    return hq

def initials(name):
    w = re.findall(r"[A-ZÇĞİÖŞÜ]", name)
    return ("".join(w[:2]) or name[:2]).upper()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=50, help="newest jobs kept per company")
    ap.add_argument("--only", default="", help="comma-separated company names")
    ap.add_argument("--detect", type=int, default=0, help="auto-detect the ATS for up to N companies without a connector")
    a = ap.parse_args()
    path = os.path.join(ROOT, "companies.csv")
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    only = {x.strip().lower() for x in a.only.split(",") if x.strip()}

    # 1) auto-detect ATS for some companies that have a careers URL but no connector yet
    if a.detect:
        todo = [r for r in rows if not r["connector"] and r["careers_url"].startswith("http") and not r.get("detect_tried")][: a.detect]
        for r in todo:
            try:
                ats, key, final = detect(r["careers_url"])
                if ats in ALL and key:
                    r["connector"], r["key"] = ats, key
                r["detect_tried"] = ats or "unknown"
                print(f"detect {r['company']:<30} {ats} {key}")
            except Exception as e:
                r["detect_tried"] = "error"
                print(f"detect {r['company']:<30} ERROR {e}")
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)

    # 2) fetch jobs
    data, status = {}, {}
    prev = {}
    try:
        for sec, cos in json.load(open(os.path.join(ROOT, "data", "jobs.json"), encoding="utf-8")).items():
            for c in cos: prev[c[0]] = (sec, c)
    except Exception:
        pass
    groups = {}
    for r in rows:
        if r["connector"]:
            groups.setdefault(r["company"], []).append(r)
    for company, rs in groups.items():
        if only and company.lower() not in only:
            if company in prev: data.setdefault(prev[company][0], []).append(prev[company][1])
            continue
        r0 = rs[0]
        jobs, err = [], None
        for r in rs:
            fn = ALL.get(r["connector"])
            try:
                for j in itertools.islice(fn(company, r["key"]), int(r.get("max_jobs") or a.max)):
                    langs, kw = keywords((j.get("title") or "") + " " + (j.get("description") or ""))
                    loc = j.get("location") or ""
                    cc = country_of(loc, r0["hq"])
                    jobs.append([j.get("title") or "", loc, cc, langs, j.get("url") or "", kw])
            except Exception as e:
                err = f"{type(e).__name__}: {e}"
                traceback.print_exc()
        seen, uniq = set(), []
        for j in jobs:
            if j[4] not in seen: seen.add(j[4]); uniq.append(j)
        if uniq:
            data.setdefault(r0["sector"], []).append([company, initials(company), r0["hq"], None, r0.get("color") or "#334155",
                                                      uniq, r0["careers_url"], f"Latest {len(uniq)} roles (updated daily)"])
        elif company in prev:   # keep yesterday's data if today's fetch failed
            data.setdefault(prev[company][0], []).append(prev[company][1])
        status[company] = {"jobs": len(uniq), "error": err, "connector": r0["connector"], "at": time.strftime("%Y-%m-%d %H:%M")}
        print(f"{company:<30} {r0['connector']:<15} {len(uniq):>4} jobs {err or ''}")
    for r in rows:
        if not r["connector"]:
            status.setdefault(r["company"], {"jobs": 0, "error": "no connector yet", "connector": "", "at": time.strftime("%Y-%m-%d %H:%M")})
    os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)
    json.dump(data, open(os.path.join(ROOT, "data", "jobs.json"), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    json.dump(status, open(os.path.join(ROOT, "data", "status.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("total jobs:", sum(len(c[5]) for v in data.values() for c in v))

if __name__ == "__main__":
    main()
