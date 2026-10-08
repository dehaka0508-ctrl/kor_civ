"""한자 보조 글꼴 만들기: 지도자 대사에 쓰인 한자만 Noto Sans CJK SC 에서 뽑아
korciv/assets/fonts/NotoSansCJKsc-Subset.otf 로 저장한다(Pretendard 에 한자가 없어서).

사용: python3 tools/build_cjk_font.py NotoSansCJKsc-Regular.otf   (fonttools 필요)
원본 글꼴은 SIL Open Font License 1.1 (korciv/assets/fonts/LICENSE-NotoSansCJK.txt).
"""
import json
import os
import sys

from fontTools import subset

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from korciv.ui.theme import is_cjk  # noqa: E402


def main(src):
    with open(os.path.join(ROOT, "korciv", "data", "leader_lines.json"), encoding="utf-8") as f:
        lines = json.load(f)
    chars = sorted({ch for d in lines.values() for v in d.values() for ch in str(v) if is_cjk(ch)})
    out = os.path.join(ROOT, "korciv", "assets", "fonts", "NotoSansCJKsc-Subset.otf")
    opts = subset.Options()
    opts.layout_features = ["*"]
    opts.hinting = False
    opts.name_IDs = ["*"]
    opts.notdef_outline = True
    font = subset.load_font(src, opts)
    sub = subset.Subsetter(opts)
    sub.populate(unicodes=[ord(c) for c in chars])
    sub.subset(font)
    subset.save_font(font, out, opts)
    print(f"한자 {len(chars)}자 → {out} ({os.path.getsize(out):,} bytes)")


if __name__ == "__main__":
    main(sys.argv[1])
