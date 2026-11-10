"""
Export service: PDF, Excel, CSV, and ICS generation in the selected local timezone.
"""
from __future__ import annotations

import csv
import io
import os
from datetime import date, timedelta
from typing import Optional

from calculations.birthday_dates import OBSERVANCE_LABELS
from services.panchang_service import FullResult
from services.timezone_service import localize_datetime


def _fmt_local(dt_utc, tz_str: str) -> str:
    local_dt = localize_datetime(dt_utc, tz_str)
    if local_dt is None:
        return ""
    return local_dt.strftime("%Y-%m-%d %H:%M %Z")


def _safe_cell(val: str) -> str:
    """Neutralize Excel/CSV formula injection on user-supplied strings."""
    if isinstance(val, str) and val and val[0] in ("=", "+", "-", "@"):
        return "'" + val
    return val


# ---------------------------------------------------------------------------
# CSV Export
# ---------------------------------------------------------------------------

def export_csv(result: FullResult) -> bytes:
    """Generate CSV bytes for all candidate birthday calendars."""
    output = io.StringIO()
    writer = csv.writer(output)
    p = result.panchang
    tz_str = p.timezone_str

    writer.writerow([
        "Candidate", "Lunar Month", "Year", "Hindu Birthday (Gregorian)", "Weekday",
        "Tithi", f"Tithi Start ({tz_str})", f"Tithi End ({tz_str})",
        "Status", "Alternate Dates", "Notes",
    ])

    calendars = result.candidate_calendars or []
    if not calendars and result.birthday_entries:
        for entry in result.birthday_entries:
            writer.writerow([
                "Option 1",
                entry.lunar_month_en,
                entry.year,
                entry.gregorian_date.isoformat() if entry.gregorian_date else "N/A",
                entry.weekday or "",
                entry.tithi_name_en,
                _fmt_local(entry.tithi_start_utc, tz_str),
                _fmt_local(entry.tithi_end_utc, tz_str),
                entry.status,
                "; ".join(d.isoformat() for d in entry.alternate_dates),
                _safe_cell(entry.notes),
            ])
    else:
        for idx, cal in enumerate(calendars, 1):
            label = f"Option {idx}: {cal.lunar_month.month_name_en} {cal.tithi.paksha_en} {cal.tithi.name_en}"
            for entry in cal.entries:
                writer.writerow([
                    label,
                    entry.lunar_month_en or cal.lunar_month.month_name_en,
                    entry.year,
                    entry.gregorian_date.isoformat() if entry.gregorian_date else "N/A",
                    entry.weekday or "",
                    entry.tithi_name_en,
                    _fmt_local(entry.tithi_start_utc, tz_str),
                    _fmt_local(entry.tithi_end_utc, tz_str),
                    entry.status,
                    "; ".join(d.isoformat() for d in entry.alternate_dates),
                    _safe_cell(entry.notes),
                ])

    return output.getvalue().encode("utf-8-sig")


# ---------------------------------------------------------------------------
# Excel Export
# ---------------------------------------------------------------------------

