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
ALLOWED_TYPES = frozenset({
    "text/html", "text/plain", "application/json", "application/pdf",
    "application/rss+xml", "application/atom+xml", "application/xml",
    "text/xml",
})
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_EXTRACTED_CHARS = 24000
MAX_REDIRECTS = 4
# News and other landing pages commonly put their actual document links after
# a large navigation header.  Keep the encounter bounded, but do not amputate
# it at the first menu-sized handful of links.
MAX_ENCOUNTERED_LINKS = 96


@dataclass(frozen=True)
class WebRangeEntry:
    entry_id: str
    host: str
    source_class: str = "public_reference"
    volatility: str = "medium"
    include_subdomains: bool = False
    discovery_url: str = ""
    discovery_terms: tuple[str, ...] = ()
    discovery_path_prefixes: tuple[str, ...] = ()

    def __post_init__(self):
        host = str(self.host or "").strip().casefold().rstrip(".")
        if not host or "/" in host or ":" in host:
            raise WebResearchError("web range host is invalid")
        if self.volatility not in {"low", "medium", "high"}:
            raise WebResearchError("web range volatility is invalid")
        object.__setattr__(self, "host", host)
        object.__setattr__(self, "entry_id", str(self.entry_id or host)[:120])
        object.__setattr__(
            self, "source_class",
            str(self.source_class or "public_reference")[:80])
        discovery_url = str(self.discovery_url or "").strip()
        if discovery_url:
            parsed = urlparse(discovery_url)
            discovery_host = (parsed.hostname or "").casefold().rstrip(".")
            if (parsed.scheme.casefold() != "https" or not discovery_host
                    or parsed.username or parsed.password
                    or not self.admits(discovery_host)):
                raise WebResearchError(
                    "web range discovery URL must stay on its admitted host")
        terms = tuple(dict.fromkeys(
            " ".join(str(value or "").casefold().split())[:120]
            for value in self.discovery_terms
            if " ".join(str(value or "").split())))
        if discovery_url and not terms:
            raise WebResearchError(
                "web range discovery URL requires matching terms")
        prefixes = tuple(dict.fromkeys(
            str(value or "").strip() for value in
            self.discovery_path_prefixes
            if str(value or "").strip()))
        if any(not value.startswith("/") or ".." in value
               for value in prefixes):
            raise WebResearchError(
                "web range discovery path prefix is invalid")
        object.__setattr__(self, "discovery_url", discovery_url)
        object.__setattr__(self, "discovery_terms", terms)
        object.__setattr__(self, "discovery_path_prefixes", prefixes)

    def admits(self, host: str) -> bool:
        host = str(host or "").casefold().rstrip(".")
        return host == self.host or (
            self.include_subdomains and host.endswith("." + self.host))


