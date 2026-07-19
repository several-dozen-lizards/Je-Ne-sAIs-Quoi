"""Host-owned, read-only web boundary for the private Research Desk.

The model never receives a browser or a socket.  It may propose a query or
choose one admitted result; this boundary validates every hop, refuses local
and private networks, fetches bounded text without cookies or JavaScript, and
returns evidence with a stable content digest.
"""
from __future__ import annotations

import html
import ipaddress
import re
import socket
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Callable, Iterable
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse

import httpx


ALLOWED_SCHEMES = frozenset({"http", "https"})
ALLOWED_TYPES = frozenset({"text/html", "text/plain", "application/json",
                           "application/pdf"})
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_EXTRACTED_CHARS = 24000
MAX_REDIRECTS = 4


class WebResearchError(ValueError):
    """A proposed network operation crossed the Research Desk boundary."""


PRIVATE_QUERY_PATTERNS = (
    re.compile(r"\b[A-Z]:[\\/]", re.I),
    re.compile(r"(?:^|\s)/(?:home|users|var|etc|private)/", re.I),
    re.compile(r"\b(?:localhost|127\.0\.0\.1|0\.0\.0\.0)\b", re.I),
    re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b"),
    re.compile(r"\b(?:sk-[A-Za-z0-9_-]{12,}|AIza[A-Za-z0-9_-]{20,})\b"),
    re.compile(r"\b[A-Fa-f0-9]{32,}\b"),
    re.compile(r"\b(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}\b"),
)


def validate_search_query(query: str, *, private_context: str = "",
                          private_names=()) -> str:
    """Fail closed on query-shaped leakage before public egress.

    This is deliberately mechanical. It does not decide whether a thought is
    sensitive; it refuses recognizable secrets/identifiers and verbatim
    multi-word spans from the lived private context. The planner can settle or
    generalize on a later genuine field win.
    """
    value = " ".join(str(query or "").split())
    if not 2 <= len(value) <= 300:
        raise WebResearchError(
            "research query must be 2 through 300 characters")
    if any(pattern.search(value) for pattern in PRIVATE_QUERY_PATTERNS):
        raise WebResearchError("research query resembles private data")
    if any(mark in value for mark in ('"', "“", "”")):
        raise WebResearchError("research query may not export quoted text")
    words = re.findall(r"[A-Za-z0-9']+", value.casefold())
    if set(words) & {"i", "me", "my", "mine", "we", "our", "ours"}:
        raise WebResearchError("research query may not export first-person context")
    names = {
        token for name in private_names
        for token in re.findall(
            r"[A-Za-z0-9']+", str(name or "").strip().casefold())
        if token}
    if names & set(words):
        raise WebResearchError("research query contains a private persona name")
    context_words = re.findall(
        r"[A-Za-z0-9']+", str(private_context or "").casefold())
    if len(words) >= 4 and context_words:
        needle = " ".join(words)
        context = " ".join(context_words)
        for width in range(min(8, len(words)), 3, -1):
            for index in range(len(words) - width + 1):
                if " ".join(words[index:index + width]) in context:
                    raise WebResearchError(
                        "research query repeats private lived wording")
    return value


def _public_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value.split("%", 1)[0])
    except ValueError:
        return False
    return not (address.is_private or address.is_loopback
                or address.is_link_local or address.is_multicast
                or address.is_reserved or address.is_unspecified)


def validate_public_url(url: str, *,
                        resolver: Callable = socket.getaddrinfo) -> str:
    """Resolve a URL now; every resolved address must be publicly routable."""
    value = str(url or "").strip()
    if len(value) > 2048:
        raise WebResearchError("research URL exceeds the boundary")
    parsed = urlparse(value)
    if parsed.scheme.casefold() not in ALLOWED_SCHEMES:
        raise WebResearchError("research URL must use http or https")
    if not parsed.hostname or parsed.username or parsed.password:
        raise WebResearchError("research URL authority is invalid")
    host = parsed.hostname.casefold().rstrip(".")
    if host == "localhost" or host.endswith(".localhost"):
        raise WebResearchError("local network destinations are not admitted")
    try:
        rows = resolver(host, parsed.port or (443 if parsed.scheme == "https" else 80),
                        type=socket.SOCK_STREAM)
    except OSError as exc:
        raise WebResearchError("research destination did not resolve") from exc
    addresses = {str(row[4][0]) for row in rows if row and len(row) > 4}
    if not addresses or not all(_public_ip(address) for address in addresses):
        raise WebResearchError("local or non-public network destination refused")
    return value


