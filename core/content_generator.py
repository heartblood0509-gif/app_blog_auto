"""
Gemini 기반 블로그 콘텐츠 생성기
App_Blog의 prompts.ts (831줄)를 Python으로 포팅
"""

import asyncio
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from google import genai
from google.genai import types

from config import settings


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class TitleSuggestion:
    title: str
    subtitles: list[str] = field(default_factory=list)


@dataclass
class BlogPost:
    title: str
    content: str
    images: list[bytes] = field(default_factory=list)
    image_markers: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Gemini Client
# ---------------------------------------------------------------------------

_client: genai.Client | None = None


def get_client() -> genai.Client:
    global _client
    if _client is None:
        if not settings.GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY가 설정되지 않았습니다. .env 파일을 확인하세요.")
        _client = genai.Client(api_key=settings.GEMINI_API_KEY)
    return _client


def format_gemini_error(error: Exception) -> str:
    msg = str(error)
    if "429" in msg or "RESOURCE_EXHAUSTED" in msg or "quota" in msg:
        return f"API 요청 한도를 초과했습니다. 잠시 후(약 30초) 다시 시도해주세요. ({msg[:200]})"
    if "403" in msg or "PERMISSION_DENIED" in msg:
        return "API 키가 유효하지 않습니다. 환경 설정을 확인해주세요."
    if "503" in msg or "UNAVAILABLE" in msg or "high demand" in msg:
        return "AI 서버가 일시적으로 혼잡합니다. 1~2분 후 다시 시도해주세요."
    if "500" in msg or "INTERNAL" in msg:
        return "AI 서버에 일시적 오류가 발생했습니다. 잠시 후 다시 시도해주세요."
    return msg


async def with_retry(fn, max_retries: int = 3):
    """지수 백오프 재시도 (429 에러 시)"""
    for attempt in range(max_retries):
        try:
            return await fn()
        except Exception as e:
            msg = str(e)
            is_rate_limit = "429" in msg or "RESOURCE_EXHAUSTED" in msg
            if is_rate_limit and attempt < max_retries - 1:
                wait = 25 * (2 ** attempt)
                print(f"[재시도] {wait}초 후 재시도... ({attempt + 1}/{max_retries})")
                await asyncio.sleep(wait)
            else:
                raise


# ---------------------------------------------------------------------------
# 네이버 금지어 섹션 (prompts.ts 189-217)
# ---------------------------------------------------------------------------

NAVER_FORBIDDEN_WORDS_SECTION = """

## 네이버 블로그 금지어 회피 (필수)
네이버 블로그는 특정 단어가 포함되면 검색 노출이 제한됩니다. 아래 단어들은 **절대 사용하지 말고**, 반드시 대체어로 바꿔 작성하세요.

### 문맥과 무관하게 위험한 단어 (대체어 사용 필수):
| 금지어 | 흔한 용도 | 대체어 |
|--------|-----------|--------|
| 총 | "총 금액", "총 정리" | 전체, 모두, 합계 |
| 약 | "약 30분", "약 5만원" | 대략, 정도, 거의 |
| 폭발 | "인기 폭발" | 대인기, 화제, 큰 인기 |
| 대박 | "대박 할인" | 놀라운, 엄청난, 파격 |
| 중독 | "맛에 중독" | 빠져들다, 반하다, 매력적 |
| 타격 | "큰 타격" | 영향, 충격, 손실 |
| 사망 | 통계 등 | 세상을 떠난, 숨진 |

### 상업성 스팸 트리거 단어 (절대 사용 금지):
무료, 공짜, 100%, 최저가, 파격세일, 초특가, 떨이, 땡처리

### 폭력/범죄 관련 (절대 사용 금지):
폭탄, 사살, 살인, 학살, 테러, 마약, 필로폰

### 도박 관련 (절대 사용 금지):
도박, 카지노, 토토, 슬롯, 배팅, 베팅

### 의료/약사법 위반 표현 (절대 사용 금지):
치료, 완치, 처방, 약효, 부작용 → "도움이 될 수 있다", "개인적 경험으로는" 등으로 우회

위 단어가 자연스럽게 쓰일 수 있는 문맥이라도, 네이버 알고리즘은 문맥을 구분하지 않으므로 반드시 대체어를 사용하세요."""


# ---------------------------------------------------------------------------
# 프롬프트 빌더 (prompts.ts 6-831 포팅)
# ---------------------------------------------------------------------------

