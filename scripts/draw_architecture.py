"""Draw docs/architecture.svg with the standard library only.

    python scripts/draw_architecture.py
"""
from html import escape
from pathlib import Path

parts = []


def text(x, y, value, size=13, weight=400, color="#172033", anchor="middle"):
    parts.append(f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{color}" '
                 f'text-anchor="{anchor}">{escape(value)}</text>')


def box(x, y, w, h, title, *lines, fill="#ffffff", stroke="#5c6780", width=1.5, dash=""):
    parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="{fill}" stroke="{stroke}" '
                 f'stroke-width="{width}" stroke-dasharray="{dash}"/>')
    top = y + h / 2 - len(lines) * 8 + 5
    text(x + w / 2, top, title, 13, 700)
    for i, line in enumerate(lines):
        text(x + w / 2, top + 17 * (i + 1), line, 12, color="#414c66")


def zone(x, y, w, h, title, fill, stroke, dash=""):
    parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" fill="{fill}" stroke="{stroke}" '
                 f'stroke-width="2" stroke-dasharray="{dash}"/>')
    text(x + 14, y + 22, title, 13, 700, stroke, "start")


def arrow(points, label="", at=None, color="#34405c", width=1.6, dash=""):
    path = " ".join(f"{'M' if i == 0 else 'L'}{x} {y}" for i, (x, y) in enumerate(points))
    parts.append(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="{width}" '
                 f'stroke-dasharray="{dash}" marker-end="url(#head)"/>')
    if label:
        text(at[0], at[1], label, 11, 600, color)


zone(185, 55, 1010, 665, "", "#f8f9fc", "#b3261e", "9 5")
text(1180, 716, "TRUST BOUNDARY: your machine, localhost only, simulation only", 13, 700, "#b3261e", "end")
zone(380, 95, 250, 605, "AI: advisory only", "#f3eefe", "#6d3fd0")
zone(665, 95, 250, 605, "CONTROL: plain code", "#eef4ff", "#2f5fdb")
zone(950, 95, 225, 605, "DATA: synthetic", "#eefaf3", "#1f7a49")
text(600, 30, "DR Runbook Agent: architecture, trust boundary and approval step", 19, 700)

box(20, 335, 135, 70, "Coordinator", "(human)")
box(215, 335, 135, 70, "Web UI + API", "blocks cross-site")

box(405, 135, 200, 75, "Drill Coordinator", "agent (Agent Framework)")
box(405, 260, 200, 75, "Failover Operator", "connected agent")
box(405, 400, 200, 75, "Briefing, analysis,", "runbook review")
box(405, 575, 200, 90, "Output checks", "steps, tools, citations,", "owners, source quotes")

box(690, 135, 200, 75, "Drill state machine", "only allowed commands")
box(690, 285, 200, 120, "HUMAN APPROVAL", "signed single-use token", "bound to drill, step,", "parameters and expiry",
    fill="#fff6dd", stroke="#a66f00", width=3)
box(690, 480, 200, 80, "Operator tools", "2 read-only", "4 need a token")
box(690, 600, 200, 70, "Report + metrics", "calculated by code")

box(970, 135, 185, 85, "Runbooks + docs", "SQLite FTS5 / BM25")
box(970, 480, 185, 80, "Scenario fixtures", "simulated systems")
box(970, 595, 185, 80, "State + event log", "append-only, hashed")

box(380, 755, 250, 62, "OpenAI API: gpt-4.1-mini", "outside the boundary", fill="#ffffff", stroke="#b3261e")

arrow([(155, 370), (213, 370)])
arrow([(282, 335), (282, 172), (403, 172)], "questions", (325, 163))
arrow([(282, 405), (282, 437), (403, 437)], "AI requests", (325, 428))
arrow([(260, 335), (260, 76), (790, 76), (790, 133)], "commands", (525, 70))
arrow([(505, 210), (505, 258)], "asks", (525, 239))
arrow([(790, 210), (790, 283)], "asks for approval", (848, 252))
arrow([(260, 405), (260, 540), (665, 540), (665, 345), (688, 345)], "Approve / Reject button", (460, 532), "#a66f00", 3)
arrow([(790, 405), (790, 478)], "token", (815, 447), "#a66f00", 3)
arrow([(605, 297), (648, 297), (648, 505), (688, 505)], "no token: refused", (590, 566), "#b3261e", 1.6, "5 4")
arrow([(605, 160), (645, 160), (645, 128), (1062, 128), (1062, 133)], "search", (940, 123))
arrow([(890, 520), (968, 520)])
arrow([(890, 192), (925, 192), (925, 625), (968, 625)], "records", (948, 440))
arrow([(968, 655), (892, 640)])
arrow([(405, 190), (392, 190), (392, 620), (403, 620)])
arrow([(505, 475), (505, 573)])
arrow([(403, 645), (240, 645), (240, 407)], "checked advice", (320, 637))
arrow([(505, 702), (505, 753)], "masked data", (560, 740), "#b3261e")

svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="1220" height="835" viewBox="0 0 1220 835" '
       'font-family="Segoe UI, Arial, sans-serif"><defs><marker id="head" viewBox="0 0 10 10" refX="9" refY="5" '
       'markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="#34405c"/>'
       '</marker></defs><rect width="1220" height="835" fill="#ffffff"/>' + "".join(parts) + "</svg>\n")
out = Path(__file__).resolve().parents[1] / "docs" / "architecture.svg"
out.write_text(svg, encoding="utf-8", newline="\n")
print(out)
