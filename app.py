
from __future__ import annotations

import argparse
import html
import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List

import fitz


LAW_TEXT = "특허법 제29조제2항"
REJECTED_COLOR = (0.82, 0.2, 0.2)
REJECTED_FILL = (1.0, 0.93, 0.93)
ALLOWED_COLOR = (0.14, 0.45, 0.23)
ALLOWED_FILL = (0.92, 0.98, 0.92)
NEUTRAL_COLOR = (0.2, 0.2, 0.2)
NEUTRAL_FILL = (0.95, 0.95, 0.95)
KOREAN_FONT_CANDIDATES = [
    Path(r"C:\Windows\Fonts\malgun.ttf"),
    Path(r"C:\Windows\Fonts\malgunbd.ttf"),
]


@dataclass
class ClaimReason:
    claims: List[int]
    heading: str
    summary: str
    full_text: str
    cited_inventions: List[int] = field(default_factory=list)


@dataclass
class ClaimEntry:
    claim_no: int
    page_number: int
    text: str
    status: str
    short_reason: str
    full_reason: str
    cited_inventions: List[int]
    cited_details: List[Dict[str, object]] = field(default_factory=list)


def find_pdf(base_dir: Path, keyword: str, exclude: str | None = None) -> Path:
    matches: List[Path] = []
    for path in base_dir.iterdir():
        if path.suffix.lower() != ".pdf":
            continue
        name = path.name
        if keyword in name and (exclude is None or exclude not in name):
            matches.append(path)
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise FileNotFoundError(f"'{keyword}'가 포함된 PDF를 찾지 못했습니다.")
    raise RuntimeError(f"'{keyword}'가 포함된 PDF가 여러 개입니다: {[p.name for p in matches]}")


def read_pdf_text(pdf_path: Path) -> List[str]:
    doc = fitz.open(pdf_path)
    return [doc.load_page(index).get_text("text") for index in range(doc.page_count)]


def expand_claim_range(raw_text: str) -> List[int]:
    values = [int(value) for value in re.findall(r"\d+", raw_text)]
    if "내지" in raw_text and len(values) >= 2:
        return list(range(values[0], values[1] + 1))
    return values


def parse_claim_list(raw_text: str) -> List[int]:
    claims: List[int] = []
    for part in raw_text.split(","):
        claims.extend(expand_claim_range(part))
    return sorted(set(claims))


def extract_status_lists(opinion_pages: List[str]) -> tuple[List[int], List[int]]:
    combined = "\n".join(opinion_pages[:2])
    rejected_match = re.search(
        r"거절이유가 있는 부분\s*관련 법조항\s*1\s*청구항\s*(.+?)\s*특허법 제29조제2항",
        combined,
        flags=re.S,
    )
    allowed_match = re.search(r"특허\s+가능한\s+청구항\s*:\s*제(.+?)항", combined, flags=re.S)
    if not rejected_match or not allowed_match:
        raise RuntimeError("의견제출통지서에서 청구항 상태를 파싱하지 못했습니다.")

    rejected_text = rejected_match.group(1).replace("제", "")
    rejected_text = re.sub(r"\s+", " ", rejected_text).replace("항", "")
    allowed_text = allowed_match.group(1)
    return parse_claim_list(rejected_text), parse_claim_list(allowed_text)


def clean_text_block(text: str) -> str:
    text = text.replace("\r", "")
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def normalize_for_compare(text: str) -> str:
    text = text.replace("\r", " ").replace("\n", " ")
    return re.sub(r"\s+", " ", text).strip()


def extract_keywords(text: str) -> List[str]:
    stopwords = {
        "청구항",
        "인용발명",
        "발명",
        "구성",
        "포함",
        "형성",
        "이용",
        "및",
        "또는",
        "하는",
        "되는",
        "있다",
        "있도록",
        "대한",
        "에서",
        "으로",
        "이고",
        "상기",
        "복수",
        "하나",
        "부재",
        "장치",
        "방법",
    }
    words = re.findall(r"[0-9A-Za-z가-힣]{2,}", normalize_for_compare(text))
    ranked: List[str] = []
    seen: set[str] = set()
    for word in words:
        if word in stopwords or word.isdigit():
            continue
        if word not in seen:
            seen.add(word)
            ranked.append(word)
    return ranked


def split_text_passages(text: str) -> List[str]:
    normalized = text.replace("\r", "\n")
    chunks = re.split(r"\n\s*\n|(?<=[.!?])\s+", normalized)
    passages: List[str] = []
    for chunk in chunks:
        cleaned = clean_text_block(chunk)
        if len(cleaned) >= 30:
            passages.append(cleaned)
    return passages


def find_best_passage(claim_text: str, pdf_pages: List[str]) -> tuple[str, int, List[str], List[str]]:
    claim_keywords = extract_keywords(claim_text)[:12]
    best_passage = ""
    best_page = 0
    best_overlap: List[str] = []
    best_score = -1

    for page_no, page_text in enumerate(pdf_pages, start=1):
        for passage in split_text_passages(page_text):
            passage_keywords = set(extract_keywords(passage))
            overlap = [keyword for keyword in claim_keywords if keyword in passage_keywords]
            score = len(overlap)
            if score > best_score or (score == best_score and len(passage) > len(best_passage)):
                best_score = score
                best_passage = passage
                best_page = page_no
                best_overlap = overlap

    missing = [keyword for keyword in claim_keywords if keyword not in best_overlap][:6]
    return best_passage, best_page, best_overlap[:6], missing