class WebRangePolicy:
    """Resident-scoped permission to read, distinct from source credibility."""

    def __init__(self, entries=(), *, mode="public_web"):
        if mode not in {"public_web", "permitted_only"}:
            raise WebResearchError("web range mode is invalid")
        self.mode = mode
        self.entries = tuple(entries)
        if mode == "permitted_only" and not self.entries:
            raise WebResearchError("permitted-only web range is empty")

    @classmethod
    def from_config(cls, raw=None):
        raw = dict(raw or {})
        entries = []
        for value in raw.get("entries") or ():
            value = dict(value or {})
            entries.append(WebRangeEntry(
                entry_id=value.get("id") or value.get("host"),
                host=value.get("host"),
                source_class=value.get("source_class", "public_reference"),
                volatility=value.get("volatility", "medium"),
                include_subdomains=bool(value.get("include_subdomains", False)),
                discovery_url=value.get("discovery_url", ""),
                discovery_terms=tuple(value.get("discovery_terms") or ()),
                discovery_path_prefixes=tuple(
                    value.get("discovery_path_prefixes") or ())))
        return cls(entries, mode=str(raw.get("mode") or "public_web"))

    def matching_discovery_entries(self, query: str):
        """Return explicitly configured native indexes relevant to a query."""
        query = " ".join(str(query or "").casefold().split())
        ranked = []
        for index, entry in enumerate(self.entries):
            matches = sum(term in query for term in entry.discovery_terms)
            if entry.discovery_url and matches:
                ranked.append((matches, -index, entry))
        return tuple(item[2] for item in sorted(ranked, reverse=True))

    def classify(self, url: str) -> dict:
        host = (urlparse(str(url or "")).hostname or "").casefold().rstrip(".")
        for entry in self.entries:
            if entry.admits(host):
                return {
                    "web_range_id": entry.entry_id,
                    "source_class": entry.source_class,
                    "volatility": entry.volatility,
                    "permission": "resident_web_range",
                }
        if self.mode == "permitted_only":
            raise WebResearchError(
                "research destination is outside the resident web range")
        return {
            "web_range_id": "public_web",
            "source_class": "unclassified_public",
            "volatility": "medium",
            "permission": "public_web",
        }

    def search_guidance(self) -> str:
        if self.mode != "permitted_only":
            return "The public web boundary will classify each admitted result."
        groups = {}
        for entry in self.entries:
            groups[entry.source_class] = groups.get(entry.source_class, 0) + 1
        rendered = "; ".join(
            f"{source_class} ({count})"
            for source_class, count in sorted(groups.items()))
        return (
            "The host admits results only inside this resident Web Range: "
            f"{len(self.entries)} configured habitats across {rendered}. "
            "Do not invent hostnames. An exact hostname already present in "
            "the admitted evidence may be used with site:host to narrow. "
            "Permission is not evidence of credibility.")


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
        if ({"result__a", "result-link"} & classes
                and values.get("href")):
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