def build_analysis_prompt(reference_text: str) -> str:
    """레퍼런스 블로그 글의 서사 구조와 스타일 분석 프롬프트"""
    return f"""다음 블로그 글의 서사 구조와 스타일을 분석해주세요.

---
{reference_text}
---

아래 항목들을 분석해주세요:

## 📖 서사 구조 분석
이 글의 이야기 흐름을 단계별로 분해하세요. 각 단계가 글에서 어떤 역할을 하는지 (공감, 문제 제기, 해결, 신뢰 보강 등) 괄호 안에 함께 표시하세요.

예시 형식:
1. 무심했던 초기 상태 (도입)
2. 이상함 감지 - 반복되는 문제 (문제 인식)
3. 스트레스 구간 (공감 포인트)
4. 정보 탐색 (행동 전환)
5. 첫 해결 시도 (시도)
6. 한계 경험 - 재발/부작용 (실패)
7. 원인 재해석 (핵심 깨달음)
8. 새로운 제품 도입 (해결)
9. 결론 (마무리)

위는 예시일 뿐이며, 실제 글의 흐름에 맞게 단계를 도출하세요. 8~15단계 정도로 분해하세요.

## 📋 서사 유형
이 글이 어떤 서사 유형에 해당하는지 판단하고, 그 이유를 한 줄로 설명하세요:
- **감정 선공형**: 스트레스/공감 상황으로 시작하여 해결로 이어지는 구조
- **결론 선공형**: "지금은 괜찮아졌다"는 결과를 먼저 보여주고 과거를 회상하는 구조
- **관리형**: 현재 루틴/방법을 소개하며 왜 이렇게 바꾸게 됐는지 설명하는 구조
- **정보 가이드형**: 주제의 개념→분류→비교→활용→주의사항 순서로 정보를 전달하는 구조
- 기타 (직접 명명하고 설명)

## 📌 소제목 분석
- **소제목 존재 여부**: 레퍼런스 글에 명시적인 소제목(H2/H3)이 있는지, 아니면 소제목 없이 흐름으로 이어지는 글인지
- **소제목 개수**: 몇 개의 소제목이 사용되었는지
- **소제목 스타일**: 키워드 포함 여부, 구어체/문어체, 질문형/서술형 등 소제목의 말투와 패턴
- **소제목 배치 위치**: 서사 구조의 어떤 단계에서 소제목이 등장하는지 (예: "3단계와 5단계 사이에 소제목 전환")
- **레퍼런스의 실제 소제목 목록**: 원문에 있는 소제목들을 그대로 나열

## 🎨 톤 & 스타일
- **문체**: 구어체/문어체 비율, 말투 특징 (예: "~거든요", "~입니다" 등)
- **제목 패턴**: 제목의 구조와 키워드 배치 방식
- **감정 표현**: 공감 유도 방식, 과장/절제 정도
- **타겟 독자층**: 연령대, 관심사, 지식 수준

## 🛒 제품 배치 분석
이 글에 특정 제품/서비스/브랜드가 등장하는지 분석하세요.

**제품이 등장하는 경우:**
- **제품 등장 여부**: 있음
- **제품 등장 시점**: 서사 구조의 몇 단계에서 처음 등장하는지 (예: "8단계 '해결' 에서 첫 등장")
- **도입 흐름**: 제품이 어떤 논리적 순서로 도입되는지 (예: "문제 원인 분석 → 해결 원리 설명 → 핵심 성분 언급 → 제품 연결")
- **제품명 언급 횟수**: 글 전체에서 제품명이 몇 회 등장하는지
- **제품 관련 분량**: 제품을 직접 다루는 문단 수 / 전체 문단 수 (비율)
- **제품 언급 톤**: 노골적 광고인지, 경험담 속 자연스러운 언급인지, 비교 리뷰인지

**제품이 등장하지 않는 경우:**
- **제품 등장 여부**: 없음 (순수 정보성/경험담 글)

## 🔍 SEO 기본 정보
- **총 글자 수**: 공백 포함/제외 글자 수
- **키워드 밀도**: 핵심 키워드와 반복 횟수, 밀도(%)
- **이미지 패턴**: 이미지 예상 개수와 간격

결과를 마크다운 형식으로 정리해주세요."""


