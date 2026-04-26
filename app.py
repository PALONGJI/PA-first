
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


LAW_TEXT = "특허법 제29조 제2항"
REJECTED_COLOR = (0.82, 0.2, 0.2)
REJECTED_FILL = (1.0, 0.93, 0.93)
ALLOWED_COLOR = (0.14, 0.45, 0.23)
ALLOWED_FILL = (0.92, 0.98, 0.92)
NEUTRAL_COLOR = (0.2, 0.2, 0.2)
NEUTRAL_FILL = (0.95, 0.95, 0.95)
KOREAN_FONT_CANDIDATES = [
    Path(__file__).resolve().parent / "fonts" / "NotoSansKR-VF.ttf",
    Path(r"C:\Windows\Fonts\malgun.ttf"),
    Path(r"C:\Windows\Fonts\malgunbd.ttf"),
]
CLAIM_HEADING_PATTERN = re.compile(
    r"(?m)^[ \t　]*(?:【\s*청구항\s*(\d+)\s*】|\[\s*청구항\s*(\d+)\s*\]|청구항\s*(\d+))[ \t　]*$"
)


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


def find_spec_pdf(base_dir: Path, opinion_pdf: Path | None = None) -> Path:
    matches: List[Path] = []
    opinion_resolved = opinion_pdf.resolve() if opinion_pdf else None
    for path in base_dir.iterdir():
        if path.suffix.lower() != ".pdf":
            continue
        if opinion_resolved and path.resolve() == opinion_resolved:
            continue
        if "인용발명" in path.stem.replace(" ", ""):
            continue
        matches.append(path)

    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise FileNotFoundError("분석할 명세서 PDF를 찾지 못했습니다.")
    raise RuntimeError(f"분석할 명세서 PDF가 여러 개입니다: {[p.name for p in matches]}")


def make_unique_output_path(path: Path) -> Path:
    if not path.exists():
        return path

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    candidate = path.with_stem(f"{path.stem}_{timestamp}")
    counter = 1
    while candidate.exists():
        candidate = path.with_stem(f"{path.stem}_{timestamp}_{counter}")
        counter += 1
    return candidate


def read_pdf_text(pdf_path: Path) -> List[str]:
    doc = fitz.open(pdf_path)
    return [doc.load_page(index).get_text("text") for index in range(doc.page_count)]


def expand_claim_range(raw_text: str) -> List[int]:
    values = [int(value) for value in re.findall(r"\d+", raw_text)]
    if any(sep in raw_text for sep in ("내지", "-", "~")) and len(values) >= 2:
        return list(range(values[0], values[1] + 1))
    return values


def parse_claim_list(raw_text: str) -> List[int]:
    claims: List[int] = []
    normalized = re.sub(r"\s+", "", raw_text)
    normalized = normalized.replace("청구항", "")
    normalized = normalized.replace("제", "")
    normalized = normalized.replace("항", "")
    normalized = normalized.replace("내지", "-")
    normalized = normalized.replace("부터", "-")
    normalized = normalized.replace("~", "-")
    normalized = normalized.replace("및", ",")
    normalized = normalized.replace("또는", ",")
    normalized = normalized.replace("또", ",")
    for part in re.split(r"[,ㆍ·]", normalized):
        if not part:
            continue
        claims.extend(expand_claim_range(part))
    return sorted(set(claims))


def parse_claim_text(raw_text: str, all_claim_numbers: Iterable[int] | None = None) -> List[int]:
    if not raw_text:
        return []

    known_claims = sorted(set(all_claim_numbers or []))
    compact = re.sub(r"\s+", "", raw_text)
    if "전체항" in compact or "전항" in compact:
        return known_claims

    matches = re.findall(
        r"청구항(.+?)(?=청구항관련법조항|구체적인거절이유|특허가능청구항|특허가능한청구항|$)",
        compact,
    )
    if matches:
        claims: List[int] = []
        for match in matches:
            claims.extend(parse_claim_list(match))
        return sorted(set(claims))

    return parse_claim_list(compact)


