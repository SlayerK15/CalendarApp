from datetime import date, datetime, time
from io import BytesIO
from zipfile import BadZipFile, ZipFile

from openpyxl import load_workbook

MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
MAX_CELLS = 250_000


def read_excel(content: bytes, sheet_name: str = ""):
    """Read a single XLSX tab in memory; never save or modify the source file."""
    if len(content) > MAX_DOWNLOAD_BYTES:
        raise ValueError("The Excel timetable is too large to read safely (25 MB limit).")
    try:
        with ZipFile(BytesIO(content)) as archive:
            entries = archive.infolist()
            if len(entries) > 5000 or sum(item.file_size for item in entries) > MAX_UNCOMPRESSED_BYTES:
                raise ValueError("The Excel timetable expands beyond the supported workbook size.")
        workbook = load_workbook(BytesIO(content), read_only=True, data_only=True, keep_links=False)
    except (BadZipFile, KeyError, OSError) as exc:
        raise ValueError("The timetable could not be read as an Excel .xlsx workbook.") from exc
    try:
        if sheet_name:
            if sheet_name not in workbook.sheetnames:
                raise ValueError("The configured Excel worksheet was not found: " + sheet_name)
            sheet = workbook[sheet_name]
        elif len(workbook.worksheets) == 1:
            sheet = workbook.worksheets[0]
        else:
            raise ValueError(
                "This Excel workbook has multiple worksheets. Set EXCEL_SHEET_NAME to the timetable tab: "
                + ", ".join(workbook.sheetnames[:20])
            )
        if sheet.max_row and sheet.max_column and sheet.max_row * sheet.max_column > MAX_CELLS:
            raise ValueError("The Excel worksheet exceeds the supported size.")
        rows = []
        cells_read = 0
        for cells in sheet.iter_rows(values_only=True):
            cells_read += len(cells)
            if cells_read > MAX_CELLS:
                raise ValueError("The Excel worksheet exceeds the supported size.")
            row = []
            for value in cells:
                if isinstance(value, (datetime, date)):
                    value = value.strftime("%Y-%m-%d")
                elif isinstance(value, time):
                    value = value.strftime("%H:%M")
                row.append("" if value is None else str(value).strip())
            while row and not row[-1]:
                row.pop()
            rows.append(row)
        while rows and not rows[-1]:
            rows.pop()
        return rows
    finally:
        workbook.close()