def build_title_prompt(
    analysis_result: str,
    topic: str,
    keywords: str,
) -> str:
    """SEO 최적화 제목 생성 프롬프트 (7가지 후기성 + 5가지 정보성 기법)"""
    return f"""당신은 블로그 SEO 제목 전문가입니다.

## 분석 결과
{analysis_result}

## 요청
- **주제**: {topic}
- **키워드**: {keywords}

**중요: 위 분석 결과의 "📋 서사 유형"을 확인하고, 아래에서 해당 유형의 제목 기법을 따르세요.**

### 제목 작성 필수 기준 (공통):
1. **키워드 필수 포함**: 모든 제목에 핵심 키워드가 반드시 포함되어야 합니다
2. **키워드 앞부분 배치**: 가능한 한 제목 앞쪽에 키워드를 배치 (SEO 최적화)
3. **레퍼런스 제목 패턴 참고**: 위 분석 결과의 "제목 패턴"을 참고하세요. 레퍼런스의 제목 구조, 말투, 키워드 배치 방식을 기반으로 제목을 만드세요.

---

### 📝 후기성/경험담 글일 때 (감정 선공형, 결론 선공형, 관리형)
주제와 키워드에 맞는 블로그 제목을 **7개** 추천해주세요.

**추가 기준:**
- **추상어 절대 금지**: "성공적인", "효과적인", "좋은" 같은 막연한 표현 대신 구체적인 사례, 결과로 바꿔야 합니다. 숫자가 아닌 방법(유명 대상, 구체적 상황, 비유)도 활용하세요.
- **숫자 사용 주의**: 숫자는 반드시 현실적이고 믿을 수 있어야 합니다. "100개 써본", "500가닥" 같은 비현실적 숫자는 금지. 숫자 없이도 강력한 제목은 많습니다.

**클릭율 높이는 7가지 핵심 기법 (각 제목마다 다른 기법 사용):**

**기법 1: 궁금증 유발** — 답을 알고 싶게 만드는 구조
- 예) "5만원짜리 수분크림보다 20% 더 촉촉한 5천원짜리 수분크림?"

**기법 2: 고정관념 극대화** — 유명한 대상을 활용해 스케일을 키운다
- 예) "백종원도 못따라할 맛집을 군산에서 찾았어요"

**기법 3: 고정관념 뒤집기 (의외성)** — 주어의 고정 속성과 반대되는 단어를 결합
- 예) "1위 로펌 변호사인 내가 아직도 3평 고시원에 사는 이유"

**기법 4: 숫자 구체화 (홀수 선호)** — 리스트형 숫자(3가지, 5가지)가 가장 안전하고 효과적
- 예) "~하는 3가지 방법"

**기법 5: 마인드 리딩** — 타겟의 걱정을 3초 안에 건드리기
- 예) "비싸기만 하고 맛없는 거 아닌가 걱정되셨죠?"

**기법 6: 금지/위협 (손실 회피)** — 부정적 표현이 더 클릭을 부른다
- 예) "이것 모르면 돈 2배로 날립니다"

**기법 7: 권위자 인용 (후광효과)** — 권위 있는 존재를 활용
- 예) "워렌 버핏이 코인을 절대 안 하는 이유"

**다양성 기준 (7개 제목이 각각 다른 후킹 전략):**
- **제목 1**: 궁금증 유발형
- **제목 2**: 고정관념 극대화형
- **제목 3**: 의외성/반전형
- **제목 4**: 숫자 구체화형
- **제목 5**: 마인드 리딩형
- **제목 6**: 금지/위협형
- **제목 7**: 권위자 인용형

---

### 📖 정보성/가이드 글일 때 (정보 가이드형)
주제와 키워드에 맞는 블로그 제목을 **5개** 추천해주세요.

**정보성 제목 원칙:**
- 정보성 글의 제목은 **신뢰감과 정보 가치**가 핵심입니다. 자극적이거나 감정적인 표현 대신, "이 글을 읽으면 무엇을 알 수 있는지"가 명확해야 합니다.
- 마인드 리딩("걱정되셨죠?"), 극단적 감정 단어("충격", "폭로"), 경험제 표현("써봤더니")은 사용하지 마세요.

**정보성 제목 5가지 기법:**

**기법 1: 총정리/완벽 가이드형** — 해당 주제의 모든 것을 다룬다는 느낌
- 예) "홍조없애는법 A to Z, 유형별 원인부터 관리법까지"

**기법 2: 비교/분류형** — 종류를 나누고 비교하여 선택을 도와주는 구조
- 예) "홍조 유형 3가지, 내 홍조는 어디에 해당될까?"

**기법 3: 숫자 리스트형** — 구체적 숫자(홀수 선호)로 정보 범위를 명시
- 예) "홍조없애는법 5가지, 피부과 전문의가 말하는 핵심"

**기법 4: 실수/주의사항형** — 독자가 피해야 할 것을 알려주는 구조
- 예) "홍조 관리할 때 절대 하면 안 되는 3가지 습관"

**기법 5: 질문/해결형** — 독자의 궁금증을 제목에서 직접 반영
- 예) "홍조, 정말 완치가 가능할까? 현실적인 관리법 정리"

**다양성 기준 (5개 제목이 각각 다른 기법):**
- **제목 1**: 총정리/완벽 가이드형
- **제목 2**: 비교/분류형
- **제목 3**: 숫자 리스트형
- **제목 4**: 실수/주의사항형
- **제목 5**: 질문/해결형

---

### 주의사항 (공통):
- 모든 제목이 완전히 다른 후킹 전략을 사용해야 함 — 비슷한 느낌의 제목이 2개 이상 나오면 안 됨
- 클릭하고 싶은 제목이어야 함 — 밋밋하거나 교과서적인 제목 금지
- 짧은 제목(15자 이내)과 긴 제목(30자 이상)을 골고루 포함

**반드시 아래 JSON 형식으로만 응답해주세요. 다른 설명은 포함하지 마세요. 서사 유형에 따라 5개 또는 7개:**
[
  {{"title": "제목1", "subtitles": []}},
  {{"title": "제목2", "subtitles": []}},
  ...
]"""