def extract_status_lists(
    opinion_pages: List[str],
    all_claim_numbers: Iterable[int] | None = None,
) -> tuple[List[int], List[int]]:
    combined = "\n".join(opinion_pages[:3])
    compact = re.sub(r"\s+", "", combined)
    known_claims = sorted(set(all_claim_numbers or []))

    rejected_text = ""
    for pattern in (
        r"\[심사결과\].*?거절이유가있는(?:청구항|부분)[:：]?(.+?)(?:특허법제\d+조제\d+항|구체적인거절이유|특허가능청구항|특허가능한청구항|$)",
        r"거절이유가있는(?:청구항|부분)[:：]?(.+?)(?:특허법제\d+조제\d+항|구체적인거절이유|특허가능청구항|특허가능한청구항|$)",
    ):
        rejected_match = re.search(pattern, compact)
        if rejected_match:
            rejected_text = rejected_match.group(1)
            break

    allowed_text = ""
    allowed_match = re.search(
        r"특허가능(?:한)?청구항[:：]?(.*?)(?:※|\[구체적인거절이유\]|구체적인거절이유|$)",
        compact,
    )
    if allowed_match:
        allowed_text = allowed_match.group(1)

    rejected_claims = parse_claim_text(rejected_text, known_claims)
    allowed_claims = parse_claim_text(allowed_text, known_claims)

    if not rejected_claims and allowed_claims and known_claims:
        rejected_claims = sorted(set(known_claims) - set(allowed_claims))
    if not allowed_claims and rejected_claims and known_claims:
        allowed_claims = sorted(set(known_claims) - set(rejected_claims))

    if not rejected_claims and not allowed_claims:
        raise RuntimeError("의견제출통지서에서 청구항 상태를 판별하지 못했습니다.")

    return rejected_claims, allowed_claims


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
        "있어서",
        "것을",
        "특징으로",
        "배터리",
        "케이스",
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


