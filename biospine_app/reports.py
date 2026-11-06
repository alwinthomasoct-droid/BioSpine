"""
Admin report builders (Excel + PDF).

These functions only receive plain Python data (dicts / lists), never Django model instances, so
they are easy to test and cannot leak anything that was not passed in on purpose.
Excel needs `openpyxl`, PDF needs `reportlab` (both are in requirements.txt).
"""
import datetime as dt
import io

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

import os

LOGO_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "img", "logo-full-small.png")

HEAD_FILL = PatternFill("solid", fgColor="1E3A8A")
HEAD_FONT = Font(bold=True, color="FFFFFF")
TITLE_FONT = Font(bold=True, size=14)


def _plain(v):
    """Excel cannot store timezone-aware datetimes -> turn them into readable text."""
    if isinstance(v, dt.datetime):
        return v.strftime("%Y-%m-%d %H:%M")
    if isinstance(v, dt.date):
        return v.isoformat()
    return v


def _sheet(wb, title, headers, rows, first=False, note=None):
    ws = wb.active if first else wb.create_sheet()
    ws.title = title[:31]
    r0 = 1
    if note:
        ws.cell(row=1, column=1, value=note).font = Font(italic=True, color="555555")
        r0 = 3
    for c, h in enumerate(headers, 1):
        cell = ws.cell(row=r0, column=c, value=h)
        cell.fill, cell.font = HEAD_FILL, HEAD_FONT
        cell.alignment = Alignment(wrap_text=True, vertical="center")
    for i, row in enumerate(rows, r0 + 1):
        for c, v in enumerate(row, 1):
            ws.cell(row=i, column=c, value=_plain(v))
    for c, h in enumerate(headers, 1):
        longest = max([len(str(h))] + [len(str(_plain(r[c - 1]))) for r in rows[:300] if c - 1 < len(r)])
        ws.column_dimensions[get_column_letter(c)].width = min(48, max(11, longest + 2))
    ws.freeze_panes = ws.cell(row=r0 + 1, column=1)
    return ws


def _pairs_sheet(wb, title, heading, pairs, first=False):
    ws = wb.active if first else wb.create_sheet()
    ws.title = title[:31]
    ws["A1"] = heading
    ws["A1"].font = TITLE_FONT
    for i, (k, v) in enumerate(pairs, 3):
        ws.cell(row=i, column=1, value=k).font = Font(bold=True)
        ws.cell(row=i, column=2, value=_plain(v))
    ws.column_dimensions["A"].width = 38
    ws.column_dimensions["B"].width = 60
    return ws


def _bytes(wb):
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------------------------
# EXCEL
# ---------------------------------------------------------------------------------------------
def _good_bad_minutes(sess):
    good = sess["duration"] * sess["score"] / 100.0 / 60.0
    return round(good, 1), round(sess["duration"] / 60.0 - good, 1)


