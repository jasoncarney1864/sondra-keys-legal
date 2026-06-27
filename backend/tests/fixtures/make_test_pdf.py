"""Generate a minimal but valid single-page PDF with extractable text.

Used to exercise the document ingestion pipeline (Document Intelligence ->
chunking -> embedding -> search indexing) end to end.
"""

from pathlib import Path

LINES = [
    "MUTUAL NON-DISCLOSURE AGREEMENT",
    "This Agreement is entered into between Sondra Keys and the Counterparty.",
    "1. Confidential Information shall be protected and not disclosed.",
    "2. The term of this Agreement is two (2) years from the Effective Date.",
    "3. Governing law shall be the State of Delaware.",
]


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_pdf() -> bytes:
    # Build the page content stream (text positioned with one line per row).
    content_lines = ["BT", "/F1 14 Tf", "72 720 Td", "16 TL"]
    for i, line in enumerate(LINES):
        if i == 0:
            content_lines.append(f"({_escape(line)}) Tj")
        else:
            content_lines.append(f"T* ({_escape(line)}) Tj")
    content_lines.append("ET")
    content = "\n".join(content_lines).encode("latin-1")

    objects: list[bytes] = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    objects.append(
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
    )
    objects.append(
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream"
    )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    pdf = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"

    xref_pos = len(pdf)
    count = len(objects) + 1
    pdf += f"xref\n0 {count}\n".encode()
    pdf += b"0000000000 65535 f \n"
    for off in offsets:
        pdf += f"{off:010d} 00000 n \n".encode()
    pdf += (
        b"trailer\n<< /Size " + str(count).encode() + b" /Root 1 0 R >>\n"
        b"startxref\n" + str(xref_pos).encode() + b"\n%%EOF"
    )
    return bytes(pdf)


if __name__ == "__main__":
    out = Path(__file__).with_name("sample_nda.pdf")
    out.write_bytes(build_pdf())
    print(f"Wrote {out} ({out.stat().st_size} bytes)")