def is_boilerplate_passage(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    boilerplate_markers = (
        "CPC특허분류",
        "출원번호",
        "출원일자",
        "심사청구일자",
        "출원인",
        "발명자",
        "대리인",
        "전체청구항수",
        "발명의명칭",
        "요약",
    )
    marker_count = sum(1 for marker in boilerplate_markers if marker in compact)
    if marker_count >= 2:
        return True
    if "Cl.)" in text and re.search(r"\(\d{2}\)\s*(출원번호|출원일자|출원인|발명자)", text):
        return True
    return False


def find_best_passage(claim_text: str, pdf_pages: List[str]) -> tuple[str, int, List[str], List[str]]:
    claim_keywords = extract_keywords(claim_text)[:12]
    best_passage = ""
    best_page = 0
    best_overlap: List[str] = []
    best_score = 0

    for page_no, page_text in enumerate(pdf_pages, start=1):
        for passage in split_text_passages(page_text):
            if is_boilerplate_passage(passage):
                continue
            passage_keywords = set(extract_keywords(passage))
            overlap = [keyword for keyword in claim_keywords if keyword in passage_keywords]
            score = len(overlap)
            if score > best_score or (score == best_score and len(passage) > len(best_passage)):
                best_score = score
                best_passage = passage
                best_page = page_no
                best_overlap = overlap

    if best_score < 2:
        missing = claim_keywords[:6]
        return "", 0, [], missing

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


def extract_claim_reasons(
    opinion_pages: List[str],
    all_claim_numbers: Iterable[int] | None = None,
) -> Dict[int, ClaimReason]:
    body = "\n".join(opinion_pages[1:])
    body = body.split("<< 안내 >>", 1)[0]
    raw_lines = body.splitlines()
    lines: List[str] = []
    for line in raw_lines:
        stripped = line.strip()
        if not stripped:
            continue
        if re.fullmatch(r"10-\d{4}-\d+", stripped):
            continue
        if re.fullmatch(r"\d+/\d+", stripped):
            continue
        if re.match(r"첨부\d", stripped):
            continue
        if stripped in {"[첨부]", "[첨부서류]", "[첨 부]"}:
            break
        lines.append(stripped)

    results: Dict[int, ClaimReason] = {}
    current_block: List[str] = []
    current_claims: List[int] = []

    def flush_block(block_lines: List[str], claim_numbers: List[int]) -> None:
        if not block_lines or not claim_numbers:
            return
        heading_line = re.sub(r"^1-\d+\.\s*", "", block_lines[0]).strip()
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
        if line.startswith("[보정에 관한 참고사항]") or line.startswith("[보정 관련 참고사항]"):
            flush_block(current_block, current_claims)
            break
        if re.match(r"^1-\d+\.\s*청구항", line):
            flush_block(current_block, current_claims)
            current_block = [line]
            current_claims = parse_claim_text(line, all_claim_numbers)
            continue
        if re.match(r"^제?\s*\d+\s*항\s*발명[은에]", line):
            flush_block(current_block, current_claims)
            current_block = [line]
            current_claims = parse_claim_text(line, all_claim_numbers)
            continue
        if current_block:
            current_block.append(line)

    flush_block(current_block, current_claims)

    if results:
        return results

    generic_lines: List[str] = []
    capture = False
    for line in lines:
        if "구체적인 거절이유" in line:
            capture = True
            continue
        if capture:
            generic_lines.append(line)

    generic_text = clean_text_block("\n".join(generic_lines or lines))
    fallback_claims = sorted(set(all_claim_numbers or []))
    if generic_text and fallback_claims:
        summary, cited_inventions = summarize_reason(generic_text, fallback_claims)
        reason = ClaimReason(
            claims=fallback_claims,
            heading="구체적인 거절이유",
            summary=summary,
            full_text=generic_text,
            cited_inventions=cited_inventions,
        )
        for claim_number in fallback_claims:
            results[claim_number] = reason

    return results


def extract_claim_texts(spec_pdf: Path) -> Dict[int, ClaimEntry]:
    doc = fitz.open(spec_pdf)
    records: Dict[int, ClaimEntry] = {}

    for page_index in range(doc.page_count):
        text = doc.load_page(page_index).get_text("text")
        matches = list(CLAIM_HEADING_PATTERN.finditer(text))
        for idx, match in enumerate(matches):
            claim_no = int(next(group for group in match.groups() if group))
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

    if not records:
        raise RuntimeError(f"{spec_pdf.name}에서 청구항을 찾지 못했습니다.")
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
    for candidate in (
        f"【청구항 {claim_no}】",
        f"청구항 {claim_no}",
        f"청구항{claim_no}",
        f"제{claim_no}항",
    ):
        matches = page.search_for(candidate)
        if matches:
            return matches[0]
    return None


def build_note_rect(page: fitz.Page, heading_rect: fitz.Rect) -> fitz.Rect:
    page_rect = page.rect
    box_width = 128
    box_height = 30
    margin = 8

    right_x0 = min(max(heading_rect.x1 + 6, page_rect.x0 + margin), page_rect.x1 - box_width - margin)
    heading_center_y = (heading_rect.y0 + heading_rect.y1) / 2
    right_y0 = min(
        max(heading_center_y - (box_height / 2), page_rect.y0 + margin),
        page_rect.y1 - box_height - margin,
    )
    right_rect = fitz.Rect(right_x0, right_y0, right_x0 + box_width, right_y0 + box_height)

    if right_rect.x0 >= heading_rect.x1 + 4:
        return right_rect

    above_y0 = heading_rect.y0 - box_height - 6
    if above_y0 >= page_rect.y0 + margin:
        x0 = min(max(heading_rect.x0, page_rect.x0 + margin), page_rect.x1 - box_width - margin)
        return fitz.Rect(x0, above_y0, x0 + box_width, above_y0 + box_height)

    below_y0 = min(heading_rect.y1 + 6, page_rect.y1 - box_height - margin)
    x0 = min(max(heading_rect.x0, page_rect.x0 + margin), page_rect.x1 - box_width - margin)
    return fitz.Rect(x0, below_y0, x0 + box_width, below_y0 + box_height)


def annotate_spec_pdf(
    source_pdf: Path,
    output_pdf: Path,
    claim_entries: Dict[int, ClaimEntry],
) -> Path:
    doc = fitz.open(source_pdf)
    save_path = make_unique_output_path(output_pdf)
    font_path = next((path for path in KOREAN_FONT_CANDIDATES if path.exists()), None)
    use_ascii_note = font_path is None

    for entry in claim_entries.values():
        page = doc.load_page(entry.page_number - 1)
        rect = find_heading_rect(page, entry.claim_no)
        if rect is None:
            continue

        if entry.status == "거절이유":
            border, fill = REJECTED_COLOR, REJECTED_FILL
        elif entry.status == "특허 가능":
            border, fill = ALLOWED_COLOR, ALLOWED_FILL
        else:
            border, fill = NEUTRAL_COLOR, NEUTRAL_FILL

        highlight = fitz.Rect(rect.x0 - 4, rect.y0 - 3, rect.x1 + 4, rect.y1 + 3)
        note_rect = build_note_rect(page, rect)

        page.draw_rect(highlight, color=border, width=1.0)
        page.draw_rect(note_rect, color=border, fill=fill, width=0.8)

        short_reason = re.sub(r"\s+", " ", entry.short_reason).strip()
        if len(short_reason) > 22:
            short_reason = short_reason[:22].rstrip() + "..."

        display_status = entry.status
        display_reason = short_reason
        if use_ascii_note:
            status_map = {
                "거절이유": "Rejected",
                "특허 가능": "Allowed",
                "미분류": "Pending",
            }
            display_status = status_map.get(entry.status, "Pending")
            display_reason = ""

        note_lines = [f"Claim {entry.claim_no}: {display_status}" if use_ascii_note else f"청구항 {entry.claim_no}: {display_status}"]
        if display_reason:
            note_lines.append(display_reason)

        if font_path is not None:
            page.insert_font(fontname="kfont", fontfile=str(font_path))
            font_name = "kfont"
        else:
            font_name = "helv"

        page.insert_textbox(
            note_rect + (4, 3, -4, -3),
            "\n".join(note_lines),
            fontsize=5.3,
            fontname=font_name,
            color=border,
            align=0,
        )

    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    try:
        doc.save(save_path)
        return save_path
    except fitz.FileDataError:
        raise
    except Exception as exc:
        if "Permission denied" not in str(exc):
            raise
        fallback = make_unique_output_path(output_pdf)
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
        (number, Path(os.path.relpath(path, output_dir)).as_posix())
        for number, path in sorted(cited_pdf_map.items())
    ]

    total_claims = len(claim_entries)
    rejected_count = len(rejected_claims)
    allowed_count = len(allowed_claims)
    pending_count = max(0, total_claims - rejected_count - allowed_count)
    rejected_ratio = round((rejected_count / total_claims) * 100) if total_claims else 0
    allowed_ratio = round((allowed_count / total_claims) * 100) if total_claims else 0
    pending_ratio = max(0, 100 - rejected_ratio - allowed_ratio)

    def status_class(status: str) -> str:
        if status == "거절이유":
            return "is-rejected"
        if status == "특허 가능":
            return "is-allowed"
        return "is-pending"

    table_rows: List[str] = []
    claim_blocks: List[str] = []
    for claim_no in sorted(claim_entries):
        entry = claim_entries[claim_no]
        badge_class = status_class(entry.status)
        cited_text = ", ".join(str(value) for value in entry.cited_inventions) or "-"

        table_rows.append(
            f"""
            <tr class="{badge_class}">
              <td><a href="#claim-{entry.claim_no}">청구항 {entry.claim_no}</a></td>
              <td><span class="status-badge {badge_class}">{html.escape(entry.status)}</span></td>
              <td>{entry.page_number}</td>
              <td>{html.escape(cited_text)}</td>
              <td>{html.escape(entry.short_reason or "-")}</td>
            </tr>
            """
        )

        cited_panels: List[str] = []
        for detail in entry.cited_details:
            overlap = ", ".join(str(value) for value in detail["overlap_keywords"]) or "-"
            missing = ", ".join(str(value) for value in detail["missing_keywords"]) or "-"
            uploaded_text = "업로드됨" if detail["uploaded"] else "미업로드"
            matched_passage = html.escape(str(detail["matched_passage"]) or "관련 본문을 찾지 못했습니다.")
            cited_panels.append(
                f"""
                <section class="detail-panel cited-panel">
                  <div class="detail-head">
                    <h4>인용발명 {detail["invention_no"]}</h4>
                    <span>{uploaded_text} · 페이지 {detail["page_number"] or "-"}</span>
                  </div>
                  <p>{html.escape(str(detail["difference_summary"]))}</p>
                  <dl class="meta-grid">
                    <div><dt>겹치는 키워드</dt><dd>{html.escape(overlap)}</dd></div>
                    <div><dt>추가 확인 필요</dt><dd>{html.escape(missing)}</dd></div>
                  </dl>
                  <pre>{matched_passage}</pre>
                </section>
                """
            )

        claim_blocks.append(
            f"""
            <article class="claim-card {badge_class}" id="claim-{entry.claim_no}">
              <div class="claim-card-head">
                <div>
                  <span class="eyebrow {badge_class}">청구항 {entry.claim_no}</span>
                  <h3>{html.escape(entry.short_reason or entry.status)}</h3>
                </div>
                <span class="status-badge {badge_class}">{html.escape(entry.status)}</span>
              </div>
              <div class="claim-meta">
                <span>페이지 {entry.page_number}</span>
                <span>인용발명 {html.escape(cited_text)}</span>
                <span>{html.escape(LAW_TEXT)}</span>
              </div>
              <details {'open' if entry.status == '거절이유' else ''}>
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
                  {"".join(cited_panels)}
                </div>
              </details>
            </article>
            """
        )

    table_groups: List[str] = []
    for index in range(0, len(table_rows), 10):
        group_rows = table_rows[index:index + 10]
        group_start = index + 1
        group_end = min(index + len(group_rows), len(table_rows))
        table_groups.append(
            f"""
            <section class="table-block">
              <h3>청구항 {group_start}-{group_end}</h3>
              <div class="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>청구항</th>
                      <th>상태</th>
                      <th>페이지</th>
                      <th>인용발명</th>
                      <th>요약</th>
                    </tr>
                  </thead>
                  <tbody>
                    {"".join(group_rows)}
                  </tbody>
                </table>
              </div>
            </section>
            """
        )

    cited_link_blocks = "".join(
        f'<a href="{html.escape(href)}">인용발명 {number}</a>'
        for number, href in cited_links
    )

    html_text = f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>거절이유 청구항 분석</title>
  <style>
    :root {{
      --bg: #f3f6fa;
      --panel: #ffffff;
      --ink: #1f2a37;
      --muted: #697586;
      --line: #dde5ee;
      --accent: #176c63;
      --accent-soft: #e8f6f3;
      --reject: #a71919;
      --reject-soft: #ffdede;
      --reject-row: #fff1f1;
      --allow: #08733d;
      --allow-soft: #d9f7e5;
      --allow-row: #effbf4;
      --pending: #7a5a13;
      --pending-soft: #fff7df;
      --shadow: 0 18px 42px rgba(31, 42, 55, 0.10);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: "Malgun Gothic", "Apple SD Gothic Neo", Arial, sans-serif;
    }}
    a {{ color: inherit; }}
    .shell {{
      min-height: 100vh;
    }}
    .hero {{
      background: linear-gradient(135deg, #17212f 0%, #176c63 100%);
      color: white;
      padding: 30px 24px 86px;
    }}
    .hero-inner, .content {{
      max-width: 1240px;
      margin: 0 auto;
    }}
    .topline {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 16px;
      margin-bottom: 30px;
      flex-wrap: wrap;
    }}
    .brand {{
      font-size: 18px;
      font-weight: 800;
    }}
    .quick-links {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }}
    .quick-links a {{
      text-decoration: none;
      border: 1px solid rgba(255,255,255,0.28);
      background: rgba(255,255,255,0.12);
      border-radius: 8px;
      padding: 9px 12px;
      font-size: 13px;
      font-weight: 400;
    }}
    h1 {{
      margin: 0 0 12px;
      font-size: 40px;
      line-height: 1.16;
      letter-spacing: 0;
    }}
    .hero p {{
      margin: 0;
      max-width: 760px;
      line-height: 1.7;
      color: rgba(255,255,255,0.82);
    }}
    .hero-tools {{
      display: grid;
      gap: 12px;
      justify-items: end;
      min-width: 340px;
      max-width: 520px;
    }}
    .distribution-card {{
      width: 100%;
      background: rgba(255,255,255,0.12);
      border: 1px solid rgba(255,255,255,0.24);
      border-radius: 8px;
      padding: 14px;
      color: white;
    }}
    .distribution-card h2 {{
      margin: 0 0 10px;
      font-size: 16px;
    }}
    .content {{
      margin-top: -56px;
      padding: 0 24px 44px;
    }}
    .stats {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 14px;
      margin-bottom: 18px;
    }}
    .stat-card, .panel, .claim-card {{
      background: var(--panel);
      border: 1px solid rgba(255,255,255,0.85);
      border-radius: 8px;
      box-shadow: var(--shadow);
    }}
    .stat-card {{
      padding: 18px;
    }}
    .stat-card span {{
      display: block;
      color: var(--muted);
      font-size: 13px;
      font-weight: 700;
      margin-bottom: 10px;
    }}
    .stat-card strong {{
      display: block;
      font-size: 30px;
      line-height: 1;
    }}
    .dashboard-grid {{
      display: block;
    }}
    .panel {{
      padding: 20px;
    }}
    .panel-head {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      margin: 0 0 6px;
    }}
    .panel h2 {{
      margin: 0;
      font-size: 20px;
    }}
    .status-badge {{
      display: inline-flex;
      width: fit-content;
      align-items: center;
      border-radius: 999px;
      padding: 5px 10px;
      font-size: 12px;
      font-weight: 800;
      white-space: nowrap;
    }}
    .is-rejected {{ color: var(--reject); background: var(--reject-soft); }}
    .is-allowed {{ color: var(--allow); background: var(--allow-soft); }}
    .is-pending {{ color: var(--pending); background: var(--pending-soft); }}
    tr.is-rejected {{
      background: var(--reject-row);
      border-left: 4px solid var(--reject);
    }}
    tr.is-allowed {{
      background: var(--allow-row);
      border-left: 4px solid var(--allow);
    }}
    tr.is-rejected td:first-child,
    tr.is-rejected td:first-child a {{
      color: var(--reject);
    }}
    tr.is-allowed td:first-child,
    tr.is-allowed td:first-child a {{
      color: var(--allow);
    }}
    tr.is-rejected .status-badge,
    tr.is-allowed .status-badge {{
      color: white;
    }}
    tr.is-rejected .status-badge {{
      background: var(--reject);
    }}
    tr.is-allowed .status-badge {{
      background: var(--allow);
    }}
    .chart {{
      display: grid;
      gap: 12px;
      margin-top: 8px;
    }}
    .bar {{
      height: 14px;
      border-radius: 999px;
      overflow: hidden;
      background: #edf1f5;
      display: grid;
      grid-template-columns: {rejected_ratio}fr {allowed_ratio}fr {pending_ratio}fr;
    }}
    .bar span:nth-child(1) {{ background: var(--reject); }}
    .bar span:nth-child(2) {{ background: var(--allow); }}
    .bar span:nth-child(3) {{ background: #d6a536; }}
    .legend {{
      display: grid;
      gap: 7px;
      color: rgba(255,255,255,0.78);
      font-size: 13px;
    }}
    .legend-row {{
      display: flex;
      justify-content: space-between;
      gap: 10px;
    }}
    .table-wrap {{
      overflow-x: auto;
      margin-top: 14px;
    }}
    .table-split-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
      margin-top: 14px;
    }}
    .table-block {{
      min-width: 0;
    }}
    .table-block h3 {{
      margin: 0 0 10px;
      font-size: 16px;
      color: var(--muted);
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      min-width: 640px;
      font-size: 14px;
    }}
    th, td {{
      padding: 12px 10px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
    }}
    th {{
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
    }}
    td a {{
      color: var(--accent);
      font-weight: 700;
      text-decoration: none;
    }}
    .claim-list {{
      display: grid;
      gap: 14px;
      margin-top: 18px;
    }}
    .claim-card {{
      padding: 18px;
      scroll-margin-top: 18px;
      border-left: 5px solid transparent;
    }}
    .claim-card.is-rejected {{
      border-left-color: var(--reject);
    }}
    .claim-card.is-allowed {{
      border-left-color: var(--allow);
    }}
    .claim-card.is-pending {{
      border-left-color: var(--pending);
    }}
    .claim-card-head {{
      display: flex;
      justify-content: space-between;
      gap: 14px;
      align-items: flex-start;
      margin-bottom: 12px;
    }}
    .eyebrow {{
      display: inline-flex;
      color: var(--accent);
      background: var(--accent-soft);
      border-radius: 999px;
      padding: 5px 9px;
      font-size: 12px;
      font-weight: 800;
      margin-bottom: 9px;
    }}
    .eyebrow.is-rejected {{
      color: white;
      background: var(--reject);
    }}
    .eyebrow.is-allowed {{
      color: white;
      background: var(--allow);
    }}
    .eyebrow.is-pending {{
      color: white;
      background: var(--pending);
    }}
    .claim-card h3 {{
      margin: 0;
      font-size: 17px;
      line-height: 1.45;
    }}
    .claim-meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-bottom: 12px;
    }}
    .claim-meta span {{
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 6px 9px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
    }}
    details {{
      border-top: 1px solid var(--line);
      padding-top: 12px;
    }}
    summary {{
      cursor: pointer;
      color: var(--accent);
      font-weight: 800;
      list-style: none;
    }}
    summary::-webkit-details-marker {{
      display: none;
    }}
    .detail-grid {{
      display: grid;
      gap: 12px;
      margin-top: 12px;
    }}
    .detail-panel {{
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      background: #fbfdff;
      color: var(--ink);
    }}
    .detail-panel h4 {{
      margin: 0 0 10px;
      font-size: 14px;
      color: var(--ink);
    }}
    .detail-panel p {{
      margin: 0 0 10px;
      color: var(--muted);
      line-height: 1.6;
      font-size: 14px;
    }}
    .detail-head {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: baseline;
      margin-bottom: 8px;
    }}
    .detail-head span {{
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
    }}
    .meta-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
      margin: 10px 0;
    }}
    .meta-grid div {{
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px;
      background: white;
    }}
    .meta-grid dt {{
      color: var(--muted);
      font-size: 12px;
      font-weight: 800;
      margin-bottom: 4px;
    }}
    .meta-grid dd {{
      margin: 0;
      font-size: 13px;
      line-height: 1.5;
    }}
    pre {{
      margin: 0;
      padding: 12px;
      white-space: pre-wrap;
      word-break: keep-all;
      color: var(--ink);
      background: white;
      border: 1px solid #edf1f5;
      border-radius: 8px;
      font-family: Consolas, monospace;
      font-size: 12px;
      line-height: 1.6;
    }}
    @media (max-width: 960px) {{
      .stats, .table-split-grid {{ grid-template-columns: 1fr; }}
      h1 {{ font-size: 32px; }}
      .content {{ padding: 0 16px 34px; }}
      .hero {{ padding-left: 16px; padding-right: 16px; }}
      .meta-grid {{ grid-template-columns: 1fr; }}
      .hero-tools {{
        width: 100%;
        min-width: 0;
        max-width: none;
        justify-items: stretch;
      }}
      .quick-links {{
        justify-content: flex-start;
      }}
    }}
  </style>
