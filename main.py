from __future__ import annotations

import base64
import html
import json
import tempfile
import zipfile
from pathlib import Path
from typing import Dict

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse

from app import process_pdfs


app = FastAPI(title="청구항 분석")


def render_home(error_message: str = "") -> str:
    error_block = (
        f'<div class="notice error">{html.escape(error_message)}</div>' if error_message else ""
    )
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>청구항 분석</title>
  <style>
    :root {{
      --bg: #f3f6fb;
      --panel: #ffffff;
      --ink: #19324d;
      --muted: #61758a;
      --line: #d8e2ec;
      --accent: #0c7a6a;
      --accent-deep: #095e52;
      --accent-soft: #e8fbf7;
      --error: #c44b4f;
      --error-bg: #fff0f1;
      --shadow: 0 20px 50px rgba(16, 42, 67, 0.10);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Malgun Gothic", "Apple SD Gothic Neo", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top right, rgba(12, 122, 106, 0.12), transparent 28%),
        linear-gradient(180deg, #eef6ff 0%, var(--bg) 220px);
    }}
    .page {{
      max-width: 1100px;
      margin: 0 auto;
      padding: 36px 20px 48px;
    }}
    .hero {{
      display: grid;
      grid-template-columns: 1.2fr 0.8fr;
      gap: 20px;
      align-items: stretch;
      margin-bottom: 22px;
    }}
    .card {{
      background: var(--panel);
      border: 1px solid rgba(255,255,255,0.9);
      border-radius: 24px;
      box-shadow: var(--shadow);
    }}
    .hero-main {{
      padding: 28px;
    }}
    .eyebrow {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 8px 12px;
      border-radius: 999px;
      background: var(--accent-soft);
      color: var(--accent-deep);
      font-size: 13px;
      font-weight: 700;
      letter-spacing: 0.02em;
    }}
    h1 {{
      margin: 16px 0 14px;
      font-size: 40px;
      line-height: 1.12;
    }}
    .lead {{
      margin: 0;
      color: var(--muted);
      font-size: 16px;
      line-height: 1.7;
    }}
    .hero-side {{
      padding: 24px;
      display: grid;
      gap: 12px;
      background: linear-gradient(180deg, #10324e, #0c5c69);
      color: #f5fbff;
    }}
    .hero-side h2 {{
      margin: 0;
      font-size: 18px;
    }}
    .tip {{
      padding: 14px 16px;
      border-radius: 18px;
      background: rgba(255,255,255,0.08);
      line-height: 1.6;
      font-size: 14px;
    }}
    form {{
      padding: 28px;
    }}
    .form-head {{
      margin-bottom: 18px;
    }}
    .form-head h2 {{
      margin: 0 0 8px;
      font-size: 24px;
    }}
    .form-head p {{
      margin: 0;
      color: var(--muted);
      line-height: 1.6;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 16px;
    }}
    .field {{
      padding: 18px;
      border: 1px solid var(--line);
      border-radius: 18px;
      background: #fbfdff;
    }}
    .field.wide {{
      grid-column: 1 / -1;
    }}
    .field label {{
      display: block;
      margin-bottom: 10px;
      font-size: 14px;
      font-weight: 700;
    }}
    .field small {{
      display: block;
      margin-top: 8px;
      color: var(--muted);
      line-height: 1.5;
    }}
    input[type="file"] {{
      width: 100%;
      padding: 12px;
      border: 1px dashed #a8b8c8;
      border-radius: 14px;
      background: #fff;
    }}
    .actions {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
      margin-top: 22px;
      flex-wrap: wrap;
    }}
    .actions p {{
      margin: 0;
      color: var(--muted);
      font-size: 14px;
    }}
    button {{
      border: 0;
      border-radius: 14px;
      background: var(--accent);
      color: white;
      padding: 14px 22px;
      font-size: 15px;
      font-weight: 700;
      cursor: pointer;
    }}
    button:hover {{
      background: var(--accent-deep);
    }}
    .notice {{
      margin-bottom: 18px;
      padding: 14px 16px;
      border-radius: 16px;
      line-height: 1.6;
    }}
    .notice.error {{
      background: var(--error-bg);
      color: var(--error);
      border: 1px solid rgba(196, 75, 79, 0.18);
    }}
    @media (max-width: 900px) {{
      .hero {{
        grid-template-columns: 1fr;
      }}
      .grid {{
        grid-template-columns: 1fr;
      }}
      h1 {{
        font-size: 32px;
      }}
    }}
  </style>
