import streamlit as st
import json
import re
import io
import base64
import time
from pathlib import Path

import google.generativeai as genai
from PIL import Image

# ──────────────────────────────────────────────
# 페이지 설정
# ──────────────────────────────────────────────
st.set_page_config(
    page_title="제안서 생성기",
    page_icon="📝",
    layout="wide",
)

# ──────────────────────────────────────────────
# 커스텀 CSS
# ──────────────────────────────────────────────
st.markdown("""
<style>
    .main-header {
        font-size: 2.2rem;
        font-weight: 700;
        margin-bottom: 0.2rem;
    }
    .sub-header {
        font-size: 1.0rem;
        color: #888;
        margin-bottom: 2rem;
    }
    .section-card {
        background: #f8f9fb;
        border-radius: 12px;
        padding: 1.5rem;
        margin-bottom: 1rem;
        border: 1px solid #e0e3ea;
    }
    .generated-section {
        background: #f0f7ff;
        border-radius: 12px;
        padding: 1.5rem;
        margin-bottom: 1rem;
        border: 1px solid #b8d4f0;
    }
    .stButton > button {
        width: 100%;
    }
</style>
""", unsafe_allow_html=True)

# ──────────────────────────────────────────────
# 파일에서 텍스트 추출
# ──────────────────────────────────────────────

def extract_text_from_file(uploaded_file) -> str:
    """업로드된 파일에서 텍스트를 추출합니다."""
    name = uploaded_file.name.lower()
    raw = uploaded_file.read()

    if name.endswith(".txt") or name.endswith(".md"):
        return raw.decode("utf-8", errors="replace")

    if name.endswith(".pdf"):
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(raw))
        pages = [p.extract_text() or "" for p in reader.pages]
        return "\n\n".join(pages)

    if name.endswith(".docx"):
        from docx import Document
        doc = Document(io.BytesIO(raw))
        return "\n".join(p.text for p in doc.paragraphs)

    if name.endswith(".pptx"):
        from pptx import Presentation
        prs = Presentation(io.BytesIO(raw))
        texts = []
        for slide in prs.slides:
            for shape in slide.shapes:
                if shape.has_text_frame:
                    texts.append(shape.text_frame.text)
        return "\n".join(texts)

    if name.endswith(".xlsx") or name.endswith(".xls"):
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(raw), data_only=True)
        texts = []
        for ws in wb.worksheets:
            for row in ws.iter_rows(values_only=True):
                row_text = "\t".join(str(c) if c is not None else "" for c in row)
                if row_text.strip():
                    texts.append(row_text)
        return "\n".join(texts)

    return raw.decode("utf-8", errors="replace")


# ──────────────────────────────────────────────
# Gemini API 호출 헬퍼
# ──────────────────────────────────────────────

TEXT_MODEL_ID = "gemini-3.1-flash-lite-preview"
IMAGE_MODEL_ID = "gemini-3.1-flash-image-preview"


def configure_api(api_key: str):
    genai.configure(api_key=api_key)


def generate_proposal_text(template_text: str, user_topic: str, additional_info: str) -> str:
    """양식을 참고하여 새 제안서 텍스트를 생성합니다."""
    prompt = f"""당신은 전문 제안서 작성자입니다. 아래에 제공된 **제안서 양식(템플릿)**의 구조, 형식, 톤, 섹션 구성을 정확히 참고하여 새로운 제안서를 작성해 주세요.

## 제안서 양식 (참고용)
---
{template_text}
---

## 새 제안서 작성 요청
- **주제/프로젝트명**: {user_topic}
- **추가 정보 및 요구사항**: {additional_info if additional_info else "없음"}

## 작성 지침
1. 위 양식의 **섹션 구조**(목차, 제목 체계)를 그대로 따르세요.
2. 양식에 있는 **형식적 요소**(표, 번호 매기기, 글머리 기호 등)를 유지하세요.
3. 내용은 새 주제에 맞게 **전문적이고 구체적으로** 작성하세요.
4. 양식에서 이미지가 들어갈 위치에는 `[이미지: 설명]` 형태의 플레이스홀더를 넣으세요.
5. 한국어로 작성하세요.
6. 마크다운 형식으로 출력하세요.
"""

    model = genai.GenerativeModel(TEXT_MODEL_ID)
    response = model.generate_content(
        prompt,
        generation_config=genai.types.GenerationConfig(
            temperature=0.7,
            max_output_tokens=8192,
        ),
    )
    return response.text


