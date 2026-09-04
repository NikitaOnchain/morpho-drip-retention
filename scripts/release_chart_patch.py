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
