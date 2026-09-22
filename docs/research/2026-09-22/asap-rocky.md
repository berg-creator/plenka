# A$AP Rocky и soothe: чему учиться СКЛЕЙКЕ

Собрано 22.09.2026 после прослушки владельца: «саунд-дизайна мало, вообще будто нет —
поучись у A$AP Rocky» и «голос можно укладывать в бит технологией soothe». Общая
звукорежиссура рэпа — в соседнем [zvukorezhissura.md](zvukorezhissura.md); здесь только
команда Rocky, soothe и Trackspacer и перевод приёмов на ffmpeg.

Метки: **цитата** — дословно, сверено скриптом со скачанной страницей; **[субтитры]**
и **[Whisper]** (моя расшифровка звука) — с ошибками распознавания; **критик** — рецензент,
а не инженер; **толкование** — мой вывод.

## Главное

1. **Цифр от команды Rocky нет.** Delgado, Clams Casino, Mike Dean, Jim Jonsin в найденных
   интервью не назвали для голоса Rocky ни миллисекунд, ни герц, ни децибел, ни полутонов.
   Есть приёмы и плагины; числа ниже — из руководств, Википедии и моих замеров ffmpeg.
2. **Главный урок — движение, а не одна обработка на весь трек.** Delgado: «We wanted the
   beats to constantly move» (цитата). Толкование: разная цепочка на куплет, припев
   и концовку даст склейке больше, чем ещё один эффект на весь трек.
3. **Питч вниз — визитная карточка ранних вещей** (The Ringer; Википедия: «chopped and
   screwed choruses»). Скрю — пластинка, замедленная до 60–70 BPM, высота и темп падают
   вместе: `asetrate=44100*0.8,aresample=44100` (−3,9 полутона, темп ×0,8).
4. **Много ревера, «ugly on purpose»** — Delgado о голосе Rocky [Whisper]. Ревер у него
   стоковый D-Verb, у Mike Dean — D-Verb и H-Delay. Длину не называет никто.
5. **Грязь как приём:** искажённый голос в припеве «Goldie» (критик), 808 через ампсим
   в «L$D» (Jonsin), «Auto-Tune and distortion» у Mike Dean. В ffmpeg — `asoftclip`.
6. **Смена бита к концу трека** — «Playa», «Stay Here 4 Life», «D.M.B.», «Max B», «L$D».
   Второго бита ffmpeg не сочинит, но тот же бит замедлит, вырежет и уведёт под фильтр.
7. **Руководства:** Trackspacer — 32 полосы с обратной кривой по спектру ключа; soothe2 —
   до 60 дБ провала, soothe3 — до 40 дБ и Max cut; оба умеют M/S; миллисекунд нет.
8. **В ffmpeg проверено:** семь колоколов по середине бита с ключом от тех же полос голоса;
   без голоса выход равен входу, с голосом — −14 дБ в его полосе, бока и низ целы.

## 1. Кто реально записывал и сводил

- **LIVE.LOVE.A$AP** (2011): Ishlab Music Studio (Дамбо, Бруклин), инженеры Daniel Lynas
  и Frans Mernick, сводил Lynas. Биты — Clams Casino («Palace», «Bass», «Wassup», «Leaf»,
  «Demons»), A$AP Ty Beats («Peso», «Purple Swag: Chapter 2») и другие.
- **LONG.LIVE.A$AP** (2013): сводили Hector Delgado, Mike Dean, Todd Monfalcone, Noel
  Campbell, Robert Marks, Para One; мастеринг — Tom Coyne.
- **AT.LONG.LAST.A$AP** (2015): Delgado — инженер всего альбома, со-исполнительный продюсер,
  сведение и монтаж; Mernick — инженер и продюсер («Canal St.», «Better Things», «Dreams»,
  сопродюсер «Everyday»); Mike Dean — сведение, продюсер «M'$»; Kennie Takahashi —
  сведение; Nikolas Marzouca — инженер; мастеринг — Dave Kutch.
- **TESTING** (2018): запись и сведение — Delgado, кроме «Changes» (Tom Elmhirst);
  мастеринг — Tatsuya Sato.
