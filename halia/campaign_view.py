"""Render a campaign's monitoring dashboard from campaign_metrics() output.

Self-contained HTML with hand-built SVG charts (no external libraries): KPI tiles, a
sales-over-time area chart, revenue-by-signal and revenue-by-grade bars, and a top-clients
table. Halia app look: light, squared (no rounded corners), brand green + gold.
"""
from __future__ import annotations

import html as _html


def _money(v) -> str:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "£0"
    if abs(v) >= 1000:
        return "£" + f"{v/1000:.1f}k".replace(".0k", "k")
    return "£" + f"{v:,.0f}"


def _e(s) -> str:
    return _html.escape(str(s if s is not None else ""))


def _area_chart(series: list[dict], w: int = 720, h: int = 240) -> str:
    """Filled area + line of weekly revenue."""
    if not series:
        return '<div class="empty">No sales in this window yet.</div>'
    pad_l, pad_b, pad_t = 44, 26, 14
    vals = [p["value"] for p in series]
    vmax = max(vals) or 1
    n = len(series)
    iw, ih = w - pad_l - 12, h - pad_b - pad_t
    def x(i): return pad_l + (iw * (i / (n - 1)) if n > 1 else iw / 2)
    def y(v): return pad_t + ih - (ih * (v / vmax))
    pts = [(x(i), y(p["value"])) for i, p in enumerate(series)]
    line = " ".join(f"{'M' if i == 0 else 'L'}{px:.1f},{py:.1f}" for i, (px, py) in enumerate(pts))
    area = f"M{pts[0][0]:.1f},{pad_t+ih:.1f} " + \
        " ".join(f"L{px:.1f},{py:.1f}" for px, py in pts) + \
        f" L{pts[-1][0]:.1f},{pad_t+ih:.1f} Z"
    # y gridlines (0, mid, max)
    grid = ""
    for gv in (0, vmax / 2, vmax):
        gy = y(gv)
        grid += (f'<line x1="{pad_l}" y1="{gy:.1f}" x2="{w-12}" y2="{gy:.1f}" class="grid"/>'
                 f'<text x="{pad_l-8}" y="{gy+3:.1f}" class="ytick">{_money(gv)}</text>')
    dots = "".join(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="3" class="dot"/>' for px, py in pts)
    # x labels: first, middle, last week
    xlab = ""
    for i in (0, n // 2, n - 1):
        xlab += f'<text x="{x(i):.1f}" y="{h-8}" class="xtick">{_e(series[i]["week"][5:])}</text>'
    return (f'<svg viewBox="0 0 {w} {h}" class="chart" preserveAspectRatio="xMidYMid meet" role="img">'
            f'{grid}<path d="{area}" class="area"/><path d="{line}" class="line"/>{dots}{xlab}</svg>')


def _bars(items: list[dict], label_key: str, w: int = 340) -> str:
    if not items:
        return '<div class="empty">Nothing yet.</div>'
    vmax = max((it["value"] for it in items), default=1) or 1
    rows = ""
    for it in items[:8]:
        pct = max(2, round(100 * it["value"] / vmax))
        rows += (f'<div class="bar"><span class="bl">{_e(it[label_key])}</span>'
                 f'<span class="bt"><span class="bf" style="width:{pct}%"></span></span>'
                 f'<span class="bv">{_money(it["value"])}</span></div>')
    return f'<div class="bars">{rows}</div>'


def render_campaign(metrics: dict, *, demo: bool = False) -> str:
    k = metrics.get("kpis", {})
    banner = ('<div class="demo">Sample data. This is what a live campaign looks like.</div>'
              if demo else "")
    window = f'{_e(metrics.get("starts"))} to {_e(metrics.get("ends"))}'
    kpi = lambda v, l: f'<div class="kpi"><div class="kn">{v}</div><div class="kl">{l}</div></div>'
    conv = f'{round(k.get("conversion", 0)*100)}%'
    kpis = "".join([
        kpi(_money(k.get("revenue", 0)), "revenue in window"),
        kpi(f'{k.get("members", 0):,}', "in campaign"),
        kpi(f'{k.get("buyers", 0):,}', "bought"),
        kpi(conv, "conversion"),
        kpi(f'{k.get("orders", 0):,}', "orders"),
        kpi(_money(k.get("aov", 0)), "avg order"),
    ])
    top = "".join(
        f'<tr><td class="nm">{_e(r["name"])}</td><td><span class="pill">{_e(r["tier"])}</span></td>'
        f'<td class="num">{r["orders"]}</td><td class="num">{_money(r["revenue"])}</td></tr>'
        for r in metrics.get("top", [])
    ) or '<tr><td colspan="4" class="empty">No buyers yet.</td></tr>'
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Halia · Campaign · {_e(metrics.get("name"))}</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><text x='16' y='16' font-family='Georgia,serif' font-size='30' text-anchor='middle' dominant-baseline='central' fill='%231F564A'>&#8258;</text></svg>">
<style>
  :root{{--bg:#F2F1ED;--card:#fff;--ink:#1A1C22;--soft:#63676E;--faint:#8C9098;
    --brand:#1F564A;--brand-deep:#143A32;--gold:#A67C34;--line:#E4E2DB;--tint:#EAF0ED;
    --f:'Helvetica Neue',Helvetica,Arial,sans-serif}}
  *{{box-sizing:border-box;margin:0;padding:0}}
  html{{-webkit-print-color-adjust:exact;print-color-adjust:exact}}   /* keep brand colours + charts when printed */
  body{{background:var(--bg);color:var(--ink);font-family:var(--f);line-height:1.5;-webkit-font-smoothing:antialiased}}
  .wrap{{max-width:1080px;margin:0 auto;padding:0 24px}}
  .demo{{background:var(--brand);color:#fff;font-size:13px;text-align:center;padding:9px}}
  header{{border-bottom:1px solid var(--line);background:var(--card)}}
  header .bar{{display:flex;align-items:center;justify-content:space-between;height:60px}}
  .logo{{font-weight:700;font-size:18px;letter-spacing:-.01em}}
  .logo span{{color:var(--brand)}}
  h1{{font-size:clamp(22px,3vw,30px);font-weight:700;letter-spacing:-.02em;margin:30px 0 4px}}
  .sub{{color:var(--soft);font-size:14px;margin-bottom:26px}}
  .stats{{display:grid;grid-template-columns:repeat(6,1fr);border:1px solid var(--line);border-right:0;background:var(--card);margin-bottom:26px}}
  @media(max-width:760px){{.stats{{grid-template-columns:repeat(3,1fr)}}}}
  .kpi{{border-right:1px solid var(--line);padding:16px 18px}}
  .kn{{font-size:clamp(18px,2.4vw,26px);font-weight:700;letter-spacing:-.02em;font-variant-numeric:tabular-nums}}
  .kl{{font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--faint);margin-top:5px;line-height:1.3}}
  .panel{{background:var(--card);border:1px solid var(--line);padding:20px 22px;margin-bottom:22px}}
  .panel h2{{font-size:13px;letter-spacing:.1em;text-transform:uppercase;color:var(--soft);font-weight:700;margin-bottom:16px}}
  .cols{{display:grid;grid-template-columns:1fr 1fr;gap:22px}}
  @media(max-width:760px){{.cols{{grid-template-columns:1fr}}}}
  .chart{{width:100%;height:auto;display:block}}
  .chart .grid{{stroke:var(--line);stroke-width:1}}
  .chart .area{{fill:var(--tint)}}
  .chart .line{{fill:none;stroke:var(--brand);stroke-width:2.5}}
  .chart .dot{{fill:var(--brand)}}
  .chart .ytick{{fill:var(--faint);font:10px var(--f);text-anchor:end}}
  .chart .xtick{{fill:var(--faint);font:10px var(--f);text-anchor:middle}}
  .bars{{display:flex;flex-direction:column;gap:11px}}
  .bar{{display:grid;grid-template-columns:130px 1fr 62px;align-items:center;gap:10px;font-size:13px}}
  .bar .bl{{color:var(--ink);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
  .bar .bt{{background:var(--bg);height:14px;position:relative}}
  .bar .bf{{position:absolute;left:0;top:0;bottom:0;background:var(--brand)}}
  .bar .bv{{text-align:right;font-variant-numeric:tabular-nums;color:var(--soft)}}
  table{{width:100%;border-collapse:collapse;font-size:14px}}
  th{{text-align:left;font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:var(--faint);font-weight:700;padding:9px 12px;border-bottom:1px solid var(--line)}}
  th.num,td.num{{text-align:right;font-variant-numeric:tabular-nums}}
  td{{padding:12px;border-bottom:1px solid var(--line)}} td.nm{{font-weight:600}}
  .pill{{font-size:11px;font-weight:700;padding:2px 8px;border:1px solid var(--line);color:var(--brand)}}
  .winback{{display:flex;align-items:center;gap:18px;background:var(--brand);color:#fff;padding:18px 22px;margin-bottom:22px}}
  .winback .wb-n{{font-size:clamp(28px,4vw,40px);font-weight:700;letter-spacing:-.02em;font-variant-numeric:tabular-nums;line-height:1}}
  .winback .wb-t{{font-size:15px;font-weight:600}}
  .winback .wb-t span{{display:block;font-weight:400;opacity:.85;font-size:13.5px;margin-top:3px}}
  .winback .wb-t b{{font-weight:700}}
  .empty{{color:var(--faint);padding:26px;text-align:center}}
  footer{{color:var(--faint);font-size:12px;padding:24px 0 40px}}
  .pdfbtn{{border:1px solid var(--brand);background:var(--brand);color:#fff;font:600 13px var(--f);padding:9px 16px;cursor:pointer}}
  .pdfbtn:hover{{background:var(--brand-deep)}}
  @media print{{
    .pdfbtn,.demo{{display:none!important}}
    header{{border:none}} body{{background:#fff}}
    .panel,.stats,.winback,.cols>.panel{{break-inside:avoid}}
    @page{{margin:14mm}}
  }}
</style></head><body>
{banner}
<header><div class="wrap bar"><span class="logo">&#8258; Halia</span><button class="pdfbtn" onclick="window.print()">Save as PDF &darr;</button></div></header>
<div class="wrap">
  <h1>{_e(metrics.get("name"))}</h1>
  <div class="sub">{window}</div>
  <div class="stats">{kpis}</div>

  <div class="winback">
    <div class="wb-n">{k.get("reactivated", 0):,}</div>
    <div class="wb-t">clients came back from gone quiet<span>reactivated during the campaign, worth <b>{_money(k.get("reactivated_revenue", 0))}</b> recovered</span></div>
  </div>

  <div class="panel">
    <h2>Sales over time</h2>
    {_area_chart(metrics.get("series", []))}
  </div>

  <div class="cols">
    <div class="panel"><h2>Revenue by signal</h2>{_bars(metrics.get("by_signal", []), "label")}</div>
    <div class="panel"><h2>Revenue by grade</h2>{_bars(metrics.get("by_tier", []), "tier")}</div>
  </div>

  <div class="panel">
    <h2>Top clients in this campaign</h2>
    <table><thead><tr><th>Client</th><th>Grade</th><th class="num">Orders</th><th class="num">Revenue</th></tr></thead>
    <tbody>{top}</tbody></table>
  </div>
</div>
<footer><div class="wrap">Halia measures campaign sales live from your book and keeps nothing. Members are held as opaque ids only.</div></footer>
</body></html>"""
