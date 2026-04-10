"""네이버 블로그 크롤러

네이버 블로그 포스트의 본문과 제목을 추출하여 마크다운 형태로 반환한다.
TypeScript 원본: App_Blog/src/lib/crawlers/naver.ts

Dependencies:
    - httpx (async HTTP)
    - beautifulsoup4 (HTML parsing)
    - chardet (encoding detection)
"""

from __future__ import annotations

import re
from urllib.parse import urlparse, parse_qs

import chardet
import httpx
from bs4 import BeautifulSoup, Tag

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FETCH_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
}

TITLE_SELECTORS: list[str] = [
    ".se-title-text",
    ".pcol1 .itemSubjectBoldfont",
    ".se_title .se_textView",
    "h3.se_textarea",
    ".tit_h3",
]

CONTENT_SELECTORS: list[str] = [
    ".se-main-container",
    "#postViewArea",
    ".se_component_wrap",
]

# ---------------------------------------------------------------------------
# URL Parsing
# ---------------------------------------------------------------------------


def parse_naver_blog_url(url: str) -> tuple[str, str] | None:
    """네이버 블로그 URL에서 blogId와 logNo를 추출한다.

    지원하는 URL 패턴:
        1. /PostView.naver?blogId=xxx&logNo=yyy
        2. /username/123456

    Args:
        url: 네이버 블로그 URL.

    Returns:
        (blogId, logNo) 튜플 또는 인식 불가 시 None.
    """
    parsed = urlparse(url)

    # Pattern 1: query parameters
    params = parse_qs(parsed.query)
    blog_id_list = params.get("blogId")
    log_no_list = params.get("logNo")
    if blog_id_list and log_no_list:
        return (blog_id_list[0], log_no_list[0])

    # Pattern 2: /username/123456
    path_match = re.match(r"^/([^/]+)/(\d+)$", parsed.path)
    if path_match:
        return (path_match.group(1), path_match.group(2))

    return None


# ---------------------------------------------------------------------------
# Encoding Detection
# ---------------------------------------------------------------------------


def _extract_charset_from_content_type(content_type: str) -> str | None:
    """Content-Type 헤더에서 charset 값을 추출한다."""
    match = re.search(r"charset=([^\s;]+)", content_type, re.IGNORECASE)
    return match.group(1).strip() if match else None


def _is_utf8(charset: str) -> bool:
    """charset 문자열이 UTF-8 계열인지 판별한다."""
    normalized = charset.lower().replace("-", "").replace("_", "")
    return normalized == "utf8"


def detect_encoding(response: httpx.Response) -> str:
    """HTTP 응답의 인코딩을 감지한다.

    확인 순서:
        1. Content-Type 헤더의 charset
        2. HTML <meta charset="..."> 태그
        3. chardet 라이브러리 자동 감지
        4. 기본값 utf-8

    Args:
        response: httpx.Response 객체.

    Returns:
        감지된 인코딩 이름 (예: 'utf-8', 'euc-kr').
    """
    # 1. Content-Type 헤더
    content_type = response.headers.get("content-type", "")
    header_charset = _extract_charset_from_content_type(content_type)
    if header_charset and not _is_utf8(header_charset):
        return header_charset

    # 2. HTML meta 태그 (raw bytes의 앞부분을 ASCII로 스캔)
    raw = response.content
    preview = raw[:4096].decode("ascii", errors="ignore")

    meta_match = re.search(
        r'<meta[^>]+charset=["\']?([^"\'\s;>]+)', preview, re.IGNORECASE
    )
    if not meta_match:
        meta_match = re.search(
            r'<meta[^>]+content=["\'][^"\']*charset=([^"\'\s;>]+)',
            preview,
            re.IGNORECASE,
        )
    if meta_match:
        meta_charset = meta_match.group(1)
        if not _is_utf8(meta_charset):
            return meta_charset

    # 3. chardet 자동 감지
    detected = chardet.detect(raw[:8192])
    if detected and detected.get("encoding"):
        enc = detected["encoding"]
        confidence = detected.get("confidence", 0)
        if confidence > 0.7 and not _is_utf8(enc):
            return enc

    # 4. 기본값
    return "utf-8"


def _decode_response(response: httpx.Response) -> str:
    """응답 바이트를 올바른 인코딩으로 디코딩한다."""
    encoding = detect_encoding(response)
    try:
        return response.content.decode(encoding)
    except (UnicodeDecodeError, LookupError):
        return response.content.decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Text Extraction