- **Don't Be Dumb** (16.01.2026): сводили Mike Dean (треки 1–4, 6–8), Rob Kinelski (5, 10),
  Matt Scatchell (8); запись — Gosha Usov, Scatchell, Kelvin Krash и другие; мастеринг — Sato.
- **Joe Fitz и Kelvin Wooten** в кредитах этих пяти релизов (по Википедии) нет. Толкование:
  спутаны с Joe Fox (певец и гитарист на A.L.L.A.) и Kelvin Krash (TESTING, Don't Be Dumb).

## 2. Что они рассказали о саунд-дизайне

**Движение и переходы.**
- Delgado, Complex, 09.06.2015, цитата: «I worked on every record. So when songs go through
  all of those transitions that you hear, like on “Jukebox Joints” and all the endings,
  those are all things that I made.» И: «We wanted the beats to constantly move. The
  chopping up of beats, the effects, the warped sounds, all of that stuff.» Журналист там
  же: в «Max B» и «L$D» бит «switch up, slow down, and completely transform».
- Delgado, Kids Take Over, 2019 [субтитры]: «testing is like a movie bro is like every
  scene is supposed to look different and sound different». Pensado's Place #406
  [субтитры]: петля в четыре такта, старт сдвинут на такт — нарезка ложится на другую долю.
- Смена бита в конце «Playa» и «Stay Here 4 Life» (2026), во второй половине «D.M.B.»
  (2022) — «deeper experimental production» (Википедия со ссылками на критиков).
  Pitchfork о TESTING (критик): «mash sounds together and capture the friction».

**Питч и темп.**
- The Ringer, 29.10.2021, цитата: «The pitched-down vocals that became Rocky’s early calling
  card were directly influenced by ... DJ Screw». Википедия о «Purple Swag»: «heavy bass
  and slowed down vocals». Christgau (критик): «screwed-and-chopped alter ego».
- Скрю по Википедии: темп «down to 60 and 70 quarter-note beats per minute», пропуски
  долей, скретчи, stop-time. Толкование: бит 85–90 BPM, опущенный до 70, — это ×0,78–0,82,
  то есть −3,4…−4,3 полутона.
- Clams Casino, RBMA 2011, цитата о бите «Bass»: «I slowed it down again because Rocky likes
  everything really slow». Работал в Sony ACID Pro на ноутбуке.
- «Purity», Delgado [субтитры]: выступление Lauryn Hill из MTV Unplugged замедлили,
  «it's not even on the grid». Второй куплет «D.M.B.» — «pitched-up vocals» (Википедия);
  «Wild for the Night» — «pitch-shifted vocals» (NME, критик). Таймкодов не даёт никто.

**Ревер, дилей, плагины.**
- Delgado, The Chop Shop, 2023 [Whisper]: «the amount of reverb we had on rocky's vocals ...
  it was like ugly on purpose», «the mixes didn't sound normal». Kids Take Over [субтитры]:
  своё — «the effects we put on our record ... all the reverb on people's voices».
- Блиц Pensado's Place #406 [субтитры]: ревер — D-Verb; дилеи — «anything sound toys ... echo
  boy and crystallizer»; голос — bx_digital V2; шина — Shadow Hills; лимитер — Massey L2007
  («the hell 2007 the masse»). Подкаст Avid, 2022 [субтитры]: компрессор голоса — CL 1B.
- Mike Dean, Sound On Sound, 04.2022, цитата: «When I work on vocals, I use plug‑ins like the
  Avid D‑Verb and Waves H‑Delay.» Толкование: EchoBoy — эмуляция ленточного эха,
  Crystallizer — гранулярное эхо с реверсом и сдвигом высоты; настроек не назвал никто.

**Грязь и автотюн.**
- «Goldie», The Guardian, 18.04.2012 (критик): «distorting his vocal on the chorus so he
  sounds practically comatose»; под битом эхо, ревер и «distant chants».
- «L$D», Jim Jonsin, Complex, 23.05.2025, цитаты: «I asked Niko Marzouca to turn the autotune
  on crank» (о черновой мелодии) и «took my 808 drums and put them through this Fender guitar
  amp modeler in Logic to make it sound broken and dirty».
- Mike Dean, SOS, 2022: «the Heartbreak sound» — «Auto‑Tune and distortion»; на подпевках
  John Legend «we put Auto‑Tune on him, set to zero».

**Эдлибы и сэмплы.**
- Delgado, Complex, 2015: финал A.L.L.A. собран из эдлибов Yams — наложений к «Suddenly»;
  цитата: «I wanted the pause at the end to be longer, but the label was pushing for time.»
- Clams, RBMA, про «Leaf»: «Rocky’s engineer put in that ODB sample like the intro and the
  stuff at the end» — вступление и концовку дописал инженер, а не битмейкер.
- «Stole Ya Flow» (2026) — «echoed ad-libs» (Википедия). Флейта «Praise the Lord» — петля
  GarageBand «Andean Stroll Panpipe 02» (Википедия с пометкой «better source needed»).
- Delgado, подкаст Avid [субтитры]: «how to group effects to make a sound».

**Сведение.** Mike Dean, SOS, 2022, цитата: «Especially with the rap stuff, everybody has
very specific vocal effects, which are part of their sound, and you want to respect that.»
Толкование: эффекты, которые артист принёс в дорожке, склейке не снимать и не заливать своими.

**Чего не нашлось.** Статей о Rocky в Sound On Sound, Tape Op, Mix, MusicTech; разбора
сессий на Pensado's Place; интервью инженеров Don't Be Dumb; чисел и таймкодов; ни слова
о даблах, панораме, телефоне, реверсе. Флэнджер упоминает лишь студенческая рецензия
PantherNOW (2015): «reverb, flanger, and delays with his signature pitched-down vocals».
Pitchfork не открылся — его фразы взяты из Википедии. soothe команда Rocky не упоминает.

## 3. soothe и Trackspacer по руководствам

**soothe2** (oeksound).
- Приём из руководства, цитата: «carve out space for the vocals by using them as the
  sidechain key input for the rest of the material. You can combine the sidechain settings
  with the mid/side stereo mode to settle vocals in the stereo image.» С ключом «the
  reduction and visualization are based on the sidechained signal».
- Полосы: кривая чувствительности из «five bands» — low cut, high cut и четыре общих (пик,
  полки, band shelf, band reject, tilt). Кривая — «inverse EQ»: где поднято, режет сильнее.
- Depth — не децибелы, на максимуме «up to 60 dB notches»; по умолчанию режим soft, чисел
  по умолчанию нет. Атака и отпуск «displayed as a referential constant, while the actual
  response times are frequency-dependent», на верхах атака быстрее; миллисекунд нет.
- M/S или L/R; link 100 % — анализ по сумме и одна обработка на оба канала; balance
  сдвигает обработку к середине или бокам, и на каждой полосе. Delta — слушать вырезанное.
- Ключ должен приходить синхронно; задержка soothe2 около 45 мс (Sound On Sound, 02.2020).

**soothe3** добавил: «up to 40 dB notches»; Max cut — предел провала; tilt — отдельно ниже
~500 Гц и выше ~2 кГц, выкрученный low tilt атаки «slows down the attack fully for
frequencies below 300-400Hz»; режим низкой задержки — около 1 мс.

**Trackspacer 2.5.10** (руководство и страница Wavesfactory).
- «an intelligent 32-band EQ to subtract those frequencies from the track where Trackspacer
  is inserted»; Amount — «the negative gain of the filters»; Low-Cut и High-Cut сужают
  диапазон ключа, Freeze замораживает кривую в статичный EQ.
- Advanced: L/R или M/S; Pan ставит эффект на середину, бока «or anything in between»;
  Attack и Release — «in milliseconds», но ни значений по умолчанию, ни пределов нет.
- Сценарий из руководства: «Voice-over on top of the background music in a more musical way
  than having a full-band compressor»; страница: «Similar to a multiband sidechain compressor».

**Бас.** «Ниже 100 Гц не трогается» не обещает ни одно руководство. Толкование: низ цел, потому
что в ключе нет низа — голос в склейке срезан на 90 Гц (`HIGHPASS`), а полосы начинаются от 100 Гц.

**Как это сделать в ffmpeg** (ffmpeg 8.1.2; розовый шум и «голос» 1 кГц).
- Сейчас в `src/skleyka.py` один провал 2,8 кГц по середине, включаемый по времени голоса
  (`BEAT_EQ`, `_dip`). Замена: середина бита (M/S) → колокола 150, 300, 600, 1200, 2400,
  4800, 9600 Гц (через октаву, Q 1,41), ключ — те же полосы голоса.
- Колокол `x − (1−g)·BP(x)` — обычный пиковый эквалайзер с провалом: без голоса g = 1,
  выход бит в бит равен входу. Одна полоса:
  `[m1]bandpass=f=1200:t=q:w=1.41,asplit[p][q];[v1]bandpass=f=1200:t=q:w=1.41[k];`
  `[p][k]sidechaincompress=threshold=T:ratio=4:attack=5:release=120:mix=0.5[c];[q]volume=-1[n]`,
  затем `[m0][c1][n1]…[c7][n7]amix=inputs=15:normalize=0` — середина; бока не трогаются.
- `mix` — предел провала, как Max cut: 0,5 — −6 дБ, 0,75 — −12 дБ. Замер: без голоса
  разница −91 дБ; с голосом середина на 1 кГц −14 дБ (без `mix`), на 5 кГц −3 дБ, бока
  и низ ниже 80 Гц без изменений; шесть прогонов из шести.
- Грабли: `acrossover` с `sidechaincompress`, когда ключ тоже из `acrossover`, зависал
  в 3 прогонах из 6 даже на одной полосе и в один поток, с `bandpass` — ни разу;
  `amix=weights=1 -1` не вычитает (вес −0,5 звучит как 0,5) — вычитать `volume=-1`.
  В Actions ffmpeg 6.1 из apt — там не проверял.
- Толкование: порог `T` — от уровня полосы голоса при −18 LUFS; атака 5 мс и отпуск
  120 мс — мой выбор. Колокол 150 Гц задевает тело 808; бас худеет — начинать с 300 Гц.

## 4. Приёмы → ffmpeg

| Приём | Где у Rocky | ffmpeg | Итог |
|---|---|---|---|
| Скрю: высота и темп вниз | припевы LIVE.LOVE.A$AP, «Purple Swag» | `asetrate=44100*0.8,aresample=44100` (−3,9 пт, ×0,8) | умеет |
| Питч вниз без смены темпа | «alter ego» Lord Flacko (критик) | `rubberband=pitch=0.794` или `asetrate=44100*0.794,aresample=44100,atempo=1.26` | умеет |
| Питч вверх | второй куплет «D.M.B.» | `asetrate=44100*1.26,aresample=44100,atempo=0.794` | умеет |
| Замедлить бит | «Bass», «Purity» | хвост: `atrim=start=T,asetrate=44100*0.9,aresample=44100` (−1,8 пт) | только концовка: голос идёт в размер бита |
| Автотюн «на кране» | «L$D», «Heartbreak sound» | в самом ffmpeg нет; склейка уже грузит x42 fat1 через `lv2`, 0,02 с — самый быстрый | через плагин |
| Искажённый голос | припев «Goldie» | `highpass=f=300,lowpass=f=4500,volume=9dB,asoftclip=type=atan:oversample=4,volume=-9dB` | умеет, это `DIRT` |
| Ампсим на 808 | «L$D» | на низе бита `volume=12dB,asoftclip=type=tanh:oversample=4,volume=-12dB,lowpass=f=5000` | приближённо; кабинет — `afir` с импульсом |
| Много ревера | голос Rocky | `afir` с синтетическим импульсом, как `_reverb` склейки | умеет, длины у Rocky нет |
| Ленточное эхо (EchoBoy) | Delgado | `aecho=in_gain=1:out_gain=0.5:delays=Q\|2Q:decays=0.5\|0.25`, на мокром `lowpass=f=3000,vibrato=f=0.6:d=0.05` | приближённо |
| Crystallizer | Delgado | кусок: `areverse,rubberband=pitch=2,aecho=…,areverse` | гранулятора нет, только приближение |
| Фейзер, флэнджер | рецензия PantherNOW | `aphaser=in_gain=0.8:out_gain=0.9:delay=3:decay=0.5:speed=0.3:type=t`, `flanger=delay=2:depth=3:regen=40:speed=0.25` | умеет |
| Телефон | не найден | `highpass=f=250,highpass=f=250,lowpass=f=2000,lowpass=f=2000` | умеет |
| Реверс | не найден | `areverse` → ревер → `areverse` (вдох склейки) | умеет |
| Вырез бита перед строкой | переходы Delgado | на бите `volume=enable='between(t,T1,T2)':volume=0` | умеет |
| Бит под фильтром | переходы | `lowpass@f=f=20000` с командами `asendcmd` (вступление склейки) | умеет |
| Остановка плёнки | — | куски с падающим `asetrate` или `rubberband` с командами `tempo` и `pitch` | умеет |
| Заикание куска | нарезка Delgado | `aloop=loop=3:size=<1/16 в отсчётах>:start=<отсчёт>` | умеет |
| Смена бита на другой | «Playa», «Stay Here 4 Life» | второй бит не сочинить; тот же — медленнее, без верха, один бас | частично |
| Эхо на эдлибах, фраза в конце | «Stole Ya Flow», финал A.L.L.A. | `aecho` на фразе; `atrim,adelay` и `amix` | нужна разметка эдлибов |
| Даблы, панорама | данных нет | `adelay`, `haas`; числа — в соседнем отчёте | у Rocky цифр нет |
| Место голосу по ключу | у Rocky нет | колокола из раздела 3 | умеет, проверено |

Строки, кроме `rubberband`, `lv2` и `afir`, прогнаны на ffmpeg 8.1.2. `rubberband` в Homebrew нет,
в Actions есть (`libavfilter9` в Ubuntu 24.04 зависит от `librubberband2`), для голоса без «мультяшности» — `formant=preserved`.

## Источники

- Complex, B. Padilla, 09.06.2015 — https://www.complex.com/music/2015/06/hector-delgado-asap-rocky-alla-producer-interview
- Complex, M. Hellerbach, 23.05.2025 — https://www.complex.com/music/a/m-hellerbach/asap-rocky-at-long-last-asap-album
- YouTube: Pensado's Place #406, 08.03.2019 — https://www.youtube.com/watch?v=aE60s0wwsxM ;
  Kids Take Over, 10.08.2019 — https://www.youtube.com/watch?v=G8Dbp2gQXi8 ; That Sounds Great
  (Avid), 14.04.2022 — https://www.youtube.com/watch?v=-V0KevsukeE ; The Chop Shop, эп. 3,
  19.03.2023 — https://www.youtube.com/watch?v=YjaNdGLlgzk
- RBMA, лекция Clams Casino, 2011 — https://www.redbullmusicacademy.com/lectures/clams-casino/
- Billboard, 28.08.2024 — https://www.billboard.com/music/rb-hip-hop/clams-casino-the-kid-laroi-nights-like-this-asap-rocky-1235761705/
- Sound On Sound, P. Tingen, 04.2022 — https://www.soundonsound.com/people/mike-dean
- The Guardian, 18.04.2012 — https://www.theguardian.com/music/musicblog/2012/apr/18/asap-rocky-goldie
- The Ringer, 29.10.2021 — https://www.theringer.com/2021/10/29/music/asap-rocky-live-love-asap-mixtape-anniversary-streaming-spotify
- PantherNOW, 27.05.2015 — https://panthernow.com/2015/05/27/album-review-aap-rocky-at-long-last-aap/
- Википедия (en.wikipedia.org/wiki/…): Live._Love._ASAP, Long._Live._ASAP, At._Long._Last._ASAP,
  Testing_(album), Don't_Be_Dumb, Purple_Swag, Chopped_and_screwed, D.M.B., Playa_(ASAP_Rocky_song),
  Stay_Here_4_Life, Stole_Ya_Flow, Wild_for_the_Night, Praise_the_Lord_(Da_Shine)
- oeksound: https://oeksound.com/manuals/soothe2/ , https://oeksound.com/manuals/soothe3/ ;
  Sound On Sound, S. Inglis, 02.2020 — https://www.soundonsound.com/reviews/oeksound-soothe-2
- Wavesfactory: https://www.wavesfactory.com/audio-plugins/manuals/Trackspacer-User-Manual.pdf , https://www.wavesfactory.com/audio-plugins/trackspacer/
- FFmpeg Filters — https://ffmpeg.org/ffmpeg-filters.html ; Ubuntu — https://packages.ubuntu.com/noble/libavfilter9
