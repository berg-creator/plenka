"""Замораживает низ клипа одним кадром: то, что в сцене не движется (ноги сидящих, пол),
LTX всё равно перерисовывает в каждом кадре, и носок ботинка «подлагивает» (владелец 25.09, 1-1).
freeze.py КЛИП ДОЛЯ_ВЫСОТЫ [КАДР] — всё ниже доли берётся из кадра КАДР (по умолчанию середина), шов мягкий."""
import subprocess, sys, tempfile
from pathlib import Path
from PIL import Image
clip, top = Path(sys.argv[1]), float(sys.argv[2])
frame = int(sys.argv[3]) if len(sys.argv) > 3 else 24
tmp = Path(tempfile.mkdtemp())
subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", clip, "-vf", f"select=eq(n\\,{frame})", "-frames:v", "1", tmp / "still.png"], check=True)
still = Image.open(tmp / "still.png").convert("RGB")
w, h = still.size; y, band = int(h * top), 48
mask = Image.new("L", (w, h), 0)
mask.paste(Image.linear_gradient("L").resize((w, band)), (0, y)); mask.paste(255, (0, y + band, w, h))
still.putalpha(mask); still.save(tmp / "top.png")
out = clip.with_name(clip.stem + "-frz.mp4")
subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", clip, "-loop", "1", "-i", tmp / "top.png", "-filter_complex",
                "[0][1]overlay=shortest=1:format=auto", "-c:v", "libx264", "-crf", "14", "-pix_fmt", "yuv420p", "-an", out], check=True)
print(out)
