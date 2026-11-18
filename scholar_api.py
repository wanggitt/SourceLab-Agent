"""Optional public arXiv lookup and explicit-ID PDF download; no free-form URLs."""

from __future__ import annotations

import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV = "{http://arxiv.org/schemas/atom}"
IDENTIFIER = re.compile(r"^\d{4}\.\d{4,5}(?:v[1-9]\d*)?$")
_LOCK = threading.Lock()
_REQUEST_LOCK = threading.Lock()
_LAST_REQUEST = 0.0
USER_AGENT = "SourceLab/0.1 (local academic-assistant demo; no bulk downloads)"


def code_links(*texts):
    """Explicit repository links only; absence is NOT proof of closed source."""
    seen, urls = set(), []
    for text in texts:
        if not isinstance(text, str):
            continue
        for match in re.finditer(
            r"https?://(?:www\.)?(?:github\.com|gitlab\.com|codeberg\.org)"
            r"/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+",
            text, re.I,
        ):
            url = match.group().rstrip(".,;:)")
            if url.lower() not in seen:
                seen.add(url.lower())
                urls.append(url)
            if len(urls) >= 3:
                return urls
    return urls


def _wait_turn():
    """Conservative pacing for public arXiv requests across threads."""
    global _LAST_REQUEST
    with _LOCK:
        delay = max(0.0, 3.2 - (time.monotonic() - _LAST_REQUEST))
        if delay:
            time.sleep(delay)
        _LAST_REQUEST = time.monotonic()


def _read_feed(params):
    """Only fixed arxiv.org endpoint and validated query parameters may enter."""
    request = urllib.request.Request(
        "https://export.arxiv.org/api/query?" + urllib.parse.urlencode(params),
        headers={"User-Agent": USER_AGENT, "Accept": "application/atom+xml"},
    )
    feed = b""
    for attempt in range(2):
        try:
            # arXiv legacy API permits only a single concurrent connection.
            with _REQUEST_LOCK:
                _wait_turn()
                with urllib.request.urlopen(request, timeout=16) as response:
                    feed = response.read(1_000_001)
            break
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt:
                raise
    if len(feed) > 1_000_000:
        raise ValueError("arXiv 返回数据超出限制")
    root = ET.fromstring(feed)
    result = []
    for entry in root.findall(ATOM + "entry"):
        url = (entry.findtext(ATOM + "id") or "").strip()
        match = re.fullmatch(r"https?://(?:export\.)?arxiv\.org/abs/([^/?#]+)", url)
        identifier = match.group(1) if match else ""
        if not IDENTIFIER.fullmatch(identifier):
            continue
        summary = " ".join((entry.findtext(ATOM + "summary") or "").split())[:420]
        comment = " ".join((entry.findtext(ARXIV + "comment") or "").split())[:420]
        journal_ref = " ".join((entry.findtext(ARXIV + "journal_ref") or "").split())[:240]
        doi = " ".join((entry.findtext(ARXIV + "doi") or "").split())[:150]
        related_links = [
            link.get("href", "") for link in entry.findall(ATOM + "link")
            if link.get("rel") == "related"
        ]
        result.append({
            "identifier": identifier,
            "title": " ".join((entry.findtext(ATOM + "title") or "").split()),
            "authors": [
                " ".join((node.findtext(ATOM + "name") or "").split())
                for node in entry.findall(ATOM + "author")[:6]
            ],
            "published": (entry.findtext(ATOM + "published") or "")[:10],
            "summary": summary,
            "comment": comment,
            "journal_ref": journal_ref,
            "doi": doi,
            "code_urls": code_links(summary, comment, *related_links),
            "source": "arXiv API",
        })
    return result


def _search(value, field, max_results, newest=False):
    if not isinstance(value, str) or not 4 <= len(value.strip()) <= 160:
        raise ValueError("检索词需要 4–160 个字符")
    value = " ".join(value.split())
    return _read_feed({
        "search_query": f'{field}:"{value.replace(chr(34), "")}"',
        "start": 0, "max_results": max_results,
        "sortBy": "submittedDate" if newest else "relevance",
        "sortOrder": "descending",
    })


def lookup(title):
    """User-supplied title search, not a scholarly identity verification."""
    return _search(title, "ti", 6)


def recent(topic, limit=10):
    """Recent arXiv metadata for an explicitly requested topic; no scheduler."""
    if type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError("每次最多获取 50 条 arXiv 元数据")
    return _search(topic, "all", limit, newest=True)


def metadata(identifier):
    """Resolve an exact numeric arXiv identifier via id_list, not title search."""
    if not isinstance(identifier, str) or not IDENTIFIER.fullmatch(identifier):
        raise ValueError("仅接受数字型 arXiv ID")
    requested = re.sub(r"v[1-9]\d*$", "", identifier)
    for candidate in _read_feed({"id_list": identifier, "max_results": 1}):
        if re.sub(r"v[1-9]\d*$", "", candidate["identifier"]) == requested:
            return candidate
    raise ValueError("arXiv 未返回该编号的元数据；禁止无核对下载")


def download(identifier, destination, max_bytes=30 * 1024 * 1024):
    if not isinstance(identifier, str) or not IDENTIFIER.fullmatch(identifier):
        raise ValueError("仅接受 arXiv 返回的数字型 ID，例如 1706.03762v7")
    folder = Path(destination)
    folder.mkdir(parents=True, exist_ok=True)
    file_path = folder / (uuid.uuid4().hex + ".pdf")
    request = urllib.request.Request(
        "https://arxiv.org/pdf/" + identifier,
        headers={"User-Agent": USER_AGENT, "Accept": "application/pdf"},
    )
    for attempt in range(2):
        try:
            with _REQUEST_LOCK:
                _wait_turn()
                with urllib.request.urlopen(request, timeout=30) as response, file_path.open("wb") as target:
                    content_type = response.headers.get("Content-Type", "").lower()
                    if "pdf" not in content_type:
                        raise ValueError("arXiv 未返回 PDF 文件")
                    written = 0
                    first = True
                    while True:
                        block = response.read(65536)
                        if not block:
                            break
                        if first:
                            if not block.startswith(b"%PDF-"):
                                raise ValueError("返回内容不是有效的 PDF")
                            first = False
                        written += len(block)
                        if written > max_bytes:
                            raise ValueError("论文超过上传大小限制（30 MB）")
                        target.write(block)
                    if not written:
                        raise ValueError("arXiv 返回空文件")
            return file_path
        except (urllib.error.URLError, TimeoutError, OSError):
            file_path.unlink(missing_ok=True)
            if attempt:
                raise
        except Exception:
            file_path.unlink(missing_ok=True)
            raise