def export_excel(result: FullResult) -> bytes:
    """Generate Excel workbook with a sheet per candidate Tithi calendar."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    # Remove default sheet after creating candidate sheets
    default_ws = wb.active
    p = result.panchang
    tz_str = p.timezone_str
    today = result.today

    calendars = result.candidate_calendars
    if not calendars:
        # Fallback single list
        sheet_specs = [("Hindu Birthdays", p.tithis[0] if p.tithis else None, result.birthday_entries)]
    else:
        sheet_specs = []
        for idx, cal in enumerate(calendars, 1):
            title = f"Opt{idx}_{cal.tithi.paksha_en}_{cal.tithi.name_en}"[:31]
            sheet_specs.append((title, cal.tithi, cal.entries))

    header_fill = PatternFill(fill_type="solid", fgColor="1B2A4A")
    header_font = Font(bold=True, color="FFFFFF")

    for sheet_title, tithi_obj, entries in sheet_specs:
        ws = wb.create_sheet(title=sheet_title)
        ws.merge_cells("A1:I1")
        ws["A1"] = "Hindu Tithi Birthday Calendar"
        ws["A1"].font = Font(bold=True, size=14, color="FF8C00")
        ws["A1"].alignment = Alignment(horizontal="center")

        tithi_desc = f"{tithi_obj.paksha_en} {tithi_obj.name_en}" if tithi_obj else "Unknown"
        obs_label = OBSERVANCE_LABELS.get(p.observance_method, p.observance_method)
        ws["A2"] = _safe_cell(
            f"DOB: {p.birth_date} | Location: {p.location_name} | "
            f"Tithi: {tithi_desc} | System: {p.lunar_system.title()} | Observance: {obs_label}"
        )
        ws["A2"].font = Font(italic=True, size=10)
        ws.merge_cells("A2:I2")

        headers = [
            "Year", "Hindu Birthday", "Weekday", "Lunar Month", "Tithi",
            f"Tithi Start ({tz_str})", f"Tithi End ({tz_str})", "Status", "Notes",
        ]
        for col, h in enumerate(headers, 1):
            cell = ws.cell(row=4, column=col, value=h)
            cell.fill = header_fill
            cell.font = header_font

        for row_num, entry in enumerate(entries, 5):
            ws.cell(row=row_num, column=1, value=entry.year)
            ws.cell(row=row_num, column=2, value=entry.gregorian_date.isoformat() if entry.gregorian_date else "N/A")
            ws.cell(row=row_num, column=3, value=entry.weekday or "")
            ws.cell(row=row_num, column=4, value=entry.lunar_month_en)
            ws.cell(row=row_num, column=5, value=entry.tithi_name_en)
            ws.cell(row=row_num, column=6, value=_fmt_local(entry.tithi_start_utc, tz_str))
            ws.cell(row=row_num, column=7, value=_fmt_local(entry.tithi_end_utc, tz_str))
            ws.cell(row=row_num, column=8, value=entry.status)
            note_val = entry.notes
            if entry.alternate_dates:
                note_val = (note_val + " " if note_val else "") + "Alternates: " + ", ".join(
                    d.isoformat() for d in entry.alternate_dates
                )
            ws.cell(row=row_num, column=9, value=_safe_cell(note_val))

            if entry.gregorian_date == today:
                for col in range(1, 10):
                    ws.cell(row=row_num, column=col).fill = PatternFill(
                        fill_type="solid", fgColor="FFF3CD"
                    )

        widths = [8, 16, 12, 14, 14, 22, 22, 14, 42]
        for col, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(col)].width = w

    wb.remove(default_ws)
    output = io.BytesIO()
    wb.save(output)
    return output.getvalue()


# ---------------------------------------------------------------------------
# PDF Export
# ---------------------------------------------------------------------------

def _register_pdf_fonts() -> tuple[str, str, bool]:
    """
    Register Unicode TTF fonts when available so Devanagari / Latin symbols
    render cleanly without black boxes. Returns (regular_font, bold_font, supports_devanagari).
    """
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    # Candidate pairs: (regular_path, bold_path, supports_devanagari)
    candidates = [
        (r"C:\Windows\Fonts\mangal.ttf", r"C:\Windows\Fonts\mangalb.ttf", True),
        ("/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf",
         "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf", True),
        (r"C:\Windows\Fonts\NotoSans-Regular.ttf", r"C:\Windows\Fonts\NotoSans-Bold.ttf", False),
        (r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\arialbd.ttf", False),
    ]
    for reg_path, bold_path, devanagari in candidates:
        if os.path.exists(reg_path):
            try:
                if "CustomReg" not in pdfmetrics.getRegisteredFontNames():
                    pdfmetrics.registerFont(TTFont("CustomReg", reg_path))
                bold_name = "CustomReg"
                if os.path.exists(bold_path):
                    if "CustomBold" not in pdfmetrics.getRegisteredFontNames():
                        pdfmetrics.registerFont(TTFont("CustomBold", bold_path))
                    bold_name = "CustomBold"
                return "CustomReg", bold_name, devanagari
            except Exception:
                continue
    return "Helvetica", "Helvetica-Bold", False


def export_pdf(result: FullResult) -> bytes:
    """Generate PDF report using ReportLab with full methodology and warnings."""
    from xml.sax.saxutils import escape
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        HRFlowable,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    reg_font, bold_font, has_devanagari = _register_pdf_fonts()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
        leftMargin=1.8 * cm,
        rightMargin=1.8 * cm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "TitleCustom",
        parent=styles["Title"],
        fontName=bold_font,
        fontSize=19,
        textColor=colors.HexColor("#FF8C00"),
        alignment=TA_CENTER,
    )
    h2_style = ParagraphStyle(
        "H2Custom",
        parent=styles["Heading2"],
        fontName=bold_font,
        textColor=colors.HexColor("#1B2A4A"),
    )
    body_style = ParagraphStyle(
        "BodyCustom",
        parent=styles["Normal"],
        fontName=reg_font,
        fontSize=9.5,
        leading=13,
    )

    story = []
    p = result.panchang
    tz_str = p.timezone_str
    obs_label = OBSERVANCE_LABELS.get(p.observance_method, p.observance_method)

    # Note: omit emoji glyphs (like Om) that standard PDF fonts cannot render
    story.append(Paragraph("Hindu Tithi Birthday Report", title_style))
    story.append(Spacer(1, 0.25 * cm))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#FF8C00")))
    story.append(Spacer(1, 0.35 * cm))

    # Birth Info
    story.append(Paragraph("Birth Information & Methodology", h2_style))
    birth_time_disp = (
        p.birth_time_local.strftime("%H:%M %Z")
        if p.birth_time_local
        else (
            f"{p.birth_time_start_local.strftime('%H:%M')} - {p.birth_time_end_local.strftime('%H:%M %Z')}"
            if p.birth_time_start_local and p.birth_time_end_local
            else "Unknown (Full Local Day Analyzed)"
        )
    )
    birth_info = [
        ["Date of Birth:", p.birth_date.strftime("%d %B %Y")],
        ["Birth Time:", birth_time_disp],
        ["Birthplace:", p.location_name],
        ["Coordinates:", f"Lat {p.lat:.4f} deg, Lon {p.lon:.4f} deg"],
        ["Timezone:", p.timezone_str],
        ["Ayanamsha:", p.ayanamsha_name],
        ["Lunar Month System:", p.lunar_system.title()],
        ["Observance Rule:", f"{obs_label} (Adhika rule: {p.adhika_rule.title()})"],
        ["Sunrise:", p.sunrise_local.strftime("%H:%M %Z") if p.sunrise_local else "N/A"],
        ["Sunset:", p.sunset_local.strftime("%H:%M %Z") if p.sunset_local else "N/A"],
    ]
    t = Table(birth_info, colWidths=[4.8 * cm, 12.6 * cm])
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), bold_font),
        ("FONTNAME", (1, 0), (1, -1), reg_font),
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t)
    story.append(Spacer(1, 0.35 * cm))

    # Ambiguity / Uncertainty Warning
    if p.ambiguity_message:
        story.append(Paragraph("Uncertainty & Confidence Notice", h2_style))
        story.append(Paragraph(escape(f"[Confidence: {p.confidence}] {p.ambiguity_message}"), body_style))
        story.append(Spacer(1, 0.35 * cm))

    # Panchang Details
    story.append(Paragraph("Birth Panchang", h2_style))
    for idx, tithi in enumerate(p.tithis, 1):
        tithi_label = f"{tithi.paksha_en} {tithi.name_en}"
        if has_devanagari:
            tithi_label += f" ({tithi.name_hi})"
        panchang_rows = [
            [f"Tithi{' (Option ' + str(idx) + ')' if len(p.tithis) > 1 else ''}:", tithi_label],
            [f"Tithi Start ({tz_str}):", _fmt_local(tithi.start_utc, tz_str) or "N/A"],
            [f"Tithi End ({tz_str}):", _fmt_local(tithi.end_utc, tz_str) or "N/A"],
        ]
        if idx == 1:
            panchang_rows.extend([
                ["Lunar Month:", (
                    f"{p.lunar_month.month_name_en}{' (Adhika)' if p.lunar_month.is_adhika else ''}"
                    if p.lunar_month else "N/A"
                )],
                ["Nakshatra:", f"{p.nakshatra.name_en} (Pada {p.nakshatra.pada})" if p.nakshatra else "N/A"],
                ["Yoga:", p.yoga.name_en if p.yoga else "N/A"],
                ["Karana:", p.karana.name_en if p.karana else "N/A"],
                ["Tithi at Sunrise:", (
                    f"{p.tithi_at_sunrise.paksha_en} {p.tithi_at_sunrise.name_en}"
                    if p.tithi_at_sunrise else "N/A"
                )],
            ])
        pt = Table(panchang_rows, colWidths=[4.8 * cm, 12.6 * cm])
        pt.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (0, -1), bold_font),
            ("FONTNAME", (1, 0), (1, -1), reg_font),
            ("FONTSIZE", (0, 0), (-1, -1), 9.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(pt)
        story.append(Spacer(1, 0.2 * cm))

    # Annual Birthday Tables (one per candidate Tithi)
    calendars = result.candidate_calendars or []
    if not calendars and result.birthday_entries:
        cal_list = [("Annual Hindu Birthday Calendar", result.birthday_entries)]
    else:
        cal_list = [
            (
                f"Annual Hindu Birthday Calendar — {cal.lunar_month.month_name_en} "
                f"{cal.tithi.paksha_en} {cal.tithi.name_en}"
                + (f" (Option {i})" if len(calendars) > 1 else ""),
                cal.entries,
            )
            for i, cal in enumerate(calendars, 1)
        ]

    for heading, entries in cal_list:
        story.append(Spacer(1, 0.25 * cm))
        story.append(Paragraph(escape(heading), h2_style))
        table_data = [["Year", "Date", "Day", "Tithi", "Local Window", "Status"]]
        for entry in entries:
            s_loc = _fmt_local(entry.tithi_start_utc, tz_str)
            e_loc = _fmt_local(entry.tithi_end_utc, tz_str)
            win = f"{s_loc[5:16]} - {e_loc[5:16]}" if s_loc and e_loc else "N/A"
            table_data.append([
                str(entry.year),
                entry.gregorian_date.strftime("%d %b %Y") if entry.gregorian_date else "N/A",
                entry.weekday or "",
                entry.tithi_name_en,
                win,
                entry.status,
            ])
        bt = Table(table_data, colWidths=[1.6 * cm, 3.2 * cm, 2.5 * cm, 3.2 * cm, 4.4 * cm, 2.5 * cm])
        bt.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1B2A4A")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), bold_font),
            ("FONTNAME", (0, 1), (-1, -1), reg_font),
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8F9FA")]),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#DEE2E6")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(bt)

    story.append(Spacer(1, 0.4 * cm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
    disclaimer = ParagraphStyle(
        "Disclaimer", parent=styles["Normal"], fontName=reg_font, fontSize=8, textColor=colors.grey
    )
    story.append(Paragraph(
        escape(
            f"Generated by Hindu Tithi Birthday Calculator using Swiss Ephemeris ({p.ayanamsha_name}, "
            f"{p.lunar_system.title()} system, {obs_label}). For important religious observances, "
            "please consult a qualified Panchang scholar."
        ),
        disclaimer,
    ))

    doc.build(story)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# ICS Calendar Export
# ---------------------------------------------------------------------------

def export_ics(result: FullResult) -> bytes:
    """Generate ICS (iCalendar) file for birthday dates across candidate Tithis."""
    import uuid
    from icalendar import Calendar, Event

    cal = Calendar()
    cal.add("prodid", "-//Hindu Tithi Birthday Calculator//EN")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("X-WR-CALNAME", "Hindu Tithi Birthdays")

    p = result.panchang
    tz_str = p.timezone_str
    calendars = result.candidate_calendars

    if not calendars:
        groups = [(p.tithis[0].name_en if p.tithis else "Hindu Birthday", result.birthday_entries)]
    else:
        groups = [
            (
                f"{c.lunar_month.month_name_en} {c.tithi.paksha_en} {c.tithi.name_en}",
                c.entries,
            )
            for c in calendars
        ]

    for idx, (label, entries) in enumerate(groups, 1):
        prefix = f"[Option {idx}] " if len(groups) > 1 else ""
        for entry in entries:
            if entry.gregorian_date is None:
                continue
            event = Event()
            event.add("uid", str(uuid.uuid4()))
            event.add("summary", f"{prefix}Hindu Birthday - {label}")
            event.add("dtstart", entry.gregorian_date)
            event.add("dtend", entry.gregorian_date + timedelta(days=1))
            s_loc = _fmt_local(entry.tithi_start_utc, tz_str)
            e_loc = _fmt_local(entry.tithi_end_utc, tz_str)
            event.add(
                "description",
                f"Hindu Tithi Birthday ({p.lunar_system.title()})\n"
                f"Tithi: {label}\n"
                f"Tithi Window ({tz_str}): {s_loc} to {e_loc}\n"
                f"Status: {entry.status}\n"
                f"Birthplace: {p.location_name}\n"
                f"{entry.notes}",
            )
            event.add("categories", ["BIRTHDAY", "HINDU"])
            cal.add_component(event)

    return cal.to_ical()