class _LinkExtractor(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self._rows = []
        self._current = None
        self._article_depth = 0
        self._navigation_depth = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.casefold()
        values = dict(attrs)
        if tag == "article":
            self._article_depth += 1
        if tag in {"nav", "header", "footer"}:
            self._navigation_depth += 1
        if tag == "img" and self._current is not None:
            alt = str(values.get("alt") or "").strip()
            if alt:
                self._current["image_alt"].append(alt)
            return
        if tag != "a":
            return
        href = values.get("href")
        if not href:
            return
        url = urljoin(self.base_url, html.unescape(str(href)))
        if url.startswith(("http://", "https://")):
            self._current = {
                "url": url,
                "text": [],
                "image_alt": [],
                "in_article": self._article_depth > 0,
                "in_navigation": self._navigation_depth > 0,
            }

    def handle_data(self, data):
        if self._current is not None:
            self._current["text"].append(str(data or ""))

    def handle_endtag(self, tag):
        tag = tag.casefold()
        if tag == "a" and self._current is not None:
            row = self._current
            self._current = None
            visible = " ".join(" ".join(row["text"]).split())[:300]
            image_alt = " ".join(
                " ".join(row["image_alt"]).split())[:300]
            row["text"] = visible or image_alt
            row["visible_text"] = bool(visible)
            prior = next(
                (item for item in self._rows if item["url"] == row["url"]),
                None)
            if prior is None:
                self._rows.append(row)
            else:
                if (row.get("visible_text") and not prior.get("visible_text")):
                    prior["text"] = row["text"]
                    prior["visible_text"] = True
                elif (bool(row.get("visible_text")) == bool(
                        prior.get("visible_text"))
                        and len(row["text"]) > len(prior.get("text") or "")):
                    prior["text"] = row["text"]
                prior["in_article"] = bool(
                    prior.get("in_article") or row["in_article"])
                prior["in_navigation"] = bool(
                    prior.get("in_navigation") and row["in_navigation"])
        if tag == "article" and self._article_depth:
            self._article_depth -= 1
        if tag in {"nav", "header", "footer"} and self._navigation_depth:
            self._navigation_depth -= 1

    @staticmethod
    def _document_likelihood(row):
        """Rank encountered documents above short navigational furniture."""
        parsed = urlparse(row["url"])
        parts = [part for part in parsed.path.split("/") if part]
        words = re.findall(r"[A-Za-z0-9']+", row.get("text") or "")
        descriptive = min(len(words), 14) / 14.0
        path_depth = min(len(parts), 6) / 6.0
        opaque_document_id = any(
            len(part) >= 16 and re.fullmatch(r"[A-Za-z0-9_-]+", part)
            for part in parts)
        return (
            round(.43 * descriptive + .20 * path_depth
                  + .12 * float(opaque_document_id)
                  + .35 * float(bool(row.get("in_article")))
                  - .35 * float(bool(row.get("in_navigation"))), 6),
            len(words), len(row.get("text") or ""))

    @property
    def documents(self):
        ranked = sorted(
            enumerate(self._rows),
            key=lambda item: (
                *self._document_likelihood(item[1]), -item[0]),
            reverse=True)
        return tuple({"url": row["url"], "title": row.get("text") or ""}
                     for _index, row in ranked)

    @property
    def links(self):
        return [row["url"] for row in self.documents]


@dataclass(frozen=True)
class WebEvidence:
    url: str
    title: str
    text: str
    content_type: str
    page_count: int = 0
    extracted_pages: tuple[int, ...] = ()
    extraction_truncated: bool = False
    web_range_id: str = "public_web"
    source_class: str = "unclassified_public"
    volatility: str = "medium"
    permission: str = "public_web"
    links: tuple[str, ...] = ()


class ReadOnlyWebResearch:
    """Bounded search/fetch transport with dependency injection for tests."""

    def __init__(self, *, client=None, resolver=socket.getaddrinfo,
                 policy=None,
                 search_url: str = "https://html.duckduckgo.com/html/",
                 fallback_search_url: str =
                 "https://lite.duckduckgo.com/lite/"):
        self.client = client or httpx.Client(
            timeout=httpx.Timeout(15.0, connect=8.0), follow_redirects=False,
            headers={"User-Agent": "JNSQ-ResearchDesk/1.0 (read-only)"})
        self.resolver = resolver
        self.search_url = search_url
        self.fallback_search_url = fallback_search_url
        self.policy = policy or WebRangePolicy()
        self.last_search_attempts = ()

    def _request(self, url: str) -> httpx.Response:
        headers = {"Accept": (
            "text/html,text/plain,application/pdf,application/json,"
            "application/rss+xml,application/atom+xml,application/xml,text/xml;q=0.8")}
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

    def _get(self, url: str, *, search_transport=False,
             search_host: str = "") -> tuple[httpx.Response, str]:
        current = validate_public_url(url, resolver=self.resolver)
        search_host = (str(search_host or "") or
                       (urlparse(self.search_url).hostname or "")).casefold()
        if not search_transport:
            self.policy.classify(current)
        for _hop in range(MAX_REDIRECTS + 1):
            response = self._request(current)
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                if not location:
                    raise WebResearchError("research redirect had no destination")
                current = validate_public_url(
                    urljoin(current, location), resolver=self.resolver)
                if search_transport:
                    if (urlparse(current).hostname or "").casefold() != search_host:
                        raise WebResearchError(
                            "research search transport redirect escaped its host")
                else:
                    self.policy.classify(current)
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
        limit = max(1, min(int(limit), 10))
        attempts = []
        for search_url in dict.fromkeys(filter(None, (
                self.search_url, self.fallback_search_url))):
            url = f"{search_url}?q={quote_plus(query)}"
            try:
                response, _final = self._get(
                    url, search_transport=True,
                    search_host=(urlparse(search_url).hostname or ""))
                parser = _SearchParser()
                parser.feed(self._bounded_body(response).decode(
                    "utf-8", "replace"))
                found = []
                for row in parser.results:
                    try:
                        validate_public_url(row["url"], resolver=self.resolver)
                        classification = self.policy.classify(row["url"])
                    except WebResearchError:
                        continue
                    if row["url"] not in {item["url"] for item in found}:
                        found.append({**row, **classification})
                    if len(found) >= limit:
                        break
                attempts.append({
                    "host": (urlparse(search_url).hostname or "")[:120],
                    "status": "results" if found else "empty",
                    "result_count": len(found),
                })
                if found:
                    self.last_search_attempts = tuple(attempts)
                    return found
            except Exception as exc:
                attempts.append({
                    "host": (urlparse(search_url).hostname or "")[:120],
                    "status": "failed",
                    "error_type": type(exc).__name__,
                })
        # A configured native index is not a generic crawler. It is a bounded
        # recovery edge from a failed discovery provider into a resident-owned
        # Web Range habitat whose matching terms are explicit in the roster.
        # Read every matching index once, then interleave their encountered
        # documents so one publisher cannot crowd the whole result set.
        native_rows = []
        for entry in self.policy.matching_discovery_entries(query):
            rows = []
            try:
                response, final_url = self._get(entry.discovery_url)
                content_type = response.headers.get(
                    "content-type", "").split(";", 1)[0].casefold()
                if content_type != "text/html":
                    raise WebResearchError(
                        "native discovery source is not HTML")
                parser = _LinkExtractor(final_url)
                parser.feed(self._bounded_body(response).decode(
                    "utf-8", "replace"))
                for row in parser.documents:
                    path = urlparse(row["url"]).path
                    if (entry.discovery_path_prefixes
                            and not any(path.startswith(prefix) for prefix in
                                        entry.discovery_path_prefixes)):
                        continue
                    try:
                        validate_public_url(row["url"], resolver=self.resolver)
                        classification = self.policy.classify(row["url"])
                    except WebResearchError:
                        continue
                    rows.append({
                        "title": (row.get("title") or
                                  urlparse(row["url"]).path.rsplit("/", 2)[-1]
                                  or entry.host)[:300],
                        "url": row["url"], **classification,
                    })
                    if len(rows) >= limit:
                        break
                attempts.append({
                    "host": entry.host[:120],
                    "status": "native_results" if rows else "native_empty",
                    "result_count": len(rows),
                })
            except Exception as exc:
                attempts.append({
                    "host": entry.host[:120],
                    "status": "native_failed",
                    "error_type": type(exc).__name__,
                })
            native_rows.append(rows)
        found = []
        while native_rows and len(found) < limit:
            progressed = False
            for rows in native_rows:
                if not rows or len(found) >= limit:
                    continue
                row = rows.pop(0)
                if row["url"] not in {item["url"] for item in found}:
                    found.append(row)
                progressed = True
            if not progressed:
                break
        self.last_search_attempts = tuple(attempts)
        return found

    def fetch(self, url: str) -> WebEvidence:
        response, final_url = self._get(url)
        classification = self.policy.classify(final_url)
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
            links = ()
            if content_type == "text/html":
                parser = _LinkExtractor(final_url)
                parser.feed(raw.decode("utf-8", "replace"))
                admitted = []
                for link in parser.links:
                    try:
                        self.policy.classify(link)
                    except WebResearchError:
                        continue
                    admitted.append(link)
                    if len(admitted) >= MAX_ENCOUNTERED_LINKS:
                        break
                links = tuple(admitted)
            page_count = 0
            extracted_pages = ()
            extraction_truncated = False
        if content_type == "application/pdf":
            links = ()
        if not text:
            raise WebResearchError("research source contained no readable text")
        return WebEvidence(
            final_url, title or urlparse(final_url).hostname or
            "Untitled source", text, content_type,
            page_count=page_count, extracted_pages=extracted_pages,
            extraction_truncated=extraction_truncated, links=links,
            **classification)