def build_generation_prompt(
    analysis_result: str,
    topic: str,
    keywords: str,
    *,
    selected_title: str | None = None,
    product_name: str | None = None,
    product_advantages: str | None = None,
    product_link: str | None = None,
    requirements: str | None = None,
    char_count_range: str | None = None,
    include_image_desc: bool = True,
) -> str:
    """블로그 글 생성 프롬프트 (서사 유형별 분기, 제품 배치 규칙 포함)"""

    product_section = ""
    if product_name:
        product_section = f"- **제품명**: {product_name}"
        if product_advantages:
            product_section += f"\n- **제품 장점**: {product_advantages}"

    char_count_map = {
        "500-1500": "- **목표 분량**: 공백 제외 약 500~1,500자 내외로 작성하세요",
        "1500-2500": "- **목표 분량**: 공백 제외 약 1,500~2,500자 내외로 작성하세요",
        "2500-3500": "- **목표 분량**: 공백 제외 약 2,500~3,500자 내외로 작성하세요",
    }
    char_count_instruction = char_count_map.get(
        char_count_range or "",
        "- **목표 분량**: 레퍼런스와 비슷한 글자 수(공백 제외)로 작성하세요",
    )

    title_instruction = f' - 제목: "{selected_title}"' if selected_title else ""

    image_instruction = (
        "- 이미지 관련 표시는 아무것도 넣지 마세요"
        if not include_image_desc
        else "- 이미지 삽입 위치를 [이미지: 설명] 형태로 표시 (레퍼런스의 이미지 패턴 참고)"
    )

    # 제품 배치 규칙
    product_rules = ""
    if product_name:
        product_rules = f"""

### 제품 배치 규칙 (매우 중요 — 반드시 준수)

**[규칙 1] 소제목에 제품 관련 표현 절대 금지**
소제목(H2)에 아래 표현을 절대 넣지 마세요:
- 제품명("{product_name}") 직접 사용
- 제품을 암시하는 표현: "운명적인 만남", "기적의 제품", "구원자", "드디어 찾은", "OO와의 만남" 등
- 소제목은 오직 글의 주제와 서사 흐름만 반영해야 합니다.
- 좋은 소제목 예시: "결국 답은 두피 환경이었다", "습관을 바꾸니 달라진 것들", "3개월 후 거울 속 변화"

**[규칙 2] 제품 도입 방식 — 레퍼런스 분석 기반 판단**

위 레퍼런스 분석 결과의 "🛒 제품 배치 분석" 섹션을 확인하세요.

**A) 레퍼런스에 제품이 등장하는 경우:**
레퍼런스의 제품 배치 패턴(등장 시점, 도입 흐름, 언급 횟수, 분량 비율, 톤)을 그대로 따르세요.
레퍼런스에서 제품이 3단계에서 나오면 3단계에, 8단계에서 나오면 8단계에 배치합니다.
단, 레퍼런스의 제품명은 "{product_name}"으로 교체하세요.{f'''
사용자가 입력한 장점({product_advantages})은 레퍼런스의 제품 언급 톤에 맞춰 경험담 속에 녹이세요.''' if product_advantages else ''}

**B) 레퍼런스에 제품이 없는 경우 (순수 정보성/경험담 글):**
아래 4단계 자연 도입법으로 제품을 배치하세요. 서사 구조의 '해결' 단계에서:

① **해결 원리 제시** — 문제의 근본 해결 방향을 먼저 설명
   예) "탈모 관련 논문자료까지 찾아봤는데, 단백질만 머리에 잘 흡수되어도 80%가 해결됩니다"

② **핵심 성분/요소 언급** — 해결 원리에 맞는 구체적 요소를 경험 속에서 언급{f'''
   사용자가 입력한 장점({product_advantages})을 직접 나열하지 말고, 이 단계에서 경험담 속에 녹이세요.''' if product_advantages else ''}
   예) "흡수율이 가장 빠르다고 유명한 게 귀리단백질이에요. 함유량 높은 제품을 쓰는 게 가장 현명한 방법이라는 거죠"

③ **비교 경험 (선택)** — 가능하다면 다른 시도/제품과 비교한 경험을 짧게 언급하여 신뢰도를 높이세요.
   예) "여기에 일치하는 제품이 몇 개 있어서 직접 다 써봤어요. A는 함유량도 낮고, B는 나쁘지 않았는데 뻑뻑함이..."
   비교는 1~2문장이면 충분합니다. 길어지면 리뷰 글이 되어버립니다.

④ **제품 연결 (1~2문장)** — 위 비교 끝에 "{product_name}"을 짧게 연결
   예) "그런 기준으로 고르다 보니 자연스럽게 OO제품을 쓰게 됐어요"

**[규칙 3] 제품 언급 톤 — 은근슬쩍, 간접적으로 (A, B 공통)**
진짜 써본 사람이 일상 속에서 툭 던지듯 언급하는 느낌이어야 합니다.
- 제품명은 글 전체에서 **최대 1~2회**만 등장. 나머지는 "요즘 쓰는 샴푸", "이걸로 바꾸고 나서" 등 간접 표현으로 대체
- 제품 직접 설명은 **2~3문장 이내**. 한 문단을 통째로 제품 설명에 쓰면 광고입니다.
- ✅ 자연스러운 예시: "요즘 쓰고 있는 OO로 바꾸고 나서 확실히 빠지는 양이 줄었어요"
- ✅ 자연스러운 예시: "지인 추천으로 써보기 시작한 건데, 두피가 편해진 느낌이에요"
- ❌ 광고 느낌: "이 제품은 특허를 받았고, 흑미 추출물과 맥주효모가 함유되어 있어 모발 생장에 탁월합니다"
- ❌ 광고 느낌: "딱 이거다 싶었죠", "제대로 된 제품을 찾은 것 같은 기분"

**[규칙 4] 금지 표현 (A, B 공통)**
- 체험단 클리셰 절대 금지: "드디어 찾았다", "운명적인 만남", "진심으로 추천", "꼭 경험해보세요", "기쁨을 누리시길", "인생템", "딱 이거다 싶었", "제대로 된 제품을 찾은"
- 스펙 나열 금지: 특허, 인증 번호, 성분 목록을 카탈로그처럼 나열하지 마세요. 성분은 경험 속에서 간접적으로("단백질 영양을 채워주는 느낌") 전달하세요.
- 제품 찬양 결말 금지: 글의 결론은 제품 추천이 아니라, 글 주제에 대한 자연스러운 마무리여야 합니다. 레퍼런스 서사 구조의 마지막 단계를 따르세요."""

        if product_link:
            product_rules += f"\n- **구매 링크**: 글 맨 마지막에 아무 설명 없이 링크만 단독으로 한 줄에 넣으세요: {product_link}"
        else:
            product_rules += "\n- 제품명만 자연스럽게 언급하세요. 가짜 URL이나 구매 링크를 만들지 마세요."

    # 후기성 클로징 (제품이 있는 경우)
    closing_product = ""
    if product_name:
        closing_product = """
- **목적**: 제품 구매를 직접 유도하는 것이 아니라, '흥미'를 갖고 검색까지만 하게 하는 것이 목적입니다.
- **유입 키워드 언급**: 글 후반부에서 자연스럽게 제품명이나 검색 키워드를 한 번 언급하세요. (규칙 3의 1~2회 제한에 포함)"""

    # 정보성 클로징 (제품이 있는 경우)
    info_closing_product = ""
    if product_name:
        info_closing_product = "\n- 제품이 있는 경우: 정보 흐름의 마지막에 자연스럽게 추천 제품으로 연결하세요."

    return f"""당신은 브랜드 블로그 콘텐츠 작성 전문가입니다.

## 레퍼런스 분석 결과
{analysis_result}

## 작성 요청
- **주제**: {topic}
- **키워드**: {keywords}
{product_section}
{f'- **추가 요구사항**: {requirements}' if requirements else ''}

## 작성 지침
위 분석 결과의 **구조와 스타일만** 참고하여 완전히 새로운 블로그 글을 작성해주세요.
레퍼런스 글의 문장을 그대로 복사하거나 살짝 바꿔 쓰지 마세요. 내용은 100% 새로 작성하되, 분석된 톤 앤 매너와 섹션 구조를 따르세요.
중학생도 쉽게 읽힐 수 있도록 어려운 전문 용어는 피하세요.

**중요: 위 분석 결과의 "📋 서사 유형"을 확인하고, 아래에서 해당 유형의 작성법을 따르세요.**

---

### 📝 후기성/경험담 글일 때 (감정 선공형, 결론 선공형, 관리형)
스토리텔링이 포함된 경험제로 작성하세요.

**STEP 1) 오프닝 — 첫 15초 안에 잡아라**
- **반드시 마크다운 H1(#) 제목으로 글을 시작할 것**{title_instruction}
- **가치입증 먼저**: 서사 유형에 따라 오프닝 안에서 독자에게 "이 글을 읽을 가치"를 느끼게 해주세요.
  - 감정 선공형: 공감 상황을 보여주되, 가치 암시를 함께 ("저처럼 고민하셨다면, 끝까지 읽어보세요")
  - 결론 선공형: 결과를 먼저 보여주고 시작 ("지금은 이렇게 달라졌어요")
  - 추가 요구사항에 "오프닝에 결론 먼저"가 있으면 결론을 먼저 말하고 시작하세요.
- **15초 후킹**: 오프닝 3~5문장 안에 반드시 후킹이 포함되어야 합니다.
- **2가지 이상 조합 필수**: 오프닝에 아래 요소 중 최소 2가지 이상 포함하세요:
  공감대 형성 / 궁금증 유발 / 결핍 극대화 / 유머
  예) "저는 탈모 때문에 결혼도 인생도 포기한 사람입니다. 그런데 지금은 인생이 행복합니다."
- **오프닝에 제품 언급 절대 금지**: 글을 읽을지 말지 결정하는 중요한 구간에 제품을 언급하는 것은, 소개팅 첫 만남에 "사귀자"고 말하는 것과 같습니다.

**STEP 2) 메리트 — 서사 전개**
- **소제목(H2) 필수**: 반드시 H2(##) 소제목을 3~5개 포함. 서사 구조의 전환점에 배치하세요.
- **소제목 앞 여백**: 소제목(H2) 위에 빈 줄 2개를 넣어 시각적으로 구간을 분리하세요
- **기능제 표현 금지 → 경험제로 전환**: 장점을 직접 나열하지 말고, 사용 경험을 통해 간접적으로 전달하세요.
  ❌ "이 샴푸는 귀리단백질이 함유되어 탈모를 예방합니다"
  ✅ "이 샴푸 써봤는데 사진 보시는대로 이렇게 좋아졌어요. 요즘 유명한 귀리단백질 함유가 높아서인가 봅니다"
- **글쓴이 페르소나**: 추가 요구사항에 타겟이 명시되어 있다면, 그 타겟과 유사한 인물로 빙의하여 작성하세요.

**STEP 3) 클로징 — 자연스러운 마무리**
- **글의 결론은 주제에 대한 자연스러운 마무리**: 레퍼런스 서사 구조의 마지막 단계를 따르세요.{closing_product}

---

### 📖 정보성/가이드 글일 때 (정보 가이드형)
객관적이고 체계적인 정보 전달 중심으로 작성하세요. 개인 경험담이나 감정 표현은 최소화합니다.

**STEP 1) 오프닝 — 주제 도입**
- **반드시 마크다운 H1(#) 제목으로 글을 시작할 것**{title_instruction}
- **왜 이 정보가 필요한지** 배경을 간결하게 설명하고, 이 글을 읽으면 얻을 수 있는 가치를 제시하세요.
- 개인 감정("저는 너무 힘들었어요")이 아닌, 독자의 실용적 필요("이걸 모르면 돈을 낭비할 수 있습니다")로 후킹하세요.
- 오프닝에 제품 언급 금지는 동일합니다.

**STEP 2) 본론 — 정보 계층 구조**
- **소제목(H2) 필수**: 반드시 H2(##) 소제목을 4~6개 포함. 논리적 전환점(정의→분류→비교→활용→주의사항)에 배치하세요.
- **소제목 앞 여백**: 소제목(H2) 위에 빈 줄 2개를 넣어 시각적으로 구간을 분리하세요
- **팩트와 데이터 중심**: 감정 표현 대신 구체적 정보, 비교, 수치를 사용하세요.
- **체계적 구성**: 개념 설명 → 종류/유형 분류 → 각 유형 비교 → 선택 기준 → 실제 활용법 → 주의사항 순서로 정리하세요.
- 필요시 "참고로", "덧붙이자면" 등으로 부가 정보를 자연스럽게 삽입하세요.

**STEP 3) 마무리 — 핵심 요약**
- 글의 핵심 내용을 간결하게 요약하고, 독자가 바로 실행할 수 있는 결론을 제시하세요.
- 감정적 응원("여러분도 할 수 있어요!")보다 실용적 조언("이 기준으로 선택하면 실패 확률이 줄어듭니다")이 적합합니다.{info_closing_product}

---

### 포맷 지침
- 지정된 키워드를 자연스럽게 포함 (키워드 밀도 1~3%, 제목·소제목·도입부 100자 이내에 배치)
- 모든 문장은 문장 부호 뒤에 줄바꿈. 3~5문장마다 빈 줄로 문단을 구분
{char_count_instruction}
{image_instruction}{product_rules}
{NAVER_FORBIDDEN_WORDS_SECTION}"""