</head>
<body>
  <div class="page">
    <section class="hero">
      <div class="card hero-main">
        <div class="eyebrow">Web App · Vercel Ready</div>
        <h1>의견제출통지서와 명세서를 바로 업로드해 청구항 분석 결과를 확인하세요.</h1>
        <p class="lead">
          브라우저에서 PDF를 업로드하면 분석 결과 HTML을 바로 보여주고,
          분석 PDF와 JSON, 전체 결과 ZIP도 함께 내려받을 수 있게 구성했습니다.
        </p>
      </div>
      <div class="card hero-side">
        <h2>업로드 안내</h2>
        <div class="tip">필수 파일은 의견제출통지서 PDF와 명세서 PDF입니다.</div>
        <div class="tip">인용발명 PDF는 최대 3개까지 선택할 수 있고, 없어도 분석은 진행됩니다.</div>
        <div class="tip">Vercel 환경에서는 요청 크기 제한이 있으니 너무 큰 PDF는 분리 업로드가 더 안전합니다.</div>
      </div>
    </section>

    {error_block}

    <section class="card">
      <form action="/analyze" method="post" enctype="multipart/form-data">
        <div class="form-head">
          <h2>청구항 분석 실행</h2>
          <p>필요한 PDF를 선택한 뒤 분석을 실행하면 결과 HTML과 다운로드 링크가 같은 페이지에 표시됩니다.</p>
        </div>

        <div class="grid">
          <div class="field">
            <label for="opinion_pdf">의견제출통지서 PDF</label>
            <input id="opinion_pdf" name="opinion_pdf" type="file" accept=".pdf,application/pdf" required>
            <small>거절이유와 청구항 상태를 추출하는 기준 문서입니다.</small>
          </div>

          <div class="field">
            <label for="spec_pdf">명세서 PDF</label>
            <input id="spec_pdf" name="spec_pdf" type="file" accept=".pdf,application/pdf" required>
            <small>청구항 본문과 위치를 읽어 분석 결과를 반영합니다.</small>
          </div>

          <div class="field">
            <label for="cited1_pdf">인용발명 1 PDF</label>
            <input id="cited1_pdf" name="cited1_pdf" type="file" accept=".pdf,application/pdf">
          </div>

          <div class="field">
            <label for="cited2_pdf">인용발명 2 PDF</label>
            <input id="cited2_pdf" name="cited2_pdf" type="file" accept=".pdf,application/pdf">
          </div>

          <div class="field wide">
            <label for="cited3_pdf">인용발명 3 PDF</label>
            <input id="cited3_pdf" name="cited3_pdf" type="file" accept=".pdf,application/pdf">
          </div>
        </div>

        <div class="actions">
          <p>업로드한 파일은 요청 처리에만 사용되고, 결과는 응답 화면에서 바로 내려받을 수 있습니다.</p>
          <button type="submit">청구항 분석 시작</button>
        </div>
      </form>
    </section>
  </div>
