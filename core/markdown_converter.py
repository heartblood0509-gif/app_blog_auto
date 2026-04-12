"""
마크다운 → SmartEditor ONE 입력 시퀀스 변환

생성된 마크다운 콘텐츠를 Playwright가 SmartEditor ONE에 입력할 수 있는
구조화된 시퀀스로 변환합니다.
"""

import re
from dataclasses import dataclass, field
from enum import Enum


class BlockType(Enum):
    TITLE = "title"           # H1 제목
    HEADING = "heading"       # H2/H3 소제목
    PARAGRAPH = "paragraph"   # 일반 텍스트
    IMAGE = "image"           # [이미지: 설명]
    QUOTE = "quote"           # 인용구 (> 또는 > 텍스트)
    BLANK = "blank"           # 빈 줄
    HORIZONTAL_RULE = "hr"    # 구분선 (---)


# 인용구 스타일 상수 (네이버 SmartEditor ONE 5종)
QUOTE_STYLES = {
    "default": "se-l-default",           # 큰따옴표 ("")
    "bubble": "se-l-quotation_bubble",   # 말풍선
    "line": "se-l-quotation_line",       # 세로선
    "underline": "se-l-quotation_underline",  # 밑줄
    "corner": "se-l-quotation_corner",   # 모서리 꺾쇠
}


@dataclass
class TextSegment:
    """인라인 텍스트 조각 (강조 여부 포함)"""
    text: str
    emphasis: bool = False


def parse_emphasis(text: str) -> tuple[str, list[str]]:
    """인라인 강조 마커 파싱: {강조}텍스트{/강조}

    Returns:
        (plain_text, emphasis_phrases)
        - plain_text: 마커가 제거된 순수 텍스트
        - emphasis_phrases: 강조할 문구 리스트
    """
    emphasis_phrases = re.findall(r'\{강조\}(.+?)\{/강조\}', text)
    plain_text = re.sub(r'\{강조\}(.+?)\{/강조\}', r'\1', text)
    return plain_text, emphasis_phrases


@dataclass
class ContentBlock:
    type: BlockType
    text: str = ""
    level: int = 0          # heading level (2, 3 등)
    image_index: int = -1   # 이미지 인덱스
    quote_style: str = "default"  # 인용구 스타일 (default/bubble/line/underline/corner)


@dataclass
class EditorSequence:
    """SmartEditor ONE에 입력할 시퀀스"""
    title: str
    blocks: list[ContentBlock] = field(default_factory=list)
    image_count: int = 0


def parse_markdown(content: str) -> EditorSequence:
    """마크다운 콘텐츠를 에디터 입력 시퀀스로 변환

    Args:
        content: 생성된 마크다운 블로그 글

    Returns:
        EditorSequence: 제목 + 블록 시퀀스
    """
    lines = content.split("\n")
    title = ""
    blocks: list[ContentBlock] = []
    image_count = 0
    current_paragraph: list[str] = []

    def flush_paragraph():
        if current_paragraph:
            text = "\n".join(current_paragraph).strip()
            if text:
                blocks.append(ContentBlock(type=BlockType.PARAGRAPH, text=text))
            current_paragraph.clear()

    for line in lines:
        stripped = line.strip()

        # 빈 줄
        if not stripped:
            flush_paragraph()
            continue

        # H1 제목
        if stripped.startswith("# ") and not stripped.startswith("## "):
            flush_paragraph()
            title = stripped[2:].strip()
            continue

        # H2/H3 소제목
        heading_match = re.match(r'^(#{2,3})\s+(.+)$', stripped)
        if heading_match:
            flush_paragraph()
            level = len(heading_match.group(1))
            blocks.append(ContentBlock(
                type=BlockType.HEADING,
                text=heading_match.group(2).strip(),
                level=level,
            ))
            continue

        # 이미지 마커
        image_match = re.match(r'^\[이미지:\s*(.+?)\]$', stripped)
        if image_match:
            flush_paragraph()
            blocks.append(ContentBlock(
                type=BlockType.IMAGE,
                text=image_match.group(1).strip(),
                image_index=image_count,
            ))
            image_count += 1
            continue

        # 구분선 (--- 또는 ***)
        if stripped in ("---", "***", "___"):
            flush_paragraph()
            blocks.append(ContentBlock(type=BlockType.HORIZONTAL_RULE))
            continue

        # 확장 인용구: >style> 텍스트 (예: >bubble> 말풍선 인용구)
        quote_style_match = re.match(
            r'^>(bubble|line|underline|corner)>\s+(.+)$', stripped
        )
        if quote_style_match:
            flush_paragraph()
            blocks.append(ContentBlock(
                type=BlockType.QUOTE,
                text=quote_style_match.group(2).strip(),
                quote_style=quote_style_match.group(1),
            ))
            continue

        # 기본 인용구 (> 텍스트)
        if stripped.startswith("> "):
            flush_paragraph()
            blocks.append(ContentBlock(
                type=BlockType.QUOTE,
                text=stripped[2:].strip(),
                quote_style="default",
            ))
            continue

        # 일반 텍스트
        current_paragraph.append(stripped)

    flush_paragraph()

    return EditorSequence(
        title=title,
        blocks=blocks,
        image_count=image_count,
    )


