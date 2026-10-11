"""칠지도·신라 금관 문양 마스크(assets/emblems/chiljido.png, crown.png)를 그린다: python tools/make_emblems.py korciv/assets/emblems"""
import math, sys
from PIL import Image, ImageDraw
S = 2  # 초벌 배율
def canvas(): 
    im = Image.new('L', (1000 * S, 1000 * S), 0); return im, ImageDraw.Draw(im)
def sc(p): return [(x * S, y * S) for x, y in p]
def circ(d, x, y, r): d.ellipse([(x - r) * S, (y - r) * S, (x + r) * S, (y + r) * S], fill=255)
def rect(d, x0, y0, x1, y1): d.rectangle([x0 * S, y0 * S, x1 * S, y1 * S], fill=255)
def thick(d, pts, w0, w1=None):
    w1 = w0 if w1 is None else w1
    n = len(pts) - 1
    for i in range(n):
        (ax, ay), (bx, by) = pts[i], pts[i + 1]
        wa = w0 + (w1 - w0) * i / n; wb = w0 + (w1 - w0) * (i + 1) / n
        dx, dy = bx - ax, by - ay; L = math.hypot(dx, dy) or 1
        px, py = -dy / L, dx / L
        d.polygon(sc([(ax + px * wa / 2, ay + py * wa / 2), (bx + px * wb / 2, by + py * wb / 2),
                      (bx - px * wb / 2, by - py * wb / 2), (ax - px * wa / 2, ay - py * wa / 2)]), fill=255)
        circ(d, bx, by, wb / 2)
def finish(im, path):
    im = im.resize((1000, 1000), Image.LANCZOS)
    bb = im.getbbox(); im = im.crop(bb); w, h = im.size; side = max(w, h) + 16
    c = Image.new('L', (side, side), 0); c.paste(im, ((side - w) // 2, (side - h) // 2))
    c = c.resize((512, 512), Image.LANCZOS)
    out = Image.new('RGBA', (512, 512), (255, 255, 255, 0)); out.putalpha(c); out.save(path)

def heart_up(d, x, y, r):
    """위로 뾰족한 잎(하트를 뒤집은 모양)."""
    circ(d, x - r * 0.55, y + r * 0.2, r * 0.62); circ(d, x + r * 0.55, y + r * 0.2, r * 0.62)
    d.polygon(sc([(x - r * 1.12, y + r * 0.05), (x, y - r * 1.25), (x + r * 1.12, y + r * 0.05), (x, y + r * 0.5)]), fill=255)

def crown(path):
    im, d = canvas()
    cx = 500
    # 맨 위 보주 잎
    heart_up(d, cx, 105, 78)
    rect(d, cx - 16, 120, cx + 16, 500)                       # 가운데 줄기
    tiers = (200, 300, 400)
    for y in tiers:
        rect(d, cx - 130, y, cx + 130, y + 22)                 # 가지(出자 가로)
    for sx in (-1, 1):
        for off in (65, 130):
            x = cx + sx * off
            rect(d, x - 11, 150, x + 11, 500)                  # 세로 가지
            for y in (150,) + tuple(t - 2 for t in tiers[:-1]):
                pass
        # 가지 끝 고리: 바깥쪽으로 말린 갈고리 + 둥근 구슬
        for off in (65, 130):
            x = cx + sx * off
            for y in (150, 250, 350):
                pts = [(x + sx * 0, y + 30)] + [(x + sx * (18 - 18 * math.cos(a)), y + 30 - 34 * math.sin(a))
                                                for a in [i * math.pi / 10 for i in range(11)]]
                thick(d, pts, 18)
                circ(d, x + sx * 36, y + 34, 15)
    rect(d, cx - 160, 495, cx + 160, 560)                      # 관테
    for k in range(7):                                          # 관테의 구슬 줄
        circ(d, cx - 135 + k * 45, 527, 0)
    # 드리개: 관테 아래로 늘어진 두 줄과 잎 장식
    for sx in (-1, 1):
        x = cx + sx * 95
        rect(d, x - 9, 560, x + 9, 950)
        for y in (620, 700, 780, 860):
            for s2 in (-1, 1):
                # 달개(잎): 줄기에서 비스듬히 위로 뻗은 물방울 잎
                lx, ly = x + s2 * 34, y - 6
                circ(d, lx, ly + 6, 19)
                d.polygon(sc([(lx - 18, ly + 2), (lx + s2 * 26, ly - 30), (lx + 18, ly + 2)]), fill=255)
                rect(d, min(x, lx), y + 2, max(x, lx), y + 8)
        heart_up(d, x, 955, 26)
    # 관테에 구멍 무늬(구슬 자리)
    for k in range(6):
        d.ellipse([(cx - 125 + k * 50 - 9) * S, (527 - 9) * S, (cx - 125 + k * 50 + 9) * S, (527 + 9) * S], fill=0)
    finish(im, path)

def chiljido(path):
    """칠지도(이소노카미 신궁 소장품 사진 비율): 곧은 칼날 + 좌우 번갈아 세 개씩 난 가지.
    가지는 칼날에서 바깥으로 살짝 처지며 나가 팔꿈치처럼 꺾인 뒤 칼날과 나란히 곧게 서고 끝이 둥글다."""
    im, d = canvas()
    cx, hw = 500, 25                       # 칼날 가운데·반폭
    # 칼날: 끝은 뭉툭하게 둥글고, 아래로 갈수록 아주 조금 넓어진다
    d.polygon(sc([(cx - hw + 4, 40), (cx + hw - 4, 40), (cx + hw + 3, 905), (cx - hw - 3, 905)]), fill=255)
    d.polygon(sc([(cx - hw + 4, 42), (cx - 8, 6), (cx + 8, 6), (cx + hw - 4, 42)]), fill=255)
    circ(d, cx, 14, 9)
    # 슴베: 어깨에서 좁아져 끝이 뾰족
    d.polygon(sc([(cx - 13, 900), (cx + 13, 900), (cx + 6, 975), (cx, 996), (cx - 6, 975)]), fill=255)
    # 가지: (방향, 갈라지는 높이, 끝 높이). 비스듬히 처지며 나가 둥글게 꺾이고, 끝은 살짝 바깥으로 기울며 가늘어진다
    for sx, j, tip in ((-1, 300, 205), (1, 395, 305), (-1, 485, 400), (1, 585, 520), (-1, 680, 600), (1, 765, 705)):
        p0, p1, p2 = (cx, j - 12), (cx + sx * 52, j + 34), (cx + sx * 74, j - 26)
        pts = []
        for k in range(13):                 # 팔꿈치: 2차 베지어
            t = k / 12
            pts.append(((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0],
                        (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1]))
        top = (cx + sx * 86, tip)
        pts += [(p2[0] + (top[0] - p2[0]) * k / 6, p2[1] + (top[1] - p2[1]) * k / 6) for k in range(1, 7)]
        thick(d, pts, 42, 24)
    finish(im, path)


crown(sys.argv[1] + '/crown.png'); chiljido(sys.argv[1] + '/chiljido.png')
