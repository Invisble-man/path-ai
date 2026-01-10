import io
from typing import List, Dict, Any

def build_compatibility_matrix_xlsx(rows: List[Dict[str, Any]]) -> bytes:
    """
    rows: list of dicts like:
      {"requirement_id":"REQ-001","requirement":"...","status":"Unknown","notes":""}
    """
    try:
        import openpyxl
        from openpyxl.utils import get_column_letter
        from openpyxl.styles import Font, Alignment
    except Exception:
        raise RuntimeError("openpyxl not installed")

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Compatibility Matrix"

    headers = ["Requirement ID", "Requirement", "Status", "Notes"]
    ws.append(headers)

    # header styling
    for col in range(1, len(headers) + 1):
        c = ws.cell(row=1, column=col)
        c.font = Font(bold=True)
        c.alignment = Alignment(wrap_text=True, vertical="top")

    for r in rows:
        ws.append([
            r.get("requirement_id", ""),
            r.get("requirement", ""),
            r.get("status", ""),
            r.get("notes", ""),
        ])

    # sizing
    widths = [18, 80, 16, 50]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w

    # wrap long cells
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row, min_col=1, max_col=4):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()