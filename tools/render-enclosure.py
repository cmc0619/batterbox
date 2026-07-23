"""Generate an artist rendering (SVG) of BatterBox in the Hammond 1456KH3BKBU
sloped console. Isometric projection, computed in Python for accuracy.
Enclosure: 254 W x 211 D x 76 H mm, 15 deg slope, black top, blue body."""
import base64, math

W, D, H = 254.0, 211.0, 76.0   # enclosure mm (Hammond spec)
ZF = 26.0                       # front lip height (slope: front low -> back 76)

C30, S30 = math.cos(math.radians(30)), math.sin(math.radians(30))
def iso(x, y, z):
    # view from the front-right corner (180° about z vs standard iso), so the
    # low front edge of the slope faces the viewer like the product photo
    xr, yr = W - x, D - y
    return ((xr - yr) * C30, (xr + yr) * S30 - z)

def ztop(y):                    # slope surface height at depth y
    return ZF + (H - ZF) * (y / D)

def pts(*xyz):
    return " ".join(f"{iso(*p)[0]:.1f},{iso(*p)[1]:.1f}" for p in xyz)

def affine_to_quad(src, dst):
    """2D affine matrix mapping 3 src points to 3 dst points (SVG matrix())."""
    (x0, y0), (x1, y1), (x2, y2) = src
    (u0, v0), (u1, v1), (u2, v2) = dst
    d = x0 * (y1 - y2) + x1 * (y2 - y0) + x2 * (y0 - y1)
    a = (u0 * (y1 - y2) + u1 * (y2 - y0) + u2 * (y0 - y1)) / d
    b = (u0 * (x2 - x1) + u1 * (x0 - x2) + u2 * (x1 - x0)) / d
    c = (v0 * (y1 - y2) + v1 * (y2 - y0) + v2 * (y0 - y1)) / d
    dd = (v0 * (x2 - x1) + v1 * (x0 - x2) + v2 * (x1 - x0)) / d
    e = (u0 * (x1 * y2 - x2 * y1) + u1 * (x2 * y0 - x0 * y2) + u2 * (x0 * y1 - x1 * y0)) / d
    f = (v0 * (x1 * y2 - x2 * y1) + v1 * (x2 * y0 - x0 * y2) + v2 * (x0 * y1 - x1 * y0)) / d
    return f"matrix({a:.5f} {c:.5f} {b:.5f} {dd:.5f} {e:.2f} {f:.2f})"

# --- screen: 10.1" panel ~235x136mm with bezel, on the slope ---
SW, SD = 235.0, 136.0
sx0, sy0 = (W - SW) / 2, 62.0
scorners = [(sx0, sy0, ztop(sy0)), (sx0 + SW, sy0, ztop(sy0)),
            (sx0 + SW, sy0 + SD, ztop(sy0 + SD)), (sx0, sy0 + SD, ztop(sy0 + SD))]
sc = [iso(*p) for p in scorners]
mat = affine_to_quad([(0, 0), (1024, 0), (0, 600)], [sc[3], sc[2], sc[0]])

img64 = base64.b64encode(open("../docs/screenshots/kiosk-grid.png", "rb").read()).decode()

# --- jumbo arcade buttons on the slope below the screen ---
def button(cx, cy, r, color, label):
    bx, by = iso(cx, cy, ztop(cy))
    ry = r * 0.55  # projected squash
    return f"""
    <ellipse cx="{bx:.1f}" cy="{by:.1f}" rx="{r}" ry="{ry:.1f}" fill="{color}" stroke="#0a0a0a" stroke-width="2.5"/>
    <ellipse cx="{bx:.1f}" cy="{by-3:.1f}" rx="{r*0.72:.1f}" ry="{ry*0.72:.1f}" fill="rgba(255,255,255,0.25)"/>
    <text x="{bx:.1f}" y="{by+ry+18:.1f}" class="bl">{label}</text>"""

buttons = (
    button(46, 34, 20, "#c1272d", "STOP") + button(120, 34, 16, "#1f6fd6", "VOL+")
    + button(166, 34, 16, "#1f6fd6", "VOL\u2212") + button(218, 34, 16, "#e8a800", "NEXT")
)

