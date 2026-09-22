# Звукорежиссура рэп-сведения: чему СКЛЕЙКЕ учиться у лучших

Задача 58, шаг 1б, пункт 1. Дата сбора — 22.09.2026. Бот сводит две дорожки,
вокал и бит, на ffmpeg (src/skleyka.py); дальше будут райдер, стерео, стили,
саунд-дизайн и умный бот, которому человек объясняет желаемое словами. Здесь —
что делают инженеры, в цифрах, где они есть, и со ссылкой. Выжимка для бота —
prompts/skleyka.md.

## Как собрано и насколько верить

- **Sound On Sound, рубрики Inside Track и Secrets Of The Mix Engineers** —
  54 статьи о рэпе и соседнем R&B (2007–2026), прочитаны целиком. Почти все
  написал Paul Tingen со слов инженера; цитата — слова инженера.
- **Технические статьи SOS** (Майк Сениор: Mix Rescue, ответы Q&A, серии
  о ревербе и вокале; Paul White, Hugh Robjohns, Geoff Smith), **iZotope, Waves,
  MusicRadar** — около 110 страниц. «Mixing Secrets For The Small Studio»
  Сениора как книги в открытом доступе нет; его приёмы взяты из его же статей
  в SOS. Сайт cambridge-mt.com закрыт Cloudflare, его не обходили.
- **Интервью вне SOS**: лекции Red Bull Music Academy (Alex Tumay, Young Guru),
  RBMA Daily (Seth Firkins), Tape Op (Manny Marroquin, Just Blaze, Bob Power),
  ответы самих инженеров на форуме Mix With The Masters (Jaycen Joshua, Leslie
  Brathwaite, Bainz, Tom Elmhirst), XXL, The FADER, Billboard. Выпуски
  Pensado's Place и уроки Mix With The Masters — видео без текста и за
  подпиской; в отчёт вошли только страницы с текстом.
- **Автотюн**: руководства Antares (Auto-Tune Pro X 10.1, EFX+, Access, Artist),
  статьи SOS и MusicRadar.
- **Площадки**: справка Spotify, технический обзор Apple Digital Masters,
  рекомендации AES TD1008, замеры iZotope и Иэна Шеперда.
- **Словарь**: диссертация Brecht De Man (Queen Mary, 2017), где сведены
  частоты слов из десяти учебников сведения; SOS; случаи из интервью.
- **Русскоязычные звукорежиссёры**: в прессе о технике почти ничего. Цепочки
  дали видеоразборы на YouTube (Podlesny Twins, Палагин, KRUG и Soundlab) —
  цитаты оттуда из машинных субтитров, с ошибками распознавания, числа надо
  сверять на слух по таймкоду. Помечены **[субтитры]**.

Все цитаты сверены скриптом со скачанными страницами (символ в символ, до
типографских дефисов). «Цифры нет» значит: в источнике числа нет, «типичное»
не подставлялось. Mix Rescue и Inside Track — настройки для конкретной песни,
а не нормы.

## Главное для склейки

1. **Голос у рэп-инженеров громче бита или вровень, но на сколько дБ,
   не называет никто.** Ближе всех Kesha Lee (Lil Uzi Vert): бит всегда ниже
   на 1–2 дБ. Цель склейки 0 LU направлению не противоречит.
2. **Райдинг — главная ручная работа финального микса** (Kadish, Grandjean,
   Bolooki, Gibbs, Сениор). Размах: у Сениора фейдер ходил больше чем на 12 дБ,
   Marroquin поднимал сэмпл на 6–7 дБ на словах, Joshua — +1 дБ на подгруппу
   в припеве. Waves Vocal Rider по умолчанию −6…+6 дБ. Миллисекунд скорости
   не даёт никто.
3. **Дилей почти всегда в темп**: четверть — самый частый, восьмая — второй,
   половина — реже. Броски — отдельные слова в конце строки, 100 % мокрого
   сигнала, дилей прижат под голосом и звучит в паузах. У склейки в темп
   только «Мелодично»; «Чисто» и «Грязно» идут с короткими 120 и 240 мс,
   и дилей под голосом не прижат.
4. **Отзвука на рэп-голосе мало, он короткий, тёмный и с предзадержкой.**
   Future: комната 751 мс, предзадержка 15 мс, срез верха 9,36 кГц, 15 %.
   Рэп у Сениора: 0,2 с и 15 мс. Joshua: «reverb is the kiss of death on rap
   vocals». Нынешние 0,8 с и 25 мс — в этом ряду.
5. **Автотюн: 0 — «робот», 10–50 мс — естественно** (руководство Antares).
   У рэп-инженеров: 20 по умолчанию, 12–5 на просьбу «Give me more Auto-Tune!» (Lil Uzi Vert),
   11–13, иногда 2 или 7 (Chris Brown), 25 с Humanize 100 % — «not very noticeable»
   (DaBaby). Тональность важнее скорости: в неверной тональности автотюн
   звучит «confidently off» (Antares).
6. **Даблы-расширитель по Сениору**: две задержки 11 и 13 мс в разные края,
   ±5 центов, возврат на 15 дБ ниже голоса. Дабл склейки (18 и 25 мс, −10 дБ)
   на 5 дБ громче.
7. **Низ в моно** ниже 100–128 Гц (iZotope 125, Soundlab 128, Podlesny Twins
   «ниже сотки», SOS — около 100 Гц). У склейки 120 Гц — в ряду.
8. **Громкость мастера**: площадки приводят к −14 LUFS (Spotify, YouTube);
   хиты 2024 года — −8,3 ±1 LUFS (iZotope), рэп-инженеры −10…−6. Spotify
   просит пик не выше **−2 dBTP**, если мастер громче −14 LUFS; у склейки
   CEILING −1 — расхождение.
9. **Клиппер перед ограничителем — обычная практика хип-хопа** (Сениор:
   несколько дБ клиппинга и 4 дБ лимитинга). Шеперд: жёсткий цифровой
   клиппинг теряет больше всего низа, мягкий держит удар. У склейки клиппер
   жёсткий (asoftclip type=hard) — стоит проверить мягкий.
10. **Место голосу в бите — динамически и по полосе**, от голоса: Gibbs —
    провалы на 900 Гц и 2 кГц только пока поёт голос; Podlesny Twins — Soothe
    по частотам голоса около 1,5 кГц; Just Blaze — сжатие верха сэмпла ключом
    от голоса. Статичный провал бита на 2,8 кГц у склейки — упрощение.
11. **Клиент почти всегда хочет свой черновик, только бьёт сильнее, чище
    и громче**; слишком чисто — частая претензия. Отсюда правило для бота:
    менять мало и по просьбе.

## Сверка с src/skleyka.py

Сверено с рабочей копией на 22.09.2026, 15:30: в ней уже стоят райдер, стили,
дабл, саунд-дизайн и моно низа (шаги 2–5). В коммите d5dab9a было VOCAL_OVER_BEAT
−1 LU и провал бита −1,5 дБ на оба канала.

