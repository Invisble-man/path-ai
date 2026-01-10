from __future__ import annotations

from io import BytesIO
from typing import List, Dict, Any

from openpyxl import Workbook
from openpyxl.utils import get_column_letter


def build_matrix_xlsx(compatibility_rows: List[Dict[str, Any]]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Compatibility Matrix"

    ws.append(["RFP Requirement", "Your Response", "Status"])

    for row in compatibility_rows or []:
        ws.append([
            row.get("requirement", "") or "",
            row.get("response", "") or "",
            row.get("status", "") or "",
        ])

    # Basic column sizing
    widths = [55, 55, 14]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w

    out = BytesIO()
    wb.save(out)
    return out.getvalue()