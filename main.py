from __future__ import annotations

import base64
import json
import tempfile
import zipfile
from pathlib import Path
from typing import Dict

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse

from app import process_pdfs


app = FastAPI(
    title="Claim Analysis API",
    description="의견제출통지서와 명세서를 분석해 청구항 결과물을 생성하는 백엔드 API입니다.",
    version="1.0.0",
)


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


@app.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    return RedirectResponse(url="/docs", status_code=307)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/analyze")
async def analyze(
    opinion_pdf: UploadFile = File(...),
    spec_pdf: UploadFile = File(...),
    cited1_pdf: UploadFile | None = File(default=None),
    cited2_pdf: UploadFile | None = File(default=None),
    cited3_pdf: UploadFile | None = File(default=None),
) -> JSONResponse:
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            output_dir = base_dir / "output"
            output_dir.mkdir(parents=True, exist_ok=True)

            opinion_path = await _save_upload(opinion_pdf, base_dir / "opinion.pdf")
            spec_path = await _save_upload(spec_pdf, base_dir / "spec.pdf")

            if opinion_path is None or spec_path is None:
                return JSONResponse(
                    status_code=400,
                    content={"detail": "의견제출통지서 PDF와 명세서 PDF는 모두 필요합니다."},
                )

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
            claim_mapping = json.loads(json_bytes.decode("utf-8"))

            payload = {
                "message": "analysis completed",
                "inputs": {
                    "opinion_pdf": opinion_path.name,
                    "spec_pdf": spec_path.name,
                    "cited_pdfs": {str(key): path.name for key, path in cited_pdf_map.items()},
                },
                "summary": {
                    "total_claims": len(claim_mapping),
                    "rejected_claims": [item["claim_no"] for item in claim_mapping if item["status"] == "거절이유"],
                    "allowed_claims": [item["claim_no"] for item in claim_mapping if item["status"] == "특허 가능"],
                },
                "artifacts": {
                    "html_report": {
                        "filename": result["html_report"].name,
                        "content_type": "text/html; charset=utf-8",
                        "data_url": _data_url(report_html.encode("utf-8"), "text/html"),
                    },
                    "annotated_pdf": {
                        "filename": result["annotated_pdf"].name,
                        "content_type": "application/pdf",
                        "data_url": _data_url(pdf_bytes, "application/pdf"),
                    },
                    "claim_mapping_json": {
                        "filename": result["json_report"].name,
                        "content_type": "application/json",
                        "data_url": _data_url(json_bytes, "application/json"),
                    },
                    "results_zip": {
                        "filename": "claim-analysis-results.zip",
                        "content_type": "application/zip",
                        "data_url": _data_url(zip_bytes, "application/zip"),
                    },
                },
                "claim_mapping": claim_mapping,
            }
            return JSONResponse(content=payload)
    except HTTPException:
        raise
    except Exception as exc:
        return JSONResponse(status_code=500, content={"detail": str(exc)})