def analyze_cited_invention(entry: ClaimEntry, invention_no: int, pdf_path: Path | None) -> Dict[str, object]:
    if pdf_path is None:
        return {
            "invention_no": invention_no,
            "pdf_name": "",
            "uploaded": False,
            "page_number": 0,
            "matched_passage": "",
            "overlap_keywords": [],
            "missing_keywords": [],
            "difference_summary": "해당 인용발명 PDF가 업로드되지 않아 원문 비교를 하지 못했습니다.",
        }

    pdf_pages = read_pdf_text(pdf_path)
    matched_passage, page_number, overlap_keywords, missing_keywords = find_best_passage(entry.text, pdf_pages)

    if matched_passage:
        if missing_keywords:
            difference_summary = (
                f"인용발명 {invention_no}에서 유사한 문단을 찾았지만 "
                f"청구항 핵심어 {', '.join(missing_keywords)}는 직접 확인되지 않았습니다."
            )
        else:
            difference_summary = f"인용발명 {invention_no}에서 청구항과 겹치는 구성을 다수 확인했습니다."
    else:
        difference_summary = f"인용발명 {invention_no} PDF에서 청구항과 직접 대응되는 문단을 찾지 못했습니다."

    return {
        "invention_no": invention_no,
        "pdf_name": pdf_path.name,
        "uploaded": True,
        "page_number": page_number,
        "matched_passage": matched_passage,
        "overlap_keywords": overlap_keywords,
        "missing_keywords": missing_keywords,
        "difference_summary": difference_summary,
    }


def enrich_with_cited_inventions(
    claim_entries: Dict[int, ClaimEntry],
    cited_pdf_map: Dict[int, Path] | None,
) -> Dict[int, Path]:
    normalized_map = {number: path.resolve() for number, path in (cited_pdf_map or {}).items() if path}
    for entry in claim_entries.values():
        entry.cited_details = []
        for invention_no in entry.cited_inventions:
            entry.cited_details.append(
                analyze_cited_invention(entry, invention_no, normalized_map.get(invention_no))
            )
    return normalized_map


def summarize_reason(block: str, claim_numbers: List[int]) -> tuple[str, List[int]]:
    cited_inventions = sorted({int(num) for num in re.findall(r"인용발명\s*(\d+)", block)})
    cited_text = ", ".join(str(num) for num in cited_inventions)

    if "단순한 결합" in block or len(cited_inventions) > 1:
        summary = f"인용발명 {cited_text}의 결합으로 통상의 기술자가 쉽게 발명 가능"
    elif cited_inventions:
        summary = f"인용발명 {cited_text}로부터 통상의 기술자가 쉽게 발명 가능"
    else:
        summary = "통상의 기술자가 쉽게 발명 가능하다고 판단"

    if claim_numbers == [10, 11]:
        summary = f"냉각유로/냉각블록 구성에 대해 {summary}"
    return summary, cited_inventions


def extract_claim_reasons(opinion_pages: List[str]) -> Dict[int, ClaimReason]:
    body = "\n".join(opinion_pages[1:6])
    raw_lines = body.splitlines()
    lines: List[str] = []
    for line in raw_lines:
        stripped = line.strip()
        if not stripped:
            continue
        if re.fullmatch(r"10-2024-0124870", stripped):
            continue
        if re.fullmatch(r"\d/7", stripped):
            continue
        if re.match(r"첨부\d", stripped):
            continue
        if stripped == "[첨 부]":
            continue
        lines.append(stripped)

    results: Dict[int, ClaimReason] = {}
    current_block: List[str] = []

    def flush_block(block_lines: List[str]) -> None:
        if not block_lines:
            return
        heading_line = re.sub(r"^1-\d+\.\s*", "", block_lines[0]).strip()
        normalized_heading = re.sub(r"\([^)]*\)", "", heading_line)
        claim_numbers = [int(value) for value in re.findall(r"제(\d+)항", normalized_heading)]
        if not claim_numbers:
            return
        content = "\n".join(block_lines[1:])
        full_text = clean_text_block(f"{heading_line}\n{content}")
        summary, cited_inventions = summarize_reason(full_text, claim_numbers)
        reason = ClaimReason(
            claims=claim_numbers,
            heading=clean_text_block(heading_line),
            summary=summary,
            full_text=full_text,
            cited_inventions=cited_inventions,
        )
        for claim_number in claim_numbers:
            results[claim_number] = reason

    for line in lines:
        if line.startswith("[보정에 관한 참고사항]"):
            flush_block(current_block)
            break
        if re.match(r"^1-\d+\.\s*청구항", line):
            flush_block(current_block)
            current_block = [line]
            continue
        if current_block:
            current_block.append(line)

    flush_block(current_block)
    return results


def extract_claim_texts(spec_pdf: Path) -> Dict[int, ClaimEntry]:
    doc = fitz.open(spec_pdf)
    claim_pages = range(18, min(doc.page_count, 23))
    records: Dict[int, ClaimEntry] = {}

    for page_index in claim_pages:
        text = doc.load_page(page_index).get_text("text")
        matches = list(re.finditer(r"【청구항\s*(\d+)】", text))
        for idx, match in enumerate(matches):
            claim_no = int(match.group(1))
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
            claim_text = clean_text_block(text[match.start():end])
            records[claim_no] = ClaimEntry(
                claim_no=claim_no,
                page_number=page_index + 1,
                text=claim_text,
                status="미분류",
                short_reason="",
                full_reason="",
                cited_inventions=[],
            )

    if len(records) != 18:
        raise RuntimeError(f"배터리케이스 PDF에서 청구항을 모두 찾지 못했습니다. 현재: {sorted(records)}")
    return records