def build_resize_prompt(
    blog_content: str,
    target_char_count: int,
    current_char_count: int,
) -> str:
    """글자 수 조절 프롬프트"""
    direction = "늘려" if target_char_count > current_char_count else "줄여"
    diff = abs(target_char_count - current_char_count)

    if target_char_count < current_char_count:
        edit_instructions = """### 줄이기 지침:
- 중복되거나 비슷한 내용의 문장/문단을 통합하거나 삭제
- 부연 설명이나 예시 중 덜 중요한 것을 삭제
- 긴 문장을 간결하게 축약
- 핵심 메시지와 키워드는 반드시 유지
- 글의 전체 흐름(서론→본론→결론)은 유지"""
    else:
        edit_instructions = """### 늘리기 지침:
- 기존 내용을 더 구체적으로 설명
- 관련 예시나 부연 설명 추가
- 소제목 아래 내용을 더 풍부하게
- 새로운 섹션은 추가하지 말고 기존 섹션 내에서 확장
- 글의 자연스러운 흐름을 유지"""

    return f"""당신은 블로그 콘텐츠 편집 전문가입니다.

## 원본 블로그 글
{blog_content}

## 요청
현재 이 글은 공백 제외 약 {current_char_count:,}자입니다.
이 글의 글자 수(공백 제외)를 **약 {target_char_count:,}자**로 {direction}주세요. (약 {diff:,}자 {direction if direction == '늘려' else '줄여'} {'추가' if direction == '늘려' else '삭제'})

## 편집 지침
{edit_instructions}

### 공통 지침:
- 마크다운 형식 유지 (제목, 소제목, 이미지 태그 등)
- 톤 앤 매너 동일하게 유지
- **소제목(H2) 구조는 반드시 유지** — 소제목을 삭제하거나 합치지 마세요
- **키워드 밀도 1~3% 유지** — 글자수를 줄이더라도 핵심 키워드는 삭제하지 마세요. 키워드가 포함된 문장은 가능한 유지하고, 키워드 없는 부연 설명을 우선 삭제하세요
- **목표 글자수(공백 제외) {target_char_count:,}자에 최대한 근접하게 작성**

전체 글을 처음부터 끝까지 다시 작성해주세요."""


