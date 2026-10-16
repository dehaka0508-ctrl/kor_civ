"""시작 화면 로고 만들기: 한지 바탕 위에 그린 로고 그림(docs/logo_source.webp)에서 바탕 종이만 투명하게 뺀다.
korciv/assets/ui/logo.png(RGBA)로 저장한다. 밤하늘 배경 위에 얹으므로 아래 영문 부제(먹색)는 밝은 금색으로 바꾼다.

- 먹 번짐(어두운 덩어리)과 그 안에 둘러싸인 곳(꽃 문양 등)은 그대로 불투명
- 그 밖은 바탕 종이 색과의 거리로 투명도를 정하고, 반투명 가장자리는 종이 색을 걷어 낸다(흰 테두리 방지)

사용: python3 tools/build_logo.py [원본 그림] (numpy·scipy·Pillow 필요, 게임 실행에는 필요 없음)
"""
from __future__ import annotations

import os
import sys

import numpy as np
from PIL import Image
from scipy import ndimage

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "docs", "logo_source.webp")
OUT = os.path.join(ROOT, "korciv", "assets", "ui", "logo.png")
OUT_W = 1800                       # 저장 폭(큰 화면에서도 충분, 파일 크기 절약)
T0, T1 = 16.0, 40.0                # 종이 색과의 거리: T0 이하 투명, T1 이상 불투명
SUB_GOLD = (236, 214, 160)         # 영문 부제 색


def build(src_path=SRC, out_path=OUT):
    img = np.asarray(Image.open(src_path).convert("RGB")).astype(np.float32)
    h, w, _ = img.shape
    border = np.concatenate([img[:8].reshape(-1, 3), img[-8:].reshape(-1, 3),
                             img[:, :8].reshape(-1, 3), img[:, -8:].reshape(-1, 3)])
    paper = np.median(border, axis=0)
    dist = np.sqrt(((img - paper) ** 2).sum(axis=2))
    lum = img @ np.array([0.299, 0.587, 0.114], dtype=np.float32)

    # 먹 번짐 덩어리: 어두운 곳을 메우고 구멍을 채운 뒤 가장 큰 덩어리
    dark = ndimage.binary_closing(lum < 110, iterations=3)
    dark = ndimage.binary_fill_holes(dark)
    lab, n = ndimage.label(dark)
    sizes = ndimage.sum(dark, lab, range(1, n + 1))
    solid = lab == (1 + int(np.argmax(sizes)))
    solid = ndimage.binary_fill_holes(solid)

    alpha = np.clip((dist - T0) / (T1 - T0), 0.0, 1.0)
    alpha[solid] = 1.0
    # 종이 결(옅은 얼룩)만으로 된 조각은 지운다: 가장 진한 곳도 반투명인 덩어리
    lab, n = ndimage.label(alpha > 0)
    peak = ndimage.maximum(alpha, lab, range(1, n + 1))
    faint = np.concatenate([[False], np.asarray(peak) < 0.75])
    alpha[faint[lab]] = 0.0
    # 반투명 가장자리에서 종이 색 걷어 내기: C = a·F + (1 − a)·P → F
    a3 = np.maximum(alpha, 1e-3)[..., None]
    fg = np.clip((img - (1.0 - a3) * paper) / a3, 0, 255)
    fg[solid] = img[solid]

    # 먹 덩어리 아래(영문 부제 줄)는 밝은 금색으로
    rows = np.where(solid.any(axis=1))[0]
    y_sub = int(rows.max()) + 3
    band = np.zeros_like(solid)
    band[y_sub:] = True
    band &= ~solid
    sub_a = np.clip((paper @ np.array([0.299, 0.587, 0.114]) - lum - 18.0) / 90.0, 0.0, 1.0)   # 종이 결은 빼고 먹색만
    alpha[band] = sub_a[band]
    fg[band] = SUB_GOLD
    lab, n = ndimage.label(band & (alpha > 0))
    peak = ndimage.maximum(alpha, lab, range(1, n + 1))
    faint = np.concatenate([[False], np.asarray(peak) < 0.6])
    alpha[faint[lab]] = 0.0

    rgba = np.dstack([fg, alpha * 255.0]).round().astype(np.uint8)
    ys, xs = np.where(alpha > 0.03)
    pad = 6
    y0, y1 = max(0, ys.min() - pad), min(h, ys.max() + pad + 1)
    x0, x1 = max(0, xs.min() - pad), min(w, xs.max() + pad + 1)
    out = Image.fromarray(rgba[y0:y1, x0:x1], "RGBA")
    if out.width > OUT_W:
        out = out.resize((OUT_W, round(out.height * OUT_W / out.width)), Image.LANCZOS)
    out.save(out_path, optimize=True)
    print(f"saved {out_path} {out.size} (종이 색 {paper.round()}, 부제 시작 줄 {y_sub})")


if __name__ == "__main__":
    build(sys.argv[1] if len(sys.argv) > 1 else SRC)
