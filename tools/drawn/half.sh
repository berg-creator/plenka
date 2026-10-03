#!/bin/zsh
# Вклейка правой части клипа поверх одобренного (владелец 26.09: спицы бабушки «в кашу», а мальчик уже одобрен):
# слева старый клип, справа новый, мягкий вертикальный шов. Оба клипа — с одного первого кадра, фон совпадает.
# half.sh СТАРЫЙ НОВЫЙ X0 X1 ВЫХОД — до X0 старый, после X1 новый, между — переход
set -e
old=$1 new=$2 x0=$3 x1=$4 out=$5
wh=$(ffprobe -v error -select_streams v -show_entries stream=width,height -of csv=s=x:p=0 $old)
n=$(ffprobe -v error -count_frames -select_streams v -show_entries stream=nb_read_frames -of csv=p=0 $old)
m=$(mktemp -d)/mask.png
~/.cache/imggen/.venv/bin/python -c "
from PIL import Image
w,h=map(int,'$wh'.split('x'))
m=Image.new('L',(w,h),0)  # линейный градиент PIL белый снизу; повёрнутый — белый слева, отражённый — справа
m.paste(Image.linear_gradient('L').rotate(90).transpose(Image.FLIP_LEFT_RIGHT).resize(($x1-$x0,h)),($x0,0))
m.paste(255,($x1,0,w,h)); m.save('$m')"
# маска с частотой клипа: по умолчанию -loop даёт 25 кадров/с против 24, и maskedmerge повторял 1-й и 25-й кадры,
# а два последних терял — заминка дважды за клип (27.09)
fps=$(ffprobe -v error -select_streams v -show_entries stream=r_frame_rate -of csv=p=0 $old)
ffmpeg -v error -y -i $old -i $new -loop 1 -framerate $fps -i $m -filter_complex \
  "[1]scale=${wh/x/:}[n];[0]format=gbrp[a];[n]format=gbrp[b];[2]format=gbrp[k];[a][b][k]maskedmerge,format=yuv420p" \
  -frames:v $n -c:v libx264 -crf 14 -an $out