def generate_image(description: str) -> Image.Image | None:
    """Gemini 이미지 생성 모델을 사용해 이미지를 생성합니다."""
    prompt = f"""다음 설명에 맞는 전문적이고 깔끔한 비즈니스 제안서용 이미지를 생성해 주세요.
설명: {description}
스타일: 깔끔하고 전문적인 비즈니스 스타일, 높은 품질, 선명한 색상"""

    try:
        model = genai.GenerativeModel(IMAGE_MODEL_ID)
        response = model.generate_content(prompt)

        if response.candidates:
            for part in response.candidates[0].content.parts:
                if hasattr(part, "inline_data") and part.inline_data and part.inline_data.mime_type.startswith("image/"):
                    img_bytes = part.inline_data.data
                    return Image.open(io.BytesIO(img_bytes))
    except Exception as e:
        st.warning(f"이미지 생성 중 오류: {e}")

    return None


def extract_image_placeholders(text: str) -> list[str]:
    """텍스트에서 [이미지: 설명] 패턴을 추출합니다."""
    return re.findall(r"\[이미지:\s*(.+?)\]", text)


# ──────────────────────────────────────────────
# 메인 UI
# ──────────────────────────────────────────────

st.markdown('<div class="main-header">📝 제안서 생성기</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">제안서 양식을 업로드하면, 새로운 주제로 제안서를 자동 생성합니다.</div>', unsafe_allow_html=True)

# ── 사이드바 ──
with st.sidebar:
    st.header("⚙️ 설정")
    api_key = st.text_input(
        "Google Gemini API Key",
        type="password",
        placeholder="AIza...",
        help="Google AI Studio에서 API 키를 발급받으세요.",
    )
    if api_key:
        st.success("API 키가 설정되었습니다.")
    else:
        st.warning("API 키를 입력해 주세요.")

    st.divider()
    st.markdown("### 사용 방법")
    st.markdown("""
1. **API 키** 입력
2. **제안서 양식** 파일 업로드
3. 새 제안서의 **주제** 입력
4. **제안서 생성** 버튼 클릭
5. 필요시 **이미지 생성** 클릭
""")
    st.divider()
    st.caption("텍스트: gemini-3.1-flash-lite-preview")
    st.caption("이미지: gemini-3.1-flash-image-preview")

# ── 메인 영역 ──
col_left, col_right = st.columns([1, 1], gap="large")

with col_left:
    st.subheader("1. 제안서 양식 업로드")
    uploaded_file = st.file_uploader(
        "양식 파일을 선택하세요",
        type=["txt", "md", "pdf", "docx", "pptx", "xlsx"],
        help="TXT, Markdown, PDF, DOCX, PPTX, XLSX 파일을 지원합니다.",
    )

    template_text = ""
    if uploaded_file:
        with st.spinner("파일 분석 중..."):
            template_text = extract_text_from_file(uploaded_file)
        st.success(f"✅ '{uploaded_file.name}' 로드 완료 ({len(template_text):,}자)")
        with st.expander("양식 미리보기", expanded=False):
            st.text(template_text[:3000] + ("..." if len(template_text) > 3000 else ""))

    st.subheader("2. 새 제안서 정보")
    topic = st.text_input(
        "제안서 주제 / 프로젝트명",
        placeholder="예: AI 기반 스마트 물류 시스템 구축",
    )
    additional = st.text_area(
        "추가 정보 및 요구사항 (선택)",
        placeholder="예: 예산 5억 원, 기간 6개월, 대상 고객: 중소기업 ...",
        height=120,
    )

    generate_btn = st.button("🚀 제안서 생성", type="primary", use_container_width=True)

