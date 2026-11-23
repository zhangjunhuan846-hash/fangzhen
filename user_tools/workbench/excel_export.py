"""Export the workbench schema and records in a Linux application runtime."""

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.worksheet.table import Table, TableStyleInfo

from user_tools.rg_workstation import column


def export_workbook(schema, workspace, destination):
    workbook = Workbook()
    workbook.remove(workbook.active)
    for index, spec in enumerate(schema["tables"]):
        sheet = workbook.create_sheet(spec["sheet"])
        rows = workspace["tables"][spec["sheet"]]
        last_row = max(104, len(rows) + 4)
        sheet.sheet_view.showGridLines = False
        sheet.cell(1, 1, spec["sheet"]).font = Font(name="Microsoft YaHei", size=16, bold=True)
        sheet.cell(2, 1, spec.get("note", ""))
        sheet.freeze_panes = "B5"
        for position, (key, label, kind) in enumerate(spec["fields"], start=1):
            letter = column(position)
            sheet.column_dimensions[letter].width = 20
            header = sheet.cell(4, position, label)
            header.font = Font(name="Microsoft YaHei", size=11, bold=True, color="FFFFFF")
            header.fill = PatternFill("solid", fgColor="243C58")
            header.alignment = Alignment(wrap_text=True)
            for number in range(5, last_row + 1):
                cell = sheet.cell(number, position)
                cell.font = Font(name="Microsoft YaHei", size=11, color="243547")
                if number - 5 < len(rows):
                    cell.value = rows[number - 5].get(key)
                if kind == "fraction" or kind == "derived":
                    cell.number_format = "0.0%"
                elif kind in ("number", "positive", "temperature", "signed"):
                    cell.number_format = "0.00"
                else:
                    cell.number_format = "@"
                    if isinstance(cell.value, str):
                        cell.data_type = "s"
                if key == "ds_m2_s" or key.endswith("diffusivity_m2_s") or key == "i0_A_m2":
                    cell.number_format = "0.00E+00"
                if key == "d002_nm":
                    cell.number_format = "0.0000"
                if kind == "derived":
                    cell.fill = PatternFill("solid", fgColor="EDF2F7")
                    cell.value = (
                        f'=IF(AND(ISNUMBER(D{number}),ISNUMBER(E{number}),D{number}>0),'
                        f'E{number}/D{number},"")'
                    )
        for number in range(1, last_row + 1):
            sheet.row_dimensions[number].height = 26
        sheet.row_dimensions[4].height = 48
        table = Table(displayName=f"Export_{index}", ref=f"A4:{column(len(spec['fields']))}{last_row}")
        table.tableStyleInfo = TableStyleInfo(name="TableStyleLight1", showRowStripes=True)
        sheet.add_table(table)
    workbook.save(destination)
