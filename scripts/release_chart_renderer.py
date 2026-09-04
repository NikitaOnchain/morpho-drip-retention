"""Generated CSV-only renderer; original producer lineage is in derivative_manifest.json."""

from __future__ import annotations
import os
from pathlib import Path
from datetime import datetime
from typing import Any
from PIL import Image,ImageDraw,ImageFont
FIGURES = {}

USDC = "0xaf88d065e77c8cc2239327c5edb3a432268e5831"

USDT0 = "0xfd086bc7cd5c481dcc9c85ebe478a1c0b69fcbb9"

ARCHETYPES = {
    "early_shared_usdc": "0xd09404e9512e1341321c8ae3bd663fab7087582142ac61486635a6c072c2af12",
    "dedicated_syrupusdc": "0xf86f3edd6f16cd8211f4d206866dc4ecd41be6211063ac11f8508e1b7112ef40",
    "late_usdt0": "0x571cb3ac535d61d92026c071ef1df4794d0bbbe1755f916ff640746f81b52af4",
}

INK = "#17202A"

MUTED = "#667085"

GRID = "#E6E9EE"

BLUE = "#356AE6"

GOLD = "#D49A00"

ORANGE = "#DD6B20"

OLIVE = "#788C3A"

PINK = "#B74873"

LIGHT_BLUE = "#B9CDFB"

LIGHT_GOLD = "#F2D894"

WHITE = "#FFFFFF"

def text(draw: ImageDraw.ImageDraw, xy: tuple[float, float], value: str, size: int = 24, fill: str = INK, bold: bool = False, anchor: str | None = None) -> None:
    draw.text(xy, value, font=font(size, bold), fill=fill, anchor=anchor)

def human(value: float, decimals: int = 1) -> str:
    absolute = abs(value)
    if absolute >= 1_000_000_000:
        return f"{value / 1_000_000_000:.{decimals}f}B"
    if absolute >= 1_000_000:
        return f"{value / 1_000_000:.{decimals}f}M"
    if absolute >= 1_000:
        return f"{value / 1_000:.{decimals}f}K"
    return f"{value:.{decimals}f}"

def ratio_label(value: str) -> str:
    if not value:
        return "N/A"
    number = float(value)
    if abs(number) < 0.01:
        return f"{number:.2%}"
    return f"{number:.2f}×"

def parse_ts(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()

def canvas(title: str, subtitle: str, width: int = 1800, height: int = 1100) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (width, height), WHITE)
    draw = ImageDraw.Draw(image)
    text(draw, (80, 54), title, 38, bold=True)
    text(draw, (80, 108), subtitle, 22, fill=MUTED)
    return image, draw

def axes(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], ymin: float, ymax: float, y_label: str, ticks: int = 4) -> None:
    left, top, right, bottom = box
    draw.line((left, top, left, bottom), fill=INK, width=2)
    draw.line((left, bottom, right, bottom), fill=INK, width=2)
    for i in range(ticks + 1):
        y = bottom - (bottom - top) * i / ticks
        value = ymin + (ymax - ymin) * i / ticks
        draw.line((left, y, right, y), fill=GRID, width=1)
        text(draw, (left - 14, y), human(value), 18, fill=MUTED, anchor="rm")
    text(draw, (left, top - 20), y_label, 19, fill=MUTED)

