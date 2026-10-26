"""Printable skin template for the OnePlus Nord Buds 4 Pro charging case.

Case size (published spec): 60.00 mm tall x 49.64 mm wide x 25.04 mm deep.
The front and back faces are rounded at the edges, so the skins are inset
from the full outline and come in three sizes (L / M / S). Test-fit the
plain outlines on page 1 first, then print the matching design page.

Run:  python3 make_skin.py   ->  writes nord_buds_4_pro_skin.pdf
Print at 100% / "Actual size" on A4.
"""

import math
import os

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nord_buds_4_pro_skin.pdf")

CASE_H, CASE_W = 60.0, 49.64
# (label, height, width, corner radius) in mm
SIZES = [
    ("L", 56.0, 46.0, 15.0),
    ("M", 54.0, 44.0, 14.0),
    ("S", 52.0, 42.0, 13.0),
]
BLEED = 1.2  # artwork extends past the cut line so scissors never leave a white edge
PAGE_W, PAGE_H = A4


def skin_path(c, x, y, w, h, r):
    p = c.beginPath()
    p.roundRect(x, y, w, h, r)
    return p


# ---------------------------------------------------------------- designs
def d_gloss_black(c, x, y, w, h):
    c.linearGradient(x, y + h, x + w, y, (colors.HexColor("#3a3a3a"), colors.HexColor("#0b0b0b"),
                                          colors.HexColor("#1c1c1c")), positions=(0, 0.55, 1))


def d_carbon(c, x, y, w, h):
    c.setFillColor(colors.HexColor("#141414"))
    c.rect(x, y, w, h, stroke=0, fill=1)
    s = 1.6 * mm
    rows, cols = int(h / s) + 2, int(w / s) + 2
    for i in range(cols):
        for j in range(rows):
            cx, cy = x + i * s, y + j * s
            light = (i + j) % 2 == 0
            c.setFillColor(colors.HexColor("#2b2b2b" if light else "#1a1a1a"))
            if light:
                c.rect(cx, cy, s, s / 2, stroke=0, fill=1)
                c.setFillColor(colors.HexColor("#363636"))
                c.rect(cx, cy + s / 2, s, s / 2, stroke=0, fill=1)
            else:
                c.rect(cx, cy, s / 2, s, stroke=0, fill=1)
                c.setFillColor(colors.HexColor("#242424"))
                c.rect(cx + s / 2, cy, s / 2, s, stroke=0, fill=1)


def d_aurora(c, x, y, w, h):
    c.linearGradient(x, y, x + w, y + h, (colors.HexColor("#0f2027"), colors.HexColor("#2c5364"),
                                          colors.HexColor("#7b2ff7"), colors.HexColor("#f107a3")),
                     positions=(0, 0.35, 0.75, 1))


def d_radiant_gray(c, x, y, w, h):
    c.linearGradient(x, y, x + w, y + h, (colors.HexColor("#8e9196"), colors.HexColor("#c9cbce"),
                                          colors.HexColor("#9fa2a6")), positions=(0, 0.5, 1))


def d_stripes(c, x, y, w, h):
    c.setFillColor(colors.HexColor("#f4f1ea"))
    c.rect(x, y, w, h, stroke=0, fill=1)
    c.setStrokeColor(colors.HexColor("#e2231a"))
    c.setLineWidth(1.4 * mm)
    step = 4.5 * mm
    k = -h
    while k < w + h:
        c.line(x + k, y, x + k + h, y + h)
        k += step
    c.setStrokeColor(colors.HexColor("#111111"))
    c.setLineWidth(0.5 * mm)
    k = -h + step / 2
    while k < w + h:
        c.line(x + k, y, x + k + h, y + h)
        k += step


def d_topo(c, x, y, w, h):
    c.setFillColor(colors.HexColor("#10302a"))
    c.rect(x, y, w, h, stroke=0, fill=1)
    c.setStrokeColor(colors.HexColor("#5fd3a8"))
    c.setLineWidth(0.25 * mm)
    cx, cy = x + w * 0.62, y + h * 0.4
    for n in range(1, 18):
        r = n * 2.6 * mm
        p = c.beginPath()
        for t in range(0, 361, 6):
            a = math.radians(t)
            wob = 1 + 0.12 * math.sin(3 * a + n * 0.7) + 0.06 * math.sin(5 * a)
            px, py = cx + r * wob * math.cos(a), cy + r * wob * 0.85 * math.sin(a)
            (p.moveTo if t == 0 else p.lineTo)(px, py)
        p.close()
        c.drawPath(p, stroke=1, fill=0)


