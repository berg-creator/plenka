# движение в области: средняя разница соседних кадров и отход от 0-го
import sys, subprocess, numpy as np
path, x0, y0, x1, y1 = sys.argv[1], *map(float, sys.argv[2:6])
w, h = 432, 768
raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vf", f"scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True).stdout
f = np.frombuffer(raw, np.uint8).reshape(-1, h, w).astype(float)[:, int(y0*h):int(y1*h), int(x0*w):int(x1*w)]
step = np.abs(np.diff(f, axis=0)).mean(axis=(1, 2))
drift = np.abs(f - f[0]).mean(axis=(1, 2))
print(f"{path.split('/')[-1]:22} шаг ср {step.mean():.2f} мин {step.min():.2f} | от 0-го макс {drift.max():.1f} | шаги по 6: " + " ".join(f"{s:.1f}" for s in step[::6]))
