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
        self.root.title("청구항 분석 프로그램")
        self.root.geometry("860x720")
        self.root.minsize(760, 560)

        self.opinion_path = tk.StringVar()
        self.spec_path = tk.StringVar()
        self.cited1_path = tk.StringVar()
        self.cited2_path = tk.StringVar()
        self.cited3_path = tk.StringVar()
        self.status_text = tk.StringVar(value="파일을 선택한 뒤 실행하세요.")

        self._load_defaults()
        self._build_ui()

    def _load_defaults(self) -> None:
        for path in BASE_DIR.iterdir():
            if path.suffix.lower() != ".pdf":
                continue
            compact_name = path.stem.replace(" ", "")
            if "의견제출" in path.name and not self.opinion_path.get():
                self.opinion_path.set(str(path))
            elif "의견제출" not in path.name and "인용발명" not in compact_name and not self.spec_path.get():
                self.spec_path.set(str(path))
            elif "인용발명1" in compact_name and not self.cited1_path.get():
                self.cited1_path.set(str(path))
            elif "인용발명2" in compact_name and not self.cited2_path.get():
                self.cited2_path.set(str(path))
            elif "인용발명3" in compact_name and not self.cited3_path.get():
                self.cited3_path.set(str(path))

    def _build_ui(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Root.TFrame", background="#eef6e8")
        style.configure("Card.TFrame", background="#fbfff8")
        style.configure("Title.TLabel", background="#eef6e8", foreground="#243b22", font=("Malgun Gothic", 18, "bold"))
        style.configure("Body.TLabel", background="#fbfff8", foreground="#45604a", font=("Malgun Gothic", 9))
        style.configure("Path.TEntry", fieldbackground="#ffffff", padding=7)

        outer = ttk.Frame(self.root, padding=16, style="Root.TFrame")
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text="청구항 분석 프로그램", style="Title.TLabel").pack(anchor="w")

        top_note = ttk.Frame(outer, padding=(14, 10), style="Card.TFrame")
        top_note.pack(fill="x", pady=(10, 12))
        ttk.Label(
            top_note,
            text="의견제출서와 명세서, 필요한 인용발명 PDF를 넣으면 PDF/HTML/JSON을 생성합니다.",
            style="Body.TLabel",
            wraplength=760,
            justify="left",
        ).pack(anchor="w")

        container = ttk.Frame(outer, style="Root.TFrame")
        container.pack(fill="both", expand=True)

        canvas = tk.Canvas(container, background="#eef6e8", highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        self.form_frame = ttk.Frame(canvas, style="Root.TFrame")

        self.form_frame.bind(
            "<Configure>",
            lambda event: canvas.configure(scrollregion=canvas.bbox("all")),
        )

        canvas.create_window((0, 0), window=self.form_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        canvas.bind_all("<MouseWheel>", lambda event: canvas.yview_scroll(int(-event.delta / 120), "units"))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(1, width=event.width))

        self._build_picker(self.form_frame, "의견제출 PDF", self.opinion_path, self.select_opinion_pdf)
        self._build_picker(self.form_frame, "명세서 PDF", self.spec_path, self.select_spec_pdf)
        self._build_picker(self.form_frame, "인용발명 1 PDF", self.cited1_path, self.select_cited1_pdf)
        self._build_picker(self.form_frame, "인용발명 2 PDF", self.cited2_path, self.select_cited2_pdf)
        self._build_picker(self.form_frame, "인용발명 3 PDF", self.cited3_path, self.select_cited3_pdf)

        button_row = ttk.Frame(self.form_frame, style="Root.TFrame")
        button_row.pack(fill="x", pady=(6, 12))

        tk.Button(
            button_row,
            text="실행",
            command=self.run,
            font=("Malgun Gothic", 11, "bold"),
            bg="#77b86c",
            fg="white",
            activebackground="#5f9f57",
            activeforeground="white",
            relief="flat",
            padx=22,
            pady=9,
            cursor="hand2",
        ).pack(side="left")

        tk.Button(
            button_row,
            text="결과 폴더 열기",
            command=self.open_output_folder,
            font=("Malgun Gothic", 10),
            bg="#dff1d9",
            fg="#35523a",
            activebackground="#cfe8c8",
            activeforeground="#35523a",
            relief="flat",
            padx=18,
            pady=9,
            cursor="hand2",
        ).pack(side="left", padx=10)

        tk.Button(
            button_row,
            text="종료",
            command=self.root.destroy,
            font=("Malgun Gothic", 10),
            bg="#dff1d9",
            fg="#35523a",
            activebackground="#cfe8c8",
            activeforeground="#35523a",
            relief="flat",
            padx=18,
            pady=9,
            cursor="hand2",
        ).pack(side="right")

        info = ttk.Frame(self.form_frame, padding=14, style="Card.TFrame")
        info.pack(fill="x", pady=(0, 10))
        ttk.Label(info, textvariable=self.status_text, style="Body.TLabel", wraplength=760, justify="left").pack(anchor="w")

    def _build_picker(self, parent: ttk.Frame, title: str, variable: tk.StringVar, command) -> None:
        panel = ttk.Frame(parent, padding=14, style="Card.TFrame")
        panel.pack(fill="x", pady=(0, 10))

        ttk.Label(panel, text=title, style="Body.TLabel").pack(anchor="w")
        row = ttk.Frame(panel, style="Card.TFrame")
        row.pack(fill="x", pady=(8, 0))
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
            self.status_text.set("파일을 분석하고 결과를 만드는 중입니다...")
            self.root.update_idletasks()
            result = process_pdfs(opinion, spec, BASE_DIR / "output", cited_pdf_map)
        except Exception as exc:
            self.status_text.set("실행 중 오류가 발생했습니다.")
            messagebox.showerror("실행 실패", str(exc))
            return

        uploaded_cited = [str(number) for number, path in cited_pdf_map.items() if path]
        self.status_text.set(
            "완료되었습니다.\n"
            f"분석 PDF: {result['annotated_pdf'].name}\n"
            f"HTML 보고서: {result['html_report'].name}\n"
            f"업로드한 인용발명: {', '.join(uploaded_cited) if uploaded_cited else '없음'}"
        )
        messagebox.showinfo("완료", "결과 파일 생성이 완료되었습니다.")
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
    root.configure(bg="#eef6e8")
    root.mainloop()


if __name__ == "__main__":
    main()