def build_edit_section_prompt(
    full_content: str,
    section_content: str,
    instruction: str,
) -> str:
    """섹션 편집 프롬프트"""
    return f"""당신은 블로그 콘텐츠 편집 전문가입니다.

## 전체 블로그 글 (참고용 — 수정하지 마세요)
{full_content}

## 수정 대상 구간
{section_content}

## 수정 지시사항
{instruction}

## 편집 규칙
1. 위 "수정 대상 구간"만 수정하세요.
2. 수정 지시사항에 따라 해당 구간을 다시 작성하세요.
3. 마크다운 형식을 유지하세요 (소제목 H2가 있었다면 H2 구조 유지).
4. 나머지 글과의 일관성(톤, 맥락, 문체)을 유지하세요.
5. 수정 대상 구간과 비슷한 분량으로 작성하세요 (대폭 늘리거나 줄이지 마세요).
6. **전체 글이 아닌, 수정 대상 구간만 출력하세요.** 다른 설명, 인사말, 부연은 포함하지 마세요."""


# ---------------------------------------------------------------------------
# 신규: 키워드 → 주제 확장 프롬프트
# ---------------------------------------------------------------------------

def build_keyword_expansion_prompt(keyword: str) -> str:
    """키워드만으로 주제 각도와 페르소나를 생성하는 프롬프트"""
    return f"""당신은 블로그 콘텐츠 기획 전문가입니다.

키워드: "{keyword}"

이 키워드를 바탕으로 네이버 블로그에 적합한 주제를 기획해주세요.

반드시 아래 JSON 형식으로만 응답하세요:
{{
  "topic": "구체적인 블로그 주제 (예: 남이섬 벚꽃 축제 봄날의 낭만을 찾아서)",
  "narrative_type": "감정 선공형" | "결론 선공형" | "관리형" | "정보 가이드형",
  "persona": {{
    "age": "30대",
    "gender": "여성",
    "role": "워킹맘",
    "tone": "친근한 경험 공유"
  }},
  "angle": "이 글만의 차별점/시각 (한 줄 설명)",
  "target_reader": "이 글을 읽을 사람 (한 줄 설명)"
}}"""


