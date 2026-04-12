"""
이미지 생성/검색 모듈
- 1차: Gemini Imagen (AI 실사 이미지 생성)
- 2차: Unsplash 무료 API (키워드 기반 스톡 이미지, 폴백)
- 3차: fal.ai FLUX.1 Schnell (AI 생성, 폴백)
"""

import asyncio
import base64
import re
from pathlib import Path

import httpx
from google.genai import types

from config import settings


async def search_unsplash(query: str, count: int = 1) -> list[bytes]:
    """Unsplash에서 키워드로 이미지 검색 후 다운로드"""
    if not settings.UNSPLASH_ACCESS_KEY:
        return []

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            "https://api.unsplash.com/search/photos",
            params={
                "query": query,
                "per_page": count,
                "orientation": "landscape",
            },
            headers={
                "Authorization": f"Client-ID {settings.UNSPLASH_ACCESS_KEY}",
            },
        )
        if resp.status_code != 200:
            print(f"  [Unsplash] 검색 실패: {resp.status_code}")
            return []

        data = resp.json()
        results = data.get("results", [])
        if not results:
            return []

        images = []
        for photo in results[:count]:
            url = photo.get("urls", {}).get("regular", "")
            if not url:
                continue
            img_resp = await client.get(url)
            if img_resp.status_code == 200:
                images.append(img_resp.content)

        return images


async def generate_with_fal(prompt: str) -> bytes | None:
    """fal.ai FLUX.1 Schnell로 이미지 생성"""
    if not settings.FAL_API_KEY:
        return None

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            "https://fal.run/fal-ai/flux/schnell",
            headers={
                "Authorization": f"Key {settings.FAL_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "prompt": prompt,
                "image_size": "landscape_16_9",
                "num_images": 1,
            },
        )
        if resp.status_code != 200:
            print(f"  [fal.ai] 생성 실패: {resp.status_code}")
            return None

        data = resp.json()
        images = data.get("images", [])
        if not images:
            return None

        image_url = images[0].get("url", "")
        if not image_url:
            return None

        img_resp = await client.get(image_url)
        if img_resp.status_code == 200:
            return img_resp.content

    return None


async def generate_with_gemini(
    prompt: str,
    ratio: str = "16:9",
) -> bytes | None:
    """Gemini Imagen으로 실사 이미지 생성"""
    try:
        from core.content_generator import get_client
        client = get_client()

        response = await asyncio.to_thread(
            client.models.generate_content,
            model=settings.GEMINI_IMAGE_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_modalities=["TEXT", "IMAGE"],
            ),
        )

        # 응답에서 이미지 추출
        if response.candidates:
            for part in response.candidates[0].content.parts:
                if part.inline_data and part.inline_data.mime_type.startswith("image/"):
                    return base64.b64decode(part.inline_data.data) if isinstance(part.inline_data.data, str) else part.inline_data.data

    except Exception as e:
        err_msg = str(e)
        if "SAFETY" in err_msg or "safety" in err_msg:
            print(f"    ⚠ 안전 필터로 이미지 생성 건너뜀")
        else:
            print(f"    ⚠ Gemini 이미지 생성 실패: {err_msg[:100]}")

    return None


async def generate_image(
    description: str,
    keyword: str,
    blog_content: str = "",
    image_index: int = 0,
) -> bytes | None:
    """이미지 생성 (Gemini Imagen 우선, fal.ai/Unsplash 폴백)

    Args:
        description: [이미지: 설명] 에서 추출한 설명
        keyword: 메인 키워드 (Unsplash 검색용)
        blog_content: 전체 블로그 본문 (Gemini 컨텍스트용)
        image_index: 이미지 순서 인덱스
    """
    # 1차: Gemini Imagen
    if settings.GEMINI_API_KEY:
        from core.content_generator import build_blog_image_prompt
        prompt = build_blog_image_prompt(description, blog_content, image_index)
        result = await generate_with_gemini(prompt)
        if result:
            return result

    # 2차: fal.ai
    if settings.FAL_API_KEY:
        prompt = f"Korean blog photo, {description}, high quality, natural lighting, no text, no watermark"
        result = await generate_with_fal(prompt)
        if result:
            return result

    # 3차: Unsplash 폴백
    search_query = f"{keyword} {description}"
    results = await search_unsplash(search_query, count=1)
    if results:
        return results[0]

    results = await search_unsplash(keyword, count=1)
    if results:
        return results[0]

    return None


async def generate_all_images(
    image_markers: list[str],
    keyword: str,
    blog_content: str = "",
    max_images: int | None = None,
) -> list[bytes]:
    """모든 이미지 마커에 대해 이미지 생성

    Args:
        image_markers: [이미지: 설명] 에서 추출한 설명 목록
        keyword: 메인 키워드
        blog_content: 전체 블로그 본문 (Gemini 컨텍스트용)
        max_images: 최대 생성할 이미지 수 (None이면 settings.IMAGE_COUNT)
    """
    max_count = max_images or settings.IMAGE_COUNT
    markers_to_process = image_markers[:max_count]

    print(f"  이미지 생성 중... ({len(markers_to_process)}장)")

    images = []
    for i, desc in enumerate(markers_to_process):
        print(f"    [{i + 1}/{len(markers_to_process)}] {desc[:30]}...")
        img = await generate_image(desc, keyword, blog_content, image_index=i)
        if img:
            images.append(img)
            print(f"    ✓ 생성 완료")
        else:
            print(f"    ⚠ 이미지 생성 실패: {desc[:30]}...")

        # 이미지 간 딜레이 (레이트 리밋 대응)
        if i < len(markers_to_process) - 1:
            await asyncio.sleep(3)

    print(f"  → {len(images)}/{len(markers_to_process)}장 생성 완료")
    return images


def save_images(images: list[bytes], keyword: str) -> list[Path]:
    """생성된 이미지를 로컬에 저장"""
    save_dir = settings.images_dir / re.sub(r'[^\w가-힣]', '_', keyword)
    save_dir.mkdir(parents=True, exist_ok=True)

    paths = []
    for i, img_bytes in enumerate(images):
        path = save_dir / f"image_{i + 1:02d}.jpg"
        path.write_bytes(img_bytes)
        paths.append(path)

    return paths