# --- dimension helpers ---
def dim_line(p1, p2, label, off=(0, 0)):
    a, b = iso(*p1), iso(*p2)
    ax, ay, bx, by = a[0] + off[0], a[1] + off[1], b[0] + off[0], b[1] + off[1]
    mx, my = (ax + bx) / 2, (ay + by) / 2
    return f"""
    <line x1="{ax:.1f}" y1="{ay:.1f}" x2="{bx:.1f}" y2="{by:.1f}" class="dim"/>
    <text x="{mx:.1f}" y="{my:.1f}" class="dt">{label}</text>"""

svg = f"""<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"
     width="1400" height="980" viewBox="-700 -520 1400 980">
<style>
  .t  {{ font: 800 34px system-ui, sans-serif; fill: #16202b; text-anchor: middle; }}
  .s  {{ font: 600 19px system-ui, sans-serif; fill: #46545f; text-anchor: middle; }}
  .dt {{ font: 700 17px system-ui, sans-serif; fill: #0b3d66; text-anchor: middle; }}
  .bl {{ font: 800 15px system-ui, sans-serif; fill: #e8edf2; text-anchor: middle; }}
  .cl {{ font: 700 18px system-ui, sans-serif; fill: #0b3d66; }}
  .dim {{ stroke: #0b3d66; stroke-width: 1.4; marker-start: url(#a); marker-end: url(#a); }}
  .lead {{ stroke: #0b3d66; stroke-width: 1.2; stroke-dasharray: 5 4; fill: none; }}
</style>
<defs>
  <marker id="a" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
    <path d="M0,0 L10,5 L0,10 z" fill="#0b3d66"/>
  </marker>
</defs>
<rect x="-700" y="-520" width="1400" height="980" fill="#f4f6f8"/>
<text x="0" y="-462" class="t">BatterBox — Field Console (artist rendering)</text>
<text x="0" y="-430" class="s">Hammond 1456KH3BKBU sloped console · 254 × 211 × 76 mm (10″ × 8.3″ × 3″) · 15° slope · aluminum</text>

<!-- body: left, right, front -->
<polygon points="{pts((0,0,0),(0,D,0),(0,D,H),(0,0,ZF))}" fill="#2273ad" stroke="#0e2a3d" stroke-width="2"/>
<polygon points="{pts((W,0,0),(W,D,0),(W,D,H),(W,0,ZF))}" fill="#1a5a88" stroke="#0e2a3d" stroke-width="2"/>
<polygon points="{pts((0,0,0),(W,0,0),(W,0,ZF),(0,0,ZF))}" fill="#174c73" stroke="#0e2a3d" stroke-width="2"/>
<!-- sloped black top -->
<polygon points="{pts((0,0,ZF),(W,0,ZF),(W,D,H),(0,D,H))}" fill="#14161a" stroke="#000" stroke-width="2"/>

<!-- touchscreen with live BatterBox UI -->
<polygon points="{pts(*scorners)}" fill="#000" stroke="#333" stroke-width="3"/>
<image xlink:href="data:image/png;base64,{img64}" width="1024" height="600"
       transform="{mat}" preserveAspectRatio="none"/>
{buttons}

<!-- callouts -->
<line x1="{sc[3][0]:.1f}" y1="{sc[3][1]:.1f}" x2="-330" y2="-120" class="lead"/>
<text x="-590" y="-128" class="cl">10.1″ touchscreen — kiosk UI (O/D/H)</text>
<line x1="{iso(228,34,ztop(34))[0]:.1f}" y1="{iso(228,34,ztop(34))[1]:.1f}" x2="300" y2="120" class="lead"/>
<text x="305" y="112" class="cl">jumbo arcade buttons → GPIO</text>
{dim_line((0,0,0),(W,0,0),'254 mm (10″)',(0,52))}
{dim_line((0,0,0),(0,D,0),'211 mm (8.3″)',(-70,26))}
{dim_line((W,D,0),(W,D,H),'76 mm (3″)',(86,-14))}
<line x1="{iso(0,0,ZF)[0]:.1f}" y1="{iso(0,0,ZF)[1]:.1f}" x2="-330" y2="40" class="lead"/>
<text x="-560" y="32" class="cl">15° sloped top panel</text>

<text x="0" y="330" class="s">inside: Raspberry Pi 4 + USB DAC (or BT speaker) · rear: power, 3.5 mm/HDMI audio, USB</text>
<text x="0" y="360" class="s">Wi-Fi hotspot or client · Bluetooth speaker pairing · GPIO buttons/LED on the header</text>
</svg>"""

open("../docs/enclosure/batterbox-enclosure-render.svg", "w", encoding="utf8").write(svg)
print("svg written")