def distribute_images(
    blocks: list[ContentBlock],
    image_count: int,
) -> list[ContentBlock]:
    """이미지 마커가 없는 경우, 적절한 위치에 이미지 블록 삽입

    규칙:
    - 첫 단락(오프닝)에는 이미지 배치하지 않음
    - 각 H2 소제목 뒤에 1장씩 배치
    - 남은 이미지는 가장 긴 구간에 균등 분배
    - 마지막 이미지는 클로징 직전에 배치
    """
    # 이미 이미지 마커가 있으면 그대로 반환
    existing_images = sum(1 for b in blocks if b.type == BlockType.IMAGE)
    if existing_images > 0:
        return blocks

    if image_count <= 0:
        return blocks

    # H2 소제목 위치 찾기 (첫 번째 제외)
    heading_indices = [
        i for i, b in enumerate(blocks)
        if b.type == BlockType.HEADING and b.level == 2
    ]

    result = list(blocks)
    inserted = 0
    img_idx = 0

    # 각 H2 소제목 뒤에 이미지 삽입
    for h_idx in heading_indices:
        if inserted >= image_count:
            break
        insert_pos = h_idx + 1 + inserted  # 삽입으로 인한 오프셋
        # 소제목 뒤 첫 단락 이후에 삽입
        while insert_pos < len(result) and result[insert_pos].type == BlockType.PARAGRAPH:
            insert_pos += 1
            break

        result.insert(insert_pos, ContentBlock(
            type=BlockType.IMAGE,
            text=f"이미지 {img_idx + 1}",
            image_index=img_idx,
        ))
        inserted += 1
        img_idx += 1

    return result


def sequence_to_plain_text(seq: EditorSequence) -> str:
    """에디터 시퀀스를 평문으로 변환 (디버깅/미리보기용)"""
    parts = [f"# {seq.title}", ""]

    for block in seq.blocks:
        if block.type == BlockType.HEADING:
            prefix = "#" * block.level
            parts.extend(["", f"{prefix} {block.text}"])
        elif block.type == BlockType.PARAGRAPH:
            parts.append(block.text)
        elif block.type == BlockType.IMAGE:
            parts.append(f"[이미지: {block.text}]")
        elif block.type == BlockType.QUOTE:
            if block.quote_style and block.quote_style != "default":
                parts.append(f">{block.quote_style}> {block.text}")
            else:
                parts.append(f"> {block.text}")
        elif block.type == BlockType.HORIZONTAL_RULE:
            parts.append("---")

    return "\n".join(parts)