</head>
<body>
  <div class="shell">
    <section class="hero">
      <div class="hero-inner">
        <div class="topline">
          <div class="brand">거절이유 청구항 분석</div>
          <div class="hero-tools">
            <nav class="quick-links">
              <a href="{html.escape(annotated_href)}">분석 PDF</a>
              <a href="{html.escape(spec_href)}">명세서</a>
              <a href="{html.escape(opinion_href)}">의견제출통지서</a>
              {cited_link_blocks}
            </nav>
            <aside class="distribution-card">
              <h2>상태 분포</h2>
              <div class="chart">
                <div class="bar" aria-label="청구항 상태 분포">
                  <span></span><span></span><span></span>
                </div>
                <div class="legend">
                  <div class="legend-row"><span>거절이유</span><strong>{rejected_count}건 · {rejected_ratio}%</strong></div>
                  <div class="legend-row"><span>특허 가능</span><strong>{allowed_count}건 · {allowed_ratio}%</strong></div>
                  <div class="legend-row"><span>미분류</span><strong>{pending_count}건 · {pending_ratio}%</strong></div>
                </div>
              </div>
            </aside>
          </div>
        </div>
        <h1>거절이유 청구항 분석</h1>
        <p>의견제출통지서의 청구항 상태와 거절이유를 기준으로, 청구항별 쟁점과 인용발명 대응 내용을 한 화면에서 검토할 수 있도록 정리했습니다.</p>
      </div>
    </section>

    <main class="content">
      <section class="stats" aria-label="분석 요약">
        <div class="stat-card"><span>전체 청구항</span><strong>{total_claims}</strong></div>
        <div class="stat-card"><span>거절이유</span><strong>{rejected_count}</strong></div>
        <div class="stat-card"><span>특허 가능</span><strong>{allowed_count}</strong></div>
        <div class="stat-card"><span>인용발명 PDF</span><strong>{len(cited_links)}</strong></div>
      </section>

      <section class="dashboard-grid">
        <section class="panel">
          <div class="panel-head">
            <h2>청구항 상태표</h2>
            <span class="status-badge is-rejected">거절이유 {rejected_count}건</span>
          </div>
          <div class="table-split-grid">
            {"".join(table_groups)}
          </div>
        </section>
      </section>

      <section class="claim-list" aria-label="청구항 상세">
        {"".join(claim_blocks)}
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

    claim_entries = extract_claim_texts(spec_pdf)
    opinion_pages = read_pdf_text(opinion_pdf)
    all_claim_numbers = sorted(claim_entries)
    rejected_claims, allowed_claims = extract_status_lists(opinion_pages, all_claim_numbers)
    reasons_by_claim = extract_claim_reasons(opinion_pages, all_claim_numbers)
    decorate_claims(claim_entries, rejected_claims, allowed_claims, reasons_by_claim)
    cited_pdf_map = enrich_with_cited_inventions(claim_entries, cited_pdf_map)

    annotated_pdf = output_dir / "청구항_분석_결과.pdf"
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
        description="의견제출통지서의 거절이유를 명세서 PDF 청구항에 분석 결과로 반영합니다."
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
    spec_pdf = Path(args.spec_pdf).resolve() if args.spec_pdf else find_spec_pdf(base_dir, opinion_pdf)
    result = process_pdfs(opinion_pdf, spec_pdf, output_dir)

    print("생성 완료")
    print(f"- 분석 PDF: {result['annotated_pdf']}")
    print(f"- HTML 보고서: {result['html_report']}")
    print(f"- JSON 데이터: {result['json_report']}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="의견제출통지서의 거절이유를 명세서 PDF 청구항에 분석 결과로 반영합니다."
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
    spec_pdf = Path(args.spec_pdf).resolve() if args.spec_pdf else find_spec_pdf(base_dir, opinion_pdf)
    cited_pdf_map = {
        1: Path(args.cited1_pdf).resolve() if args.cited1_pdf else None,
        2: Path(args.cited2_pdf).resolve() if args.cited2_pdf else None,
        3: Path(args.cited3_pdf).resolve() if args.cited3_pdf else None,
    }
    result = process_pdfs(opinion_pdf, spec_pdf, output_dir, cited_pdf_map)

    print("생성 완료")
    print(f"- 분석 PDF: {result['annotated_pdf']}")
    print(f"- HTML 보고서: {result['html_report']}")
    print(f"- JSON 데이터: {result['json_report']}")


if __name__ == "__main__":
    main()
