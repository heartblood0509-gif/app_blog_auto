"""네이버 블로그 금지어 검사 및 대체

네이버 블로그에서 검색 노출이 제한되는 금지어를 탐지하고,
안전한 대체어로 자동 치환하는 모듈.

Reference: App_Blog/src/lib/prompts.ts NAVER_FORBIDDEN_WORDS_SECTION
"""

from __future__ import annotations

import re

# ── 문맥과 무관하게 위험한 단어 (대체어 사용 필수) ──────────────────────────
FORBIDDEN_REPLACEMENTS: dict[str, list[str]] = {
    "총": ["전체", "모두", "합계"],
    "약": ["대략", "정도", "거의"],
    "폭발": ["대인기", "화제", "큰 인기"],
    "대박": ["놀라운", "엄청난", "파격"],
    "중독": ["빠져들다", "반하다", "매력적"],
    "타격": ["영향", "충격", "손실"],
    "사망": ["세상을 떠난", "숨진"],
}

# ── 카테고리별 절대 금지 단어 ────────────────────────────────────────────────
BANNED_COMMERCIAL: list[str] = [
    "무료", "공짜", "100%", "최저가", "파격세일", "초특가", "떨이", "땡처리",
]
BANNED_VIOLENCE: list[str] = [
    "폭탄", "사살", "살인", "학살", "테러", "마약", "필로폰",
]
BANNED_GAMBLING: list[str] = [
    "도박", "카지노", "토토", "슬롯", "배팅", "베팅",
]
BANNED_MEDICAL: list[str] = [
    "치료", "완치", "처방", "약효", "부작용",
]

# ── 체험단 클리셰 표현 (경고 수준) ──────────────────────────────────────────
CLICHE_EXPRESSIONS: list[str] = [
    "드디어 찾았다",
    "운명적인 만남",
    "진심으로 추천",
    "꼭 경험해보세요",
    "기쁨을 누리시길",
    "인생템",
    "딱 이거다 싶었",
    "제대로 된 제품을 찾은",
]

# ── 모든 절대 금지 단어를 하나로 합침 (대체어 없음) ──────────────────────────
_ALL_BANNED_WORDS: list[str] = (
    BANNED_COMMERCIAL + BANNED_VIOLENCE + BANNED_GAMBLING + BANNED_MEDICAL
)

# ---------------------------------------------------------------------------
# 한국어 단어 경계 처리
# ---------------------------------------------------------------------------
# 한국어에는 \b 가 제대로 동작하지 않는 경우가 많다.
# 짧은 단어("총", "약")는 단독으로 쓰이거나 뒤에 조사/공백이 올 때만 매칭한다.
# 긴 단어(2자 이상)는 단순 포함 매치로 충분하다.

# 한글 문자 범위 (가-힣: 완성형 한글)
_HANGUL = r"\uAC00-\uD7A3"


def _build_pattern_for_word(word: str) -> re.Pattern[str]:
    """금지어에 맞는 정규식 패턴을 생성한다.

    - 1글자 단어("총", "약"): 앞뒤가 한글이 아닌 경우에만 매칭.
      예) "총 금액" -> 매칭, "총알" -> 매칭 안 됨, "권총" -> 매칭 안 됨
    - 2글자 이상: 단순 포함 매치.
    """
    escaped = re.escape(word)
    if len(word) == 1:
        # 앞에 한글이 없고 뒤에 한글이 없을 때만 매칭
        return re.compile(
            rf"(?<![{_HANGUL}]){escaped}(?![{_HANGUL}])",
            re.MULTILINE,
        )
    return re.compile(escaped, re.MULTILINE)


# 미리 컴파일
_FORBIDDEN_PATTERNS: dict[str, re.Pattern[str]] = {
    word: _build_pattern_for_word(word)
    for word in FORBIDDEN_REPLACEMENTS
}