</body>
</html>"""


def render_error_page(message: str, status_code: int = 400) -> HTMLResponse:
    return HTMLResponse(render_home(message), status_code=status_code)


def _sanitize_filename(name: str, fallback: str) -> str:
    name = Path(name or fallback).name
    return name or fallback


async def _save_upload(upload: UploadFile | None, target: Path) -> Path | None:
    if upload is None or not upload.filename:
        return None

    filename = _sanitize_filename(upload.filename, target.name)
    destination = target.with_name(filename)
    data = await upload.read()
    if not data:
        return None
    destination.write_bytes(data)
    return destination


def _data_url(payload: bytes, mime_type: str) -> str:
    encoded = base64.b64encode(payload).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _build_zip_bundle(files: Dict[str, Path]) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".zip") as temp_zip:
        with zipfile.ZipFile(temp_zip.name, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for arcname, path in files.items():
                archive.write(path, arcname)
        return Path(temp_zip.name).read_bytes()


def render_result_page(
    report_html: str,
    pdf_name: str,
    pdf_bytes: bytes,
    json_bytes: bytes,
    zip_bytes: bytes,
) -> str:
    iframe_doc = html.escape(report_html, quote=True)
    pdf_link = _data_url(pdf_bytes, "application/pdf")
    json_link = _data_url(json_bytes, "application/json")
    zip_link = _data_url(zip_bytes, "application/zip")

    return f"""<!doctype html>
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
      --accent-deep: #11524c;
      --accent-soft: #e8f6f3;
      --reject: #c2413f;
      --reject-soft: #fff0f0;
      --shadow: 0 18px 42px rgba(31, 42, 55, 0.10);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Malgun Gothic", "Apple SD Gothic Neo", sans-serif;
      color: var(--ink);
      background: var(--bg);
    }}
    .hero {{
      background: linear-gradient(135deg, #17212f 0%, #176c63 100%);
      color: white;
      padding: 28px 20px 82px;
    }}
    .hero-inner, .page {{
      max-width: 1320px;
      margin: 0 auto;
    }}
    .topbar {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: center;
      flex-wrap: wrap;
      margin-bottom: 26px;
    }}
    .brand {{
      font-size: 18px;
      font-weight: 800;
    }}
    h1 {{
      margin: 0;
      font-size: 38px;
      line-height: 1.16;
    }}
    .muted {{
      color: rgba(255,255,255,0.82);
      margin-top: 10px;
      line-height: 1.7;
      max-width: 720px;
    }}
    .button-row {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
    }}
    .button, .button-secondary {{
      text-decoration: none;
      border-radius: 14px;
      padding: 12px 16px;
      font-weight: 700;
      font-size: 14px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
    }}
    .button {{
      background: white;
      color: var(--accent-deep);
    }}
    .button:hover {{
      background: #f1f5f9;
    }}
    .button-secondary {{
      background: rgba(255,255,255,0.12);
      color: white;
      border: 1px solid rgba(255,255,255,0.28);
    }}
    .page {{
      padding: 0 16px 40px;
      margin-top: -54px;
    }}
    .summary-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 14px;
      margin-bottom: 16px;
    }}
    .summary-card {{
      background: var(--panel);
      border: 1px solid rgba(255,255,255,0.85);
      border-radius: 8px;
      box-shadow: var(--shadow);
      padding: 18px;
    }}
    .summary-card span {{
      display: block;
      color: var(--muted);
      font-size: 13px;
      font-weight: 800;
      margin-bottom: 8px;
    }}
    .summary-card strong {{
      display: block;
      font-size: 20px;
      line-height: 1.35;
      word-break: keep-all;
    }}
    .summary-card.accent {{
      background: var(--reject-soft);
      border-color: rgba(194,65,63,0.14);
    }}
    .summary-card.accent strong {{
      color: var(--reject);
    }}
    .grid {{
      display: grid;
      grid-template-columns: 300px 1fr;
      gap: 16px;
    }}
    .panel {{
      background: var(--panel);
      border: 1px solid rgba(255,255,255,0.9);
      border-radius: 8px;
      box-shadow: var(--shadow);
    }}
    .sidebar {{
      padding: 20px;
      display: grid;
      gap: 16px;
      align-content: start;
    }}
    .sidebar h2, .sidebar h3 {{
      margin: 0 0 10px;
      font-size: 18px;
    }}
    .sidebar p {{
      margin: 0;
      line-height: 1.7;
      color: var(--muted);
    }}
    .viewer {{
      padding: 10px;
    }}
    iframe {{
      width: 100%;
      min-height: 82vh;
      border: 0;
      border-radius: 6px;
      background: white;
    }}
    .side-link {{
      display: flex;
      text-decoration: none;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 11px 12px;
      color: var(--accent-deep);
      background: var(--accent-soft);
      font-weight: 800;
      justify-content: center;
    }}
    @media (max-width: 960px) {{
      .grid, .summary-grid {{
        grid-template-columns: 1fr;
      }}
      h1 {{
        font-size: 30px;
      }}
      iframe {{
        min-height: 70vh;
      }}
    }}
  </style>
