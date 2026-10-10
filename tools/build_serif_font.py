"""화면 장식용 한자 글꼴 만들기: theme.UI_HANJA 에 있는 한자만 Noto Serif KR Black 에서 뽑아
korciv/assets/fonts/NotoSerifKR-Hanja-Subset.otf 로 저장한다(나눔명조에 한자가 없어서).

사용: python3 tools/build_serif_font.py NotoSerifKR-Black.otf   (fonttools 필요)
원본 글꼴은 SIL Open Font License 1.1 (korciv/assets/fonts/LICENSE-NotoSerifKR.txt).
"""
import os
import sys

from fontTools import subset

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from korciv.ui.theme import UI_HANJA  # noqa: E402


def main(src):
    chars = sorted(set(UI_HANJA))
    out = os.path.join(ROOT, "korciv", "assets", "fonts", "NotoSerifKR-Hanja-Subset.otf")
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