def _session_sheet(wb, idx, sess):
    """One sheet per session: the time, the numbers, the lean-angle graph and the good / slouching circle diagram."""
    from openpyxl.chart import DoughnutChart, LineChart, Reference
    tr = sess["trend"]
    title = f"S{idx} {sess['start']:%d %b %H.%M}"[:31]
    ws = wb.create_sheet(title)
    ws["A1"] = f"Session on {sess['start']:%A %d %B %Y}, {sess['start']:%H:%M} to {sess['end']:%H:%M}"
    ws["A1"].font = TITLE_FONT
    info = [("Minutes worn", round(sess["duration"] / 60, 1)), ("Posture score %", sess["score"]), ("Alerts", sess["alerts"]),
            ("Average forward lean (deg)", round(sess["avg"], 1)), ("Alert angle set (deg)", sess.get("angle") or "-"), ("Mode", sess.get("mode") or "-")]
    for i, (k, v) in enumerate(info, 3):
        ws.cell(row=i, column=1, value=k).font = Font(bold=True)
        ws.cell(row=i, column=2, value=v)
    good, bad = _good_bad_minutes(sess)
    ws["A10"], ws["B10"] = "Good posture (min)", good
    ws["A11"], ws["B11"] = "Slouching (min)", bad
    # data for the line graph
    r0 = 14
    for c, h in enumerate(["Time", "Minutes from start", "Forward lean (deg)", "Sideways lean (deg)", "Slouching (0-1)"], 1):
        cell = ws.cell(row=r0, column=c, value=h)
        cell.fill, cell.font = HEAD_FILL, HEAD_FONT
    n = len(tr["pitch"])
    for i in range(n):
        t = sess["start"] + dt.timedelta(seconds=tr["step"] * i)
        ws.cell(row=r0 + 1 + i, column=1, value=t.strftime("%H:%M:%S"))
        ws.cell(row=r0 + 1 + i, column=2, value=round(tr["step"] * i / 60, 2))
        ws.cell(row=r0 + 1 + i, column=3, value=tr["pitch"][i])
        ws.cell(row=r0 + 1 + i, column=4, value=(tr["roll"][i] if i < len(tr["roll"]) else 0))
        ws.cell(row=r0 + 1 + i, column=5, value=(tr["bad"][i] if i < len(tr["bad"]) else 0))
    for col, w in zip("ABCDE", (26, 18, 20, 20, 16)):
        ws.column_dimensions[col].width = w
    line = LineChart()
    line.title = "Lean angle during this session"
    line.y_axis.title, line.x_axis.title = "Degrees", "Minutes from start"
    line.height, line.width = 8.5, 20
    line.add_data(Reference(ws, min_col=3, max_col=4, min_row=r0, max_row=r0 + n), titles_from_data=True)
    line.set_categories(Reference(ws, min_col=2, min_row=r0 + 1, max_row=r0 + n))
    for ser in line.series:
        ser.smooth = False
    ws.add_chart(line, "G3")
    pie = DoughnutChart()
    pie.title = "Good posture vs slouching (minutes)"
    pie.add_data(Reference(ws, min_col=2, min_row=10, max_row=11), titles_from_data=False)
    pie.set_categories(Reference(ws, min_col=1, min_row=10, max_row=11))
    pie.height, pie.width = 7.5, 10
    ws.add_chart(pie, "G21")
    return ws


def user_workbook(report):
    """report = {"title", "pairs", "insights", "weekly", "sessions", "hours", "daily"?} - sessions need start / end / trend for the graphs."""
    from openpyxl.chart import DoughnutChart, Reference
    wb = Workbook()
    _pairs_sheet(wb, "Summary", report["title"], report["pairs"], first=True)
    ws = wb["Summary"]
    r = len(report["pairs"]) + 5
    ws.cell(row=r, column=1, value="What this means (plain language)").font = Font(bold=True, size=12)
    for i, line in enumerate(report["insights"], r + 1):
        ws.cell(row=i, column=1, value="• " + line)
    # circle diagram of all the time worn
    tot_good = round(sum(s["duration"] * s["score"] / 100.0 for s in report["sessions"]) / 60.0, 1)
    tot_bad = round(sum(s["duration"] for s in report["sessions"]) / 60.0 - tot_good, 1)
    ws["D3"], ws["E3"] = "All time (minutes)", ""
    ws["D4"], ws["E4"] = "Good posture", tot_good
    ws["D5"], ws["E5"] = "Slouching", tot_bad
    ws["D3"].font = Font(bold=True)
    if tot_good + tot_bad > 0:
        pie = DoughnutChart()
        pie.title = "Good posture vs slouching, all sessions"
        pie.add_data(Reference(ws, min_col=5, min_row=4, max_row=5), titles_from_data=False)
        pie.set_categories(Reference(ws, min_col=4, min_row=4, max_row=5))
        pie.height, pie.width = 7.5, 11
        ws.add_chart(pie, "G3")
    _sheet(wb, "Weekly", ["Week starting", "Sessions", "Hours worn", "Avg compliance %", "Alerts"],
           [[w["week"], w["sessions"], w["hours"], w["compliance"], w["alerts"]] for w in report["weekly"]])
    _sheet(wb, "Sessions", ["Date", "Started", "Ended", "Minutes worn", "Compliance %", "Alerts", "Avg forward lean (deg)", "Typical lean (deg)",
                            "Worst lean (deg)", "Highest neck load (lbs)", "Mode", "Source"],
           [[s["start"].strftime("%Y-%m-%d"), s["start"].strftime("%H:%M"), s["end"].strftime("%H:%M"), round(s["duration"] / 60, 1), s["score"], s["alerts"],
             round(s["avg"], 1), s.get("median", ""), s.get("max", ""), s.get("peak", ""), s.get("mode", ""), s.get("source", "")] for s in report["sessions"]])
    if report.get("daily"):
        _sheet(wb, "Time periods by day", ["Date", "Weekday", "Time periods used", "Minutes worn", "Sessions", "Avg deviation (deg)", "Compliance %", "Alerts"],
               [[d["date"], d["weekday"], d.get("periods", ""), d["minutes"], d["sessions"], d["avg_dev"], d["compliance"], d["alerts"]] for d in report["daily"]])
    _sheet(wb, "Time of day", ["Hour of day", "Sessions"], [[f"{h:02d}:00", n] for h, n in enumerate(report["hours"])])
    with_graph = [s for s in report["sessions"] if s.get("trend")][:10]
    for i, sess in enumerate(with_graph, 1):
        _session_sheet(wb, i, sess)
    return _bytes(wb)


