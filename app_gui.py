from __future__ import annotations

import os
import subprocess
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from app import process_pdfs


BASE_DIR = Path(__file__).resolve().parent


class ClaimMarkerApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("동희산업 청구항 표시 프로그램")
        self.root.geometry("860x760")
        self.root.minsize(820, 700)

        self.opinion_path = tk.StringVar()
        self.spec_path = tk.StringVar()
        self.cited1_path = tk.StringVar()
        self.cited2_path = tk.StringVar()
        self.cited3_path = tk.StringVar()
        self.status_text = tk.StringVar(
            value="의견제출 PDF, 명세서 PDF, 필요하면 인용발명 1~3 PDF도 올린 뒤 실행하세요."
        )

        self._load_defaults()
        self._build_ui()

    def _load_defaults(self) -> None:
        for path in BASE_DIR.iterdir():
            if path.suffix.lower() != ".pdf":
                continue
            if "의견제출" in path.name and not self.opinion_path.get():
                self.opinion_path.set(str(path))
            elif "배터리케이스" in path.name and "의견제출" not in path.name and not self.spec_path.get():
                self.spec_path.set(str(path))
            elif "인용발명1" in path.stem.replace(" ", "") and not self.cited1_path.get():
                self.cited1_path.set(str(path))
            elif "인용발명2" in path.stem.replace(" ", "") and not self.cited2_path.get():
                self.cited2_path.set(str(path))
            elif "인용발명3" in path.stem.replace(" ", "") and not self.cited3_path.get():
                self.cited3_path.set(str(path))

    def _build_ui(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Root.TFrame", background="#eff9eb")
        style.configure("Panel.TFrame", background="#fbfff8")
        style.configure("Title.TLabel", background="#eff9eb", foreground="#244028", font=("Malgun Gothic", 19, "bold"))
        style.configure("Body.TLabel", background="#fbfff8", foreground="#45604a", font=("Malgun Gothic", 10))
        style.configure("Path.TEntry", fieldbackground="#ffffff", padding=8)

        root_frame = ttk.Frame(self.root, padding=20, style="Root.TFrame")
        root_frame.pack(fill="both", expand=True)

        ttk.Label(root_frame, text="동희산업 청구항 표시 프로그램", style="Title.TLabel").pack(anchor="w")

        hero = ttk.Frame(root_frame, padding=18, style="Panel.TFrame")
        hero.pack(fill="x", pady=(14, 16))
        ttk.Label(
            hero,
            text="의견제출통지서의 거절이유를 명세서 PDF 청구항에 표시하고, 인용발명 PDF를 추가로 열어 관련 문단과 차이 키워드를 HTML에 함께 정리합니다.",
            style="Body.TLabel",
            wraplength=760,
            justify="left",
        ).pack(anchor="w")

        self._build_picker(root_frame, "의견제출 PDF", self.opinion_path, self.select_opinion_pdf)
        self._build_picker(root_frame, "명세서 PDF", self.spec_path, self.select_spec_pdf)
        self._build_picker(root_frame, "인용발명 1 PDF", self.cited1_path, self.select_cited1_pdf)
        self._build_picker(root_frame, "인용발명 2 PDF", self.cited2_path, self.select_cited2_pdf)
        self._build_picker(root_frame, "인용발명 3 PDF", self.cited3_path, self.select_cited3_pdf)

        button_row = ttk.Frame(root_frame, style="Root.TFrame")
        button_row.pack(fill="x", pady=(4, 14))

        run_button = tk.Button(
            button_row,
            text="실행",
            command=self.run,
            font=("Malgun Gothic", 11, "bold"),
            bg="#77b86c",
            fg="white",
            activebackground="#5f9f57",
            activeforeground="white",
            relief="flat",
            padx=24,
            pady=10,
            cursor="hand2",
        )
        run_button.pack(side="left")

        open_button = tk.Button(
            button_row,
            text="결과 폴더 열기",
            command=self.open_output_folder,
            font=("Malgun Gothic", 10),
            bg="#dff1d9",
            fg="#35523a",
            activebackground="#cfe8c8",
            activeforeground="#35523a",
            relief="flat",
            padx=20,
            pady=10,
            cursor="hand2",
        )
        open_button.pack(side="left", padx=10)

        done_button = tk.Button(
            button_row,
            text="종료",
            command=self.root.destroy,
            font=("Malgun Gothic", 10),
            bg="#dff1d9",
            fg="#35523a",
            activebackground="#cfe8c8",
            activeforeground="#35523a",
            relief="flat",
            padx=20,
            pady=10,
            cursor="hand2",
        )
        done_button.pack(side="right")

        info = ttk.Frame(root_frame, padding=18, style="Panel.TFrame")
        info.pack(fill="x", pady=(0, 8))
        ttk.Label(info, textvariable=self.status_text, style="Body.TLabel", wraplength=760, justify="left").pack(anchor="w")

    def _build_picker(self, parent: ttk.Frame, title: str, variable: tk.StringVar, command) -> None:
        panel = ttk.Frame(parent, padding=18, style="Panel.TFrame")
        panel.pack(fill="x", pady=(0, 14))

        ttk.Label(panel, text=title, style="Body.TLabel").pack(anchor="w")

        row = ttk.Frame(panel, style="Panel.TFrame")
        row.pack(fill="x", pady=(10, 0))
        ttk.Entry(row, textvariable=variable, style="Path.TEntry").pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="파일 선택", command=command).pack(side="left", padx=(10, 0))

    def _select_pdf(self, title: str) -> str:
        return filedialog.askopenfilename(
            title=title,
            initialdir=str(BASE_DIR),
            filetypes=[("PDF files", "*.pdf")],
        )

    def select_opinion_pdf(self) -> None:
        path = self._select_pdf("의견제출 PDF 선택")
        if path:
            self.opinion_path.set(path)

    def select_spec_pdf(self) -> None:
        path = self._select_pdf("명세서 PDF 선택")
        if path:
            self.spec_path.set(path)

    def select_cited1_pdf(self) -> None:
        path = self._select_pdf("인용발명 1 PDF 선택")
        if path:
            self.cited1_path.set(path)

    def select_cited2_pdf(self) -> None:
        path = self._select_pdf("인용발명 2 PDF 선택")
        if path:
            self.cited2_path.set(path)

    def select_cited3_pdf(self) -> None:
        path = self._select_pdf("인용발명 3 PDF 선택")
        if path:
            self.cited3_path.set(path)

    def run(self) -> None:
        opinion = Path(self.opinion_path.get().strip()) if self.opinion_path.get().strip() else None
        spec = Path(self.spec_path.get().strip()) if self.spec_path.get().strip() else None

        if not opinion or not opinion.exists():
            messagebox.showerror("오류", "의견제출 PDF를 선택해 주세요.")
            return
        if not spec or not spec.exists():
            messagebox.showerror("오류", "명세서 PDF를 선택해 주세요.")
            return

        cited_pdf_map = {
            1: Path(self.cited1_path.get().strip()) if self.cited1_path.get().strip() else None,
            2: Path(self.cited2_path.get().strip()) if self.cited2_path.get().strip() else None,
            3: Path(self.cited3_path.get().strip()) if self.cited3_path.get().strip() else None,
        }
        for number, path in cited_pdf_map.items():
            if path and not path.exists():
                messagebox.showerror("오류", f"인용발명 {number} PDF 경로를 다시 확인해 주세요.")
                return

        try:
            self.status_text.set("인용발명 PDF까지 포함해 비교 중입니다. 잠시만 기다려 주세요...")
            self.root.update_idletasks()
            result = process_pdfs(opinion, spec, BASE_DIR / "output", cited_pdf_map)
        except Exception as exc:
            self.status_text.set("실행 중 오류가 발생했습니다.")
            messagebox.showerror("실행 실패", str(exc))
            return

        uploaded_cited = [str(number) for number, path in cited_pdf_map.items() if path]
        self.status_text.set(
            "완료되었습니다.\n"
            f"표시된 PDF: {result['annotated_pdf'].name}\n"
            f"HTML 보고서: {result['html_report'].name}\n"
            f"업로드한 인용발명: {', '.join(uploaded_cited) if uploaded_cited else '없음'}"
        )
        messagebox.showinfo(
            "완료",
            "결과 파일 생성이 완료되었습니다.\noutput 폴더를 바로 열어 드립니다.",
        )
        self.open_output_folder()

    def open_output_folder(self) -> None:
        output_dir = BASE_DIR / "output"
        output_dir.mkdir(exist_ok=True)
        try:
            subprocess.Popen(["explorer", str(output_dir)])
        except Exception:
            try:
                os.startfile(str(output_dir))
            except Exception as exc:
                messagebox.showerror("오류", f"결과 폴더를 열지 못했습니다.\n{exc}")


def main() -> None:
    root = tk.Tk()
    ClaimMarkerApp(root)
    root.configure(bg="#eff9eb")
    root.mainloop()


if __name__ == "__main__":
    main()