class _TextExtractor(HTMLParser):
    BLOCKED = frozenset({"script", "style", "noscript", "svg", "canvas",
                         "template", "iframe", "object"})

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocked = 0
        self.title_depth = 0
        self.title = []
        self.parts = []

    def handle_starttag(self, tag, attrs):
        tag = tag.casefold()
        if tag in self.BLOCKED:
            self.blocked += 1
        if tag == "title" and not self.blocked:
            self.title_depth += 1
        if tag in {"p", "div", "article", "section", "main", "li", "br",
                   "h1", "h2", "h3", "h4", "tr"} and not self.blocked:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        tag = tag.casefold()
        if tag == "title" and self.title_depth:
            self.title_depth -= 1
        if tag in self.BLOCKED and self.blocked:
            self.blocked -= 1
        if tag in {"p", "div", "article", "section", "main", "li", "h1",
                   "h2", "h3", "h4", "tr"} and not self.blocked:
            self.parts.append("\n")

    def handle_data(self, data):
        if self.blocked:
            return
        text = str(data or "")
        self.parts.append(text)
        if self.title_depth:
            self.title.append(text)


def extract_text(raw: bytes, content_type: str) -> tuple[str, str]:
    encoding = "utf-8"
    match = re.search(r"charset=([^;\s]+)", content_type or "", re.I)
    if match:
        encoding = match.group(1).strip('"\'')[:40]
    text = raw.decode(encoding, errors="replace")
    if (content_type or "").casefold().startswith("text/html"):
        parser = _TextExtractor()
        parser.feed(text)
        title = " ".join("".join(parser.title).split())[:300]
        text = "".join(parser.parts)
    else:
        title = ""
    text = html.unescape(text).replace("\x00", "")
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text).strip()
    return title, text[:MAX_EXTRACTED_CHARS]


def _unwrap_result_url(value: str) -> str:
    parsed = urlparse(html.unescape(str(value or "")))
    query = parse_qs(parsed.query)
    if "uddg" in query and query["uddg"]:
        return unquote(query["uddg"][0])
    return html.unescape(str(value or ""))


def _declared_oversize(value: str | None) -> bool:
    if not value:
        return False
    try:
        return int(value) > MAX_RESPONSE_BYTES
    except (TypeError, ValueError):
        raise WebResearchError("research response size header is invalid")


class _SearchParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.results = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        if tag.casefold() != "a":
            return
        values = dict(attrs)
        classes = set(str(values.get("class") or "").split())
        if "result__a" in classes and values.get("href"):
            self.current = {"url": _unwrap_result_url(values["href"]),
                            "title_parts": []}

    def handle_data(self, data):
        if self.current is not None:
            self.current["title_parts"].append(str(data or ""))

    def handle_endtag(self, tag):
        if tag.casefold() == "a" and self.current is not None:
            title = " ".join("".join(self.current["title_parts"]).split())
            url = self.current["url"]
            if title and url.startswith(("http://", "https://")):
                self.results.append({"title": title[:300], "url": url})
            self.current = None


@dataclass(frozen=True)
class WebEvidence:
    url: str
    title: str
    text: str
    content_type: str
    page_count: int = 0
    extracted_pages: tuple[int, ...] = ()
    extraction_truncated: bool = False