# ---------------------------------------------------------------------------
# 템플릿 로더
# ---------------------------------------------------------------------------

def load_template(template_id: str) -> str:
    """내장 분석 템플릿을 로드하여 analysis_result 문자열 반환"""
    templates_dir = Path(__file__).parent.parent / "templates"

    template_map = {
        "review": "review_style.json",
        "review-style": "review_style.json",
        "informational": "informational_style.json",
        "informational-style": "informational_style.json",
        "brand-info": "brand_info_style.json",
        "brand-informational-style": "brand_info_style.json",
        "brand-intro": "brand_intro_style.json",
        "brand-introduction-style": "brand_intro_style.json",
    }

    filename = template_map.get(template_id)
    if not filename:
        raise ValueError(f"알 수 없는 템플릿: {template_id}. 사용 가능: {list(template_map.keys())}")

    filepath = templates_dir / filename
    if not filepath.exists():
        raise FileNotFoundError(f"템플릿 파일을 찾을 수 없습니다: {filepath}")

    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    return data["analysis_result"]


def list_templates() -> list[dict]:
    """사용 가능한 템플릿 목록 반환"""
    templates_dir = Path(__file__).parent.parent / "templates"
    templates = []
    for f in sorted(templates_dir.glob("*.json")):
        with open(f, "r", encoding="utf-8") as fh:
            data = json.load(fh)
            templates.append({
                "id": data["id"],
                "name": data["name"],
                "description": data["description"],
                "file": f.name,
            })
    return templates


# ---------------------------------------------------------------------------
# 이미지 마커 추출
# ---------------------------------------------------------------------------

def extract_image_markers(content: str) -> list[str]:
    """마크다운 콘텐츠에서 [이미지: 설명] 마커를 추출"""
    pattern = r'\[이미지:\s*(.+?)\]'
    return re.findall(pattern, content)


# ---------------------------------------------------------------------------
# Gemini API 호출
# ---------------------------------------------------------------------------

async def generate_titles(
    analysis_result: str,
    topic: str,
    keywords: str,
) -> list[TitleSuggestion]:
    """AI로 제목 후보 생성"""
    client = get_client()
    prompt = build_title_prompt(analysis_result, topic, keywords)

    async def _call():
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=settings.GEMINI_MODEL_GENERATION,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.9,
                response_mime_type="application/json",
            ),
        )
        text = response.text.strip()
        # JSON 블록 추출
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()

        data = json.loads(text)
        return [TitleSuggestion(title=t["title"], subtitles=t.get("subtitles", [])) for t in data]

    return await with_retry(_call)


