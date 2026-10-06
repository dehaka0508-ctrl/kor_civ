"""국기 문양 마스크·역사 국기 이미지를 만든다(개발용, 한 번 실행해서 결과 PNG를 저장소에 넣는다).

필요: pillow, cairosvg
  python tools/build_flag_assets.py --icons <game-icons 저장소> --deva-font <NotoSansDevanagari.ttf> \
      --samjogo <삼족오.png> --cheonma <천마도.png> --taegeukgi <태극기.png> --eogi <조선 어기.jpg> --goryeo <고려 의장기.jpg>

문양 마스크는 흰색 + 알파(512×512 안에 비율 유지)로 korciv/assets/emblems/ 에,
역사 국기는 korciv/assets/flags/ 에 저장한다.
"""
from __future__ import annotations

import argparse
import io
import math
import os

from PIL import Image, ImageChops, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EMB = os.path.join(ROOT, "korciv", "assets", "emblems")
FLG = os.path.join(ROOT, "korciv", "assets", "flags")
M = 512


def save_mask(alpha: Image.Image, name):
    """알파(L) → 내용 bbox 로 잘라 512 정사각형 가운데에 맞춰 흰색 RGBA 로 저장."""
    alpha = alpha.point(lambda v: 0 if v < 24 else v)
    box = alpha.getbbox()
    alpha = alpha.crop(box)
    w, h = alpha.size
    k = (M - 8) / max(w, h)
    alpha = alpha.resize((max(1, round(w * k)), max(1, round(h * k))), Image.LANCZOS)
    out = Image.new("L", (M, M), 0)
    out.paste(alpha, ((M - alpha.width) // 2, (M - alpha.height) // 2))
    img = Image.new("RGBA", (M, M), (255, 255, 255, 0))
    img.putalpha(out)
    img.save(os.path.join(EMB, name + ".png"), optimize=True)


def svg_alpha(path):
    import cairosvg
    png = cairosvg.svg2png(url=path, output_width=1024, output_height=1024)
    return Image.open(io.BytesIO(png)).convert("L")       # game-icons: 검은 배경 위 흰 그림


def pine_alpha():
    """휘어진 줄기 + 위가 둥글고 아래가 평평한 솔잎 덩어리(한국 소나무, 일월오봉도 풍)."""
    S = 1024
    im = Image.new("L", (S, S), 0)
    d = ImageDraw.Draw(im)

    def stroke(p0, p1, p2, w0, w1):
        for i in range(61):                  # 2차 베지어를 따라 두께가 줄어드는 원을 찍는다
            t = i / 60
            x = (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0]
            y = (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1]
            r = w0 + (w1 - w0) * t
            d.ellipse((x - r, y - r, x + r, y + r), fill=255)
    stroke((430, 1000), (640, 760), (470, 560), 62, 40)        # 줄기 아래
    stroke((470, 560), (330, 400), (520, 250), 40, 22)         # 줄기 위
    stroke((480, 600), (640, 560), (790, 600), 26, 14)         # 가지
    stroke((420, 470), (290, 470), (210, 500), 24, 12)
    stroke((470, 350), (620, 330), (700, 360), 20, 10)

    def clump(cx, cy, rw, rh):
        d.pieslice((cx - rw, cy - rh, cx + rw, cy + rh), 180, 360, fill=255)
        d.rectangle((cx - rw, cy - 1, cx + rw, cy + rh * 0.22), fill=255)
    for c in ((790, 590, 200, 120), (210, 495, 190, 110), (700, 355, 210, 125), (330, 300, 200, 120),
              (530, 200, 220, 140)):
        clump(*c)
    return im


def cloud_alpha():
    """전통 구름무늬(운문): 소용돌이 셋 + 길게 꼬리 끄는 두 줄. 선으로만 그린다."""
    S = 1024
    im = Image.new("L", (S, S), 0)
    d = ImageDraw.Draw(im)
    w = 22

    def dot(x, y):
        d.ellipse((x - w, y - w, x + w, y + w), fill=255)

    def spiral(cx, cy, r0, r1, a0, turns, sign=1):
        n = int(260 * turns)
        for i in range(n + 1):
            t = i / n
            r = r0 + (r1 - r0) * t
            a = a0 + sign * turns * 2 * math.pi * t
            dot(cx + r * math.cos(a), cy + r * math.sin(a))

    def bez(*p):
        for i in range(301):
            t = i / 300
            pts = list(p)
            while len(pts) > 1:
                pts = [((1 - t) * a[0] + t * b[0], (1 - t) * a[1] + t * b[1]) for a, b in zip(pts, pts[1:])]
            dot(*pts[0])
    spiral(520, 330, 125, 22, math.pi * 0.9, 1.5)           # 왼쪽 위 소용돌이
    spiral(770, 360, 150, 24, math.pi * 0.6, 1.55)           # 오른쪽 소용돌이
    spiral(610, 520, 120, 22, math.pi * 1.05, 1.5, sign=-1)   # 가운데 아래 소용돌이
    bez((60, 660), (240, 470), (390, 610), (490, 540))       # 꼬리 위 줄 → 가운데 소용돌이
    bez((60, 660), (300, 560), (420, 800), (680, 760), (900, 720), (940, 560), (900, 470))   # 꼬리 아래 줄 → 오른쪽
    return im


def main():
    ap = argparse.ArgumentParser()
    # 넘긴 입력만 다시 만든다(소나무·구름은 항상)
    for k in ("--icons", "--deva-font", "--samjogo", "--cheonma", "--taegeukgi", "--eogi", "--goryeo", "--dragon"):
        ap.add_argument(k)
    a = ap.parse_args()
    os.makedirs(EMB, exist_ok=True)
    os.makedirs(FLG, exist_ok=True)
    save_mask(pine_alpha(), "pine")
    save_mask(cloud_alpha(), "cloud")
    if a.icons:
        # game-icons (CC BY 3.0, Delapouite·Lorc)
        save_mask(svg_alpha(os.path.join(a.icons, "delapouite", "tiger-head.svg")), "tiger")
        if not a.dragon:
            save_mask(svg_alpha(os.path.join(a.icons, "lorc", "sea-dragon.svg")), "dragon")
    if a.dragon:
        # 밝은 바탕의 빨간 그림 → 붉을수록 불투명 (워터마크 없는 정식 이미지를 넣을 것)
        rr, gg, bb = Image.open(a.dragon).convert("RGB").split()
        red = ImageChops.subtract(rr, ImageChops.lighter(gg, bb))
        save_mask(red.point(lambda v: max(0, min(255, int((v - 60) * 255 / 80)))), "dragon")
    if a.deva_font:
        build_om(a.deva_font)
    if a.samjogo:
        # 삼족오: 빨간 바탕의 검은 그림 → 어두울수록 불투명
        r = Image.open(a.samjogo).convert("RGB").split()[0]
        save_mask(r.point(lambda v: max(0, min(255, int((170 - v) * 255 / 150)))), "samjogo")
    if a.cheonma:
        # 천마도: 흰 바탕의 검은 그림(아래쪽 출처 표기 줄은 제외)
        c = Image.open(a.cheonma).convert("L")
        c = c.crop((0, 0, c.width, int(c.height * 0.85)))
        save_mask(ImageChops.invert(c), "cheonma")
    # 역사 국기
    if a.taegeukgi:
        Image.open(a.taegeukgi).convert("RGB").save(os.path.join(FLG, "taegeukgi.png"), optimize=True)
    if a.eogi:
        e = Image.open(a.eogi).convert("RGB")
        e = e.crop((0, 0, e.width, 697))                       # 아래쪽 스크린샷 여백 제거
        e.resize((900, round(900 * e.height / e.width)), Image.LANCZOS).save(os.path.join(FLG, "eogi.png"), optimize=True)
    if a.goryeo:
        g = Image.open(a.goryeo).convert("RGB")
        g.resize((900, round(900 * g.height / g.width)), Image.LANCZOS).save(os.path.join(FLG, "goryeo.png"), optimize=True)


def build_om(font_path):
    """옴(ॐ): Noto Sans Devanagari(OFL) 굵게."""
    f = ImageFont.truetype(font_path, 800)
    try:
        f.set_variation_by_axes([800, 100])     # Weight, Width
    except Exception:
        pass
    im = Image.new("L", (1400, 1400), 0)
    ImageDraw.Draw(im).text((700, 700), "ॐ", font=f, fill=255, anchor="mm")
    save_mask(im, "om")


if __name__ == "__main__":
    main()