</head>
<body>
  <section class="hero">
    <div class="hero-inner">
      <div class="topbar">
        <div class="brand">거절이유 청구항 분석</div>
        <div class="button-row">
          <a class="button" href="{zip_link}" download="claim-analysis-results.zip">결과 ZIP 다운로드</a>
          <a class="button-secondary" href="{pdf_link}" download="{html.escape(pdf_name)}">분석 PDF 다운로드</a>
          <a class="button-secondary" href="{json_link}" download="claim_mapping.json">JSON 다운로드</a>
          <a class="button-secondary" href="/">새 분석 실행</a>
        </div>
      </div>
      <h1>거절이유 청구항 분석 결과</h1>
      <div class="muted">분석 결과를 대시보드 형태로 확인하고, 필요한 산출물을 바로 내려받을 수 있습니다.</div>
    </div>
  </section>

  <div class="page">
    <section class="summary-grid">
      <div class="summary-card accent">
        <span>분석 상태</span>
        <strong>결과 생성 완료</strong>
      </div>
      <div class="summary-card">
        <span>분석 PDF</span>
        <strong>{html.escape(pdf_name)}</strong>
      </div>
      <div class="summary-card">
        <span>산출물</span>
        <strong>PDF · HTML · JSON · ZIP</strong>
      </div>
    </section>

    <div class="grid">
      <aside class="panel sidebar">
        <section>
          <h2>다운로드</h2>
          <p>분석 PDF, JSON, 전체 ZIP을 바로 받을 수 있습니다.</p>
        </section>
        <a class="side-link" href="{pdf_link}" download="{html.escape(pdf_name)}">분석 PDF</a>
        <a class="side-link" href="{json_link}" download="claim_mapping.json">JSON</a>
        <a class="side-link" href="{zip_link}" download="claim-analysis-results.zip">전체 ZIP</a>
      </aside>

      <section class="panel viewer">
        <iframe title="거절이유 청구항 분석" srcdoc="{iframe_doc}"></iframe>
      </section>
    </div>
  </div>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
async def home() -> HTMLResponse:
    return HTMLResponse(render_home())


@app.post("/analyze", response_class=HTMLResponse)
async def analyze(
    opinion_pdf: UploadFile = File(...),
    spec_pdf: UploadFile = File(...),
    cited1_pdf: UploadFile | None = File(default=None),
    cited2_pdf: UploadFile | None = File(default=None),
    cited3_pdf: UploadFile | None = File(default=None),
) -> HTMLResponse:
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            output_dir = base_dir / "output"
            output_dir.mkdir(parents=True, exist_ok=True)

            opinion_path = await _save_upload(opinion_pdf, base_dir / "opinion.pdf")
            spec_path = await _save_upload(spec_pdf, base_dir / "spec.pdf")

            if opinion_path is None or spec_path is None:
                return render_error_page("의견제출통지서 PDF와 명세서 PDF는 모두 필요합니다.")

            cited_pdf_map = {
                1: await _save_upload(cited1_pdf, base_dir / "cited1.pdf"),
                2: await _save_upload(cited2_pdf, base_dir / "cited2.pdf"),
                3: await _save_upload(cited3_pdf, base_dir / "cited3.pdf"),
            }
            cited_pdf_map = {key: value for key, value in cited_pdf_map.items() if value is not None}

            result = process_pdfs(opinion_path, spec_path, output_dir, cited_pdf_map)

            report_html = result["html_report"].read_text(encoding="utf-8")
            pdf_bytes = result["annotated_pdf"].read_bytes()
            json_bytes = result["json_report"].read_bytes()
            zip_bytes = _build_zip_bundle(
                {
                    result["annotated_pdf"].name: result["annotated_pdf"],
                    result["html_report"].name: result["html_report"],
                    result["json_report"].name: result["json_report"],
                }
            )

            page = render_result_page(
                report_html=report_html,
                pdf_name=result["annotated_pdf"].name,
                pdf_bytes=pdf_bytes,
                json_bytes=json_bytes,
                zip_bytes=zip_bytes,
            )
            return HTMLResponse(page)
    except HTTPException:
        raise
    except Exception as exc:
        return render_error_page(str(exc), status_code=500)
