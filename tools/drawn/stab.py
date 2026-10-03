"""Снимает сдвиг камеры в клипе LTX без якоря конца: каждый кадр выравнивается по первому.

Без конечного якоря LTX ведёт камеру сам (к кадру 24 — на ~10 px), а владелец наезд
LTX запретил. Опора — неподвижные места клипа (малый разброс яркости по всем кадрам),
люди в неё не попадают; края, открытые сдвигом, берутся из первого кадра.
Запуск: python stab.py клип.mp4  (перезаписывает клип, звук LTX не нужен)
"""
import subprocess, sys, tempfile, os
import cv2, numpy as np

path = sys.argv[1]
cap = cv2.VideoCapture(path); fps = cap.get(cv2.CAP_PROP_FPS); frames = []
while True:
    ok, f = cap.read()
    if not ok: break
    frames.append(f)
gray = [cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255 for f in frames]
std = np.std(np.stack(gray), axis=0)
mask = (std < np.percentile(std, 40)).astype(np.uint8) * 255
h, w = gray[0].shape; out = [frames[0]]; M = np.eye(2, 3, dtype=np.float32)
crit = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 100, 1e-6)
for f, g in zip(frames[1:], gray[1:]):
    try:  # прошлый сдвиг — начальное приближение: камера ползёт плавно
        _, M = cv2.findTransformECC(gray[0], g, M, cv2.MOTION_AFFINE, crit, mask, 5)
    except cv2.error:
        pass
    warped = cv2.warpAffine(f, M, (w, h), flags=cv2.INTER_LINEAR + cv2.WARP_INVERSE_MAP)
    valid = cv2.warpAffine(np.full((h, w), 255, np.uint8), M, (w, h), flags=cv2.INTER_NEAREST + cv2.WARP_INVERSE_MAP)
    warped[valid == 0] = frames[0][valid == 0]; out.append(warped)
print(f"stab: последний сдвиг {M[0, 2]:+.1f} {M[1, 2]:+.1f} px, масштаб {np.sqrt(abs(np.linalg.det(M[:, :2]))):.3f}")
with tempfile.TemporaryDirectory() as tmp:
    for i, f in enumerate(out):
        cv2.imwrite(f"{tmp}/{i:04d}.png", f)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", str(fps), "-i", f"{tmp}/%04d.png",
                    "-c:v", "libx264", "-crf", "14", "-pix_fmt", "yuv420p", path + ".tmp.mp4"], check=True)
os.replace(path + ".tmp.mp4", path)