with col_right:
    st.subheader("3. 생성된 제안서")

    if generate_btn:
        # 입력 검증
        if not api_key:
            st.error("사이드바에서 API 키를 입력해 주세요.")
            st.stop()
        if not template_text:
            st.error("제안서 양식 파일을 업로드해 주세요.")
            st.stop()
        if not topic:
            st.error("제안서 주제를 입력해 주세요.")
            st.stop()

        configure_api(api_key)

        # 텍스트 생성
        with st.spinner("제안서를 생성하고 있습니다... (최대 1~2분 소요)"):
            try:
                proposal = generate_proposal_text(template_text, topic, additional)
            except Exception as e:
                st.error(f"제안서 생성 실패: {e}")
                st.stop()

        st.session_state["proposal"] = proposal
        st.session_state["images"] = {}

    # 결과 표시
    if "proposal" in st.session_state:
        proposal = st.session_state["proposal"]

        # 마크다운 렌더링
        st.markdown('<div class="generated-section">', unsafe_allow_html=True)
        st.markdown(proposal)
        st.markdown('</div>', unsafe_allow_html=True)

        # 이미지 플레이스홀더 감지
        placeholders = extract_image_placeholders(proposal)
        if placeholders:
            st.divider()
            st.subheader("4. 이미지 생성")
            st.info(f"제안서에서 {len(placeholders)}개의 이미지 플레이스홀더를 감지했습니다.")

            for i, desc in enumerate(placeholders):
                with st.container():
                    st.markdown(f"**이미지 {i+1}**: {desc}")
                    col_a, col_b = st.columns([3, 1])
                    with col_b:
                        if st.button(f"생성", key=f"img_gen_{i}"):
                            if not api_key:
                                st.error("API 키를 입력해 주세요.")
                            else:
                                configure_api(api_key)
                                with st.spinner(f"이미지 생성 중..."):
                                    img = generate_image(desc)
                                    if img:
                                        st.session_state["images"][i] = img
                    with col_a:
                        if i in st.session_state.get("images", {}):
                            st.image(st.session_state["images"][i], use_container_width=True)

        # 다운로드 버튼
        st.divider()
        col_dl1, col_dl2 = st.columns(2)
        with col_dl1:
            st.download_button(
                label="📄 마크다운으로 다운로드",
                data=proposal,
                file_name="제안서.md",
                mime="text/markdown",
                use_container_width=True,
            )
        with col_dl2:
            # HTML 변환 다운로드
            html_content = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<title>제안서 - {topic if 'topic' in dir() else ''}</title>
<style>
    body {{ font-family: 'Malgun Gothic', sans-serif; max-width: 900px; margin: 40px auto; padding: 20px; line-height: 1.8; color: #333; }}
    h1 {{ color: #1a365d; border-bottom: 3px solid #2b6cb0; padding-bottom: 10px; }}
    h2 {{ color: #2b6cb0; border-bottom: 1px solid #bee3f8; padding-bottom: 6px; margin-top: 2rem; }}
    h3 {{ color: #2c5282; }}
    table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; }}
    th, td {{ border: 1px solid #cbd5e0; padding: 10px 14px; text-align: left; }}
    th {{ background: #ebf8ff; font-weight: 600; }}
    ul, ol {{ margin: 0.5rem 0; }}
    blockquote {{ border-left: 4px solid #2b6cb0; padding-left: 1rem; color: #555; }}
</style>
</head>
<body>
{proposal}
</body>
</html>"""
            st.download_button(
                label="🌐 HTML로 다운로드",
                data=html_content,
                file_name="제안서.html",
                mime="text/html",
                use_container_width=True,
            )
    else:
        st.markdown("""
        <div class="section-card" style="text-align:center; padding: 3rem;">
            <p style="font-size: 3rem; margin-bottom: 1rem;">📋</p>
            <p style="color: #888;">왼쪽에서 양식을 업로드하고 주제를 입력한 뒤<br><b>제안서 생성</b> 버튼을 클릭하세요.</p>
        </div>
        """, unsafe_allow_html=True)
