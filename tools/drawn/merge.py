"""Склейка двух правок одного кадра по вертикальному шву: слева первый файл, справа второй.
Правка FLUX «Keep image 1…» меняет и то, что не просили (у бабушки пропадали очки), —
удачную половину берём из правки, остальное из исходника. merge.py ЛЕВЫЙ ПРАВЫЙ X ШИРИНА_ШВА ВЫХОД"""
import sys
from PIL import Image, ImageDraw, ImageFilter
if sys.argv[1] == "--box":
    # merge.py --box ИСХОДНИК ПРАВКА X0 Y0 X1 Y1 ВЫХОД — из правки только прямоугольник, края размыты:
    # лишний кроссовок под столом 1-2 убирается, остальной кадр не трогается (25.09)
    base, fix = Image.open(sys.argv[2]).convert("RGB"), Image.open(sys.argv[3]).convert("RGB")
    box = [int(v) for v in sys.argv[4:8]]
    mask = Image.new("L", base.size, 0); ImageDraw.Draw(mask).rectangle(box, fill=255)
    Image.composite(fix, base, mask.filter(ImageFilter.GaussianBlur(12))).save(sys.argv[8]); sys.exit()
left, right = Image.open(sys.argv[1]).convert("RGB"), Image.open(sys.argv[2]).convert("RGB")
x, band = int(sys.argv[3]), int(sys.argv[4])
mask = Image.linear_gradient("L").rotate(90).resize((band, left.height))  # белое слева
full = Image.new("L", left.size, 0); full.paste(255, (0, 0, x, left.height)); full.paste(mask, (x, 0))
Image.composite(left, right, full).save(sys.argv[5])