def platform_workbook(report):
    """report = {"title", "pairs", "insights", "weekly": [dict], "daily": [dict], "users": [dict], "distribution": [dict], "reviews": [dict]}"""
    wb = Workbook()
    _pairs_sheet(wb, "Overview", report["title"], report["pairs"], first=True)
    ws = wb["Overview"]
    r = len(report["pairs"]) + 5
    ws.cell(row=r, column=1, value="What this means (plain language)").font = Font(bold=True, size=12)
    for i, line in enumerate(report["insights"], r + 1):
        ws.cell(row=i, column=1, value="• " + line)
    _sheet(wb, "Averages by week",
           ["Week starting", "Active users", "Sessions", "Sessions per active user", "Avg hours per active user",
            "Avg compliance %", "Alerts per hour worn", "New sign-ups"],
           [[w["week"], w["users"], w["sessions"], w["sessions_per_user"], w["hours_per_user"], w["compliance"],
             w["alerts_per_hour"], w["signups"]] for w in report["weekly"]])
    _sheet(wb, "Daily", ["Date", "Sessions", "Active users", "Avg compliance %", "Hours worn", "Alerts"],
           [[d["date"], d["sessions"], d["users"], d["compliance"], d["hours"], d["alerts"]] for d in report["daily"]])
    _sheet(wb, "Every user",
           ["Email", "Joined", "Status", "Sessions", "Active days", "Time worn", "Avg compliance %", "Alerts",
            "Current streak", "Best streak", "Last active"],
           [[u["email"], u["created_at"], u["status"], u["sessions"], u["active_days"], u["hours"], u["avg_compliance"],
             u["alerts"], u["current_streak"], u["longest_streak"], u["last_active"] or ""] for u in report["users"]])
    _sheet(wb, "Compliance spread", ["Compliance band", "Sessions"], [[d["label"], d["count"]] for d in report["distribution"]])
    _sheet(wb, "Reviews", ["Date", "Stars", "Name shown", "Comment", "Shown on home page"],
           [[r_["date"], r_["rating"], r_["name"], r_["comment"], "yes" if r_["shown"] else "no"] for r_ in report["reviews"]])
    return _bytes(wb)


# ---------------------------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------------------------
def _pdf(title, subtitle, pairs, insights, tables, chart=None, donut=None, story=None):
    from reportlab.graphics.charts.lineplots import LinePlot
    from reportlab.graphics.shapes import Drawing, String
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from xml.sax.saxutils import escape

    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Title"], textColor=colors.HexColor("#1E3A8A"), fontSize=20, alignment=0)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], textColor=colors.HexColor("#1E3A8A"), spaceBefore=12)
    body = ParagraphStyle("b", parent=ss["BodyText"], fontSize=10, leading=14)
    small = ParagraphStyle("s", parent=body, fontSize=8, textColor=colors.HexColor("#666666"))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
                            title=title, author="BioSpine")
    el = []
    if os.path.exists(LOGO_PATH):
        from reportlab.platypus import Image as RLImage
        el.append(RLImage(LOGO_PATH, width=30 * mm, height=30 * mm, hAlign="LEFT"))
    el += [Paragraph(escape(title), h1), Paragraph(escape(subtitle), small), Spacer(1, 6)]

    t = Table([[escape(str(k)), escape(str(_plain(v)))] for k, v in pairs], colWidths=[70 * mm, 106 * mm])
    t.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 9), ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                           ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.whitesmoke, colors.white]),
                           ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    el += [Paragraph("At a glance", h2), t, Paragraph("What this means", h2)]
    for line in insights:
        el.append(Paragraph("• " + escape(line), body))

    if chart and len(chart["points"]) >= 2:
        d = Drawing(176 * mm, 55 * mm)
        lp = LinePlot()
        lp.x, lp.y, lp.width, lp.height = 12 * mm, 8 * mm, 156 * mm, 40 * mm
        lp.data = [[(i, v) for i, v in enumerate(chart["points"])]]
        lp.lines[0].strokeColor = colors.HexColor("#2563EB")
        lp.lines[0].strokeWidth = 1.6
        lp.yValueAxis.valueMin, lp.yValueAxis.valueMax = 0, 100
        lp.yValueAxis.labels.fontSize = 7
        lp.xValueAxis.labels.fontSize = 7
        d.add(lp)
        d.add(String(12 * mm, 50 * mm, chart["title"], fontSize=8, fillColor=colors.HexColor("#444444")))
        el += [Paragraph("Trend", h2), d]

    if donut and (donut["good"] + donut["bad"]) > 0:
        el += [Paragraph("Posture time (all sessions)", h2), _pie_drawing(donut["good"], donut["bad"], 56),
               Paragraph(escape(f"Good posture {donut['good']} min (green)  |  slouching {donut['bad']} min (red)"), small)]
    if story:
        el += [Paragraph("Each time period, with its graph", h2)] + story
    for heading, headers, rows in tables:
        el.append(Paragraph(escape(heading), h2))
        data = [headers] + [[escape(str(_plain(c))) for c in r] for r in rows]
        tb = Table(data, repeatRows=1)
        tb.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E3A8A")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                                ("FONTSIZE", (0, 0), (-1, -1), 8), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.whitesmoke]),
                                ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey)]))
        el.append(tb)
    el += [Spacer(1, 10), Paragraph("Posture figures come from the wearable sensor and are for wellness coaching only - "
                                    "they are not a medical diagnosis.", small)]
    doc.build(el)
    return buf.getvalue()


