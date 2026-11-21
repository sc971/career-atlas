"""Extra connectors for large employers with their own career APIs."""
import json, re, html
from ats_tools import http, get_json, strip_html, job

def fetch_amazon(company, key="", limit=50):
    d = get_json(f"https://www.amazon.jobs/en/search.json?sort=recent&result_limit={limit}&offset=0")
    for x in d.get("jobs", []):
        desc = " ".join(x.get(k) or "" for k in ("description", "basic_qualifications", "preferred_qualifications"))
        yield job(company, x.get("title"), ", ".join(v for v in [x.get("city"), x.get("state"), x.get("country_code")] if v),
                  "https://www.amazon.jobs" + x.get("job_path", ""), x.get("posted_date"), strip_html(desc), "amazon")

def fetch_google(company, key="", pages=3):
    for p in range(1, pages + 1):
        _, h = http(f"https://www.google.com/about/careers/applications/jobs/results?sort_by=date&page={p}")
        m = re.search(r"key: 'ds:1'.*?data:(.*?), sideChannel", h, re.S)
        if not m: break
        for x in json.loads(m.group(1))[0]:
            locs = x[9] or []
            l0 = locs[0] if locs else [""]
            slug = re.sub(r"[^a-z0-9]+", "-", x[1].lower()).strip("-")
            desc = " ".join(((x[i] or [None, ""])[1] or "") for i in (3, 4, 10))
            loc = l0[0] + (f" +{len(locs)-1} more" if len(locs) > 1 else "")
            yield job(company, x[1], loc, f"https://www.google.com/about/careers/applications/jobs/results/{x[0]}-{slug}",
                      None, strip_html(desc), "google")

def fetch_apple(company, key="", pages=3):
    for p in range(1, pages + 1):
        _, h = http(f"https://jobs.apple.com/en-us/search?sort=newest&page={p}")
        m = re.search(r'window\.__staticRouterHydrationData = JSON\.parse\(("(?:[^"\\]|\\.)*")\)', h)
        if not m: break
        sr = json.loads(json.loads(m.group(1)))["loaderData"]["search"]["searchResults"]
        for x in sr:
            L = x.get("locations") or []
            l0 = L[0] if L else {}
            loc = ", ".join(v for v in [l0.get("city"), l0.get("stateProvince"), l0.get("countryName")] if v)
            yield job(company, x.get("postingTitle"), loc + (f" +{len(L)-1} more" if len(L) > 1 else ""),
                      f"https://jobs.apple.com/en-us/details/{x.get('positionId')}/{x.get('transformedPostingTitle')}",
                      x.get("postDateInGMT"), x.get("jobSummary", ""), "apple")

def fetch_oracle_hcm(company, key, limit=50):
    """key = 'host|siteNumber'  e.g. 'eeho.fa.us2.oraclecloud.com|CX_45001'"""
    host, site = key.split("|")
    base = f"https://{host}/hcmRestApi/resources/latest"
    d = get_json(f"{base}/recruitingCEJobRequisitions?onlyData=true&expand=requisitionList.secondaryLocations"
                 f"&finder=findReqs;siteNumber={site},facetsList=NONE,limit={limit},sortBy=POSTING_DATES_DESC")
    for x in d["items"][0]["requisitionList"]:
        desc = ""
        try:
            it = get_json(f'{base}/recruitingCEJobRequisitionDetails?expand=all&onlyData=true&finder=ById;Id=%22{x["Id"]}%22,siteNumber={site}')["items"][0]
            desc = strip_html(" ".join(it.get(k) or "" for k in ("ExternalDescriptionStr", "ExternalQualificationsStr", "ExternalResponsibilitiesStr")))
        except Exception:
            pass
        yield job(company, x.get("Title"), x.get("PrimaryLocation"),
                  f"https://{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{x['Id']}", x.get("PostedDate"), desc, "oracle_hcm")

def fetch_eightfold_pcsx(company, key, limit=50):
    """key = 'host|domain'  e.g. 'apply.careers.microsoft.com|microsoft.com'"""
    host, domain = key.split("|")
    n = 0
    for start in range(0, limit, 10):
        d = get_json(f"https://{host}/api/pcsx/search?domain={domain}&query=&location=&start={start}&sort_by=timestamp")
        for p in d["data"]["positions"]:
            desc = ""
            try:
                desc = strip_html(get_json(f"https://{host}/api/pcsx/position_details?position_id={p['id']}&domain={domain}&hl=en")["data"].get("jobDescription", ""))
            except Exception:
                pass
            locs = p.get("standardizedLocations") or p.get("locations") or [""]
            yield job(company, p.get("name"), locs[0] + (f" +{len(p['locations'])-1} more" if len(p.get("locations", [])) > 1 else ""),
                      f"https://{host}/careers/job/{p['id']}", p.get("postedTs"), desc, "eightfold")
            n += 1
        if n >= limit: break

EXTRA = {"amazon": fetch_amazon, "google": fetch_google, "apple": fetch_apple,
         "oracle_hcm": fetch_oracle_hcm, "eightfold_pcsx": fetch_eightfold_pcsx}

def fetch_phenom(company, key, limit=50):
    """Phenom career sites. key = host or URL, e.g. 'careers.adobe.com' or 'https://careers.adobe.com/us/en'."""
    import urllib.parse as up
    k = key if key.startswith("http") else "https://" + key
    u = up.urlparse(k)
    path = u.path.rstrip("/")
    if "/search-results" in path:
        path = path.split("/search-results")[0]
    base = f"{u.scheme}://{u.netloc}"
    if not re.match(r"^/[a-z]{2}/[a-z]{2}$", path or ""):
        final, h = http(base + "/")      # discover the locale path (/us/en, /global/en …)
        m = re.search(r"https?://[^/]+(/[a-z]{2,6}/[a-z]{2})(?:/|$)", final) or re.search(r'href="(/[a-z]{2,6}/[a-z]{2})/search-results', h)
        path = m.group(1) if m else "/us/en"
    n = 0
    for start in range(0, limit, 10):
        _, h = http(f"{base}{path}/search-results?from={start}&s=1")
        i = h.find('"eagerLoadRefineSearch":')
        if i < 0: break
        obj, _ = json.JSONDecoder().raw_decode(h[i + len('"eagerLoadRefineSearch":'):])
        jobs = ((obj or {}).get("data") or {}).get("jobs") or []
        if not jobs: break
        for x in jobs:
            desc = (x.get("descriptionTeaser") or "") + " " + " ".join(x.get("ml_skills") or [])
            loc = x.get("cityStateCountry") or x.get("location") or ""
            more = len(x.get("multi_location") or []) - 1
            yield job(company, x.get("title"), loc + (f" +{more} more" if more > 0 else ""),
                      x.get("jobUrl") or f"{base}{path}/job/{x.get('jobId')}", x.get("postedDate"), desc, "phenom")
            n += 1
            if n >= limit: return

EXTRA["phenom"] = fetch_phenom