| Параметр | Сейчас | Что в источниках | Вывод |
|---|---|---|---|
| Срез низа голоса | 90 Гц | 50–100 Гц у рэперов: 69,8 (Mann), 70 (Young Guru), 70–80 (Davis), 80 (Pigliapoco, Bolooki), 84 (Marasciullo), 96,4 (Lee), 100 (LaRay), 69 и 98 (Сениор); 130–200 — Палагин [субтитры] | в ряду |
| Компрессия | 4:1, 1/60 мс + 3:1, 10/150 мс, 3–4 дБ постоянно; «Близко» — третья 6:1 | Сениор: быстрый 8:1, 2/10 мс на 3–6 дБ пиков, затем 3:1, 20/100 мс на 1–3 дБ, можно три ступени по 3–6 дБ; в общем 2:1–4:1, атака ~10 мс, отпуск 50–100 мс, до ~5 дБ, рэп выдерживает больше. DaBaby — CLA-76 на 3 дБ, Davis — 2–3 дБ, Podlesny — 5–6 дБ [субтитры] | в ряду |
| Де-эссер | последним, ffmpeg deesser | у мужского рэпа 4,2–6,5 кГц: 4230, 4270, 4398, 4500, 5424, 5506, 5634 Гц; часто два-три лёгких вместо одного сильного (McCloskey: один сильный даёт шепелявость) | порядок спорный: у многих до компрессора |
| Голос к биту | 0 LU | цифр нет; Lee: бит на 1–2 дБ ниже; Сениор: слишком громкий голос делает бит «маленьким» | в ряду |
| Райдер | только вверх, до +4 дБ, держит 0,5 с, сглажен на 1 с | Waves Vocal Rider: −6…+6 дБ, в паузах к середине диапазона; Сениор: фейдер ходит больше чем на 12 дБ, в обе стороны; скорость в мс не называет никто | в ряду; вниз райдер не ведёт — у инженеров ведут и вниз |
| Бит под голос | −2 дБ на 2,8 кГц только в середине, постоянно; сайдчейн 2:1 | Gibbs: провалы на 900 Гц и 2 кГц только пока звучит голос; Сениор: дакинг 1–3 дБ, 1,04:1 до 2 дБ; Just Blaze: только верх сэмпла ключом от голоса | провал стоит и в паузах голоса — у инженеров он динамический |
| Отзвук | «Чисто» 0,8 с / 7 %, «Мелодично» 2 с / 12 %, предзадержка 25 мс, 300–7000 Гц | Firkins: 751 мс, 15 мс, срез 9,36 кГц, 15 %; Сениор на рэпе: 0,2 с, 15 мс; длинный — с предзадержкой 30–70 мс и тише короткого (Сениор, Brathwaite); Joshua: на рэпе ревер — «kiss of death» | «Чисто» в ряду; 2 с для рэпа длинно, для пения обычно |
| Дилей | «коротко» 120/240 мс; «в темп» — слева пунктирная восьмая, справа четверть, по три повтора, 300–4000 Гц | четверть — главный вокальный (Firkins, Young Guru, LaRay, Hurtt), восьмая — второй; пунктир у Сениора (3/16 пинг-понг на вокал); прижат голосом и звучит в паузах (Bainz; Сениор: 2:1, атака 0, отпуск ~150 мс, 8–10 дБ) | в темп — в ряду; прижать голосом |
| Броски | каждое последнее слово строки перед паузой > 0,4 с, доля 0,4 | 3–4 места на трек (Profitt); Сениор ловит «the odd word at the ends of lines»; эффект на слове 100 % мокрый (iZotope, Bainz); Moneybagg Yo броски не выносит | у склейки бросков больше, чем у инженеров: ограничить числом |
| Дабл | копии 18 и 25 мс влево и вправо, плавание высоты, −10 дБ, срез 150 Гц | Сениор: 11 и 13 мс, ±5 центов, −15 дБ, и это, по его словам, больше обычного; Paul White: 20–40 мс, ±2–6 центов; срез слоёв 150–200 Гц (Paul White) | на 5 дБ громче, чем у Сениора |
| Вдох (реверс-отзвук) | 2,5 с, нарастает за 2 доли | Paul White: плита ~4 с, сдвиг на 2–3 с; MusicRadar: комната 1,5 с; «sparingly», во вступлении | в ряду |
| Фильтр во вступлении | до 400 Гц, 8 долей, открывается за 2 доли | Сениор: ФНЧ 400 Гц на басе в разреженном вступлении; Colmenero: закрыл быстро, открывал медленно | в ряду |
| Остановка плёнки | 2 доли в конце | чисел нет; Paul White: «popular (and sometimes overused)» | не противоречит |
| Моно низа | ниже 120 Гц | 100–128 Гц: iZotope 125, Soundlab 128, Podlesny Twins «ниже сотки», SOS ~100 | в ряду |
| Мастер | −10 LUFS | площадки −14; хиты −8,3 ±1; Jaycen −8…−6; Central Cee −7,5…−8; Pop Smoke −8; Trippie Redd −10; Шеперд ≤ −10 short-term | в ряду, на тихой стороне рэпа |
| Пик | −1 dBTP | Spotify: ≤ −2 dBTP, если громче −14 LUFS; AES: ≤ −1 dBTP на входе кодека, на низком битрейте ниже; склейка сама отдаёт MP3 | опустить до −2 |
| Клиппер | жёсткий (asoftclip type=hard), 2 дБ над порогом, 4× частота | Сениор: несколько дБ клиппинга перед 4 дБ лимитинга — обычно для хип-хопа; Шеперд: жёсткий — больше искажений и потеря низа, мягкий держит удар; Robjohns: цифровой клип даёт алиасинг, особенно на голосе; iZotope: жёстко — только миллисекунды, с передискретизацией | проверить мягкий тип на прослушке |

## 1. Цепочка вокала