def _pie_drawing(good, bad, size=62):
    """A circle (donut) diagram: good posture vs slouching minutes."""
    from reportlab.graphics.charts.piecharts import Pie
    from reportlab.graphics.shapes import Circle, Drawing, String
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    d = Drawing(size * mm, size * mm)
    total = good + bad
    if total <= 0:
        return d
    p = Pie()
    p.x, p.y, p.width, p.height = 4 * mm, 4 * mm, (size - 8) * mm, (size - 8) * mm
    p.data = [max(good, 0.01), max(bad, 0.01)]
    p.labels = None
    p.slices[0].fillColor, p.slices[1].fillColor = colors.HexColor("#34D399"), colors.HexColor("#F87171")
    p.slices.strokeColor = colors.white
    d.add(p)
    cx, cy, r = size * mm / 2, size * mm / 2, (size - 8) * mm / 2 * 0.56
    d.add(Circle(cx, cy, r, fillColor=colors.white, strokeColor=colors.white))
    d.add(String(cx, cy - 2, f"{100 * good / total:.0f}%", textAnchor="middle", fontSize=11, fillColor=colors.HexColor("#1E3A8A")))
    return d


def _line_drawing(sess):
    """Lean angle over the session, with the alert angle drawn as a red line."""
    from reportlab.graphics.charts.lineplots import LinePlot
    from reportlab.graphics.shapes import Drawing, String
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    tr = sess["trend"]
    n = len(tr["pitch"])
    xs = [i * tr["step"] / 60.0 for i in range(n)]
    d = Drawing(120 * mm, 50 * mm)
    lp = LinePlot()
    lp.x, lp.y, lp.width, lp.height = 12 * mm, 9 * mm, 102 * mm, 36 * mm
    series = [list(zip(xs, tr["pitch"])), list(zip(xs, tr["roll"][:n] or [0] * n))]
    thr = sess.get("angle")
    if thr:
        series.append([(0, thr), (xs[-1] or 1, thr)])
    lp.data = series
    lp.lines[0].strokeColor, lp.lines[0].strokeWidth = colors.HexColor("#2563EB"), 1.4
    lp.lines[1].strokeColor, lp.lines[1].strokeWidth = colors.HexColor("#A78BFA"), 1.0
    if thr:
        lp.lines[2].strokeColor, lp.lines[2].strokeWidth, lp.lines[2].strokeDashArray = colors.HexColor("#DC2626"), 0.9, (3, 2)
    lo = min(min(tr["pitch"]), min(tr["roll"] or [0]), 0)
    hi = max(max(tr["pitch"]), max(tr["roll"] or [0]), thr or 0, 10)
    lp.yValueAxis.valueMin, lp.yValueAxis.valueMax = lo - 2, hi + 2
    lp.yValueAxis.labels.fontSize = lp.xValueAxis.labels.fontSize = 6
    lp.xValueAxis.valueMin, lp.xValueAxis.valueMax = 0, max(xs[-1], 0.1)
    d.add(lp)
    d.add(String(12 * mm, 46 * mm, "Blue: forward lean (deg)   Purple: sideways lean   Red dashes: alert angle   (x: minutes from start)",
                 fontSize=6, fillColor=colors.HexColor("#555555")))
    return d


