"""Generate a minimal, dependency-free placeholder PDF (text only).
Used only to seed sample-001 so the site can be exercised end-to-end
before real problem PDFs are dropped in.
"""
import sys


def build_pdf(text_lines):
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        "/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]

    y = 720
    content_lines = []
    for line in text_lines:
        esc = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        content_lines.append(f"BT /F1 14 Tf 72 {y} Td ({esc}) Tj ET")
        y -= 24
    content = "\n".join(content_lines)
    stream_bytes = content.encode("latin-1")
    objects.append(f"<< /Length {len(stream_bytes)} >>\nstream\n{content}\nendstream")

    header = "%PDF-1.4\n"
    body = ""
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(header) + len(body))
        body += f"{i} 0 obj\n{obj}\nendobj\n"

    xref_offset = len(header) + len(body)
    xref = f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n"
    for off in offsets:
        xref += f"{off:010d} 00000 n \n"
    trailer = (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF"
    )
    return (header + body + xref + trailer).encode("latin-1")


if __name__ == "__main__":
    out_path = sys.argv[1]
    lines = sys.argv[2:]
    with open(out_path, "wb") as f:
        f.write(build_pdf(lines))
    print(f"wrote {out_path}")