**Срез низа.**
- Young Guru — Rihanna в «Run This Town» (SOS, 12.2009): де-эссер около 5 кГц,
  вырез около 9792 Гц, срез ниже 70 Гц.
  [SOS](https://www.soundonsound.com/techniques/secrets-mix-engineers-young-guru)
- Kevin Davis — Ne-Yo (SOS, 10.2008): «clean up the low end… say below 70-80Hz,
  because there's not a lot going on below that vocally».
  [SOS](https://www.soundonsound.com/techniques/secrets-mix-engineers-kevin-davis)
- Kesha Lee — Lil Uzi Vert (SOS, 12.2017): де-эссер около 4230 Гц, срез 96,4 Гц,
  вырезы «грязи» на 200 и 500 Гц.
  [SOS](https://www.soundonsound.com/techniques/inside-track-lil-uzi-vert)
- Tillie Mann — Lil Baby (SOS, 06.2020): срез 69,8 Гц, вырезы 184,7 и 425,2 Гц,
  подъём на 2 кГц и 5,37 кГц «because I wanted some more presence» (дБ не названы).
  [SOS](https://www.soundonsound.com/techniques/inside-track-lil-baby-sum-2-prove)
- Evan LaRay — Cardi B «Bodak Yellow» (SOS, 02.2018): срез около 100 Гц,
  −3 дБ на 300 Гц («muddy»), −3 дБ на 4 кГц («piercing»).
  [SOS](https://www.soundonsound.com/techniques/inside-track-cardi-b-bodak-yellow)
- Dylan «3D» Dresdow — Black Eyed Peas (SOS, 07.2009): «I rolled off everything
  below 50Hz, and sometimes as high as 100Hz»; срез первым, чтобы низ не гонял
  компрессор. [SOS](https://www.soundonsound.com/techniques/secrets-mix-engineers-dylan-3d-dresdow)
- Tom Elmhirst (форум MWTM, 14.11.2023): «lose below 80/90hz».
  [MWTM](https://community.mwtm.com/t/1275)
- Палагин — MORGENSHTERN «Sheikh» [субтитры]: вокал с ноутбука в необработанной
  комнате, низ срезан «до 130». [YouTube](https://www.youtube.com/watch?v=EZFuvSVw57A)

**Компрессия.**
- Mike Senior (SOS): последовательно — быстрый 8:1, атака 2 мс, отпуск 10 мс,
  3–6 дБ на пиках; затем около 3:1, атака 20 мс, отпуск 100 мс, максимум
  3–6 дБ, чаще 1–3. В общем случае 2:1–4:1, атака ~10 мс, отпуск 50–100 мс,
  не больше ~5 дБ на пиках; рэп и рок выдерживают больше. Статьи — в списке
  источников, раздел «Сениор».
- McCloskey — DaBaby «Intro» (SOS, 12.2019): «the Waves CLA76 knocking off 3dB
  to flatten peaks, as they did not track with a compressor».
  [SOS](https://www.soundonsound.com/techniques/inside-track-dababy-intro)
- Kevin Davis (SOS, 10.2008): быстрый на пики, потом аппаратный «slow attack,
  slow release and very minimal compression, 2-3dB max».
- Manny Marroquin — Kanye West «Stronger» (SOS, 12.2007): Neve 32264 3:1
  с быстрым восстановлением, затем CL1B 4:1 со средней атакой.
  [SOS](https://www.soundonsound.com/techniques/secrets-mix-engineers-manny-marroquin)
- Koen Heldens — Trippie Redd (SOS, 10.2023): параллельный CLA-76, средняя или
  медленная атака, самый быстрый отпуск, около −10 дБ; после него +4–5 дБ на
  100 Гц и срез выше ~5 кГц — «lifts the lead vocal nicely out of the mix».
  [SOS](https://www.soundonsound.com/techniques/inside-track-trippie-redd-love-letter-you-5)
- Clint Gibbs — Doja Cat (SOS, 07.2020): параллельная шина с 1176 на −20 дБ —
  «This is where I get my vocal loudness from».
  [SOS](https://www.soundonsound.com/techniques/inside-track-doja-cat-ft-nicki-minaj-say-so)
- Manon Grandjean — Dave (SOS, 06.2019): у рэпера громкость ровная, динамика
  на атаке согласных, поэтому компрессоры не давит: «you don't want to slam the
  compressors». [SOS](https://www.soundonsound.com/techniques/inside-track-dave-funky-friday-black)
- Podlesny Twins — BATO [субтитры]: «в хип-хопе… компрессировать нужно меньше»,
  иначе «кач пропал». 9mice — базовый компрессор «5-6 децибел».
  [YouTube](https://www.youtube.com/watch?v=TInq3SD4z9o),
  [YouTube](https://www.youtube.com/watch?v=Mk64EhVvppo)

**Де-эссер и порядок.**
- Частоты у мужского рэпа: 4230 Гц (Lee), 4270 и 4398 Гц (LaRay), 4500 и
  5424 Гц (Marasciullo: T-Pain и Flo Rida), 5506 Гц (Firkins, Future), 5634 Гц
  (Muzzy, Nicki Minaj), 6–7 кГц (Marroquin). Dresdow: у женщин около 8 кГц,
  у мужчин около 4 кГц.
- McCloskey (DaBaby): несколько лёгких де-эссеров вместо одного — «If you do too
  much de-essing with one de-esser it sounds like someone has a lisp».
- Порядок расходится: до компрессора — Bolooki («fix issues before you boost
  the whole track with a compressor»), McCloskey, Morris; после — Chhim, Gibbs.
  Firkins ставит де-эссер после подъёма верха, и тот срабатывает не чаще раза
  на 10 слов. [SOS](https://www.soundonsound.com/techniques/inside-track-future-draco)
- Bob Power — A Tribe Called Quest (Tape Op #60): «de-ess at 2 kHz and then
  again at 8 kHz». [Tape Op](https://tapeop.com/interviews/60/bob-power)

**Перегруз и «песок».**
- Chhim — 21 Savage (SOS, 03.2019): Avid Lo-Fi, разрядность 15 бит на шине
  голосов — «works like a form of compression, and makes the vocals a bit more
  up-front and louder»; приём Jaycen Joshua.
  [SOS](https://www.soundonsound.com/techniques/inside-track-21-savage)
- McCloskey — DaBaby: тот же Lo-Fi (15 бит, distortion 0.1, saturation 0.1),
  потому что бит перегружен: «The vocal would sound out of place if it sounded
  too clean».
- Bolooki — Lil Nas X (SOS, 08.2019): L2 бьёт сильно в конце каждой вокальной
  дорожки ради сатурации — «It was part of Nas' sound».
  [SOS](https://www.soundonsound.com/techniques/inside-track-lil-nas-x-ft-billy-ray-cyrus-old-town-road)
- Derek Ali — Kendrick Lamar (SOS, 06.2015): Distressor «adds some grit and
  presence at the top». [SOS](https://www.soundonsound.com/techniques/inside-track-kendrick-lamars-pimp-butterfly)
- Donoghue — Central Cee (SOS, 05.2022): звук дрилла — «not over‑polishing it,
  not over‑EQ’ing, and keeping the saturation».
  [SOS](https://www.soundonsound.com/techniques/inside-track-central-cee-straight-back-it)

## 2. Баланс голоса и бита, райдинг

- Kesha Lee — Lil Uzi Vert: «we like the vocals to be louder than the beat.
  I always turn the beat down 1-2 dB». Единственная цифра голос к биту.
- Mike Senior — рэп Alex Giddens (SOS, 10.2009): голос внятный, но не настолько
  громкий, чтобы бас и барабаны стали «маленькими». То же в «Mix Mistakes»
  (09.2011): слишком громкий голос или лишняя нижняя середина «make the rest
  of the production sound small».
- Koen Heldens — Trippie Redd: проверка на почти нулевой громкости — «If it is
  only vocal, your vocals are too loud… You want to hear both».
- Pensado (SOS, 01.2007): «If you put in too much bass, every time the 808 hits
  the vocal level sounds like it's dropping by 3dB».
  [SOS](https://www.soundonsound.com/techniques/secrets-mix-engineers-david-pensado)
- LaRay — Cardi B: «золотая середина» между голосом, который тонет в бочке,
  и 808, которого не чувствуешь.

**Райдинг.**
- Mike Senior, «St Vitus» (SOS, 11.2008): «riding the fader over more than a
  12dB range to pull up all the little details». Где поднимать: начала слов для
  напора, хвосты фраз, тусклые согласные «n», «m», «h», «l», «v»
  ([Q&A, 01.2018](https://www.soundonsound.com/sound-advice/q-why-use-so-much-level-automation)).
  Большую часть райдов — до компрессора: «it often sounds more musical if you
  automate into the compressors».
- Marroquin — Kanye West: «I had to ride the levels, sometimes as much as 6–7dB
  on certain words» (о сэмпле, не о голосе).
- Jaycen Joshua — «Baby» (SOS, 08.2010): «in the subgroup mix I may lift an
  entire section a dB for the chorus or an outro».
  [SOS](https://www.soundonsound.com/techniques/secrets-mix-engineers-jaycen-joshua)
- Soundlab [субтитры]: ровнять строки автоматизацией на несколько децибел,
  компрессию оставлять лёгкой. [YouTube](https://www.youtube.com/watch?v=pbrP4LIErIA)
- Waves Vocal Rider, руководство: пределы по умолчанию −6…+6 дБ (максимум ±12),
  в паузах фейдер уходит к «idle» — «typically… in the middle of the range, to
  avoid drastic gain changes between words»; атака Fast/Slow, по умолчанию Slow;
  с инструменталом на сайдчейне следит и за громкостью бита.
  [PDF](https://assets.wavescdn.com/pdf/plugins/vocal-rider.pdf)
- Mike Senior, «DIY Vocal Rider» (SOS, 06.2010): экспандер, которым управляет
  бит; детектор с подъёмом 1–5 кГц — полоса маскировки.
  [SOS](https://www.soundonsound.com/techniques/cubase-diy-vocal-rider)
- John Walden (SOS, 06.2025): барабаны в сайдчейн райдера подавать тише, иначе
  голос качает в такт бочке. [SOS](https://www.soundonsound.com/techniques/cubase-14-using-modulators-automatic-vocal-level-riding)
- Скорость райдера в миллисекундах не назвал никто.

**Место голосу в бите.**
- Gibbs — Doja Cat: F6 на шине клавиш с ключом от голоса — «dynamic dips in the
  900Hz and 2kHz range when she is singing»; в ремиксе так же давит середину
  808, пока читает Nicki Minaj.
- Mike Senior, «Ducking At Mixdown» (SOS, 05.2009): компрессор 1,04:1, порог
  −60 дБ, не больше 2 дБ; вариант с гейтом — посыл −20 дБ даёт ~1 дБ
  приседания, −11 дБ — ~3 дБ; можно приседать только верхом.
  [SOS](https://www.soundonsound.com/techniques/ducking-mixdown)
- Just Blaze — Jay-Z (Tape Op #101): «we used Jay's vocal as the key to
  sidechain compress the high frequencies of the horn sample».
  [Tape Op](https://tapeop.com/interviews/101/just-blaze)
- Jaycen Joshua (MWTM, 06.01.2025): подавитель резонансов на шине музыки
  с голосом в сайдчейне. [MWTM](https://community.mwtm.com/t/12189)
- Podlesny Twins — Dose «Адреналин» [субтитры]: Soothe на мелодии «на частоты
  вокала 1500», в миксе 80 %. [YouTube](https://www.youtube.com/watch?v=YfctOhV--pk)
- Hidalgo — Stormzy (SOS, 01.2023): на шине музыки 1 дБ чуть выше 6 кГц и
  провал около 280 Гц — «clearing a tiny little bit of space for vocals».
  [SOS](https://www.soundonsound.com/techniques/inside-track-stormzy-hide-seek)

## 3. Автотюн

**Документация Antares.**
- Retune Speed в миллисекундах. «Setting the Retune Speed to 0 will cause
  immediate changes from one pitch to another, and will completely suppress any
  vibrato»; для естественного звучания — «set between 10 and 50»; в уроке
  диапазон 0–400. Рецепт эффекта: Flex-Tune 0, Retune 0, верные тональность
  и гамма. EFX+: для эффекта около 0, естественно — от 20. Humanize замедляет
  коррекцию только на длинных нотах; Flex-Tune правит только вблизи целевой
  ноты; Detune сдвигает опорное «ля» от 440 Гц (±100 центов).
  [Pro X 10.1](https://antares-web-frontend.sfo3.cdn.digitaloceanspaces.com/documentation/pdfs/Auto-Tune_Pro_X_User_Guide_Version_10.1.pdf),
  [EFX+](https://antares-web-frontend.sfo3.cdn.digitaloceanspaces.com/documentation/pdfs/Auto-Tune_EFX_Plus_User_Guide_v1.1.pdf)
- Неверная тональность (блог Antares, 19.08.2026): «the result sounds confidently
  off rather than obviously broken». Тот же блог: мелодичный рэп — 15–25 мс
  (маркетинговый текст, без ссылок на инженеров).
  [Antares](https://www.antarestech.com/blog/pitch-correction-the-complete-guide-to-tuning-vocals)
- Paul White (SOS, 04.2019): певец ушёл дальше середины интервала — «you can end
  up with a perfectly tuned wrong note».
  [SOS](https://www.soundonsound.com/reviews/antares-auto-tune-access)
- John Walden (SOS, 12.2015): естественно — Pitch Tracking 70, Retune 90,
  Humanize 50 (Auto-Tune 8). Mike Thornton (SOS, 12.2011): параллельная копия
  в хроматике с медленной скоростью даёт хорус.
  [SOS](https://www.soundonsound.com/techniques/creative-pitch-processing),
  [SOS](https://www.soundonsound.com/techniques/pitch-correction-plug-ins)

**Что ставят рэп-инженеры.**
- Kesha Lee — Lil Uzi Vert: «We used to just have it on default, with a Retune
  speed of 20, but lately he has been like: ‘Give me more Auto-Tune!’ so now we
  have the Retune Speed set to anywhere from 12 to 5».
- Patrizio Pigliapoco — Chris Brown (SOS, 09.2019): «alto/tenor setting, with
  Retune usually set to 11-12-13. But sometimes we go crazy with Auto-Tune and we
  set it to 2. Or it may be 7». Печатается при записи.
  [SOS](https://www.soundonsound.com/techniques/inside-track-chris-brown-heat)
- McCloskey — DaBaby: «default setting of 25 with Humanize at 100 percent, so it's
  not very noticeable. The main vocal don't have Auto-Tune».
- Jess Jackson — Pop Smoke (XXL, 08.10.2020): 0 мс — «T-Pain, Travis Scott and
  Migos effect», 50 мс — «relaxed». Оговорка: Jackson связан с Antares.
  [XXL](https://www.xxlmag.com/engineers-give-rappers-autotune-advice/)
- Seth Firkins — Future: автотюн всегда в шаблоне записи, «It’s his sound»;
  «It’s either transparent or obvious».
  [RBMA Daily](https://daily.redbullmusicacademy.com/2017/08/seth-firkins-interview/)
- Mike Dean — Travis Scott (The FADER, 08.10.2018): знать тональность, «so you
  can set your Auto-Tune right»; частая ошибка — автотюн не в той тональности.
  [FADER](https://www.thefader.com/2018/10/08/mike-dean-interview-travis-scott-and-kanye-west)
- Alex Tumay — 21 Savage «Ocean Drive» (RBMA, 2016): чинил запись, где автотюн
  стоял не в той тональности: EFX «like 100%» в правильной, поверх — медленнее.
  [RBMA](https://www.redbullmusicacademy.com/lectures/alex-tumay-lecture/)
- Bolooki — Lil Nas X: на припевах медленная автоматизированная скорость и
  Flex-Tune «to allow a lot of humanising»; ноты вне лада — обходом.
- Evan LaRay (XXL): «Once you sing into it, it gives you that sound»; поставить
  только в миксе — «takes away the effect».
- Против и в меру: Grandjean — «Auto-Tune has a sound… more of an effects tool
  than a correcting tool»; Muzzy — рэп Nicki Minaj не тюнил; Mike Strange —
  у Eminem автотюна нет; Donoghue — в дрилле тюнят редко.
- Podlesny Twins — 9mice [субтитры]: «автотюн в режиме максимальная агрессия»
  вторым в цепочке. Палагин — вокал часто пишут сразу через автотюн.

## 4. Дилей

- Время: ms = 60 000 ÷ BPM; пунктирная восьмая = 3/16. Geoff Smith (SOS,
  05.2012). [SOS](https://www.soundonsound.com/techniques/creating-using-custom-delay-effects)
- Четверть — главный вокальный дилей: Firkins (Future, в наушниках при записи),
  Young Guru (Jay-Z: TC D•Two), LaRay («my own quarter delay is my main vocal
  delay»), Hurtt (Polo G), Muzzy (броски), Schaeffer (Kendrick). Восьмая — Mike
  Strange (Eminem), Castellon, Gibbs; половина — Lil Uzi Vert (фидбек 43 %),
  Bolooki («lazy half-note delay»).
- Броски на концах строк. Сениор (SOS, 02.2008): «ride the level up occasionally
  to catch the odd word at the ends of lines». Profitt — NF (SOS, 10.2019):
  «three or four moments in the track». Bainz — Young Thug: 15 дорожек бросков,
  эффект на вставке «100‑percent wet». iZotope (Messitte, 12.2021): Mix 100 %,
  «so that you don’t actually hear the initial word—only the delays».
  [iZotope](https://www.izotope.com/en/learn/8-tips-for-mixing-rap-and-hip-hop)
- Дилей в паузах. Bainz — Young Thug: четвертной дилей с компрессором, «side‑chained to the vocal, so it only sounds
  when the vocal isn’t there».
  [SOS](https://www.soundonsound.com/techniques/inside-track-young-thug-gunna-ski)
  Сениор, Logic (SOS, 10.2004): 2:1, атака 0, отпуск ~150 мс, «8-10dB of
  reduction while the vocalist was singing».
  [SOS](https://www.soundonsound.com/techniques/logic-dynamics-processing-reverbdelay)
- Фильтры на шине дилея: Сениор — ФВЧ 360 Гц и ФНЧ 6,6 кГц (Mix Rescue Imprint,
  01.2008); вырез 4 кГц, чтобы повторы не лезли в присутствие голоса (01.2011);
  Tom Elmhirst — «removing all high end above 5/6k and low below 200hz»
  ([MWTM](https://community.mwtm.com/t/1057)); Pensado — «If you have too much
  top end on a delay it tends to sound like candy».
- Слэпбэк: 50–100 мс без обратной связи (Сениор, 07.2008), 60–180 мс «thickening»
  (Geoff Smith), около 80 мс «mixed quite far back» (Marroquin), 30 мс EchoBoy
  для ширины (Chhim — J Cole), 1/32 — «он здорово стабилизирует, особенно середину трека» (Podlesny
  Twins — BATO [субтитры]).
- Против бросков: Moneybagg Yo «hates the traditional ear candy like delay
  throws, reverb swells, reversing things» (Morris, SOS, 01.2022).
  [SOS](https://www.soundonsound.com/techniques/inside-track-moneybagg-yo-wockesha)

## 5. Отзвук

- Seth Firkins — Future «Draco» (SOS, 05.2017): вставкой в цепи шины — «Medium
  Room with a pre-delay of 15ms, a decay of 751ms, a high-frequency cut at 9.36kHz,
  and just 15 percent wet». При записи: «12-15 percent mix with 12ms pre-delay».
- Mike Senior — рэп Alex Giddens (SOS, 10.2009): «a 0.2s chamber impulse, with
  15ms of predelay». Pocket Lips (12.2008): в урбан-стилях ревер на ведущем
  голосе часто не нужен, склеивают дилеи.
- Jaycen Joshua (SOS, 08.2010): «everyone knows that reverb is the kiss of death on
  rap vocals». Matt Schaeffer — Kendrick (SOS, 05.2018): Valhalla «set to -12, so
  it only gives a tiny bit of ambience».
  [SOS](https://www.soundonsound.com/techniques/inside-track-kendrick-lamar-black-panther-all-stars)
  Chhim — 21 Savage: просили сухо, «a small room reverb really subtly».
- Противоположный полюс: Travis Harrington — Rod Wave: «I’m an excessive reverb
  user» (SOS, 11.2021); Tillie Mann: «I like rap vocals to be wet and wide».
- Предзадержка: Сениор — короткий ревер (заметно меньше секунды) с 5–10 мс,
  длинный — 30–70 мс, демонстрация: без предзадержки «the vocalist takes a clear
  step backwards» ([SOS, 07.2008](https://www.soundonsound.com/techniques/how-use-reverb-pro-1));
  Pensado — «16th or 32nd note»; Podlesny Twins — 1/32 или 1/64 [субтитры];
  Jaycen — отдельный дилей 100 % мокрый с нулевой обратной связью перед
  ревером ([MWTM](https://community.mwtm.com/t/2380)).
- Фильтры на возврате: Сениор — ФВЧ «somewhere in the 100-300Hz range», пример
  240 Гц и пологий ФНЧ от ~7 кГц; Paul White — верх до 3–4 кГц, низ ниже ~150 Гц,
  голос остаётся близким; Pensado — верх с 4–5 кГц, низ от 300 Гц; де-эссер
  первым на возврате (Сениор, 05.2009; KRUG [субтитры]).
- Уровень: Сениор — ревер должен быть заметен, только когда его выключишь;
  Paul White — опускать возврат, пока голос не начнёт «отрываться» от бита.
- Два ревера: Leslie Brathwaite — короткий и длинный, длинный «a lot lower just
  to provide the tail effect» ([MWTM](https://community.mwtm.com/t/16484));
  Jaycen — короткий тёмный ревер «to add warmth and low end to a vocal».

## 6. Даблы и эдлибы

- Расширитель Сениора (Mix Rescue Santi Vega, SOS, 07.2012): «two short delays
  (in this case, 11ms and 13ms) hard‑panned to opposite extremes», короткая на
  5 центов вниз, длинная на 5 вверх; возврат на 15 дБ ниже голоса — больше, чем
  обычно. Общий вид: 5–20 мс, 2–10 центов (Q&A, 11.2008).
  [SOS](https://www.soundonsound.com/techniques/mix-rescue-santi-vega),
  [SOS](https://www.soundonsound.com/sound-advice/q-how-can-i-achieve-wider-vocal-sound)
- Paul White: две копии ±2–6 центов, одна задержана на 20–40 мс
  ([SOS, 08.2020](https://www.soundonsound.com/techniques/doubling-thicker-sounds));
  ±3–4 цента и около 25 мс (Logic, 07.2020); ADT одним повтором 80–120 мс на
  уровне оригинала ([SOS, 04.2009](https://www.soundonsound.com/techniques/double-tracking-vocals)).
- Stuart White — Beyoncé и Jay-Z «Apeshit» (SOS, 09.2018): MicroShift, левый на
  6 центов ниже, правый на 6 выше — «wider without them being out of phase».
  [SOS](https://www.soundonsound.com/techniques/inside-track-beyonce-and-jay-z-apeshit)
- Jaycen Joshua — «Baby»: «I set the delay to 21ms and mixed the original 100
  percent to the left and the delay to the right».
- Предел сдвига (iZotope, 12.2021): слои в одной точке панорамы, разошедшиеся
  больше чем на ~20 мс, звучат как заикание или слэпбэк.
- Моно (Сениор, Q&A, 03.2020): даблы по краям в моно теряют около 3 дБ; разведённые
  держать на одном уровне; точная подгонка и тихий дабл — один голос
  с хорусом, свободная и вровень — «двое поют».
  [SOS](https://www.soundonsound.com/sound-advice/q-how-should-you-pan-vocals-when-double-tracking)
- Рэп-дабл (Сениор, Q&A, 12.2003): ведущий сжат, дабл нет — ударные слова
  звучат сдвоенно; дабл можно поднимать руками на акцентах.
  [SOS](https://www.soundonsound.com/sound-advice/q-whats-best-way-produce-double-tracked-rap-vocal)
- Эдлибы: Goldberg (YoungBoy) — бэки «very wide left and right» с Doubler;
  Harrington (Rod Wave) — Doubler на эдлибах; Heldens (Trippie Redd) — эдлибы
  и бэки на «H3000» (левый чуть ниже, правый чуть выше), центр — ведущему;
  McCloskey (DaBaby) — эдлибы в моно по просьбе артиста (выступал на клубных
  системах). Waves (Hoffman, 08.2020): эдлибам можно меньше внятности и больше
  ревера, дилея и искажений.
- Даблы тише и суше: KRUG [субтитры] — «ревёрб идёт только от основы на дабла его
  нету они просто в балансе достаточно тихо», у даблов срезано больше низа;
  Podlesny Twins — из даблов убирают эски; искусственные даблы копированием —
  в худшей категории тир-листа, лучше даблер на посыле [субтитры].
- Eminem (Mike Strange, SOS, 10.2010) удваивает весь рэп вручную; Polo G (Todd
  Hurtt) даблов не делает вовсе. [SOS](https://www.soundonsound.com/techniques/mike-strange-jr-eminem-recovery),
  [SOS](https://www.soundonsound.com/techniques/inside-track-polo-g-rapstar)

## 7. Ширина и моно

- Частота моно-низа: iZotope — «narrowed 125 Hz and below to 100% mono» (пример
  автора, [10.2022](https://www.izotope.com/community/blog/mono-vs-stereo));
  Soundlab — моно до 128 Гц на мастере [субтитры]; Podlesny Twins — «всё, что
  ниже сотки в моно» [субтитры]; Палагин — «где-то соточка» [субтитры];
  SOS (Tom Flint, 01.2007) — стерео ниже ~100 Гц не локализуется.
- Как делается: Hugh Robjohns — это ФВЧ на боковом канале M/S; граница плавная,
  при 100 Гц и фильтре второго порядка −15 дБ на 200 Гц и −27 дБ на 400 Гц.
  [SOS](https://www.soundonsound.com/sound-advice/q-how-do-mono-maker-plug-ins-work)
- Клубы и PA суммируют низ в моно (Сениор, «Mixing Bass», 09.2012); Dresdow проверяет
  моно, потому что в клубах и магазинах звук моно (пересказ).
- Моно-проверка голоса: Derek Ali сводит «about 80 percent of my time… in mono»
  (один Auratone); Heldens — «mix for a moment in mono» (приём Dre). Против:
  Jaycen Joshua — «I really don't pay attention to the mono compat»
  ([MWTM](https://community.mwtm.com/t/12359)).
- Ширина бита, голос в центре: Chhim — bx_shredspread «to make space for the
  vocals»; Podlesny Twins — сэмпл «где-то на 30%» шире [субтитры]; Colmenero —
  S1 на 30 % на шине бита; McCloskey — наоборот, стороны микса −1…−2 дБ.
  iZotope 2024: у хитов стороны в среднем на 8,5 LU тише середины, а хип-хоп —
  самый узкий из жанров.
- Хаас и расширители: гребёнка в моно (Geoff Smith; iZotope); безопасный вариант —
  расширитель питать от возврата дилея, а не от сухого голоса (Сениор, 03.2014).

## 8. Мастер: громкость, пик, клиппер

**Площадки (официально).**
- Spotify приводит к −14 LUFS; тихие поднимает, оставляя 1 дБ запаса; советует
  истинный пик не выше −1 dBTP, а «If your master is louder than -14dB integrated
  LUFS, keep True Peak below -2dB to avoid extra distortion». Режим Loud
  (−11 LUFS) — свой ограничитель: −1 дБ, атака 5 мс, спад 100 мс.
  [Spotify](https://support.spotify.com/us/artists/article/loudness-normalization/)
- Apple (Apple Digital Masters, 04.2021): цифры громкости нет; Sound Check делает
  громкие мастера тише, «which can make tracks actually sound weaker»; «leave at
  least 1 dB of headroom». [PDF](https://www.apple.com/apple-music/apple-digital-masters/docs/apple-digital-masters.pdf)
- AES TD1008 (2021): музыка −16 LUFS по трекам, громкий трек альбома −14;
  «Maximum True Peak level not exceed -1 dBTP at the codec input»; на 256 кбит/с
  может хватить −0,5, на низком битрейте нужно ниже; фильтр или смена частоты
  после ограничителя сами дают выбросы.
  [PDF](https://aes2.org/wp-content/uploads/2024/01/20210924_TD1008_v3.13.pdf)
- YouTube: официальной цифры нет; по замерам Шеперда видео — −14 LUFS,
  YouTube Music уменьшает только громче −7 LUFS (11.10.2023).
  [Production Advice](https://productionadvice.co.uk/youtube-music/)
- Яндекс Музыка, VK Музыка: официальных цифр нет; на доске пожеланий Яндекса
  просьба о нормализации громкости висит 7 лет в статусе «Идеи».
  [userecho](https://yandexmusic.userecho.ru/communities/45/topics/774-normalizatsiya-gromkosti-trekov)

**Как громко сводят.**
- iZotope (Ian Stewart, 16.07.2024), 54 песни из десятки Billboard Global 200:
  «the average integrated level comes out to -8.3 LUFS, with a standard deviation
  of 1LU»; максимум краткосрочной громкости −6 ±1; у половины истинный пик
  от 0,00 до +0,75 dBTP. [iZotope](https://www.izotope.com/en/learn/mastering-trends)
- Рэп: Jaycen Joshua — «anywhere from -8 to -6»
  ([MWTM](https://community.mwtm.com/t/2395)); Donoghue — Central Cee
  «‑7.5 to ‑8 LUFS»; Jess Jackson — Pop Smoke «‑8 LUFS» с пульта без
  ограничителя ([SOS](https://www.soundonsound.com/techniques/inside-track-pop-smoke-woo));
  Heldens — альбом Trippie Redd «mastered to ‑10 LUFS» (на плёнке, громче
  искажало); Colmenero — Lil Tecca на утверждение «at -9LUFS»
  ([SOS](https://www.soundonsound.com/techniques/inside-track-lil-tecca-ransom));
  McCloskey — RMS −8 «as hot as I can get it before it breaks apart».
- Иэн Шеперд: «Master no louder than -10 LUFS short-term at the loudest moments»
  (истинный пик не выше −1), так интегрально выходит −11…−14
  ([2017](https://productionadvice.co.uk/how-loud/)); в SOS (04.2023): «the point
  where I tend to stop enjoying things is roughly ‑10 LUFS»
  ([SOS](https://www.soundonsound.com/techniques/ian-shepherd-loudness-dynamics)).
- Podlesny Twins: демо приходят на −5…−6 LUFS, война громкости не кончилась
  ([WaveForum](https://waveforum.ru/biblioteka/problemi-demo-trekov)); Soundlab:
  −6 LUFS «отвратный», «я за динамику» [субтитры].

**Клиппер против ограничителя.**
- Mike Senior — Pocket Lips (SOS, 12.2008): «Using clipping to take some of the
  strain off the limiter is very common in commercial releases in this kind of
  style, as it tends to keep a punchier sound»; там — «a few decibels» клиппинга
  и 4 дБ лимитинга. [SOS](https://www.soundonsound.com/techniques/mix-rescue-pocket-lips)
- Иэн Шеперд (2013): «Hard digital clipping gives the highest apparent loudness,
  but also the most distortion and the biggest loss of low bass»; мягкий
  сохраняет удар; ограничитель чище, но теряет громкость и удар больше всех;
  сам сочетает мягкий клиппинг и ограничитель.
  [Production Advice](https://productionadvice.co.uk/clipping/)
- Hugh Robjohns (SOS, 08.2013): цифровой клиппинг даёт алиасинг, «especially
  obvious for signals with a well-defined harmonic structure, such as pianos,
  voices». [SOS](https://www.soundonsound.com/sound-advice/q-there-difference-between-clipping-and-limiting)
- Ian Stewart (iZotope, 09.2022): жёсткий клиппинг — только на миллисекунды
  верхушки удара, с передискретизацией.
  [iZotope](https://www.izotope.com/en/learn/what-is-soft-clipping)
- Bettermaker (обзор Robjohns, SOS, 12.2017): порог клиппера на 3 дБ выше порога
  ограничителя. Chhim — 21 Savage: мягкий клип Event Horizon, затем Pro-L.
- Podlesny Twins [субтитры]: клиппер на голосе — «полнейший» худший тир;
  инструментал можно подклиповать «на пару ДБ».
- Alex Tumay: «I never want to digitally clip the 808’s in the red» — нарушил
  на «Mamacita». [RBMA Daily](https://daily.redbullmusicacademy.com/2017/01/alex-tumay-interview/)

## 9. Саунд-дизайн переходов

- Реверс-ревер: Paul White — перевёрнутая плита около 4 с, 100 % мокрого,
  дорожка сдвинута на 2–3 с раньше сухой; укоротить кусок, чтобы нарастание не
  накрывало голос ([SOS, 08.2006](https://www.soundonsound.com/techniques/mix-rescue-dance-track));
  «best to use it sparingly. It works well on a vocal intro or bridge section»
  ([SOS, 12.1998](https://www.soundonsound.com/techniques/creating-reverse-reverb));
  MusicRadar — средняя комната со спадом 1,5 с, длинные «take too long to build
  up» ([MusicRadar](https://www.musicradar.com/how-to/reverse-reverb)).
  Marasciullo — «a reverse effect just before the downbeat at the beginning of
  the song» (Flo Rida). Donoghue: в дрилле реверс-реверб и заикания — «really
  important to the energy».
- Вырезать бит перед строкой: McCloskey — DaBaby: «Jon wanted maximum impact at
  this point, and the easiest way of doing that is to have nothing happening just
  before it»; полная тишина звучала плохо, оставили хвосты дилея и ревера.
  Kesha Lee — Uzi сам жмёт mute, потом дропы выравнивают на сильную долю.
  Сениор — Preslin Davis (хип-хоп, SOS, 02.2010): дорожки выключаются с начала
  предыдущей сильной доли, бас — в конце её ноты
  ([SOS](https://www.soundonsound.com/techniques/mix-rescue-preslin-davis)).
- Фильтр на бите: Сениор — ФНЧ 400 Гц на басе в разреженном вступлении
  ([SOS, 04.2011](https://www.soundonsound.com/techniques/mix-rescue-tom-marcovitch)),
  ФНЧ на бочке и малом первые 40 с (05.2024); Colmenero — DJ-фильтр в конце
  последнего припева, «takes the high end out really quickly, and then slowly
  brings it back in»; Todd Hurtt — провалы на готовом бите срезом баса, но Polo G
  их не любит; Stuart White — FilterFreak «with the filter opening up».
- Остановка плёнки: Paul White — «popular (and sometimes overused)»
  ([SOS, 03.2020](https://www.soundonsound.com/techniques/using-logics-time-pitch-machine));
  Jimmy Douglass — «record slowdown at the end» (Timberlake «Sexyback»); Dot Da
  Genius — аутро на половинной скорости (Kid Cudi). Ни в одной рэп-статье SOS
  остановка плёнки как приём голоса не описана.
- Телефонный фильтр: Paul White — полоса примерно 250 Гц–2 кГц, крутыми
  фильтрами, на короткие места ([SOS, 12.2006](https://www.soundonsound.com/techniques/vocal-fx));
  Gibbs — дилей с ревером на месте вырезанного слова, «more of that radio sound».
- Резкая смена эффектов на границе частей «can be profoundly attention‑grabbing»
  (Сениор, SOS, 11.2025, [«Mixing Pop Vocals»](https://www.soundonsound.com/techniques/mixing-pop-vocals)).

## 10. Словарь: слова человека → параметры

**Таблица частот из учебников.** Brecht De Man, диссертация (Queen Mary, 2017),
таблица 2.3 «Spectral descriptors in practical sound engineering literature» —
сведены диапазоны из книг Izhaki, Owsinski, Gibson, Katz, Huber и других.
Разброс большой, одно слово у разных авторов — разные полосы.
[PDF](http://www.brechtdeman.com/publications/pdf/PhD-thesis.pdf)

| Слово | Диапазоны у разных авторов |
|---|---|
| warm / тёплый | 90–175 Гц; 100–600 Гц; 200 Гц; 200–800 Гц; 200–500 Гц; 250–600 Гц |
| muddy / грязный, мутный | 20–400 Гц; 60–500 Гц; 150–600 Гц; 175–350 Гц; 200–400 Гц; 200–800 Гц |
| boxy / коробка | 250–800 Гц; 300–600 Гц; 300–900 Гц |
| nasal / в нос | 400–2500 Гц; 500–1000 Гц; 700–1200 Гц |
| thin / тонкий | недостаток 20–200, 40–200, 60–250 или 62–600 Гц |
| full, fat / плотный, жирный | 40–200; 50–250; 60–250; 80–240; 100–500; 175–350 Гц |
| presence / присутствие | 1,5–6 кГц; 2–8 кГц; 2–11 кГц; 2,5–5 кГц; 4–6 кГц |
| in-your-face / в лицо | 1,5–6 кГц |
| close / близко | 2–4 кГц; 4–6 кГц |
| intelligible / разборчиво | 800–5000 Гц; 2–4 кГц |
| distant / далеко | недостаток 200–800 Гц; 700–20 000 Гц; 4–6 кГц; около 5 кГц |
| harsh / резкий | 2–10 кГц; 2–12 кГц; 5–20 кГц |
| sibilant / шипит | 2–8; 2–10; 4; 5–20; 6–12 кГц |
| bright / яркий | 2–12; 2–20; 5–8 кГц |
| dull, dark / глухой, тёмный | недостаток 4–20; 5–8; 6–16 кГц |
| air / воздух | 5–8 кГц; 10–20 кГц |
| punch / удар | 40–200 Гц; 62–250 Гц |
| boomy / бубнит | 20–100; 40–200; 60–250; 62–125 Гц |

Для голоса там же: «Lead vocal cut below 80 Hz», подъёмы на 250 Гц, 1–6 кГц и
10–12 кГц (сводка из учебников, не правило).

**Тепло и воздух (SOS, 12.2001).** «a very gentle amount of low‑end boost (2‑3dB
at approximately 90Hz), can be combined with an air EQ setting (2‑4dB at
12‑15kHz)»; подъём между 2 и 7 кГц рискует сделать верх резким и утомительным;
тепло можно получить и компрессией с низким ratio (меньше 1,5:1).
[SOS](https://www.soundonsound.com/techniques/secrets-warmth-air)

**Как инженеры переводили слова артистов.**
- **Сделай роботом.** T-Pain — «Please turn it up even more, I want to sound
  robotic!» (Brathwaite, SOS, 05.2014) → сильнее автотюн.
  [SOS](https://www.soundonsound.com/techniques/inside-track-pharrell-williams-happy)
- **Больше автотюна** (Lil Uzi Vert, «Give me more Auto-Tune!») → Retune с 20 до 12–5 мс.
- **Как Motown** (Pharrell) → голос «a little in the background and spread out»,
  не «в лицо» (Brathwaite).
- **Похрустче** (YoungBoy) → «pushed some top end and midrange» (Goldberg, SOS,
  10.2022). [SOS](https://www.soundonsound.com/techniques/inside-track-youngboy-loner-life)
- **Бей сильнее** — самая частая просьба в трэпе: «Mostly they want me to get it to hit hard, to add more knock» (LaRay).
- **Сделай ярче** (Lizer) → верх «на пределе», пока не вылезают эски (KRUG
  [субтитры]).
- **Эха побольше** — неоднозначно: «в его понятии «эхо» — это Delay или Reverb?»
  (Podlesny Twins, [WaveForum](https://waveforum.ru/biblioteka/intervyu-podlesny-twins--)).
- **Звучит по-другому** (Polo G, «It sound different») → откат к черновику (Hurtt);
  «The kick is too clean… Please take it back to how it sounded» (DaBaby) → вернули грязь лимитера FL Studio (McCloskey).
- **Сделай слаще** («can you make it sweeter?») — Hidalgo идёт говорить с артистом: контекст подсказывает
  направление. Jay-Z «like therapy», «army marching» — Young Guru подложил стомп
  под бочку (RBMA 2011) — у склейки такого инструмента нет.
- **Как у <артиста>, референс.** iZotope (Nick Messitte) — «Level match the reference
  tracks to the mix», в примере референс опущен на 4,1 дБ
  ([iZotope](https://www.izotope.com/en/learn/13-tips-for-using-references-while-mixing));
  Podlesny Twins — референс раскладывают на АЧХ, LUFS, стерео и mid/side и
  сверяют с песней (артист шепчет, а шлёт The Weeknd); Brathwaite — «When
  someone says to you, 'I want this to sound like Aretha Franklin,' it's an easy
  blueprint»; Tillie Mann — «I'm very upfront about the vocal not sounding like
  anyone else»; Morris — с Moneybagg Yo «we never reference anyone else’s music».
- Машина: в машинных системах низ поднят, а верх падает примерно на 1,5 дБ на
  октаву; шум в дороге — в основном низкочастотный (SOS, 12.2022).
  [SOS](https://www.soundonsound.com/sound-advice/7-reasons-not-check-your-mixes-car)
  Saluki досводили «чуть ли не в машине», чтобы эффекты не убивали слова
  ([Афиша Daily](https://daily.afisha.ru/music/28265-saluki-stranno-kogda-rebenka-rastyat-yutub-i-kakieto-repery-tipa-menya/)).
- Клуб: PA суммирует низ в моно (Сениор); DaBaby держит эдлибы в моно из-за
  клубных систем.

## 11. Что делает звук артиста узнаваемым

- **Автотюн как постоянная часть голоса**: Future — «It’s his sound» (Firkins);
  Polo G — «I set it to the sound Polo wants, and then we forget about it»
  (Hurtt); Chris Brown — «You will never find a raw vocal by Chris without
  Auto-Tune» (Pigliapoco); Lil Uzi Vert — «signature autotuned tone» (Puremix
  о Brathwaite); Rod Wave — наоборот, «a natural rawness of not quite hitting some
  notes» (Harrington).
- **Количество ревера и сухость**: Rod Wave — «excessive reverb»; Moneybagg Yo —
  «bone‑dry, raw power»; 21 Savage — «pretty dry»; Polo G — «not a fan of too
  many effects»; Jimmy Douglass — «a dry sound. That's my sound».
- **Фирменный дилей**: Eminem «Not Afraid» — дилей повторяет каждую строку хука,
  «a real feature» (Mike Strange).
- **Перегруз**: Lil Nas X — L2 «part of Nas' sound»; DaBaby — голос под грязный
  бит; Beastie Boys — «gentle distortion… not distortion like Slayer» (Zdar).
- **Даблы**: Eminem удваивает весь рэп; Polo G — один голос без даблов.
- **Голос над битом**: Lil Uzi Vert — «louder than the beat»; Drake — «I wanted
  the mixes to have a huge bottom end and I wanted it to have his vocal sit on
  top» (40, [Mix](http://www.mixonline.com/news/profiles/drake-take-care/366321));
  Travis Scott — «He wants to be loud. He wants to be in your face» (Tumay).
- **Постоянство цепи**: Bisel (SZA), Firkins, Donoghue — одна цепь на весь
  альбом; Jess Jackson сменил Auto-Tune Pro на Live «to keep the sound of the album
  consistent».
- **Эффекты делает сам артист**: Travis Scott — «He’s really good at doing his own
  vocal effects» (Mike Dean, [Albumism](https://albumism.com/interviews/sound-and-vision-a-conversation-with-mike-dean)).
- Громкость голоса к биту в дБ как черту артиста не назвал никто.

## 12. Русскоязычные звукорежиссёры

Проверяемых текстовых интервью с техникой нет от звукорежиссёров Скриптонита,
Басты и Gazgolder, Black Star, Face, Pharaoh, Kizaru, Big Baby Tape, Miyagi,
Macan, Ганвеста, Toxi$, Heronwater, Obladaet, «Касты», ЛСП, 104 и Truwer.
Технику дали разборы сессий на YouTube; все цитаты — машинные субтитры.

- **Podlesny Twins** (9mice, BATO, Dose, тир-лист техник): «мы голос разгоняем под бит», эски «примерно как хэты»; вырезы резонансов «на 4 дБ» почти в каждом
  миксе; базовый компрессор 5–6 дБ, в хип-хопе жать меньше; +0,5 широкой полосой
  на 3200; параллельный верх с низом, срезанным «до 2000»; предилей ревера 1/32
  или 1/64, из ревера вырезают эски и середину; слэп 1/32; моно ниже «сотки»;
  клиппер на голосе — худший тир.
  [9mice](https://www.youtube.com/watch?v=Mk64EhVvppo),
  [BATO](https://www.youtube.com/watch?v=TInq3SD4z9o),
  [Dose](https://www.youtube.com/watch?v=YfctOhV--pk),
  [тир-лист](https://www.youtube.com/watch?v=Ns2ap2w1CK8)
- **Палагин** (MORGENSHTERN, Markul): срез «до 130» и «до 200»; «соточка» на
  эмуляции пульта даёт тело; форманта на «единичку» вниз — мягче; Soothe на
  шине эффектов с ключом от голоса, «чтобы типа эффекты не перебивали вокал»;
  моно низа «где-то соточка»; глубину лимитера выбирает по искажениям, а не
  по LUFS. [Sheikh](https://www.youtube.com/watch?v=EZFuvSVw57A),
  [Пойдёт](https://www.youtube.com/watch?v=u7Ptllr-NRk),
  [Белка](https://www.youtube.com/watch?v=rbHPLjAsrfE)
- **KRUG и Soundlab** (Lizer, lildrughill): де-эссер «4.200 с чем-то»; «грид»
  около 2,7 — разборчивость; ревер 803 мс; де-эссер перед ревером; даблы сухие
  и тихие; моно до 128 Гц; «вайб в записи… преобладает над качеством».
  [YouTube](https://www.youtube.com/watch?v=pbrP4LIErIA)
- Под Яндекс Музыку, ВКонтакте и Spotify цифр LUFS не назвал никто.

## Чего не нашлось

- Скорость райдинга в миллисекундах; громкость голоса к биту в дБ (кроме «бит
  −1…−2 дБ» у Lee).
- Время отзвука и предзадержка в долях такта у рэп-инженеров — единичные числа
  (Firkins, Сениор, Pensado); длины ревера на рэп-голосе кроме 751 мс и 0,2 с —
  нет.
- Даблы и эдлибы у рэп-инженеров — без миллисекунд и дБ; числа — только
  у Сениора, Paul White, Stuart White, Jaycen Joshua (21 мс).
- Остановка плёнки на рэп-голосе — ни в одной статье Inside Track.
- Выпуски Pensado's Place и уроки Mix With The Masters — без текста, не вошли.
- Нормализация Яндекс Музыки и VK Музыки — официально не описана.

## Источники

Sound On Sound, Inside Track и Secrets Of The Mix Engineers (все —
https://www.soundonsound.com/techniques/…): inside-track-young-thug-gunna-ski
(Bainz, 07.2021); inside-track-future-draco (Seth Firkins, 05.2017);
inside-track-lil-uzi-vert (Kesha Lee, 12.2017); inside-track-chris-brown-heat
(Patrizio Pigliapoco, 09.2019); inside-track-dababy-intro (12.2019);
inside-track-cardi-b-bodak-yellow (Evan LaRay, 02.2018);
inside-track-lil-nas-x-ft-billy-ray-cyrus-old-town-road (08.2019);
inside-track-doja-cat-ft-nicki-minaj-say-so (Clint Gibbs, 07.2020);
inside-track-lil-baby-sum-2-prove (Tillie Mann, 06.2020); inside-track-21-savage
(03.2019); inside-track-central-cee-straight-back-it (Sean Donoghue, 05.2022);
inside-track-moneybagg-yo-wockesha (01.2022); inside-track-kendrick-lamars-pimp-butterfly
(Derek Ali, 06.2015); inside-track-kendrick-lamar-black-panther-all-stars (Matt
Schaeffer, 05.2018); inside-track-trippie-redd-love-letter-you-5 (Koen Heldens,
10.2023); inside-track-pop-smoke-woo (Jess Jackson, 11.2020);
inside-track-rod-wave-street-runner (Travis Harrington, 11.2021);
inside-track-youngboy-loner-life (Jason Goldberg, 10.2022); inside-track-polo-g-rapstar
(Todd Hurtt, 09.2021); inside-track-nf-search (Tommee Profitt, 10.2019);
inside-track-beyonce-and-jay-z-apeshit (Stuart White, 09.2018);
inside-track-pharrell-williams-happy (Leslie Brathwaite, 05.2014);
inside-track-dave-funky-friday-black (Manon Grandjean, 06.2019);
inside-track-stormzy-hide-seek (Leandro Hidalgo, 01.2023); inside-track-lil-tecca-ransom
(Joe Colmenero, 11.2019); inside-track-weeknd (Carlo Montagnese, 12.2015);
secrets-mix-engineers-young-guru (12.2009); secrets-mix-engineers-jaycen-joshua
(08.2010); secrets-mix-engineers-manny-marroquin (12.2007);
secrets-mix-engineers-fabian-marasciullo (08.2008); secrets-mix-engineers-david-pensado
(01.2007); secrets-mix-engineers-kevin-davis (10.2008);
secrets-mix-engineers-dylan-3d-dresdow (07.2009); secrets-mix-engineers-dot-da-genius
(10.2009); secrets-mix-engineers-jimmy-douglass (07.2007);
noah-40-shebib-recording-drakes-headlines (03.2012); mike-strange-jr-eminem-recovery
(10.2010); trevor-muzzy-recording-nicki-minajs-starships (08.2012).

Сениор и технические статьи SOS: how-use-reverb-pro-1 (07.2008);
mix-rescue-richard-wilkinson (02.2008); mix-rescue-imprint (01.2008);
mix-rescue-pocket-lips (12.2008); mix-rescue-alex-giddens (10.2009);
mix-rescue-preslin-davis (02.2010); mix-rescue-santi-vega (07.2012);
mix-rescue-tom-marcovitch (04.2011); mix-rescue-mixing-metal (01.2011);
logic-dynamics-processing-reverbdelay (10.2004); ducking-mixdown (05.2009);
cubase-diy-vocal-rider (06.2010); mixing-bass (09.2012); mixing-pop-vocals
(11.2025); mix-mistakes (09.2011); creating-using-custom-delay-effects (Geoff
Smith, 05.2012); double-tracking-vocals, doubling-thicker-sounds, vocal-fx,
mix-rescue-dance-track, creating-reverse-reverb, using-logics-time-pitch-machine
(Paul White); creative-pitch-processing (John Walden, 12.2015);
pitch-correction-plug-ins (Mike Thornton, 12.2011); secrets-warmth-air (12.2001);
ian-shepherd-loudness-dynamics (Matt Houghton, 04.2023). Q&A
(https://www.soundonsound.com/sound-advice/…): q-why-use-so-much-level-automation;
q-how-can-i-achieve-wider-vocal-sound; q-how-should-you-pan-vocals-when-double-tracking;
q-whats-best-way-produce-double-tracked-rap-vocal; q-how-do-mono-maker-plug-ins-work;
q-there-difference-between-clipping-and-limiting; 7-reasons-not-check-your-mixes-car.
Обзоры: https://www.soundonsound.com/reviews/antares-auto-tune-access.

Интервью: https://www.redbullmusicacademy.com/lectures/alex-tumay-lecture/ ;
https://daily.redbullmusicacademy.com/2017/01/alex-tumay-interview/ ;
https://www.redbullmusicacademy.com/lectures/young-guru-vibe-over-money/ ;
https://daily.redbullmusicacademy.com/2017/08/seth-firkins-interview/ ;
https://tapeop.com/interviews/101/just-blaze ; https://tapeop.com/interviews/60/bob-power ;
https://www.thefader.com/2018/10/08/mike-dean-interview-travis-scott-and-kanye-west ;
https://albumism.com/interviews/sound-and-vision-a-conversation-with-mike-dean ;
https://www.xxlmag.com/engineers-give-rappers-autotune-advice/ ;
http://www.mixonline.com/news/profiles/drake-take-care/366321 ; форум Mix With The
Masters, ответы инженеров: https://community.mwtm.com/t/1057, /1275, /2380, /2395,
/12189, /12359, /16484.

Автотюн: руководства Antares Pro X 10.1 и EFX+ 1.1 (ссылки в разделе 3);
https://www.antarestech.com/blog/pitch-correction-the-complete-guide-to-tuning-vocals .

Площадки и громкость: https://support.spotify.com/us/artists/article/loudness-normalization/ ;
https://www.apple.com/apple-music/apple-digital-masters/docs/apple-digital-masters.pdf ;
https://aes2.org/wp-content/uploads/2024/01/20210924_TD1008_v3.13.pdf ;
https://www.izotope.com/en/learn/mastering-trends ; https://productionadvice.co.uk/how-loud/ ;
https://productionadvice.co.uk/clipping/ ; https://productionadvice.co.uk/youtube-music/ ;
https://assets.wavescdn.com/pdf/plugins/vocal-rider.pdf .

iZotope: 8-tips-for-mixing-rap-and-hip-hop; 13-tips-for-using-references-while-mixing;
what-is-soft-clipping (https://www.izotope.com/en/learn/…);
https://www.izotope.com/community/blog/mono-vs-stereo .

Словарь: http://www.brechtdeman.com/publications/pdf/PhD-thesis.pdf .

Русскоязычные: YouTube Mk64EhVvppo, TInq3SD4z9o, YfctOhV--pk, Ns2ap2w1CK8,
EZFuvSVw57A, u7Ptllr-NRk, rbHPLjAsrfE, pbrP4LIErIA; https://waveforum.ru/biblioteka/problemi-demo-trekov ;
https://waveforum.ru/biblioteka/intervyu-podlesny-twins-- .