# ---------------------------------------------------------------------------


def extract_naver_text(soup: BeautifulSoup, element: Tag) -> str:
    """네이버 블로그 요소에서 텍스트를 추출하고 마크다운으로 변환한다.

    처리하는 태그:
        - h2/h3/h4 -> ##/###/#### 접두사
        - li -> - 접두사
        - blockquote -> > 접두사
        - p, span.se-text-paragraph, div.se-text-paragraph -> 일반 텍스트

    연속 중복 라인은 자동 제거한다.

    Args:
        soup: BeautifulSoup 인스턴스.
        element: 본문 컨테이너 태그.

    Returns:
        마크다운 형식 텍스트.
    """
    blocks: list[str] = []

    target_tags = element.select(
        "h2, h3, h4, p, li, "
        "span.se-text-paragraph, div.se-text-paragraph, blockquote"
    )

    for child in target_tags:
        tag_name = child.name if child.name else ""
        text = child.get_text(strip=True)
        if not text:
            continue

        if tag_name.startswith("h") and len(tag_name) == 2 and tag_name[1].isdigit():
            level = int(tag_name[1])
            blocks.append(f"{'#' * level} {text}")
        elif tag_name == "li":
            blocks.append(f"- {text}")
        elif tag_name == "blockquote":
            blocks.append(f"> {text}")
        elif len(text) > 2:
            blocks.append(text)

    # 연속 중복 제거
    deduped: list[str] = []
    for block in blocks:
        if not deduped or deduped[-1] != block:
            deduped.append(block)

    return "\n\n".join(deduped)


# ---------------------------------------------------------------------------
# Main Crawl Function
# ---------------------------------------------------------------------------


async def crawl_naver_blog(url: str) -> dict:
    """네이버 블로그 포스트를 크롤링한다.

    Args:
        url: 네이버 블로그 포스트 URL.

    Returns:
        dict with keys:
            - title (str): 포스트 제목.
            - content (str): 마크다운 형식 본문.
            - platform (str): 항상 'naver'.

    Raises:
        ValueError: URL 형식을 인식할 수 없는 경우.
        httpx.HTTPStatusError: HTTP 요청 실패 시.
        RuntimeError: 콘텐츠 추출 실패 시.
    """
    params = parse_naver_blog_url(url)
    if params is None:
        raise ValueError(
            "네이버 블로그 URL 형식을 인식할 수 없습니다. "
            "(예: blog.naver.com/아이디/글번호)"
        )

    blog_id, log_no = params
    post_url = (
        f"https://blog.naver.com/PostView.naver"
        f"?blogId={blog_id}&logNo={log_no}&directAccess=true"
    )

    async with httpx.AsyncClient(
        headers=FETCH_HEADERS,
        follow_redirects=True,
        timeout=30.0,
    ) as client:
        response = await client.get(post_url)
        response.raise_for_status()

    html = _decode_response(response)
    soup = BeautifulSoup(html, "html.parser")

    # 불필요한 요소 제거
    for selector in ("script", "style", ".se-oglink-container", ".se-section-oglink"):
        for tag in soup.select(selector):
            tag.decompose()

    # 제목 추출
    title = ""
    for sel in TITLE_SELECTORS:
        el = soup.select_one(sel)
        if el and el.get_text(strip=True):
            title = el.get_text(strip=True)
            break
    if not title:
        title_tag = soup.find("title")
        if title_tag:
            title = title_tag.get_text(strip=True)

    # 본문 추출
    content = ""
    for sel in CONTENT_SELECTORS:
        el = soup.select_one(sel)
        if el:
            content = extract_naver_text(soup, el)
            if len(content) > 100:
                break

    # Fallback: 모든 p 태그에서 추출
    if len(content) < 100:
        paragraphs: list[str] = []
        for el in soup.select("p, .se-text-paragraph"):
            text = el.get_text(strip=True)
            if len(text) > 5:
                paragraphs.append(text)
        fallback = "\n\n".join(paragraphs)
        if len(fallback) > len(content):
            content = fallback

    if not content or len(content) < 50:
        raise RuntimeError(
            "네이버 블로그에서 콘텐츠를 추출할 수 없습니다. "
            "비공개 글이거나 접근이 제한된 글일 수 있습니다."
        )

    return {
        "title": title,
        "content": content,
        "platform": "naver",
    }
