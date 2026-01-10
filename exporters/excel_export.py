import io
from typing import List, Dict, Any

def build_compatibility_matrix_xlsx(rows: List[Dict[str, Any]]) -> bytes:
    """
    rows: list of dicts like:
      {"requirement_id": "...", "requirement": "...", "status": "Pass/Fail/Unknown", "notes": "..."}
    """
    try:
        import openpyxl
        from openpyxl.utils import get_column_letter
    except Exception as e:
        raise RuntimeError("openpyxl not installed. Add it to requirements.txt") from e

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Compatibility Matrix"

    headers = ["Requirement ID", "Requirement", "Status", "Notes"]
    ws.append(headers)

    for r in rows:
        ws.append([
            r.get("requirement_id", ""),
            r.get("requirement", ""),
            r.get("status", ""),
            r.get("notes", ""),
        ])

    # basic sizing
    for col in range(1, len(headers) + 1):
        ws.column_dimensions[get_column_letter(col)].width = 28

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