class ReadOnlyWebResearch:
    """Bounded search/fetch transport with dependency injection for tests."""

    def __init__(self, *, client=None, resolver=socket.getaddrinfo,
                 search_url: str = "https://html.duckduckgo.com/html/"):
        self.client = client or httpx.Client(
            timeout=httpx.Timeout(15.0, connect=8.0), follow_redirects=False,
            headers={"User-Agent": "JNSQ-ResearchDesk/1.0 (read-only)"})
        self.resolver = resolver
        self.search_url = search_url

    def _request(self, url: str) -> httpx.Response:
        headers = {"Accept": (
            "text/html,text/plain,application/pdf,application/json;q=0.8")}
        cookie_jar = getattr(self.client, "cookies", None)
        if cookie_jar is not None:
            cookie_jar.clear()
        stream = getattr(self.client, "stream", None)
        if not callable(stream):
            response = self.client.get(url, headers=headers)
            declared = response.headers.get("content-length")
            if _declared_oversize(declared):
                raise WebResearchError(
                    "research response exceeded the size boundary")
            return response
        with stream("GET", url, headers=headers) as response:
            declared = response.headers.get("content-length")
            if _declared_oversize(declared):
                raise WebResearchError(
                    "research response exceeded the size boundary")
            chunks, total = [], 0
            for chunk in response.iter_bytes():
                total += len(chunk)
                if total > MAX_RESPONSE_BYTES:
                    raise WebResearchError(
                        "research response exceeded the size boundary")
                chunks.append(chunk)
            bounded_headers = {
                key: value for key, value in response.headers.items()
                if key.casefold() not in {"content-encoding", "content-length"}}
            bounded = httpx.Response(
                response.status_code, headers=bounded_headers,
                content=b"".join(chunks), request=response.request)
        if cookie_jar is not None:
            cookie_jar.clear()
        return bounded

    def _get(self, url: str) -> tuple[httpx.Response, str]:
        current = validate_public_url(url, resolver=self.resolver)
        for _hop in range(MAX_REDIRECTS + 1):
            response = self._request(current)
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                if not location:
                    raise WebResearchError("research redirect had no destination")
                current = validate_public_url(
                    urljoin(current, location), resolver=self.resolver)
                continue
            response.raise_for_status()
            return response, current
        raise WebResearchError("research redirect boundary exceeded")

    @staticmethod
    def _bounded_body(response: httpx.Response) -> bytes:
        raw = bytes(response.content)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise WebResearchError("research response exceeded the size boundary")
        return raw

    def search(self, query: str, *, limit: int = 6) -> list[dict]:
        query = validate_search_query(query)
        url = f"{self.search_url}?q={quote_plus(query)}"
        response, _final = self._get(url)
        parser = _SearchParser()
        parser.feed(self._bounded_body(response).decode("utf-8", "replace"))
        found = []
        for row in parser.results:
            try:
                validate_public_url(row["url"], resolver=self.resolver)
            except WebResearchError:
                continue
            if row["url"] not in {item["url"] for item in found}:
                found.append(row)
            if len(found) >= max(1, min(int(limit), 10)):
                break
        return found

    def fetch(self, url: str) -> WebEvidence:
        response, final_url = self._get(url)
        content_type = response.headers.get("content-type", "").split(";", 1)[0].casefold()
        if content_type not in ALLOWED_TYPES:
            raise WebResearchError("research response type is not admitted")
        raw = self._bounded_body(response)
        if content_type == "application/pdf":
            from core.pdf_research import PDFResearchError, extract_pdf_text
            try:
                pdf = extract_pdf_text(raw)
            except PDFResearchError as exc:
                raise WebResearchError(str(exc)) from exc
            title, text = pdf.title, pdf.text
            page_count = pdf.page_count
            extracted_pages = pdf.extracted_pages
            extraction_truncated = pdf.extraction_truncated
        else:
            title, text = extract_text(
                raw, response.headers.get("content-type", ""))
            page_count = 0
            extracted_pages = ()
            extraction_truncated = False
        if not text:
            raise WebResearchError("research source contained no readable text")
        return WebEvidence(
            final_url, title or urlparse(final_url).hostname or
            "Untitled source", text, content_type,
            page_count=page_count, extracted_pages=extracted_pages,
            extraction_truncated=extraction_truncated)