async def generate_content(
    analysis_result: str,
    topic: str,
    keywords: str,
    **options,
) -> str:
    """AI로 블로그 본문 생성"""
    client = get_client()
    prompt = build_generation_prompt(analysis_result, topic, keywords, **options)

    async def _call():
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=settings.GEMINI_MODEL_GENERATION,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.8,
            ),
        )
        return response.text.strip()

    return await with_retry(_call)


async def expand_keyword(keyword: str) -> dict:
    """키워드를 주제/페르소나로 확장"""
    client = get_client()
    prompt = build_keyword_expansion_prompt(keyword)

    async def _call():
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=settings.GEMINI_MODEL_GENERATION,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.7,
                response_mime_type="application/json",
            ),
        )
        text = response.text.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
        return json.loads(text)

    return await with_retry(_call)


async def analyze_reference(reference_text: str) -> str:
    """레퍼런스 블로그 글 분석"""
    client = get_client()
    prompt = build_analysis_prompt(reference_text)

    async def _call():
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=settings.GEMINI_MODEL_ANALYSIS,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.3,
            ),
        )
        return response.text.strip()

    return await with_retry(_call)


# ---------------------------------------------------------------------------
# 메인 파이프라인: 키워드 → 완성 블로그 글
# ---------------------------------------------------------------------------

async def generate_from_keyword(
    keyword: str,
    *,
    template: str = "review",
    product_name: str | None = None,
    product_advantages: str | None = None,
    product_link: str | None = None,
    requirements: str | None = None,
    char_count_range: str | None = None,
    reference_url: str | None = None,
) -> BlogPost:
    """키워드만으로 완성된 블로그 글 생성

    Args:
        keyword: 메인 키워드 (예: "남이섬 벚꽃 축제")
        template: 내장 템플릿 ID (review, informational, brand-info, brand-intro)
        product_name: 제품명 (선택)
        product_advantages: 제품 장점 (선택)
        product_link: 구매 링크 (선택)
        requirements: 추가 요구사항 (선택)
        char_count_range: 글자 수 범위 (500-1500, 1500-2500, 2500-3500)
        reference_url: 레퍼런스 블로그 URL (선택, 제공 시 크롤링 후 분석)
    """
    char_count_range = char_count_range or settings.CHAR_COUNT_RANGE

    # Step 1: 분석 결과 준비
    if reference_url:
        from core.naver_crawler import crawl_naver_blog
        print("[1/5] 레퍼런스 블로그 크롤링 중...")
        crawl_result = await crawl_naver_blog(reference_url)
        print("[2/5] 레퍼런스 분석 중...")
        analysis_result = await analyze_reference(crawl_result["content"])
    else:
        print("[1/5] 내장 템플릿 로드 중...")
        analysis_result = load_template(template)

    # Step 2: 키워드 → 주제 확장
    print("[2/5] 키워드 확장 중..." if not reference_url else "[3/5] 키워드 확장 중...")
    topic_info = await expand_keyword(keyword)
    topic = topic_info.get("topic", keyword)

    # 페르소나 정보를 requirements에 추가
    persona = topic_info.get("persona", {})
    persona_req = f"타겟/페르소나: {persona.get('age', '')} {persona.get('gender', '')} {persona.get('role', '')}, {persona.get('tone', '')}"
    if requirements:
        requirements = f"{requirements}\n{persona_req}"
    else:
        requirements = persona_req

    # Step 3: 제목 생성
    step = 3 if not reference_url else 4
    print(f"[{step}/5] 제목 생성 중...")
    titles = await generate_titles(analysis_result, topic, keyword)
    selected_title = titles[0].title if titles else topic
    print(f"  → 선택된 제목: {selected_title}")

    # Step 4: 본문 생성
    step += 1
    print(f"[{step}/5] 본문 생성 중...")
    content = await generate_content(
        analysis_result,
        topic,
        keyword,
        selected_title=selected_title,
        product_name=product_name,
        product_advantages=product_advantages,
        product_link=product_link,
        requirements=requirements,
        char_count_range=char_count_range,
    )

    # Step 5: 품질 검증
    step += 1
    print(f"[{step}/5] 품질 검증 중...")
    from core.forbidden_words import validate_content_quality
    quality = validate_content_quality(content, keyword)

    if quality["forbidden_words"]:
        print(f"  ⚠ 금지어 {len(quality['forbidden_words'])}개 발견 → 자동 대체 중...")
        from core.forbidden_words import auto_replace_forbidden
        content = auto_replace_forbidden(content)

    density = quality["keyword_density"]
    print(f"  → 글자 수: {density['total_chars']:,}자 (공백 제외)")
    print(f"  → 키워드 밀도: {density['density']:.1f}% ({density['count']}회)")

    # 이미지 마커 추출
    image_markers = extract_image_markers(content)
    print(f"  → 이미지 마커: {len(image_markers)}개")

    return BlogPost(
        title=selected_title,
        content=content,
        image_markers=image_markers,
    )
