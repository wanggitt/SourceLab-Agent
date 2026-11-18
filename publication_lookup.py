"""Manual, bounded title/DOI cross-check; never infer journal impact factors.

Crossref is registrant-submitted metadata; DBLP search may challenge bots.
Google Scholar is offered only as a manual browser link (not scraped).
"""

from __future__ import annotations

import difflib
import json
import re
import urllib.error
import urllib.parse
import urllib.request

AGENT = "SourceLab/0.1 (local academic metadata review; manual one-paper lookup)"


def normalized_title(value):
    return " ".join(re.findall(r"[a-z0-9]+", str(value).lower()))


def is_same_title(candidate, official, minimum=.96):
    a, b = normalized_title(candidate), normalized_title(official)
    if len(a) < 12 or len(b) < 12:
        return False
    return a == b or difflib.SequenceMatcher(
        None, a, b, autojunk=False,
    ).ratio() >= minimum


def _get_json(url, max_bytes=350_000):
    req = urllib.request.Request(
        url, headers={"User-Agent": AGENT, "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=8) as response:
        kind = response.headers.get("Content-Type", "")
        if response.status != 200 or "json" not in kind.lower():
            raise ValueError(
                "接口未提供 JSON（可能启用反机器人校验）；请手动打开官方搜索链接"
            )
        data = response.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError("出版元数据响应超过大小限制")
    return json.loads(data)


def lookup_publication(title, doi=""):
    if not isinstance(title, str) or not 12 <= len(title.strip()) <= 220:
        raise ValueError("题名需要 12–220 字符")
    if not isinstance(doi, str) or len(doi) > 180:
        raise ValueError("DOI 无效或过长")
    if doi and not re.fullmatch(r"10\.\d{4,9}/[\w./():;-]+", doi, re.I):
        raise ValueError("DOI 格式无效；不访问外部提供的 URL")
    title = " ".join(title.split())
    query = urllib.parse.quote(title, safe="")
    dblp_search = "https://dblp.org/search?q=" + query
    scholar_search = "https://scholar.google.com/scholar?q=" + query
    crossref_search = "https://search.crossref.org/?q=" + query
    result = {
        "title": title, "venue": "", "venue_source": "", "type": "",
        "doi": "", "year": "", "matches": [], "errors": [],
        "impact_factor": None,
        "impact_note": (
            "Crossref/DBLP/Google Scholar 不提供可核验的年度 JCR 期刊影响因子。"
            "会议不适用期刊影响因子；未获授权且含年份来源的 JCR 数据时不猜数。"
        ),
        "manual_links": {
            "dblp": dblp_search, "google_scholar": scholar_search,
            "crossref": crossref_search,
            "jcr": "https://jcr.clarivate.com/",
        },
        "note": ("仅对严格匹配题名的公开注册元数据给出候选出版信息；"
                 "未找到不代表未发表。Google Scholar 仅供手动打开，不自动爬取。"),
    }
    urls = []
    if doi:
        urls.append(("Crossref DOI", "https://api.crossref.org/works/"
                     + urllib.parse.quote(doi, safe="")))
    urls.append(("Crossref title", "https://api.crossref.org/works?"
                 + urllib.parse.urlencode({
                     "query.title": title, "rows": 5,
                     "select": "DOI,title,container-title,type,published,URL",
                 })))
    for source, url in urls:
        try:
            items = _get_json(url).get("message", {})
            items = items.get("items", []) if "title" in source else [items]
            for record in items:
                if not isinstance(record, dict):
                    continue
                official_title = (record.get("title") or [""])[0]
                if not is_same_title(
                    title, official_title, .93 if doi and source == "Crossref DOI"
                    else .97,
                ):
                    continue
                container = (record.get("container-title") or [""])[0].strip()
                kind = record.get("type") or ""
                record_doi = record.get("DOI") or ""
                if not container or "preprint" in kind.lower():
                    continue
                year_parts = (record.get("published") or {}).get("date-parts") or []
                year = year_parts[0][0] if year_parts and year_parts[0] else ""
                result["matches"].append({
                    "title": official_title, "venue": container,
                    "type": kind, "doi": record_doi,
                    "year": year, "source": source,
                })
                break
            if result["matches"]:
                break
        except (ValueError, KeyError, IndexError, TypeError,
                urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            result["errors"].append(f"{source}: {str(exc)[:120]}")
    try:
        data = _get_json("https://dblp.org/search/publ/api?"
                         + urllib.parse.urlencode({
                             "q": title, "h": 5, "format": "json",
                         }))
        hits = data.get("result", {}).get("hits", {}).get("hit", [])
        if isinstance(hits, dict):
            hits = [hits]
        for hit in hits[:5]:
            info = hit.get("info") or {}
            official_title = re.sub(r"<[^>]*>", "", info.get("title", ""))
            venue = info.get("venue") or ""
            if venue and is_same_title(title, official_title):
                result["matches"].append({
                    "title": official_title, "venue": venue,
                    "year": info.get("year", ""), "type": info.get("type", ""),
                    "doi": info.get("doi", ""), "source": "DBLP bibliographic index",
                })
                break
    except (ValueError, KeyError, IndexError, TypeError,
            urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        result["errors"].append("DBLP: " + str(exc)[:120])
    if result["matches"]:
        best = result["matches"][0]
        result.update({
            "venue": best["venue"], "venue_source": best["source"],
            "type": best["type"], "doi": best["doi"],
            "year": best["year"],
        })
        venues = {normalized_title(item["venue"]) for item in result["matches"]}
        if len(venues) > 1:
            result["note"] += (
                " Crossref 与 DBLP 的出版来源不一致；已列出双方候选，"
                "不可自动裁决，请人工检查正式版本。"
            )
    return result
