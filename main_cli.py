"""
App_blog_auto CLI 진입점
키워드 기반 블로그 글 자동 생성 테스트용
"""

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
sys.path.insert(0, str(Path(__file__).parent))

from config import settings


async def cmd_generate(args):
    """키워드 → 블로그 글 생성"""
    from core.content_generator import generate_from_keyword, list_templates

    print(f"\n{'='*60}")
    print(f"  App_blog_auto — 블로그 글 자동 생성")
    print(f"{'='*60}")
    print(f"  키워드: {args.keyword}")
    print(f"  템플릿: {args.template}")
    print(f"  글자수: {args.char_count}")
    if args.product:
        print(f"  제품명: {args.product}")
    if args.reference:
        print(f"  레퍼런스: {args.reference}")
    print(f"{'='*60}\n")

    post = await generate_from_keyword(
        keyword=args.keyword,
        template=args.template,
        product_name=args.product,
        product_advantages=args.advantages,
        product_link=args.link,
        requirements=args.requirements,
        char_count_range=args.char_count,
        reference_url=args.reference,
    )

    # 결과 저장
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_keyword = args.keyword.replace(" ", "_")[:20]
    filename = f"{timestamp}_{safe_keyword}.md"
    save_path = settings.posts_dir / filename

    with open(save_path, "w", encoding="utf-8") as f:
        f.write(post.content)

    print(f"\n{'='*60}")
    print(f"  생성 완료!")
    print(f"  제목: {post.title}")
    print(f"  저장: {save_path}")
    print(f"  이미지 마커: {len(post.image_markers)}개")
    print(f"{'='*60}")

    # 이미지 생성 (--images 플래그가 있는 경우)
    if args.images:
        print("\n이미지 생성 시작...")
        from core.image_generator import generate_all_images, save_images

        images = await generate_all_images(post.image_markers, args.keyword)
        if images:
            paths = save_images(images, args.keyword)
            print(f"  이미지 저장: {paths[0].parent}/")
            for p in paths:
                print(f"    - {p.name}")

    # 미리보기 (--preview 플래그)
    if args.preview:
        print(f"\n{'─'*60}")
        print("  미리보기:")
        print(f"{'─'*60}\n")
        # 처음 1000자만 표시
        preview = post.content[:1000]
        if len(post.content) > 1000:
            preview += "\n\n... (이하 생략)"
        print(preview)

    return post


async def cmd_templates(args):
    """사용 가능한 템플릿 목록"""
    from core.content_generator import list_templates

    templates = list_templates()
    print(f"\n사용 가능한 템플릿 ({len(templates)}개):\n")
    for t in templates:
        print(f"  [{t['id']}] {t['name']}")
        print(f"    {t['description']}")
        print()


async def cmd_check(args):
    """금지어 검사"""
    from core.forbidden_words import validate_content_quality

    # 파일에서 읽기
    filepath = Path(args.file)
    if not filepath.exists():
        print(f"파일을 찾을 수 없습니다: {filepath}")
        return

    content = filepath.read_text(encoding="utf-8")
    result = validate_content_quality(content, args.keyword or "")

    print(f"\n{'='*60}")
    print(f"  품질 검사 결과: {filepath.name}")
    print(f"{'='*60}\n")

    # 금지어
    forbidden = result["forbidden_words"]
    if forbidden:
        print(f"  ⚠ 금지어 {len(forbidden)}개 발견:")
        for fw in forbidden:
            print(f"    - '{fw['word']}' → 추천: {fw['suggestion']}")
    else:
        print("  ✓ 금지어 없음")

    # 키워드 밀도
    density = result["keyword_density"]
    if args.keyword:
        status = "✓" if density["is_valid"] else "⚠"
        print(f"  {status} 키워드 밀도: {density['density']:.1f}% ({density['count']}회)")

    # 클리셰
    cliches = result.get("cliche_expressions", [])
    if cliches:
        print(f"  ⚠ 클리셰 표현 {len(cliches)}개:")
        for c in cliches:
            print(f"    - '{c}'")


def main():
    parser = argparse.ArgumentParser(
        description="App_blog_auto — 네이버 블로그 자동 생성 CLI",
    )
    subparsers = parser.add_subparsers(dest="command", help="명령어")

    # generate 명령
    gen_parser = subparsers.add_parser("generate", aliases=["gen", "g"], help="블로그 글 생성")
    gen_parser.add_argument("keyword", help="메인 키워드")
    gen_parser.add_argument("-t", "--template", default="review",
                           choices=["review", "informational", "brand-info", "brand-intro"],
                           help="글쓰기 템플릿 (기본: review)")
    gen_parser.add_argument("-c", "--char-count", default="1500-2500",
                           choices=["500-1500", "1500-2500", "2500-3500"],
                           help="목표 글자수 범위 (기본: 1500-2500)")
    gen_parser.add_argument("-p", "--product", help="제품명")
    gen_parser.add_argument("-a", "--advantages", help="제품 장점")
    gen_parser.add_argument("-l", "--link", help="구매 링크")
    gen_parser.add_argument("-r", "--reference", help="레퍼런스 블로그 URL")
    gen_parser.add_argument("-q", "--requirements", help="추가 요구사항")
    gen_parser.add_argument("--images", action="store_true", help="이미지도 생성")
    gen_parser.add_argument("--preview", action="store_true", help="생성 후 미리보기")

    # templates 명령
    subparsers.add_parser("templates", aliases=["tpl"], help="템플릿 목록")

    # check 명령
    check_parser = subparsers.add_parser("check", help="금지어/품질 검사")
    check_parser.add_argument("file", help="검사할 마크다운 파일 경로")
    check_parser.add_argument("-k", "--keyword", help="키워드 (밀도 검사용)")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    if args.command in ("generate", "gen", "g"):
        asyncio.run(cmd_generate(args))
    elif args.command in ("templates", "tpl"):
        asyncio.run(cmd_templates(args))
    elif args.command == "check":
        asyncio.run(cmd_check(args))


if __name__ == "__main__":
    main()