def decorate_claims(
    claim_entries: Dict[int, ClaimEntry],
    rejected_claims: Iterable[int],
    allowed_claims: Iterable[int],
    reasons_by_claim: Dict[int, ClaimReason],
) -> None:
    rejected_set = set(rejected_claims)
    allowed_set = set(allowed_claims)

    for claim_no, entry in claim_entries.items():
        if claim_no in rejected_set:
            reason = reasons_by_claim.get(claim_no)
            entry.status = "거절이유"
            entry.short_reason = reason.summary if reason else "진보성 부족"
            entry.full_reason = reason.full_text if reason else LAW_TEXT
            entry.cited_inventions = reason.cited_inventions if reason else []
        elif claim_no in allowed_set:
            entry.status = "특허 가능"
            entry.short_reason = "의견제출통지 시점 기준 특허 가능 청구항"
            entry.full_reason = "의견제출통지서에 따르면 현재 심사 의견상 특허 가능 청구항으로 표시되었습니다."
            entry.cited_inventions = []


def find_heading_rect(page: fitz.Page, claim_no: int) -> fitz.Rect | None:
    for candidate in (f"【청구항 {claim_no}】", f"청구항 {claim_no}"):
        matches = page.search_for(candidate)
        if matches:
            return matches[0]
    return None


def build_note_rect(page: fitz.Page, heading_rect: fitz.Rect) -> fitz.Rect:
    page_rect = page.rect
    box_width = 84
    box_height = 16
    margin = 8

    right_x0 = min(max(heading_rect.x1 + 6, page_rect.x0 + margin), page_rect.x1 - box_width - margin)
    right_y0 = min(max(heading_rect.y0 + 1, page_rect.y0 + margin), page_rect.y1 - box_height - margin)
    right_rect = fitz.Rect(right_x0, right_y0, right_x0 + box_width, right_y0 + box_height)

    if right_rect.x0 >= heading_rect.x1 + 4:
        return right_rect

    above_y0 = heading_rect.y0 - box_height - 4
    if above_y0 >= page_rect.y0 + margin:
        x0 = min(max(heading_rect.x0, page_rect.x0 + margin), page_rect.x1 - box_width - margin)
        return fitz.Rect(x0, above_y0, x0 + box_width, above_y0 + box_height)

    below_y0 = min(heading_rect.y1 + 4, page_rect.y1 - box_height - margin)
    x0 = min(max(heading_rect.x0, page_rect.x0 + margin), page_rect.x1 - box_width - margin)
    return fitz.Rect(x0, below_y0, x0 + box_width, below_y0 + box_height)


def annotate_spec_pdf(
    source_pdf: Path,
    output_pdf: Path,
    claim_entries: Dict[int, ClaimEntry],
) -> Path:
    doc = fitz.open(source_pdf)
    font_path = next((path for path in KOREAN_FONT_CANDIDATES if path.exists()), None)

    for entry in claim_entries.values():
        page = doc.load_page(entry.page_number - 1)
        rect = find_heading_rect(page, entry.claim_no)
        if rect is None:
            continue

        if entry.status == "????":
            border, fill = REJECTED_COLOR, REJECTED_FILL
        elif entry.status == "?? ??":
            border, fill = ALLOWED_COLOR, ALLOWED_FILL
        else:
            border, fill = NEUTRAL_COLOR, NEUTRAL_FILL

        highlight = fitz.Rect(rect.x0 - 4, rect.y0 - 3, rect.x1 + 4, rect.y1 + 3)
        note_rect = build_note_rect(page, rect)

        page.draw_rect(highlight, color=border, width=0.9)
        page.draw_rect(note_rect, color=border, width=0.8)

        short_status = "거절" if entry.status == "????" else "가능" if entry.status == "?? ??" else "검토"
        note_text = f"청{entry.claim_no} {short_status}"

        if font_path is not None:
            page.insert_font(fontname="kfont", fontfile=str(font_path))
            font_name = "kfont"
        else:
            font_name = "helv"

        page.insert_textbox(
            note_rect + (3, 2, -3, -2),
            note_text,
            fontsize=4.6,
            fontname=font_name,
            color=border,
            align=1,
        )

    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    try:
        doc.save(output_pdf)
        return output_pdf
    except fitz.FileDataError:
        raise
    except Exception as exc:
        if "Permission denied" not in str(exc):
            raise
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        fallback = output_pdf.with_stem(f"{output_pdf.stem}_{timestamp}")
        doc.save(fallback)
        return fallback