def d_blank(c, x, y, w, h):
    c.setFillColor(colors.white)
    c.rect(x, y, w, h, stroke=0, fill=1)


DESIGNS = [
    ("Gloss Black", d_gloss_black),
    ("Carbon Fibre", d_carbon),
    ("Aurora", d_aurora),
    ("Radiant Gray", d_radiant_gray),
    ("Racing Stripes", d_stripes),
    ("Topo Lines", d_topo),
]


# ---------------------------------------------------------------- helpers
def seam_ruler(c, x, top, h):
    """mm ticks measured DOWN from the top of a skin, so the lid/base seam can be marked."""
    c.setStrokeColor(colors.HexColor("#666666"))
    c.setFillColor(colors.HexColor("#666666"))
    c.setLineWidth(0.2)
    c.setFont("Helvetica", 4)
    for i in range(int(h) + 1):
        ln = 2.5 if i % 10 == 0 else 1.6 if i % 5 == 0 else 0.9
        yy = top - i * mm
        c.line(x - ln * mm, yy, x, yy)
        if i % 10 == 0 and i:
            c.drawRightString(x - 2.8 * mm, yy - 1.3, str(i))


def draw_skin(c, x, y, size, design=None, label="", top_label=True):
    name, h, w, r = size
    X, Y, W, H, R = x * mm, y * mm, w * mm, h * mm, r * mm
    if design:
        c.saveState()
        b = BLEED * mm
        c.clipPath(skin_path(c, X - b, Y - b, W + 2 * b, H + 2 * b, R + b), stroke=0, fill=0)
        design(c, X - b, Y - b, W + 2 * b, H + 2 * b)
        c.restoreState()
    # cut line
    c.setStrokeColor(colors.HexColor("#ff00ff") if design else colors.black)
    c.setLineWidth(0.35)
    if design:
        c.setDash(1.5, 1.5)
    c.drawPath(skin_path(c, X, Y, W, H, R), stroke=1, fill=0)
    c.setDash()
    # centre cross for the plain test pieces
    if not design:
        c.setStrokeColor(colors.HexColor("#999999"))
        c.setLineWidth(0.2)
        c.line(X + W / 2 - 3 * mm, Y + H / 2, X + W / 2 + 3 * mm, Y + H / 2)
        c.line(X + W / 2, Y + H / 2 - 3 * mm, X + W / 2, Y + H / 2 + 3 * mm)
    seam_ruler(c, X - 1.5 * mm, Y + H, h)
    c.setFillColor(colors.HexColor("#333333"))
    if top_label:
        c.setFont("Helvetica", 6)
        c.drawCentredString(X + W / 2, Y + H + 2.2 * mm, "↑ TOP (lid)")
    c.setFont("Helvetica", 5.5)
    c.drawCentredString(X + W / 2, Y - 3.6 * mm, label)


def calibration(c, x, y):
    c.setStrokeColor(colors.black)
    c.setLineWidth(0.4)
    c.line(x * mm, y * mm, (x + 100) * mm, y * mm)
    c.setFont("Helvetica", 5)
    for i in range(101):
        ln = 3 if i % 10 == 0 else 2 if i % 5 == 0 else 1
        c.line((x + i) * mm, y * mm, (x + i) * mm, (y + ln) * mm)
        if i % 10 == 0:
            c.drawCentredString((x + i) * mm, (y + 4) * mm, str(i))
    c.setFont("Helvetica-Bold", 7)
    c.drawString((x + 104) * mm, (y + 0.5) * mm, "← must measure exactly 100 mm. If not, reprint at 100% / Actual size.")


def header(c, title, sub):
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 13)
    c.drawString(12 * mm, PAGE_H - 14 * mm, title)
    c.setFont("Helvetica", 7.5)
    c.drawString(12 * mm, PAGE_H - 19 * mm, sub)