def save_png(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    image.save(part, format="PNG", optimize=True)
    os.replace(part, path)

def chart_borrowed_series(series_rows: list[dict[str, Any]], portfolio_rows: list[dict[str, Any]]) -> None:
    image, draw = canvas(
        "Borrowed assets at exact aligned checkpoints",
        "Fixed 45-market panel; USDC and USD₮0 remain separate; state immediately before each 13:00 UTC boundary block",
        height=1250,
    )
    grouped = {(r["unit_address"], r["post_checkpoint"]): r for r in portfolio_rows if r["metric"] == "borrowed_assets"}
    for panel_index, (address, symbol) in enumerate([(USDC, "USDC"), (USDT0, "USD₮0")]):
        rows = [r for r in series_rows if r["metric"] == "borrowed_assets" and r["population_id"] == address]
        rows.sort(key=lambda r: r["target_timestamp_utc"])
        left, right = 160, 1700
        top = 210 + panel_index * 500
        bottom = top + 365
        values = [float(r["value_native"]) for r in rows]
        ymax = max(values) * 1.12 if max(values) else 1
        axes(draw, (left, top, right, bottom), 0, ymax, f"{symbol}, native tokens")
        xmin, xmax = parse_ts(rows[0]["target_timestamp_utc"]), parse_ts(rows[-1]["target_timestamp_utc"])
        points = []
        for row, value in zip(rows, values):
            x = left + (parse_ts(row["target_timestamp_utc"]) - xmin) / (xmax - xmin) * (right - left)
            y = bottom - value / ymax * (bottom - top)
            points.append((x, y))
        draw.line(points, fill=BLUE, width=5, joint="curve")
        end_row = grouped[(address, "p180")]
        peak_ts = end_row["campaign_peak_timestamp_utc"]
        key_ts = ["2025-09-03T13:00:00Z", "2026-02-18T13:00:00Z", "2026-03-20T13:00:00Z", "2026-05-19T13:00:00Z", "2026-08-17T13:00:00Z"]
        for ts in key_ts:
            x = left + (parse_ts(ts) - xmin) / (xmax - xmin) * (right - left)
            draw.line((x, top, x, bottom), fill="#9BA5B1", width=2)
        for row, value, point in zip(rows, values, points):
            if row["target_timestamp_utc"] in key_ts:
                draw.ellipse((point[0]-7, point[1]-7, point[0]+7, point[1]+7), fill=BLUE, outline=WHITE, width=2)
            if row["target_timestamp_utc"] == peak_ts:
                draw.ellipse((point[0]-9, point[1]-9, point[0]+9, point[1]+9), fill=GOLD, outline=INK, width=2)
        text(draw, (left, top - 54), f"{symbol} ({32 if address == USDC else 13} markets)", 27, bold=True)
        labels = [("Sep 3", key_ts[0]), ("End", key_ts[1]), ("+30", key_ts[2]), ("+90", key_ts[3]), ("+180", key_ts[4])]
        for label, ts in labels:
            x = left + (parse_ts(ts) - xmin) / (xmax - xmin) * (right - left)
            text(draw, (x, bottom + 18), label, 17, fill=MUTED, anchor="ma")
        text(draw, (right, top - 52), f"Peak {human(float(end_row['campaign_peak_native']))} on {peak_ts[:10]}", 20, fill=GOLD, anchor="ra")
    text(draw, (80, 1190), "Gold dot = campaign peak; blue checkpoint at End is the frozen primary denominator. Post points are +30/+90/+180 only.", 19, fill=MUTED)
    save_png(image, FIGURES["borrowed_checkpoint_series"])

def chart_retention(portfolio_rows: list[dict[str, Any]]) -> None:
    image, draw = canvas(
        "Primary retained uplift and campaign-peak sensitivity",
        "Borrowed assets; aggregate state first within each exact loan token; ratios are not clamped",
        height=1050,
    )
    for panel_index, (address, symbol) in enumerate([(USDC, "USDC"), (USDT0, "USD₮0")]):
        rows = [r for r in portfolio_rows if r["metric"] == "borrowed_assets" and r["scope_id"] == address]
        rows.sort(key=lambda r: ["p30", "p90", "p180"].index(r["post_checkpoint"]))
        primary = [float(r["primary_retained_uplift"]) for r in rows]
        peak = [float(r["peak_retained_uplift"]) for r in rows]
        all_values = primary + peak + [0]
        ymin = min(0, min(all_values))
        ymax = max(1, max(all_values))
        pad = max(0.15, (ymax - ymin) * 0.15)
        ymin -= pad if ymin < 0 else 0
        ymax += pad
        left = 160 + panel_index * 820
        right = left + 650
        top, bottom = 230, 780
        axes(draw, (left, top, right, bottom), ymin, ymax, "retained uplift ratio")
        zero_y = bottom - (0 - ymin) / (ymax - ymin) * (bottom - top)
        draw.line((left, zero_y, right, zero_y), fill=INK, width=2)
        for idx, label in enumerate(["+30", "+90", "+180"]):
            center = left + (idx + 0.5) * (right - left) / 3
            for offset, value, color, series in [(-45, primary[idx], BLUE, "End"), (45, peak[idx], GOLD, "Peak")]:
                y = bottom - (value - ymin) / (ymax - ymin) * (bottom - top)
                bar_left, bar_right = center + offset - 28, center + offset + 28
                draw.rectangle((bar_left, min(zero_y, y), bar_right, max(zero_y, y)), fill=color)
                text(draw, (center + offset, y - 11 if value >= 0 else y + 11), f"{value:.2f}×", 18, fill=INK, bold=True, anchor="mb" if value >= 0 else "ma")
            text(draw, (center, bottom + 22), label, 19, fill=MUTED, anchor="ma")
        text(draw, (left, top - 55), f"{symbol}", 28, bold=True)
    draw.rectangle((650, 885, 680, 910), fill=BLUE)
    text(draw, (694, 897), "Primary: campaign-end uplift", 20, anchor="lm")
    draw.rectangle((1030, 885, 1060, 910), fill=GOLD)
    text(draw, (1074, 897), "Sensitivity: campaign peak uplift", 20, anchor="lm")
    save_png(image, FIGURES["retained_uplift"])

def chart_flow_decomposition(flow_rows: list[dict[str, Any]]) -> None:
    image, draw = canvas(
        "Debt change components by exact loan token",
        "Gross Borrow and interest add debt; Repay, liquidation repayment and bad debt reduce it; native tokens, no USD conversion",
        height=1250,
    )
    components = [
        ("borrow_assets_out_native", "Borrow", BLUE, 1),
        ("accrued_interest_assets_native", "Interest", GOLD, 1),
        ("repay_assets_in_native", "Repay", ORANGE, -1),
        ("liquidation_repaid_assets_native", "Liq. repay", PINK, -1),
        ("liquidation_bad_debt_assets_native", "Bad debt", OLIVE, -1),
    ]
    for panel_index, (address, symbol) in enumerate([(USDC, "USDC"), (USDT0, "USD₮0")]):
        rows = [r for r in flow_rows if r["scope_type"] == "exact_loan_asset_group" and r["loan_address"] == address]
        rows.sort(key=lambda r: ["baseline", "incentive", "post_180"].index(r["period"]))
        signed = [[float(r[field]) * sign for field, _, _, sign in components] for r in rows]
        limit = max(abs(value) for group in signed for value in group) * 1.18 or 1
        left, right = 170, 1700
        top = 220 + panel_index * 470
        bottom = top + 330
        axes(draw, (left, top, right, bottom), -limit, limit, f"{symbol}, native tokens")
        zero_y = bottom - (0 + limit) / (2 * limit) * (bottom - top)
        draw.line((left, zero_y, right, zero_y), fill=INK, width=2)
        group_width = (right - left) / 3
        bar_w = 34
        for gi, (row, values) in enumerate(zip(rows, signed)):
            center = left + (gi + 0.5) * group_width
            for ci, value in enumerate(values):
                x = center + (ci - 2) * 54
                y = bottom - (value + limit) / (2 * limit) * (bottom - top)
                draw.rectangle((x - bar_w/2, min(y, zero_y), x + bar_w/2, max(y, zero_y)), fill=components[ci][2])
            observed = float(row["observed_debt_delta_native"])
            oy = bottom - (observed + limit) / (2 * limit) * (bottom - top)
            draw.polygon([(center+155, oy-9), (center+164, oy), (center+155, oy+9), (center+146, oy)], fill=INK)
            text(draw, (center, bottom + 18), {"baseline":"Baseline", "incentive":"Incentive", "post_180":"Post 180d"}[row["period"]], 18, fill=MUTED, anchor="ma")
        text(draw, (left, top - 50), f"{symbol}", 27, bold=True)
        incentive = next(r for r in rows if r["period"] == "incentive")
        post = next(r for r in rows if r["period"] == "post_180")
        text(
            draw,
            (right, top - 48),
            f"Incentive: interest {human(float(incentive['accrued_interest_assets_native']), 2)}, debt Δ {human(float(incentive['observed_debt_delta_native']), 2)}  ·  "
            f"Post: interest {human(float(post['accrued_interest_assets_native']), 2)}, debt Δ {human(float(post['observed_debt_delta_native']), 2)}",
            18,
            fill=MUTED,
            anchor="ra",
        )
    legend_x = 230
    for field, label, color, sign in components:
        draw.rectangle((legend_x, 1165, legend_x + 24, 1188), fill=color)
        text(draw, (legend_x + 34, 1177), ("+ " if sign > 0 else "− ") + label, 17, anchor="lm")
        legend_x += 225
    draw.polygon([(legend_x, 1165), (legend_x+10, 1175), (legend_x, 1185), (legend_x-10, 1175)], fill=INK)
    text(draw, (legend_x + 20, 1177), "Observed debt change", 17, anchor="lm")
    save_png(image, FIGURES["flow_decomposition"])

def chart_concentration(concentration_rows: list[dict[str, Any]]) -> None:
    image, draw = canvas(
        "Market concentration within each exact loan token",
        "Top eight markets ranked by +180 borrowed assets; bars compare campaign end and +180 shares of the same-token total",
        height=1300,
    )
    for panel_index, (address, symbol) in enumerate([(USDC, "USDC"), (USDT0, "USD₮0")]):
        p180 = [r for r in concentration_rows if r["loan_address"] == address and r["checkpoint"] == "p180"][:8]
        market_ids = [r["market_id"] for r in p180]
        end_map = {r["market_id"]: r for r in concentration_rows if r["loan_address"] == address and r["checkpoint"] == "campaign_end"}
        left, right = 500, 1680
        top = 220 + panel_index * 500
        bottom = top + 400
        draw.line((left, top, left, bottom), fill=INK, width=2)
        draw.line((left, bottom, right, bottom), fill=INK, width=2)
        for tick in range(5):
            share_tick = tick / 4
            x = left + share_tick * (right-left)
            draw.line((x, top, x, bottom), fill=GRID, width=1)
            text(draw, (x, bottom + 14), f"{share_tick:.0%}", 16, fill=MUTED, anchor="ma")
        text(draw, (left, top - 18), "share of exact-token borrowed assets", 19, fill=MUTED)
        row_h = (bottom - top) / 8
        for idx, p_row in enumerate(p180):
            y = top + (idx + 0.5) * row_h
            end_share = float(end_map[p_row["market_id"]]["share_of_exact_loan_total"])
            p_share = float(p_row["share_of_exact_loan_total"])
            draw.line((left, y - 8, left + end_share * (right-left), y - 8), fill=LIGHT_GOLD, width=12)
            draw.line((left, y + 8, left + p_share * (right-left), y + 8), fill=BLUE, width=12)
            label = f"{p_row['collateral_symbol']} · {p_row['market_id'][2:8]}"
            text(draw, (left - 18, y), label, 18, fill=INK, anchor="rm")
            text(draw, (left + p_share * (right-left) + 12, y + 8), f"{p_share:.1%}", 16, fill=BLUE, anchor="lm")
            if end_share >= 0.015:
                text(draw, (left + end_share * (right-left) + 12, y - 8), f"{end_share:.1%}", 15, fill="#9A7200", anchor="lm")
        text(draw, (left, top - 55), f"{symbol} ({32 if address == USDC else 13} markets)", 27, bold=True)
    draw.rectangle((700, 1210, 730, 1225), fill=LIGHT_GOLD)
    text(draw, (742, 1218), "Campaign end", 18, anchor="lm")
    draw.rectangle((980, 1210, 1010, 1225), fill=BLUE)
    text(draw, (1022, 1218), "+180", 18, anchor="lm")
    save_png(image, FIGURES["market_concentration"])

def chart_archetypes(series_rows: list[dict[str, Any]], market_rows: list[dict[str, Any]]) -> None:
    image, draw = canvas(
        "Borrowed assets and collateral for the three frozen archetypes",
        "Each panel uses its own native token and y-scale; no heterogeneous assets are added",
        width=2000,
        height=1700,
    )
    titles = {
        "early_shared_usdc": "Early shared USDC · weETH collateral",
        "dedicated_syrupusdc": "Dedicated syrupUSDC · USDC loan",
        "late_usdt0": "Late USD₮0 · syrupUSDC collateral",
    }
    text(draw, (550, 170), "Borrowed assets", 24, bold=True, anchor="ma")
    text(draw, (1510, 170), "Collateral", 24, bold=True, anchor="ma")
    for row_index, archetype in enumerate(ARCHETYPES):
        row_top = 245 + row_index * 455
        text(draw, (105, row_top - 48), titles[archetype], 25, bold=True)
        for column, metric in enumerate(["borrowed_assets", "collateral_assets"]):
            rows = [r for r in series_rows if r["population_type"] == "archetype_market" and r["population_id"] == archetype and r["metric"] == metric]
            rows.sort(key=lambda r: r["target_timestamp_utc"])
            left = 150 + column * 970
            right = left + 800
            top, bottom = row_top, row_top + 300
            values = [float(r["value_native"]) for r in rows]
            ymax = max(values) * 1.15 if max(values) else 1
            axes(draw, (left, top, right, bottom), 0, ymax, f"{rows[0]['unit_symbol']}, native tokens")
            xmin, xmax = parse_ts(rows[0]["target_timestamp_utc"]), parse_ts(rows[-1]["target_timestamp_utc"])
            points = []
            for row, value in zip(rows, values):
                x = left + (parse_ts(row["target_timestamp_utc"]) - xmin) / (xmax-xmin) * (right-left)
                y = bottom - value / ymax * (bottom-top)
                points.append((x, y))
            sparse_line(draw, rows, points, BLUE, 5)
            retained = next(r for r in market_rows if r["market_id"] == ARCHETYPES[archetype] and r["metric"] == metric and r["post_checkpoint"] == "p180")
            for ts, color in [(retained["campaign_peak_timestamp_utc"], GOLD), ("2026-02-18T13:00:00Z", BLUE), ("2026-08-17T13:00:00Z", PINK)]:
                match = next((point for series_row, point in zip(rows, points) if series_row["target_timestamp_utc"] == ts), None)
                if match:
                    draw.ellipse((match[0]-7,match[1]-7,match[0]+7,match[1]+7),fill=color,outline=INK,width=2)
            text(draw, (right, top - 26), f"+180 retained: {ratio_label(retained['primary_retained_uplift'])}", 17, fill=MUTED, anchor="ra")
            for label, ts in [("Sep 3","2025-09-03T13:00:00Z"),("End","2026-02-18T13:00:00Z"),("+30","2026-03-20T13:00:00Z"),("+90","2026-05-19T13:00:00Z"),("+180","2026-08-17T13:00:00Z")]:
                x = left + (parse_ts(ts)-xmin)/(xmax-xmin)*(right-left)
                draw.line((x,top,x,bottom),fill="#9BA5B1",width=2)
                text(draw,(x,bottom+14),label,15,fill=MUTED,anchor="ma")
    text(draw, (80, 1575), "Post: +30/+90/+180 markers only; intermediate trajectory not observed. No post connectors.", 22, fill=MUTED)
    text(draw, (80, 1640), "Gold = campaign peak; blue = campaign end; pink = +180. Selection was frozen before outcomes.", 19, fill=MUTED)
    save_png(image, FIGURES["archetypes"])

def chart_active_borrowers(series_rows: list[dict[str, Any]], portfolio_rows: list[dict[str, Any]]) -> None:
    image, draw = canvas(
        "Cross-sectional active borrowers at exact checkpoints",
        "Distinct wallets across 45 markets; primary requires ≥1 native loan token per position; shares-only line shows dust sensitivity",
        height=950,
    )
    primary = [r for r in series_rows if r["population_type"] == "fixed_program" and r["metric"] == "active_borrowers"]
    dust = [r for r in series_rows if r["population_type"] == "fixed_program" and r["metric"] == "active_borrowers_shares_only"]
    primary.sort(key=lambda r:r["target_timestamp_utc"])
    dust.sort(key=lambda r:r["target_timestamp_utc"])
    left, top, right, bottom = 160, 220, 1700, 730
    ymax = max(max(int(r["value_native"]) for r in primary), max(int(r["value_native"]) for r in dust)) * 1.12 or 1
    axes(draw,(left,top,right,bottom),0,ymax,"distinct wallets")
    xmin,xmax=parse_ts(primary[0]["target_timestamp_utc"]),parse_ts(primary[-1]["target_timestamp_utc"])
    point_maps: dict[str, dict[str, tuple[float, float]]] = {}
    for rows,color,width,name in [(dust,GOLD,4,"dust"),(primary,BLUE,6,"primary")]:
        points=[]
        for row in rows:
            x=left+(parse_ts(row["target_timestamp_utc"])-xmin)/(xmax-xmin)*(right-left)
            y=bottom-float(row["value_native"])/ymax*(bottom-top)
            points.append((x,y))
        sparse_line(draw, rows, points, color, width)
        point_maps[name] = {row["target_timestamp_utc"]: point for row,point in zip(rows,points)}
    for label,ts in [("Sep 3","2025-09-03T13:00:00Z"),("End","2026-02-18T13:00:00Z"),("+30","2026-03-20T13:00:00Z"),("+90","2026-05-19T13:00:00Z"),("+180","2026-08-17T13:00:00Z")]:
        x=left+(parse_ts(ts)-xmin)/(xmax-xmin)*(right-left)
        draw.line((x,top,x,bottom),fill="#9BA5B1",width=2)
        text(draw,(x,bottom+18),label,17,fill=MUTED,anchor="ma")
    retained=next(r for r in portfolio_rows if r["metric"]=="active_borrowers" and r["post_checkpoint"]=="p180")
    for ts,color in [(retained["campaign_peak_timestamp_utc"],GOLD),("2026-02-18T13:00:00Z",BLUE),("2026-08-17T13:00:00Z",PINK)]:
        point=point_maps["primary"][ts]
        draw.ellipse((point[0]-8,point[1]-8,point[0]+8,point[1]+8),fill=color,outline=INK,width=2)
    text(draw,(left,top-52),f"Primary +180 retained uplift: {ratio_label(retained['primary_retained_uplift'])}",22,bold=True)
    text(draw,(right,top-50),f"Peak {int(retained['campaign_peak_native']):,} on {retained['campaign_peak_timestamp_utc'][:10]} · End {int(retained['campaign_end_native']):,} · +180 {int(retained['post_value_native']):,}",18,fill=MUTED,anchor="ra")
    draw.line((620,840,680,840),fill=BLUE,width=6); text(draw,(695,840),"Primary material positions",19,anchor="lm")
    draw.line((1040,840,1100,840),fill=GOLD,width=5); text(draw,(1115,840),"Any positive borrow shares",19,anchor="lm")
    text(draw,(80,905),"Post: +30/+90/+180 markers only; intermediate trajectory not observed. No post connectors.",20,fill=MUTED)
    save_png(image, FIGURES["active_borrowers"])

def render_figures(series_rows: list[dict[str, Any]], market_rows: list[dict[str, Any]], portfolio_rows: list[dict[str, Any]], flow_rows: list[dict[str, Any]], concentration_rows: list[dict[str, Any]]) -> None:
    chart_borrowed_series(series_rows, portfolio_rows)
    chart_retention(portfolio_rows)
    chart_flow_decomposition(flow_rows)
    chart_concentration(concentration_rows)
    chart_archetypes(series_rows, market_rows)
    chart_active_borrowers(series_rows, portfolio_rows)
"""Presentation-only overrides for the generated standalone CSV renderer."""
import os
from pathlib import Path


def font_paths():
    folder = Path(os.environ['MORPHO_FONT_DIR']) if os.environ.get('MORPHO_FONT_DIR') else Path(os.environ.get('WINDIR',''))/'Fonts'
    return [folder/'segoeui.ttf',folder/'segoeuib.ttf']


def font_evidence():
    import hashlib
    return [{'filename':p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in font_paths() if p.is_file()]


def font(size, bold=False):
    path=font_paths()[int(bold)]
    if not path.is_file():
        raise RuntimeError('Exact PNG reproduction needs segoeui.ttf and segoeuib.ttf in MORPHO_FONT_DIR or the system Fonts folder; fonts are not distributed.')
    return ImageFont.truetype(str(path),size=size)


def sparse_line(draw, rows, points, color, width):
    """Dense baseline/campaign line ends at E. Post: three isolated markers."""
    end='2026-02-18T13:00:00Z'
    observed=[p for r,p in zip(rows,points) if r['target_timestamp_utc']<=end]
    draw.line(observed,fill=color,width=width)
    for r,p in zip(rows,points):
        if r['target_timestamp_utc']>end:
            draw.ellipse((p[0]-7,p[1]-7,p[0]+7,p[1]+7),fill=color,outline=INK,width=2)