_BANNED_PATTERNS: dict[str, re.Pattern[str]] = {
    word: _build_pattern_for_word(word)
    for word in _ALL_BANNED_WORDS
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def check_forbidden_words(text: str) -> list[dict]:
    """텍스트에서 금지어를 검사하고 위반 목록을 반환한다.

    Args:
        text: 검사할 본문 텍스트.

    Returns:
        위반 항목 리스트. 각 항목은 다음 키를 갖는다:
        - word (str): 발견된 금지어
        - line (int): 해당 줄 번호 (1-based)
        - suggestion (str | None): 대체어 제안 (있을 경우)
        - category (str): 'replaceable' | 'commercial' | 'violence' |
                          'gambling' | 'medical' | 'cliche'
    """
    lines = text.split("\n")
    violations: list[dict] = []

    for line_no, line_text in enumerate(lines, start=1):
        # 1) 대체 가능 금지어
        for word, pattern in _FORBIDDEN_PATTERNS.items():
            if pattern.search(line_text):
                alternatives = FORBIDDEN_REPLACEMENTS[word]
                violations.append(
                    {
                        "word": word,
                        "line": line_no,
                        "suggestion": alternatives[0],
                        "category": "replaceable",
                    }
                )

        # 2) 절대 금지 단어 (카테고리별)
        for word, pattern in _BANNED_PATTERNS.items():
            if pattern.search(line_text):
                category = _categorize_banned(word)
                violations.append(
                    {
                        "word": word,
                        "line": line_no,
                        "suggestion": None,
                        "category": category,
                    }
                )

        # 3) 클리셰 표현 (경고)
        for expr in CLICHE_EXPRESSIONS:
            if expr in line_text:
                violations.append(
                    {
                        "word": expr,
                        "line": line_no,
                        "suggestion": None,
                        "category": "cliche",
                    }
                )

    return violations


def auto_replace_forbidden(text: str) -> str:
    """텍스트 내 금지어를 첫 번째 대체어로 자동 치환한다.

    FORBIDDEN_REPLACEMENTS에 등록된 단어만 치환 대상이며,
    절대 금지 단어(BANNED_*)는 단순 제거가 위험하므로 치환하지 않는다.

    Args:
        text: 원본 텍스트.

    Returns:
        금지어가 대체어로 치환된 텍스트.
    """
    result = text
    for word, pattern in _FORBIDDEN_PATTERNS.items():
        replacement = FORBIDDEN_REPLACEMENTS[word][0]
        result = pattern.sub(replacement, result)
    return result


def validate_keyword_density(
    text: str,
    keyword: str,
    min_pct: float = 1.0,
    max_pct: float = 3.0,
) -> dict:
    """키워드 밀도를 검증한다.

    Args:
        text: 본문 텍스트.
        keyword: 타겟 키워드.
        min_pct: 최소 허용 밀도 (%).
        max_pct: 최대 허용 밀도 (%).

    Returns:
        - density (float): 키워드 밀도 (%).
        - count (int): 키워드 출현 횟수.
        - total_chars (int): 전체 문자 수 (공백 제외).
        - is_valid (bool): 밀도가 min_pct~max_pct 범위 안인지.
    """
    # 공백 제외 문자 수 기준
    total_chars = len(text.replace(" ", "").replace("\n", ""))
    if total_chars == 0:
        return {
            "density": 0.0,
            "count": 0,
            "total_chars": 0,
            "is_valid": False,
        }

    keyword_len = len(keyword.replace(" ", ""))
    count = text.count(keyword)
    density = (count * keyword_len / total_chars) * 100

    return {
        "density": round(density, 2),
        "count": count,
        "total_chars": total_chars,
        "is_valid": min_pct <= density <= max_pct,
    }


def validate_content_quality(text: str, keyword: str) -> dict:
    """콘텐츠 품질을 종합 검증한다.

    금지어 검사, 키워드 밀도, 클리셰 여부, 글자 수 등을 한 번에 확인한다.

    Args:
        text: 본문 텍스트.
        keyword: 타겟 키워드.

    Returns:
        - forbidden_words (list[dict]): 금지어 위반 목록.
        - keyword_density (dict): 키워드 밀도 정보.
        - cliche_count (int): 발견된 클리셰 표현 수.
        - char_count (int): 총 글자 수 (공백 포함).
        - char_count_no_spaces (int): 총 글자 수 (공백 제외).
        - line_count (int): 줄 수.
        - has_critical_violations (bool): 심각한 위반이 있는지.
        - summary (str): 한국어 요약 메시지.
    """
    violations = check_forbidden_words(text)
    density_info = validate_keyword_density(text, keyword)

    cliche_count = sum(1 for v in violations if v["category"] == "cliche")
    critical_categories = {"commercial", "violence", "gambling", "medical"}
    critical_violations = [
        v for v in violations if v["category"] in critical_categories
    ]
    replaceable_violations = [
        v for v in violations if v["category"] == "replaceable"
    ]

    char_count = len(text)
    char_count_no_spaces = len(text.replace(" ", "").replace("\n", ""))
    line_count = len(text.split("\n"))

    has_critical = len(critical_violations) > 0

    # 요약 메시지 조합
    parts: list[str] = []
    if critical_violations:
        words = sorted({v["word"] for v in critical_violations})
        parts.append(f"절대 금지어 {len(critical_violations)}건 발견: {', '.join(words)}")
    if replaceable_violations:
        words = sorted({v["word"] for v in replaceable_violations})
        parts.append(f"대체 필요 단어 {len(replaceable_violations)}건: {', '.join(words)}")
    if cliche_count:
        parts.append(f"클리셰 표현 {cliche_count}건")
    if not density_info["is_valid"]:
        parts.append(
            f"키워드 밀도 {density_info['density']}% "
            f"(권장 1.0~3.0%)"
        )
    if not parts:
        parts.append("품질 검사 통과")

    summary = " / ".join(parts)

    return {
        "forbidden_words": violations,
        "keyword_density": density_info,
        "cliche_count": cliche_count,
        "char_count": char_count,
        "char_count_no_spaces": char_count_no_spaces,
        "line_count": line_count,
        "has_critical_violations": has_critical,
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _categorize_banned(word: str) -> str:
    """절대 금지 단어의 카테고리를 반환한다."""
    if word in BANNED_COMMERCIAL:
        return "commercial"
    if word in BANNED_VIOLENCE:
        return "violence"
    if word in BANNED_GAMBLING:
        return "gambling"
    if word in BANNED_MEDICAL:
        return "medical"
    return "unknown"