# ---------------------------------------------------------------- pages
def page_test(c):
    header(c, "OnePlus Nord Buds 4 Pro – case skin: TEST-FIT page",
           f"Case spec: {CASE_H:.2f} mm tall x {CASE_W:.2f} mm wide x 25.04 mm deep. "
           "Print this page on plain paper first. Print at 100% / Actual size, no 'fit to page'.")
    calibration(c, 12, PAGE_H / mm - 32)

    c.setFont("Helvetica-Bold", 9)
    c.drawString(12 * mm, PAGE_H - 44 * mm, "1. Full case outline (reference only)")
    draw_skin(c, 20, PAGE_H / mm - 112, ("full", CASE_H, CASE_W, 17.0), None, f"FULL {CASE_H:.0f} x {CASE_W:.1f}")

    c.setFont("Helvetica-Bold", 9)
    c.drawString(85 * mm, PAGE_H - 44 * mm, "2. Cut these out and hold them on the case")
    xs = [85, 140]
    for i, s in enumerate(SIZES[:2]):
        draw_skin(c, xs[i] + 3, PAGE_H / mm - 112, s, None, f"SIZE {s[0]}  {s[1]:.0f} x {s[2]:.0f} mm")
    draw_skin(c, 88, PAGE_H / mm - 185, SIZES[2], None, f"SIZE {SIZES[2][0]}  {SIZES[2][1]:.0f} x {SIZES[2][2]:.0f} mm")

    steps = [
        "HOW TO PICK A SIZE",
        "• Cut out L, M and S along the black line. Centre each on the FRONT face of the case.",
        "• Pick the largest one whose edges stay on the flat-ish part of the face, about 1–2 mm before",
        "   the edge starts curving round to the side. Paper/vinyl can't wrap a curved corner – it lifts.",
        "• Check the LED / any button / logo you want to keep visible is not under it.",
        "",
        "FIND THE LID SEAM",
        "• With the test piece centred on the case, draw a pencil mark where the lid/base",
        "   seam crosses it. Read that distance from the TOP of the piece (mm).",
        "• On the design pages, every skin has a mm ruler on its left measured from its top.",
        "   Cut the skin in two at that number, then trim 0.5 mm off both sides of the cut so",
        "   there's a ~1 mm gap over the seam. Otherwise the lid won't open, or the skin tears.",
        "",
        "Pages 2–4 = designs in size L, M, S. Print only the page you need.",
        "Pink dashed line = cut line. Colour runs 1.2 mm past it so you never get a white rim.",
    ]
    yy = PAGE_H / mm - 200
    for line in steps:
        bold = line.isupper() and line != ""
        c.setFont("Helvetica-Bold" if bold else "Helvetica", 8.5 if bold else 8)
        c.drawString(14 * mm, yy * mm, line)
        yy -= 4.6


def page_designs(c, size):
    name, h, w, r = size
    header(c, f"Designs – SIZE {name} ({h:.0f} x {w:.0f} mm skins)",
           "Print on printable glossy vinyl sticker sheet at 100% / Actual size. "
           "FRONT + BACK per design. Top of each skin = lid end. Cut on the pink dashed line.")
    calibration(c, 12, PAGE_H / mm - 30)
    col_x = [22, 87, 152]
    rows = 4
    row_h = (PAGE_H / mm - 45) / rows
    for idx, (dname, fn) in enumerate(DESIGNS):
        for side in (0, 1):
            slot = idx * 2 + side
            col, row = slot % 3, slot // 3
            x = col_x[col] + (46 - w) / 2
            y = PAGE_H / mm - 40 - (row + 1) * row_h + (row_h - h) / 2
            draw_skin(c, x, y, size, fn, f"{dname} – {'FRONT' if side == 0 else 'BACK'}", top_label=False)


def main():
    c = canvas.Canvas(OUT, pagesize=A4)
    c.setTitle("OnePlus Nord Buds 4 Pro case skin")
    page_test(c)
    c.showPage()
    for s in SIZES:
        page_designs(c, s)
        c.showPage()
    c.save()
    print("wrote", OUT)


if __name__ == "__main__":
    main()