def _session_story(sessions):
    """Flowables for the 'time periods' pages: heading with the time, numbers, line graph and circle diagram."""
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import KeepTogether, Paragraph, Spacer, Table, TableStyle
    from xml.sax.saxutils import escape
    ss = getSampleStyleSheet()
    h3 = ParagraphStyle("h3", parent=ss["Heading3"], textColor=colors.HexColor("#1E3A8A"), spaceBefore=10, spaceAfter=2)
    small = ParagraphStyle("sm", parent=ss["BodyText"], fontSize=8, textColor=colors.HexColor("#444444"))
    out = []
    for s in sessions:
        good, bad = _good_bad_minutes(s)
        head = Paragraph(escape(f"{s['start']:%a %d %b %Y}, {s['start']:%H:%M} to {s['end']:%H:%M}  ({round(s['duration'] / 60)} min)"), h3)
        facts = Paragraph(escape(f"Score {s['score']}%  |  alerts {s['alerts']}  |  average lean {round(s['avg'], 1)} deg"
                                 + (f"  |  worst {s['max']} deg" if s.get("max") is not None else "")
                                 + (f"  |  highest neck load {s['peak']} lbs" if s.get("peak") else "")
                                 + (f"  |  mode {s['mode']}" if s.get("mode") else "") + (f"  |  {s['source']}" if s.get("source") == "demo" else "")), small)
        row = Table([[_line_drawing(s), _pie_drawing(good, bad)]], colWidths=[122 * mm, 58 * mm])
        row.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
        legend = Paragraph(f"Circle: good posture {good} min (green), slouching {bad} min (red).", small)
        out.append(KeepTogether([head, facts, row, legend, Spacer(1, 4)]))
    return out


def user_pdf(report):
    pts = [w["compliance"] for w in report["weekly"] if w["compliance"] is not None]
    tot_good = round(sum(s["duration"] * s["score"] / 100.0 for s in report["sessions"]) / 60.0, 1)
    tot_bad = round(sum(s["duration"] for s in report["sessions"]) / 60.0 - tot_good, 1)
    graph_sessions = [s for s in report["sessions"] if s.get("trend")][:8]
    return _pdf(report["title"], report["subtitle"], report["pairs"], report["insights"],
                [("Week by week", ["Week starting", "Sessions", "Hours", "Compliance %", "Alerts"],
                  [[w["week"], w["sessions"], w["hours"], w["compliance"], w["alerts"]] for w in report["weekly"][-26:]]),
                 ("Most recent sessions", ["Started", "Ended", "Minutes", "Compliance %", "Alerts", "Avg lean (deg)"],
                  [[s["start"].strftime("%Y-%m-%d %H:%M"), s["end"].strftime("%H:%M"), round(s["duration"] / 60, 1), s["score"], s["alerts"], round(s["avg"], 1)]
                   for s in report["sessions"][:40]])],
                chart={"title": "Average compliance % per week", "points": pts},
                donut={"good": tot_good, "bad": tot_bad}, story=_session_story(graph_sessions) if graph_sessions else None)


def platform_pdf(report):
    pts = [w["compliance"] for w in report["weekly"] if w["compliance"] is not None]
    return _pdf(report["title"], report["subtitle"], report["pairs"], report["insights"],
                [("Averages by week", ["Week", "Active users", "Sessions", "Sess./user", "Hours/user", "Compl. %", "New users"],
                  [[w["week"], w["users"], w["sessions"], w["sessions_per_user"], w["hours_per_user"], w["compliance"], w["signups"]]
                   for w in report["weekly"]]),
                 ("Most active users", ["Email", "Sessions", "Time worn", "Compl. %", "Streak"],
                  [[u["email"], u["sessions"], u["hours"], u["avg_compliance"], u["current_streak"]] for u in report["users"][:15]]),
                 ("Client reviews", ["Date", "Stars", "Name", "Comment"],
                  [[r["date"], r["rating"], r["name"], (r["comment"] or "")[:90]] for r in report["reviews"][:15]])],
                chart={"title": "Average compliance % per week (all users)", "points": pts})