def build_html_report(
    output_path: Path,
    source_spec_pdf: Path,
    source_opinion_pdf: Path,
    annotated_pdf: Path,
    claim_entries: Dict[int, ClaimEntry],
    rejected_claims: List[int],
    allowed_claims: List[int],
    cited_pdf_map: Dict[int, Path] | None = None,
) -> None:
    output_dir = output_path.parent
    annotated_href = annotated_pdf.name
    spec_href = Path(os.path.relpath(source_spec_pdf, output_dir)).as_posix()
    opinion_href = Path(os.path.relpath(source_opinion_pdf, output_dir)).as_posix()
    cited_pdf_map = cited_pdf_map or {}
    cited_links = [
        (number, Path(os.path.relpath(path, output_dir)).as_posix(), path.name)
        for number, path in sorted(cited_pdf_map.items())
    ]

    claim_cards: List[str] = []
    sidebar_items: List[str] = []
    table_rows: List[str] = []

    for claim_no in sorted(claim_entries):
        entry = claim_entries[claim_no]
        badge_class = "rejected" if entry.status == "거절이유" else "allowed"
        cited_text = ", ".join(str(value) for value in entry.cited_inventions) or "-"

        sidebar_items.append(
            f"""
            <a class="nav-item" href="#claim-{entry.claim_no}">
              <span class="nav-icon">{entry.claim_no}</span>
              <span>청구항 {entry.claim_no}</span>
            </a>
            """
        )

        table_rows.append(
            f"""
            <tr>
              <td>청구항 {entry.claim_no}</td>
              <td><span class="badge {badge_class}">{html.escape(entry.status)}</span></td>
              <td>{entry.page_number}</td>
              <td>{html.escape(cited_text)}</td>
            </tr>
            """
        )

        cited_sections: List[str] = []
        for detail in entry.cited_details:
            overlap = ", ".join(str(value) for value in detail["overlap_keywords"]) or "-"
            missing = ", ".join(str(value) for value in detail["missing_keywords"]) or "-"
            uploaded_text = "업로드 완료" if detail["uploaded"] else "미업로드"
            matched_passage = html.escape(str(detail["matched_passage"]) or "관련 본문을 찾지 못했습니다.")
            cited_sections.append(
                f"""
                <section class="detail-panel cited-panel">
                  <h4>인용발명 {detail["invention_no"]} 비교</h4>
                  <p class="cited-meta">{uploaded_text} · 페이지 {detail["page_number"] or "-"}</p>
                  <p class="card-summary">{html.escape(str(detail["difference_summary"]))}</p>
                  <p class="keyword-line"><strong>겹치는 키워드</strong> {html.escape(overlap)}</p>
                  <p class="keyword-line"><strong>추가 확인 필요</strong> {html.escape(missing)}</p>
                  <pre>{matched_passage}</pre>
                </section>
                """
            )

        claim_cards.append(
            f"""
            <article class="claim-card" id="claim-{entry.claim_no}">
              <div class="claim-card-top">
                <div class="claim-chip">#{entry.claim_no}</div>
                <span class="badge {badge_class}">{html.escape(entry.status)}</span>
              </div>
              <h3>청구항 {entry.claim_no}</h3>
              <p class="card-sub">페이지 {entry.page_number} · 인용발명 {html.escape(cited_text)}</p>
              <p class="card-summary">{html.escape(entry.short_reason)}</p>
              <details class="detail-box" {'open' if entry.status == '거절이유' else ''}>
                <summary>상세 보기</summary>
                <div class="detail-grid">
                  <section class="detail-panel">
                    <h4>청구항 본문</h4>
                    <pre>{html.escape(entry.text)}</pre>
                  </section>
                  <section class="detail-panel">
                    <h4>거절이유 / 심사의견</h4>
                    <pre>{html.escape(entry.full_reason)}</pre>
                  </section>
                  {"".join(cited_sections)}
                </div>
              </details>
            </article>
            """
        )

    html_text = f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>동희산업 배터리케이스 청구항 표시 결과</title>
  <style>
    :root {{
      --bg: #f5f7ff;
      --panel: #ffffff;
      --ink: #28304a;
      --muted: #7b84a3;
      --line: #e8ebf7;
      --accent: #6d7cff;
      --accent-soft: #eef1ff;
      --accent-deep: #4d5de0;
      --reject: #ff8b6b;
      --reject-bg: #fff2ed;
      --allow: #23b98f;
      --allow-bg: #ebfff8;
      --shadow: 0 18px 40px rgba(102, 118, 191, 0.12);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background:
        linear-gradient(180deg, #eef2ff 0%, #f8f9ff 180px, var(--bg) 100%);
      font-family: "Malgun Gothic", "Apple SD Gothic Neo", sans-serif;
      color: var(--ink);
    }}
    a {{ color: inherit; }}
    .topbar {{
      height: 74px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 24px;
      border-bottom: 1px solid rgba(255,255,255,0.45);
      position: sticky;
      top: 0;
      background: rgba(245, 247, 255, 0.86);
      backdrop-filter: blur(16px);
      z-index: 10;
    }}
    .brand {{
      display: flex;
      align-items: center;
      gap: 14px;
      font-weight: 800;
      font-size: 22px;
    }}
    .brand-badge {{
      width: 38px;
      height: 38px;
      border-radius: 12px;
      background: linear-gradient(135deg, var(--accent), #8ea0ff);
      color: white;
      display: grid;
      place-items: center;
      font-size: 14px;
      box-shadow: 0 12px 24px rgba(109, 124, 255, 0.35);
    }}
    .searchbar {{
      width: min(560px, 45vw);
      display: flex;
      align-items: center;
      border: 1px solid #dfe4ff;
      border-radius: 999px;
      overflow: hidden;
      background: rgba(255,255,255,0.95);
      box-shadow: 0 8px 24px rgba(134, 147, 206, 0.12);
    }}
    .searchbar input {{
      width: 100%;
      border: 0;
      padding: 14px 18px;
      font-size: 15px;
      outline: none;
      color: #6b7391;
      background: transparent;
    }}
    .search-action {{
      width: 62px;
      height: 50px;
      border-left: 1px solid #e5e9ff;
      background: #f7f8ff;
      display: grid;
      place-items: center;
      color: var(--accent);
    }}
    .layout {{
      display: grid;
      grid-template-columns: 210px minmax(0, 1fr);
      gap: 28px;
      padding: 24px;
    }}
    aside {{
      position: sticky;
      top: 98px;
      align-self: start;
      background: rgba(255,255,255,0.75);
      border: 1px solid rgba(255,255,255,0.8);
      box-shadow: var(--shadow);
      border-radius: 26px;
      padding: 20px 14px;
      backdrop-filter: blur(12px);
    }}
    .side-group {{
      padding-bottom: 16px;
      border-bottom: 1px solid var(--line);
      margin-bottom: 16px;
    }}
    .side-title {{
      font-size: 15px;
      font-weight: 700;
      margin: 0 0 10px;
      padding: 0 12px;
    }}
    .nav-item {{
      text-decoration: none;
      display: flex;
      align-items: center;
      gap: 12px;
      padding: 10px 12px;
      border-radius: 12px;
      margin-bottom: 4px;
      color: var(--muted);
      font-size: 14px;
      font-weight: 700;
    }}
    .nav-item:hover {{
      background: var(--accent-soft);
      color: var(--accent-deep);
    }}
    .nav-icon {{
      width: 28px;
      height: 28px;
      border-radius: 10px;
      background: var(--accent-soft);
      color: var(--accent-deep);
      display: grid;
      place-items: center;
      font-size: 12px;
      font-weight: 700;
      flex: 0 0 auto;
    }}
    main {{
      display: grid;
      gap: 18px;
    }}
    .hero {{
      display: flex;
      justify-content: space-between;
      gap: 20px;
      align-items: flex-start;
      padding: 8px 6px 10px;
    }}
    .hero h1 {{
      margin: 0 0 10px;
      font-size: 30px;
      line-height: 1.2;
    }}
    .hero p {{
      margin: 0;
      color: var(--muted);
      line-height: 1.55;
      max-width: 760px;
    }}
    .links {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 16px;
    }}
    .links a {{
      text-decoration: none;
      background: var(--panel);
      color: var(--accent-deep);
      border: 1px solid #dde3ff;
      padding: 10px 14px;
      border-radius: 999px;
      box-shadow: 0 8px 18px rgba(121, 135, 200, 0.1);
      font-size: 14px;
      font-weight: 700;
    }}
    .hero-side {{
      min-width: 280px;
      background: linear-gradient(180deg, #ffffff, #f9faff);
      border-radius: 24px;
      padding: 16px;
      border: 1px solid #edf0ff;
      box-shadow: var(--shadow);
    }}
    .hero-side h3 {{
      margin: 0 0 12px;
      font-size: 16px;
    }}
    .hero-side p {{
      margin: 0 0 10px;
      font-size: 14px;
      color: var(--muted);
    }}
    .chips {{
      display: flex;
      gap: 10px;
      overflow-x: auto;
      padding: 0 4px 8px;
    }}
    .chip {{
      padding: 10px 14px;
      border-radius: 10px;
      background: #ffffff;
      border: 1px solid #e7ebff;
      white-space: nowrap;
      font-size: 14px;
      font-weight: 700;
      color: var(--muted);
    }}
    .chip.active {{
      background: linear-gradient(135deg, var(--accent), #8ea0ff);
      color: white;
      border-color: transparent;
      box-shadow: 0 12px 24px rgba(109, 124, 255, 0.28);
    }}
    .stats {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 18px;
    }}
    .stat {{
      background: linear-gradient(180deg, #ffffff, #f9faff);
      border: 1px solid #edf0ff;
      border-radius: 24px;
      padding: 20px;
      box-shadow: var(--shadow);
    }}
    .stat h3 {{
      margin: 0 0 8px;
      font-size: 18px;
    }}
    .stat p {{
      margin: 0;
      color: var(--muted);
      font-size: 14px;
      line-height: 1.5;
    }}
    .dashboard-grid {{
      display: grid;
      grid-template-columns: 1.5fr 1fr 1fr;
      gap: 18px;
    }}
    .badge {{
      display: inline-block;
      padding: 4px 10px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 700;
    }}
    .badge.rejected {{ color: var(--reject); background: var(--reject-bg); }}
    .badge.allowed {{ color: var(--allow); background: var(--allow-bg); }}
    .panel {{
      background: linear-gradient(180deg, #ffffff, #f9faff);
      border: 1px solid #edf0ff;
      border-radius: 24px;
      padding: 20px;
      box-shadow: var(--shadow);
      min-width: 0;
    }}
    .panel h2 {{
      margin: 0 0 14px;
      font-size: 17px;
    }}
    .chart-card {{
      min-height: 280px;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
    }}
    .profit {{
      font-size: 28px;
      font-weight: 800;
      margin: 4px 0 0;
      color: var(--accent-deep);
    }}
    .chart-area {{
      height: 150px;
      margin-top: 12px;
      border-radius: 18px;
      background:
        linear-gradient(180deg, rgba(109,124,255,0.12), rgba(109,124,255,0.02)),
        repeating-linear-gradient(to right, transparent 0, transparent 46px, rgba(213,219,255,0.65) 46px, rgba(213,219,255,0.65) 47px),
        repeating-linear-gradient(to top, transparent 0, transparent 36px, rgba(232,235,247,0.85) 36px, rgba(232,235,247,0.85) 37px);
      position: relative;
      overflow: hidden;
    }}
    .chart-line {{
      position: absolute;
      inset: 18px 16px 20px;
    }}
    .chart-line svg {{
      width: 100%;
      height: 100%;
    }}
    .mini-list {{
      display: grid;
      gap: 12px;
    }}
    .mini-row {{
      display: grid;
      grid-template-columns: 28px 1fr auto;
      gap: 10px;
      align-items: center;
      color: var(--muted);
      font-size: 14px;
    }}
    .dot {{
      width: 10px;
      height: 10px;
      border-radius: 50%;
      background: var(--accent);
      box-shadow: 0 0 0 6px rgba(109,124,255,0.12);
    }}
    .pie-card {{
      display: grid;
      place-items: center;
      min-height: 280px;
    }}
    .pie {{
      width: 180px;
      height: 180px;
      border-radius: 50%;
      background: conic-gradient(#7a5cff 0 42%, #ffca63 42% 66%, #19c7c7 66% 81%, #57d68d 81% 92%, #cdd3f5 92% 100%);
      position: relative;
      margin: 10px auto 18px;
      box-shadow: 0 16px 34px rgba(122, 92, 255, 0.18);
    }}
    .pie::after {{
      content: "";
      position: absolute;
      inset: 42px;
      background: white;
      border-radius: 50%;
    }}
    .legend {{
      width: 100%;
      display: grid;
      gap: 10px;
      font-size: 14px;
      color: var(--muted);
    }}
    .legend-row {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
    }}
    .legend-label {{
      display: flex;
      align-items: center;
      gap: 8px;
    }}
    .legend-swatch {{
      width: 10px;
      height: 10px;
      border-radius: 50%;
    }}
    .summary-card {{
      margin: 0;
      background: linear-gradient(180deg, #ffffff, #f9faff);
      border: 1px solid #edf0ff;
      border-radius: 24px;
      padding: 20px;
      box-shadow: var(--shadow);
    }}
    .summary-card p {{
      margin: 0 0 8px;
      color: var(--muted);
      line-height: 1.55;
    }}
    .table-card table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 14px;
    }}
    .table-card th, .table-card td {{
      padding: 12px 10px;
      border-bottom: 1px solid var(--line);
      text-align: left;
    }}
    .table-card th {{
      color: var(--muted);
      font-weight: 700;
    }}
    .claim-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 18px;
    }}
    .claim-card {{
      background: linear-gradient(180deg, #ffffff, #fbfcff);
      border: 1px solid #edf0ff;
      border-radius: 22px;
      padding: 18px;
      box-shadow: var(--shadow);
    }}
    .claim-card-top {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      margin-bottom: 12px;
    }}
    .claim-chip {{
      width: 36px;
      height: 36px;
      display: grid;
      place-items: center;
      border-radius: 12px;
      background: var(--accent-soft);
      color: var(--accent-deep);
      font-weight: 800;
    }}
    .claim-card h3 {{
      margin: 0 0 8px;
      font-size: 19px;
    }}
    .card-sub, .card-summary {{
      margin: 0;
      color: var(--muted);
      font-size: 14px;
      line-height: 1.5;
    }}
    .card-summary {{
      margin-top: 8px;
      color: #4d5677;
    }}
    .detail-box {{
      margin-top: 14px;
      background: #fafbff;
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 12px 14px;
    }}
    .detail-grid {{
      display: grid;
      grid-template-columns: 1fr;
      gap: 12px;
      margin-top: 12px;
    }}
    .detail-panel {{
      background: white;
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 14px;
    }}
    .detail-panel h4 {{
      margin: 0 0 10px;
      font-size: 14px;
    }}
    .cited-panel {{
      background: #f8fbff;
    }}
    .cited-meta, .keyword-line {{
      margin: 0 0 8px;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.5;
    }}
    pre {{
      white-space: pre-wrap;
      word-break: keep-all;
      background: #ffffff;
      border: 1px solid #efefef;
      border-radius: 14px;
      padding: 12px;
      font-family: "Consolas", monospace;
      font-size: 12px;
      line-height: 1.55;
    }}
    details summary {{
      cursor: pointer;
      color: var(--accent-deep);
      font-weight: 700;
      list-style: none;
    }}
    @media (max-width: 1280px) {{
      .dashboard-grid {{ grid-template-columns: 1fr 1fr; }}
      .claim-grid {{ grid-template-columns: 1fr; }}
    }}
    @media (max-width: 1024px) {{
      .layout {{ grid-template-columns: 1fr; }}
      aside {{ position: static; }}
      .stats {{ grid-template-columns: 1fr; }}
      .hero {{ flex-direction: column; }}
      .dashboard-grid {{ grid-template-columns: 1fr; }}
    }}
    @media (max-width: 720px) {{
      .topbar {{ padding: 0 14px; gap: 12px; }}
      .brand {{ font-size: 20px; }}
      .searchbar {{ width: 100%; }}
      .layout {{ padding: 14px; }}
      .claim-grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <header class="topbar">
    <div class="brand">
      <span class="brand-badge">▣</span>
      <span>Claim Dashboard</span>
    </div>
    <div class="searchbar">
      <input value="배터리 케이스 청구항 분석 현황" readonly>
      <div class="search-action">⌕</div>
    </div>
    <div class="badge allowed">동희산업</div>
  </header>

  <div class="layout">
    <aside>
      <div class="side-group">
        <div class="side-title">바로가기</div>
        <a class="nav-item" href="{html.escape(annotated_href)}"><span class="nav-icon">PDF</span><span>표시된 PDF</span></a>
        <a class="nav-item" href="{html.escape(spec_href)}"><span class="nav-icon">명</span><span>원본 명세서</span></a>
        <a class="nav-item" href="{html.escape(opinion_href)}"><span class="nav-icon">의</span><span>원본 의견제출</span></a>
        {"".join(f'<a class="nav-item" href="{html.escape(href)}"><span class="nav-icon">C{number}</span><span>인용발명 {number}</span></a>' for number, href, _ in cited_links)}
      </div>
      <div class="side-group">
        <div class="side-title">청구항 이동</div>
        {"".join(sidebar_items)}
      </div>
    </aside>

    <main>
      <section class="hero">
        <div>
          <h1>동희산업 배터리케이스 청구항 분석 대시보드</h1>
          <p>의견제출통지서의 거절이유를 기준으로 명세서 청구항을 한 화면에서 관리할 수 있도록 요약 위젯, 상태표, 청구항 상세 카드로 재구성했습니다.</p>
          <div class="links">
            <a href="{html.escape(annotated_href)}">표시된 PDF 열기</a>
            <a href="{html.escape(spec_href)}">명세서 PDF</a>
            <a href="{html.escape(opinion_href)}">의견제출 PDF</a>
            {"".join(f'<a href="{html.escape(href)}">인용발명 {number} PDF</a>' for number, href, _ in cited_links)}
          </div>
        </div>
        <section class="hero-side">
          <h3>분석 요약</h3>
          <p>거절이유 청구항: {", ".join(str(v) for v in rejected_claims)}</p>
          <p>특허 가능 청구항: {", ".join(str(v) for v in allowed_claims)}</p>
          <p>업로드된 인용발명 PDF: {", ".join(str(number) for number, _, _ in cited_links) or "없음"}</p>
          <p>관련 법조항: {LAW_TEXT}</p>
        </section>
      </section>

      <div class="chips">
        <div class="chip active">전체</div>
        <div class="chip">진보성 거절</div>
        <div class="chip">특허 가능</div>
        <div class="chip">청구항 표</div>
        <div class="chip">상세 카드</div>
      </div>

      <section class="stats">
        <div class="stat"><h3>거절이유 청구항</h3><p>{", ".join(str(v) for v in rejected_claims)}</p></div>
        <div class="stat"><h3>특허 가능 청구항</h3><p>{", ".join(str(v) for v in allowed_claims)}</p></div>
        <div class="stat"><h3>관련 법조항</h3><p>{LAW_TEXT}</p></div>
      </section>

      <section class="dashboard-grid">
        <section class="panel chart-card">
          <div>
            <h2>청구항 처리 현황</h2>
            <p class="profit">{len(rejected_claims)} / {len(claim_entries)} 지적</p>
          </div>
          <div class="chart-area">
            <div class="chart-line">
              <svg viewBox="0 0 300 100" preserveAspectRatio="none" aria-hidden="true">
                <path d="M0,78 C30,76 44,70 63,64 C84,57 102,70 121,54 C143,35 165,42 187,28 C214,12 238,22 260,18 C276,15 288,18 300,12" fill="none" stroke="#6d7cff" stroke-width="4" stroke-linecap="round"/>
              </svg>
            </div>
          </div>
        </section>

        <section class="panel">
          <h2>핵심 포인트</h2>
          <div class="mini-list">
            <div class="mini-row"><span class="dot"></span><span>진보성 거절 중심</span><strong>{len(rejected_claims)}건</strong></div>
            <div class="mini-row"><span class="dot" style="background:#23b98f; box-shadow:0 0 0 6px rgba(35,185,143,0.12)"></span><span>특허 가능 청구항</span><strong>{len(allowed_claims)}건</strong></div>
            <div class="mini-row"><span class="dot" style="background:#ffb14a; box-shadow:0 0 0 6px rgba(255,177,74,0.12)"></span><span>검토 총 청구항</span><strong>{len(claim_entries)}건</strong></div>
          </div>
        </section>

        <section class="panel pie-card">
          <div>
            <h2>상태 비율</h2>
            <div class="pie"></div>
            <div class="legend">
              <div class="legend-row"><span class="legend-label"><span class="legend-swatch" style="background:#7a5cff"></span>거절이유</span><span>{len(rejected_claims)}</span></div>
              <div class="legend-row"><span class="legend-label"><span class="legend-swatch" style="background:#57d68d"></span>특허 가능</span><span>{len(allowed_claims)}</span></div>
              <div class="legend-row"><span class="legend-label"><span class="legend-swatch" style="background:#cdd3f5"></span>기타</span><span>{max(0, len(claim_entries)-len(rejected_claims)-len(allowed_claims))}</span></div>
            </div>
          </div>
        </section>
      </section>

      <section class="dashboard-grid">
        <section class="panel table-card">
          <h2>청구항 상태표</h2>
          <table>
            <thead>
              <tr>
                <th>청구항</th>
                <th>상태</th>
                <th>페이지</th>
                <th>인용발명</th>
              </tr>
            </thead>
            <tbody>
              {"".join(table_rows)}
            </tbody>
          </table>
        </section>

        <section class="summary-card">
          <h2 style="margin:0 0 14px; font-size:17px;">표시 기준</h2>
          <p>주황 배지는 의견제출통지서에서 진보성 거절이유가 지적된 청구항입니다.</p>
          <p>초록 배지는 의견제출 시점 기준 특허 가능 청구항입니다.</p>
          <p>아래 카드에서 각 청구항의 원문과 심사의견 전문을 확인할 수 있습니다.</p>
        </section>
      </section>

      <section class="claim-grid">
        {"".join(claim_cards)}
      </section>
    </main>
  </div>
</body>
</html>
"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_text, encoding="utf-8")


def write_json(output_path: Path, claim_entries: Dict[int, ClaimEntry]) -> None:
    payload = [asdict(claim_entries[key]) for key in sorted(claim_entries)]
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def process_pdfs(
    opinion_pdf: Path,
    spec_pdf: Path,
    output_dir: Path,
    cited_pdf_map: Dict[int, Path] | None = None,
) -> Dict[str, Path]:
    opinion_pdf = opinion_pdf.resolve()
    spec_pdf = spec_pdf.resolve()
    output_dir = output_dir.resolve()

    opinion_pages = read_pdf_text(opinion_pdf)
    rejected_claims, allowed_claims = extract_status_lists(opinion_pages)
    reasons_by_claim = extract_claim_reasons(opinion_pages)
    claim_entries = extract_claim_texts(spec_pdf)
    decorate_claims(claim_entries, rejected_claims, allowed_claims, reasons_by_claim)
    cited_pdf_map = enrich_with_cited_inventions(claim_entries, cited_pdf_map)

    annotated_pdf = output_dir / "동희산업_배터리케이스_청구항표시.pdf"
    html_report = output_dir / "result.html"
    json_report = output_dir / "claim_mapping.json"

    annotated_pdf = annotate_spec_pdf(spec_pdf, annotated_pdf, claim_entries)
    build_html_report(
        html_report,
        spec_pdf,
        opinion_pdf,
        annotated_pdf,
        claim_entries,
        rejected_claims,
        allowed_claims,
        cited_pdf_map,
    )
    write_json(json_report, claim_entries)

    return {
        "annotated_pdf": annotated_pdf,
        "html_report": html_report,
        "json_report": json_report,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="의견제출통지서의 거절이유를 배터리케이스 PDF 청구항에 표시합니다."
    )
    parser.add_argument("--base-dir", default=".", help="PDF가 있는 작업 폴더")
    parser.add_argument("--output-dir", default="output", help="결과 저장 폴더")
    parser.add_argument("--opinion-pdf", help="의견제출 PDF 경로")
    parser.add_argument("--spec-pdf", help="명세서 PDF 경로")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    base_dir = Path(args.base_dir).resolve()
    output_dir = (base_dir / args.output_dir).resolve()

    opinion_pdf = Path(args.opinion_pdf).resolve() if args.opinion_pdf else find_pdf(base_dir, "의견제출")
    spec_pdf = Path(args.spec_pdf).resolve() if args.spec_pdf else find_pdf(base_dir, "배터리케이스", exclude="의견제출")
    result = process_pdfs(opinion_pdf, spec_pdf, output_dir)

    print("생성 완료")
    print(f"- 표시된 PDF: {result['annotated_pdf']}")
    print(f"- HTML 보고서: {result['html_report']}")
    print(f"- JSON 데이터: {result['json_report']}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="의견제출통지서의 거절이유를 배터리케이스 PDF 청구항에 표시합니다."
    )
    parser.add_argument("--base-dir", default=".", help="PDF가 있는 작업 폴더")
    parser.add_argument("--output-dir", default="output", help="결과 저장 폴더")
    parser.add_argument("--opinion-pdf", help="의견제출 PDF 경로")
    parser.add_argument("--spec-pdf", help="명세서 PDF 경로")
    parser.add_argument("--cited1-pdf", help="인용발명 1 PDF 경로")
    parser.add_argument("--cited2-pdf", help="인용발명 2 PDF 경로")
    parser.add_argument("--cited3-pdf", help="인용발명 3 PDF 경로")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    base_dir = Path(args.base_dir).resolve()
    output_dir = (base_dir / args.output_dir).resolve()

    opinion_pdf = Path(args.opinion_pdf).resolve() if args.opinion_pdf else find_pdf(base_dir, "의견제출")
    spec_pdf = Path(args.spec_pdf).resolve() if args.spec_pdf else find_pdf(base_dir, "배터리케이스", exclude="의견제출")
    cited_pdf_map = {
        1: Path(args.cited1_pdf).resolve() if args.cited1_pdf else None,
        2: Path(args.cited2_pdf).resolve() if args.cited2_pdf else None,
        3: Path(args.cited3_pdf).resolve() if args.cited3_pdf else None,
    }
    result = process_pdfs(opinion_pdf, spec_pdf, output_dir, cited_pdf_map)

    print("생성 완료")
    print(f"- 표시된 PDF: {result['annotated_pdf']}")
    print(f"- HTML 보고서: {result['html_report']}")
    print(f"- JSON 데이터: {result['json_report']}")


if __name__ == "__main__":
    main()
