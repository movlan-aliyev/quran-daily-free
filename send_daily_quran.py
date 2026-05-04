#!/usr/bin/env python3
"""
Daily Quran study email (no n8n): Al-Baqarah 2:1 through An-Nas, CHUNK_SIZE ayahs per run.

Progress is stored in data/progress.json. Delete that file (or edit JSON) to reset.
"""
from __future__ import annotations

import json
import os
import re
import smtplib
import ssl
import sys
import time
from email.message import EmailMessage
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
STATE_PATH = ROOT / "data" / "progress.json"

START_SURAH = 2
END_SURAH = 114

# Hafs — ayahs per surah; index = surah number
AYAH_COUNT = [
    0,
    7, 286, 200, 176, 120, 165, 206, 75, 129, 109, 123, 111, 43, 52, 99, 128, 111, 110, 98, 135,
    112, 78, 118, 64, 77, 227, 93, 88, 69, 60, 34, 30, 73, 54, 45, 83, 182, 88, 75, 85, 54, 53, 89,
    59, 37, 35, 38, 29, 18, 45, 60, 49, 62, 55, 78, 96, 29, 22, 24, 13, 14, 11, 11, 18, 12, 12, 30,
    52, 52, 44, 28, 28, 20, 56, 40, 31, 50, 40, 46, 42, 29, 19, 36, 25, 22, 17, 19, 26, 30, 20, 15,
    21, 11, 8, 8, 19, 5, 8, 8, 11, 11, 8, 3, 9, 5, 4, 7, 3, 6, 3, 5, 4, 6, 5, 6,
]

EDITIONS = "quran-uthmani,en.sahih,tr.diyanet,en.transliteration"

# Türkçe sure adları (1 = Fâtiha … 114 = Nâs); Kur’an’da yer bilgisinde kullanılır.
_SURAH_NAMES_TR_LINES = """
Fâtiha
Bakara
Âl-i İmrân
Nisâ
Mâide
En'âm
A'râf
Enfâl
Tevbe
Yûnus
Hûd
Yûsuf
Ra'd
İbrâhîm
Hicr
Nahl
İsrâ
Kehf
Meryem
Tâhâ
Enbiyâ
Hac
Mü'minûn
Nûr
Furkân
Şuarâ
Neml
Kasas
Ankebût
Rûm
Lokmân
Secde
Ahzâb
Sebe'
Fâtır
Yâsîn
Sâffât
Sâd
Zümer
Mü'min
Fussilet
Şûrâ
Zuhruf
Duhân
Câsiye
Ahkâf
Muhammed
Fetih
Hucurât
Kâf
Zâriyât
Tûr
Necm
Kamer
Rahmân
Vâkıa
Hadîd
Mücâdele
Haşr
Mümtehine
Saf
Cum'a
Munâfikûn
Teğâbün
Talâk
Tahrim
Mülk
Kalem
Hâkka
Meâric
Nûh
Cin
Müzzemmil
Müddessir
Kıyâmet
İnsân
Mürselât
Nebe'
Nâziât
Abese
Tekvîr
İnfitâr
Mutaffifîn
İnşikâk
Bürûc
Târık
A'lâ
Ğâşiye
Fecr
Beled
Şems
Leyl
Duhâ
İnşirâh
Tîn
Alak
Kadir
Beyyine
Zilzâl
Âdiyât
Kâria
Tekâsür
Asr
Hümeze
Fil
Kurays
Mâûn
Kevser
Kâfirûn
Nasr
Tebbet
İhlâs
Felak
Nâs
""".strip().splitlines()
SURAH_NAMES_TR: list[str] = [""] + [x.strip() for x in _SURAH_NAMES_TR_LINES]
assert len(SURAH_NAMES_TR) == 115, f"Expected 114 surahs, got {len(SURAH_NAMES_TR) - 1}"


def surah_name_tr(surah: int) -> str:
    if 1 <= surah < len(SURAH_NAMES_TR):
        return SURAH_NAMES_TR[surah]
    return f"Sure {surah}"


def load_state() -> dict:
    if not STATE_PATH.is_file():
        return {
            "surah": START_SURAH,
            "ayah": 1,
            "completion_email_sent": False,
        }
    with STATE_PATH.open(encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("surah", START_SURAH)
    data.setdefault("ayah", 1)
    data.setdefault("completion_email_sent", False)
    return data


def save_state(data: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with STATE_PATH.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def next_chunk(surah: int, ayah: int, n: int) -> tuple[list[tuple[int, int]], int, int]:
    """Return list of (surah, ayah), then next cursor (surah, ayah) after chunk."""
    refs: list[tuple[int, int]] = []
    s, a = surah, ayah
    for _ in range(n):
        if s > END_SURAH:
            break
        max_a = AYAH_COUNT[s]
        refs.append((s, a))
        a += 1
        if a > max_a:
            s += 1
            a = 1
    return refs, s, a


def fetch_ayah(session: requests.Session, surah: int, ayah: int) -> dict:
    ref = f"{surah}:{ayah}"
    url = f"https://api.alquran.cloud/v1/ayah/{ref}/editions/{EDITIONS}"
    last: requests.Response | None = None
    for attempt in range(8):
        last = session.get(url, timeout=90)
        if last.status_code == 429:
            time.sleep(min(45, 1.5 * (2**attempt)))
            continue
        last.raise_for_status()
        body = last.json()
        if body.get("code") != 200:
            raise RuntimeError(f"API error for {ref}: {body}")
        parts = {"surah": surah, "ayah": ayah, "ar": "", "en": "", "tr": "", "translit_line": ""}
        for ed in body.get("data", []):
            eid = (ed.get("edition") or {}).get("identifier") or ""
            text = ed.get("text") or ""
            if eid == "quran-uthmani":
                parts["ar"] = text
            elif eid == "en.sahih":
                parts["en"] = text
            elif eid == "tr.diyanet":
                parts["tr"] = text
            elif eid == "en.transliteration":
                parts["translit_line"] = text
        return parts
    assert last is not None
    last.raise_for_status()
    raise RuntimeError(f"Unreachable fetch {ref}")


def escape_html(s: str) -> str:
    return (
        (s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _qcom_words_get_json(session: requests.Session, url: str) -> dict:
    last: requests.Response | None = None
    for attempt in range(8):
        last = session.get(url, timeout=90)
        if last.status_code == 429:
            time.sleep(min(45, 1.5 * (2**attempt)))
            continue
        last.raise_for_status()
        return last.json()
    assert last is not None
    last.raise_for_status()
    raise RuntimeError("Quran.com words: too many 429 responses")


def _parse_qcom_word_rows(body: dict) -> list[dict]:
    rows: list[dict] = []
    for w in body.get("verse", {}).get("words", []):
        if w.get("char_type_name") != "word":
            continue
        trlit = w.get("transliteration") or {}
        trans = w.get("translation") or {}
        rows.append(
            {
                "pos": w.get("position"),
                "ar": w.get("text_uthmani") or w.get("text") or "",
                "lat": (trlit.get("text") or "").strip(),
                "gloss": (trans.get("text") or "").strip(),
            }
        )
    return rows


def fetch_words_qcom(session: requests.Session, surah: int, ayah: int) -> list[dict]:
    """Word-by-word: Arabic + Latin + EN gloss + TR gloss (Quran.com: default + language=tr)."""
    key = f"{surah}:{ayah}"
    url_en = (
        f"https://api.quran.com/api/v4/verses/by_key/{key}"
        f"?words=true&word_fields=text_uthmani,transliteration,text"
    )
    url_tr = url_en + "&language=tr"
    j_en = _qcom_words_get_json(session, url_en)
    time.sleep(0.45)
    j_tr = _qcom_words_get_json(session, url_tr)
    en_rows = _parse_qcom_word_rows(j_en)
    tr_by_pos = {r["pos"]: r["gloss"] for r in _parse_qcom_word_rows(j_tr)}
    return [
        {
            "ar": r["ar"],
            "lat": r["lat"],
            "en_word": r["gloss"],
            "tr_word": tr_by_pos.get(r["pos"], ""),
        }
        for r in en_rows
    ]


def word_reading_and_grammar_notes(ar: str, lat: str, en_word: str, tr_word: str) -> list[str]:
    """Heuristic TR notes: tecvid + basit nahiv (not scholarly i'rab)."""
    notes: list[str] = []
    a = ar or ""

    if "\u0651" in a:
        notes.append("Şedde (ّ): Ünsüzü gerektiği gibi iki kez tutun; öncesindeki ünlü şeddeye ‘táşrif’ eder.")
    if "\u0671" in a:
        notes.append("ٱ (Elif vasla): Kelime başında genelde ünsüzle akar; kuralları tecvid dersinde netleşir.")
    if a.startswith("ٱل") or a.startswith("ال"):
        notes.append("ال: Tanımlı isim (âlem). Lam genelde ‘şemsî/kamerî’ tecvidle okunur (örn. ar-Rahmân).")
    if any(x in a for x in ("\u064b", "\u064c", "\u064d")):
        notes.append("Tenvîn (ً ٍ ٌ): Kelime tamamında -an/-in/-un benzeri; duruş ve i‘rab ile değişebilir.")
    if "\u0652" in a:
        notes.append("Sükûn (ْ): Harfi kısa tutun; sonraki harfle cezm/med ilişkisine dikkat.")
    if "\u0670" in a:
        notes.append("Üst elif (ٰ): Önceki harfi uzatır (med — uzatma süresi tecvide göre).")
    if any(x in a for x in "ۚۖۛۗ"):
        notes.append("Vakıf işareti: Mushaf’ta anlam sınırı için durak; klasik telâvvüh rehberiyle çalışın.")
    if any(x in a for x in "أإؤئء"):
        notes.append("Hemze taşıyan yazım: Ünlü kalitesi ve medde hemze hoca eşliğinde doğrulanır.")
    if "ة" in a:
        notes.append("Tâ merbûta (ة): Durakta çoğu kez ‘h’, cümle ortasında ‘t’ eğilimi; dişil isim göstergesi.")
    if a.endswith("ى"):
        notes.append("Elif makûsû (ى): Sözlük kökü ve fiil kalıplarında ‘yâ’ ile karıştırmamak için nahiv çalışın.")
    if "\u0653" in a or "ٓ" in a:
        notes.append("Medd işareti (ٓ): Önceki ünlüyü uzatır; süre (2/4/6 müdd) tecvid ile belirlenir.")
    if a.startswith("لِل"):
        notes.append("لِلْ…: لِ + ال birleşimi; ‘için / …a âit’ zincirleri (كَمَا لِلْمُتَّقِينَ). Okunuşta ‘lil’ ile kaynaşım.")
    elif a.startswith("لِ"):
        notes.append("لِ- başı: Yönelme / ‘için’ zincirleri; sonraki kelime ال ile başlıyorsa lam tecvidine dikkat.")
    if a.startswith("بِ"):
        notes.append("بِ- başı: ‘birlikte / ile’ veya ‘içinde’ gibi anlamlarda harf-i cer; sonraki kelimeye bağlanır (idğam/açık).")
    if a.startswith("فَ") or a.startswith("فِ"):
        notes.append("ف- başı: Cümleleri bağlayan ‘sonra / bu yüzden’ vb. anlamlar taşıyabilir; önceki ayete bakın.")

    el = (en_word or "").lower().strip()
    if el.startswith("(is)") or el.startswith("(are)"):
        notes.append("Çeviri notu: (is)/(are) çoğu kez Arapça isim cümlesinde ‘gizli yükleme’; sıra İngilizceden farklıdır.")
    if el.startswith("who ") or el.startswith("those who"):
        notes.append(
            "‘Who / those who’: Göreli cümle; Arapça’da tanımlayıcı + sıfat tamamlayıcı yapısı yaygındır — nahiv kitabıyla işleyin."
        )
    if " not " in f" {el} " or el.startswith("no ") or " no " in el:
        notes.append("Olumsuzluk: لَا / مَا / لَم / لَن aileleri farklı zaman ve istek bildirir; bu kelimede çoğu zaman لَا görülür.")
    if "the " in el and len(el) < 40:
        notes.append("‘The’: Belirlilik çoğu kez ال veya idâfa ile gelir; tenkîr (تَنْوِين) azalır.")
    if "for " in el[:15] or el.startswith("to ") or " in " in el[:20]:
        notes.append("Edat/anlam: for/to/in çoğu kez لِـ / بِـ / فِي gibi harf-i cer ile kurulur; telâffuzda bağlayıcı ünsüzlere dikkat.")

    if (tr_word or "").strip():
        tw = tr_word.strip()
        if " için" in f" {tw}" or tw.endswith("için") or " ve " in tw:
            notes.append(
                "Türkçe küçük kelime: ‘için / ve’ gibi bağlar Arapça’da harf-i cer veya وَ ile kurulur; birebir kelime sırası beklemeyin."
            )

    out: list[str] = []
    seen: set[str] = set()
    for n in notes:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out[:6]


# (Ayet metninde geçen alt dizi → Türkçe nahiv notu)
_VERSE_AR_GRAMMAR_PATTERNS: list[tuple[str, str]] = [
    (
        "ٱلَّذِينَ",
        "ٱلَّذِينَ: Müzekker çoğul isim belirteci (mâusûl). Önceki cümledeki isim/zamire ‘sıla’ cümlesi bağlar; özne-fiil uyumunu ayette izleyin.",
    ),
    (
        "ٱلَّذِي",
        "ٱلَّذِي: Müzekker tekil isim belirteci; ardından tanımlayıcı cümle gelir (صفة موصوف). İngilizce ‘who/which/that’ kalıplarına benzer ama Arapça bağ ayrıntılıdır.",
    ),
    (
        "ٱلَّتِي",
        "ٱلَّتِي: Müennes tekil isim belirteci; müennes isme bağlanan sıla cümlelerinde görülür.",
    ),
    (
        "إِنَّ",
        "إِنَّ ve benzeri (خَوَاتِمُ إِنَّ): İsim cümle düzeninde haber–mübtedâ ilişkisini kurar; Türkçe tercümeyle kelime sırası genelde örtüşmez — nahiv kitabındaki ‘el-havâtiim’ konusuna bakın.",
    ),
    ("أَنَّ", "أَنَّ: Çoğu kez نَصْبٌ (المفعول به) veya iç cümle başlatır; fiilden sonra gelen ‘أن’ ailesiyle karıştırmayın — bağlama göre ‘ki / -dığını’ hissi verir."),
    ("لَٰكِنَّ", "لَٰكِنَّ: İstisna / karşıtlık bildiren havâtımdan; kabar–ism yeniden düzenlenir."),
    ("كَأَنَّ", "كَأَنَّ: Teşbih / ‘sanki …mış’ yapısında kullanılır; tam çözümlemma için hocayla çalışın."),
    (
        "لَا",
        "لَا: Olumsuzluk ailesinden en sık kardeş; عَرَبِي’de زَمَنْ ve نَوْع (istek/yasak) diğer kardeşler (مَا, لَمْ, لَنْ) ile ayrılır — bu ayette hangi anlamda olduğuna bağlı.",
    ),
    (" لَمْ", "لَمْ: Geçmişi (ناقِس) cezim ile nafi yapar; fiilde سُكُون görürsünüz — لَمْ يَفْعَل kalıbı."),
    (
        " لَنْ",
        "لَنْ: Geleceğe yönelik nâfi (olumsuzluk); fiil genelde مجزوم görünür (مضارع bağlamında لَنْ يَفْعَل … biçimi).",
    ),
    (" مَا ", "مَا: Olumsuzluk veya bağlaç/isim olarak bağlama göre değişir; nafile ile sıfat/nakıs fiil arasında ayrım yapın."),
    ("أَمْ", "أَمْ: İkilem (veya) soru yapısında kullanılır; أَمْ … أَمْ kalıplarına dikkat."),
    ("هَلْ", "هَلْ: Evet/hayır soru partikülü; cevap genelde اَوْ مُخَفَّفَة ile özelleşir."),
    ("لَوْ", "لَوْ: Şart cümlesi başlatıcılarından (غير واقع); جَزَاء ile tamamlanır — klasik şart dersleriyle çalışın."),
    ("عَلَى", "عَلَى: Arapça’da كَثْرَةُ الْجُلُوسِ gibi ‘üzerinde/ karşısında’ anlamlarında حَرْفُ جَرّ; kelime جنس görür."),
    ("إِلَى", "إِلَى: Yönelme (إلي/حتى) harfleri; تَبْيِين ومصدر bağlarında sık görülür."),
    ("مِنْ", "مِنْ: Kaynak/ayrılma/başlangıç; بابُ مِنْ dersinde genişler."),
    ("عَنْ", "عَنْ: Uzaklaşma / konu hakkında; تَجَرُّب dersleriyle birlikte işlenir."),
    ("بِمَا", "بِمَا: بِ + مَا birleşimi;‘şu sebeple / onunla’ gibi sebep–bağ kurar."),
    ("فِي", "فِي: ‘İçinde / konusunda’; zaman–mekân haberlerinde yer tutar."),
    ("لِّ", "لِ: Yönelme / mülkiyet zincirinde لِـ; كَمَا لِـ… kalıpları tefsirî bağ taşır."),
    ("إِذْ", "إِذْ: Zaman bağlacı (‘… zamanında’); ماضي bağlamında sık."),
    ("إِذَا", "إِذَا: ‘Ne zaman … ise’ şart/zaman; جواب بيان gelir."),
    ("ٱذْكُرُوا", "امر (أمر): Emir kipi; çoğul نُون ile اذكروا gibi — hitap ve tazarru kullanımı ayette önemlidir."),
    ("ٱتَّقُوا", "ٱتَّقُوا: VIII. bab veya تَفَعَّل kalıbı ile ‘sakınmak’ kökü; teşrif dersinde işlenir."),
    ("يُؤْمِنُونَ", "يُؤْمِنُونَ: Müzari’ ثلاثي مَجْهُول/مَعْلُوم ayrımına dikkat; واو جَمَاعَة öznesi."),
    ("يَخْتَصِّ", "تَفَعَّل / افتعال babları: Anlam yoğunlaşması; teşrif tablosu ile eşleştirin."),
]


def verse_level_pattern_grammar_turkish(ar: str) -> list[str]:
    """Ayet metnine göre sabit nahiv/yapı notları (metin alt dizesi eşleşmesi)."""
    if not ar:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for needle, tip in _VERSE_AR_GRAMMAR_PATTERNS:
        if needle in ar and tip not in seen:
            seen.add(tip)
            out.append(tip)
    if ar.count("ٱل") >= 2 or ar.count("ال") >= 2:
        msg = "Birden fazla ال: Tanımlılık veya idâfa zinciri mümkün; hangi kelimenin hangisine bağlandığını (مضاف/مضاف إليه) tabloya yazarak çözün."
        if msg not in seen:
            out.append(msg)
    if ar.count("وَ") >= 2:
        msg = "Birden fazla وَ: Cümle veya öğe zinciri; anlam kesitleri için vakıf ve tefsirî bağ önemlidir."
        if msg not in seen:
            out.append(msg)
    return out


def aggregate_word_grammar_from_row(row: dict) -> list[str]:
    words = row.get("words") or []
    seen: set[str] = set()
    out: list[str] = []
    for w in words:
        for tip in word_reading_and_grammar_notes(
            w.get("ar", ""),
            w.get("lat", ""),
            w.get("en_word", ""),
            w.get("tr_word", ""),
        ):
            if tip not in seen:
                seen.add(tip)
                out.append(tip)
    return out[:16]


def openai_verse_grammar_html(row: dict) -> str:
    """İsteğe bağlı: OpenAI ile ayete özel Türkçe nahiv açıklaması (tefsir yok)."""
    load_dotenv(ROOT / ".env")
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return ""
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini").strip()
    surah, ayah = row["surah"], row["ayah"]
    words = row.get("words") or []
    wbw_parts = [
        f"{w.get('ar', '')} [{w.get('lat', '')}] → TR:{w.get('tr_word', '')} / EN:{w.get('en_word', '')}"
        for w in words
    ]
    wbw = "\n".join(wbw_parts)[:6000]
    user_text = (
        f"Ayet konumu: {surah}:{ayah}\n"
        f"Arapça (Uthmani):\n{row.get('ar', '')}\n\n"
        f"Türkçe (Diyanet):\n{row.get('tr', '')}\n\n"
        f"İngilizce:\n{row.get('en', '')}\n\n"
        f"Latin (satır):\n{row.get('translit_line', '')}\n\n"
        f"Kelime listesi:\n{wbw}\n\n"
        "Yalnızca bu ayette görünen nahiv, sarf, cümle yapısı ve okuma için gerekli dilbilgisini "
        "Türkçede 5–8 kısa paragrafta anlat. Tefsir, sebep-i nüzul, fıkıh, hikâye ve hadis YAZMA. "
        "Emin olmadığın yerde ‘mutlaka bir Arapça öğretmeniyle doğrula’ de. Düz metin; başlık yok; paragraflar arasında boş satır bırak."
    )
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "temperature": 0.25,
        "max_tokens": 900,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Sen Kur’an Arapçasında nahiv ve sarf konusunda yardımcı bir öğretmensin. "
                    "Kullanıcıya verilen tek ayet üzerinde çalış. Asla tefsir, tarihî olay veya hukum üretme. "
                    "Sadece dilbilgisi ve cümle örgüsü."
                ),
            },
            {"role": "user", "content": user_text},
        ],
    }
    try:
        r = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=120,
        )
        r.raise_for_status()
        data = r.json()
        raw = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
    except Exception as e:
        print(f"OpenAI grammar skip {surah}:{ayah}: {e}", file=sys.stderr)
        return ""
    if not raw.strip():
        return ""
    blocks = [p.strip() for p in raw.replace("\r\n", "\n").split("\n\n") if p.strip()]
    return "".join(f"<p style=\"margin:0 0 10px\">{escape_html(p)}</p>" for p in blocks)


def build_deep_grammar_section_html(row: dict) -> str:
    """Diyanet paragrafının altına: desenler + özet + isteğe bağlı AI."""
    parts: list[str] = []
    patterns = verse_level_pattern_grammar_turkish(row.get("ar", ""))
    if patterns:
        parts.append(
            '<h4 style="margin:16px 0 8px;color:#1e3a5f">Ayet metnine bağlı nahiv / yapı işaretleri</h4>'
        )
        parts.append(
            '<ul style="margin:0 0 12px;padding-left:20px;font-size:13px;line-height:1.5">'
            + "".join(f"<li>{escape_html(p)}</li>" for p in patterns)
            + "</ul>"
        )
    agg = aggregate_word_grammar_from_row(row)
    if agg:
        parts.append(
            '<h4 style="margin:16px 0 8px;color:#1e3a5f">Kelime tablosunun derin özeti (tekrarlar birleştirildi)</h4>'
        )
        parts.append(
            '<ul style="margin:0 0 12px;padding-left:20px;font-size:12px;line-height:1.45">'
            + "".join(f"<li>{escape_html(a)}</li>" for a in agg)
            + "</ul>"
        )
    ai_html = openai_verse_grammar_html(row)
    if ai_html:
        parts.append(
            '<h4 style="margin:16px 0 8px;color:#1e3a5f">Geniş dilbilgisi (AI taslağı — mutlaka hoca ile doğrulayın)</h4>'
        )
        parts.append(
            f'<div style="font-size:13px;line-height:1.55;border-left:3px solid #64748b;padding-left:12px">{ai_html}</div>'
        )
    if not parts:
        return ""
    disclaimer = (
        '<p style="font-size:11px;color:#64748b;margin:14px 0 0">'
        "Tam iʿrâb, tecvid ve tefsir için klasik kaynak ve âlim şarttır. "
        "AI bölümü yalnızca yardımcı taslaktır.</p>"
    )
    return (
        '<div style="direction:ltr;text-align:left;margin-top:12px;padding:14px;background:#f8fafc;'
        'border:1px solid #e2e8f0;border-radius:8px">'
        + "".join(parts)
        + disclaimer
        + "</div>"
    )


def _strip_code_fence(s: str) -> str:
    s = (s or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\s*", "", s)
        s = re.sub(r"\s*```\s*$", "", s)
    return s.strip()


def _parse_guidance_sections(raw: str) -> dict[str, str]:
    raw = _strip_code_fence(raw)
    out: dict[str, str] = {"NEREDEN": "", "MESAJ": "", "OGREN": ""}
    current: str | None = None
    buf: list[str] = []
    for line in raw.splitlines():
        u = line.strip().upper()
        if u == "===NEREDEN===":
            if current:
                out[current] = "\n".join(buf).strip()
            current = "NEREDEN"
            buf = []
        elif u == "===MESAJ===":
            if current:
                out[current] = "\n".join(buf).strip()
            current = "MESAJ"
            buf = []
        elif u == "===OGREN===":
            if current:
                out[current] = "\n".join(buf).strip()
            current = "OGREN"
            buf = []
        else:
            buf.append(line)
    if current:
        out[current] = "\n".join(buf).strip()
    return out


def _guidance_dict_to_html(parts: dict[str, str], raw_fallback: str) -> str:
    ned, mes, ogr = parts.get("NEREDEN", ""), parts.get("MESAJ", ""), parts.get("OGREN", "")
    if not (ned or mes or ogr) and raw_fallback.strip():
        mes = raw_fallback.strip()
    blocks: list[str] = []
    if ned:
        blocks.append(
            '<h5 style="margin:10px 0 6px;color:#78350f;font-size:14px">'
            "Bu ayet nereden gelir? (genel bağlam)</h5>"
        )
        for para in [p.strip() for p in ned.split("\n\n") if p.strip()]:
            blocks.append(
                f'<p style="margin:0 0 8px;font-size:13px;line-height:1.55">{escape_html(para)}</p>'
            )
    if mes:
        blocks.append(
            '<h5 style="margin:10px 0 6px;color:#78350f;font-size:14px">Temel mesaj</h5>'
        )
        for para in [p.strip() for p in mes.split("\n\n") if p.strip()]:
            blocks.append(
                f'<p style="margin:0 0 8px;font-size:13px;line-height:1.55">{escape_html(para)}</p>'
            )
    if ogr:
        blocks.append(
            '<h5 style="margin:10px 0 6px;color:#78350f;font-size:14px">'
            "Bu ayetle ne öğrenmeliyiz?</h5>"
        )
        items: list[str] = []
        for line in ogr.splitlines():
            t = line.strip()
            if not t:
                continue
            if t[0] in "-*•·":
                t = t[1:].strip()
                if t.startswith(" "):
                    t = t.strip()
            if t:
                items.append(t)
        if not items and ogr.strip():
            items = [ogr.strip()]
        blocks.append('<ul style="margin:0;padding-left:20px;font-size:13px;line-height:1.5">')
        blocks.extend(f"<li>{escape_html(it)}</li>" for it in items)
        blocks.append("</ul>")
    return "".join(blocks)


def openai_verse_guidance_html(row: dict) -> str:
    """İsteğe bağlı: ayetin yeri, teması ve öğrenme maddeleri (Türkçe, tefsir iddiası yok)."""
    load_dotenv(ROOT / ".env")
    if os.environ.get("OPENAI_GUIDANCE", "1").strip() == "0":
        return ""
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return ""
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini").strip()
    surah, ayah = row["surah"], row["ayah"]
    sname = surah_name_tr(surah)
    total = AYAH_COUNT[surah] if 0 < surah < len(AYAH_COUNT) else "?"
    user_text = (
        f"Ayet konumu: {surah}:{ayah}. Türkçe sure adı: {sname}. Bu surede toplam ayet sayısı (yaklaşık): {total}.\n\n"
        f"Arapça (Uthmani):\n{row.get('ar', '')}\n\n"
        f"Türkçe (Diyanet meali):\n{row.get('tr', '')}\n\n"
        f"İngilizce meali:\n{row.get('en', '')}\n\n"
        "Görev: Bu tek ayet için Türkçede öğrenme odaklı özet. "
        "Tefsir âlimi gibi kesin hüküm verme; tartışmalı sebep-i nüzul rivayetleri, isnadlı hadis ve fıkıh fetvası yazma. "
        "Surenin genel konusuna ve ayetin o konudaki yerine en fazla 2–4 cümleyle değin (yaygın müfredat düzeyinde, ihtiyatlı). "
        "Ana mesajı Diyanet ve İngilizce meal ifadeleriyle uyumlu şekilde açıkla. "
        "Son bölümde 3–5 madde: uygulanabilir ders (ahlak, tevekkül, adalet, dua, aile, toplum vb. — ayete uygun ne varsa).\n\n"
        "Çıktı formatı (başlık satırları harfi harfine aynı olsun):\n"
        "===NEREDEN===\n"
        "...\n\n"
        "===MESAJ===\n"
        "...\n\n"
        "===OGREN===\n"
        "- ...\n"
        "- ...\n"
    )
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "temperature": 0.35,
        "max_tokens": 700,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Sen Kur’an okuyucularına yardımcı bir rehbersin. "
                    "Yalnızca verilen ayet metinlerine dayanarak tema ve öğrenme maddeleri üret; "
                    "tarihî rivayet uydurma, mezhep tartışması veya teville derin tefsir yazma. "
                    "Kısa, net Türkçe kullan."
                ),
            },
            {"role": "user", "content": user_text},
        ],
    }
    try:
        r = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=120,
        )
        r.raise_for_status()
        data = r.json()
        raw = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
    except Exception as e:
        print(f"OpenAI guidance skip {surah}:{ayah}: {e}", file=sys.stderr)
        return ""
    if not raw.strip():
        return ""
    time.sleep(0.12)
    parsed = _parse_guidance_sections(raw)
    return _guidance_dict_to_html(parsed, raw)


def fallback_guidance_inner_html(row: dict) -> str:
    """API yokken: meal alıntısı + genel çalışma maddeleri."""
    tr = (row.get("tr") or "").strip()
    excerpt = tr[:320] + ("…" if len(tr) > 320 else "")
    blocks = [
        '<h5 style="margin:10px 0 6px;color:#78350f;font-size:14px">Temel mesaj (Diyanet mealinden)</h5>',
        f'<p style="margin:0 0 8px;font-size:13px;line-height:1.55">'
        f"Tema doğrudan mealde geçer: <em>{escape_html(excerpt)}</em>"
        f"{' (tam metin yukarıda.)' if len(tr) > 320 else ''}</p>",
        '<h5 style="margin:10px 0 6px;color:#78350f;font-size:14px">Bu ayetle ne öğrenmeliyiz? (çalışma önerisi)</h5>',
        "<ul style=\"margin:0;padding-left:20px;font-size:13px;line-height:1.5\">",
        "<li>Meali sesli okuyup her kelimeyi kelime tablosuyla eşleştirin.</li>",
        "<li>Aynı surede birkaç ayet öncesi/sonrasını okuyup konu bağını kendiniz çıkarın.</li>",
        "<li>Tefsir ve bağlam için Diyanet veya seçtiğiniz güvenilir kaynağı hoca ile okuyun.</li>",
        "</ul>",
    ]
    return "".join(blocks)


def build_verse_guidance_section_html(row: dict) -> str:
    s, a = row["surah"], row["ayah"]
    name = surah_name_tr(s)
    total = AYAH_COUNT[s] if 0 < s < len(AYAH_COUNT) else "?"
    placement = (
        f"<strong>Kur’an’daki yeri:</strong> {escape_html(name)} Suresi, <strong>{a}. ayet</strong> "
        f"(bu surede toplam <strong>{total}</strong> ayet). "
        "Günlük e-posta diziniz Bakara’dan başlayıp Nâs suresine uzanır; bu ayet o sıranın bir parçasıdır."
    )
    inner = openai_verse_guidance_html(row)
    if not inner:
        inner = fallback_guidance_inner_html(row)
    return (
        '<div style="direction:ltr;text-align:left;margin-top:14px;padding:14px;background:#fffbeb;'
        'border:1px solid #fde68a;border-radius:8px">'
        '<h4 style="margin:0 0 8px;color:#92400e;font-size:15px">Ayetin kaynağı, mesajı ve öğrenilecekler</h4>'
        f'<p style="margin:0 0 12px;font-size:13px;line-height:1.55">{placement}</p>'
        f"{inner}"
        '<p style="font-size:11px;color:#a8a29e;margin:12px 0 0">'
        "Özet niteliğindedir. Rivayet ayrıntısı, ictihad ve derin tefsir için kitap ve âlime başvurun.</p>"
        "</div>"
    )


def build_html(rows: list[dict]) -> tuple[str, str]:
    rows = sorted(rows, key=lambda r: (r["surah"], r["ayah"]))
    if not rows:
        return "", ""
    r0, r1 = rows[0], rows[-1]
    range_label = f"Surah {r0['surah']} Ayah {r0['ayah']} — Surah {r1['surah']} Ayah {r1['ayah']}"
    subject = f"Quran study — {range_label}"

    harakat = """
<div style="direction:ltr;text-align:left;font-size:14px;background:#f7f7f2;padding:12px;border-radius:8px;margin:16px 0;">
<strong>Okuma / Harakāt — kısa rehber</strong>
<ul style="margin:8px 0;padding-left:18px;">
<li><span dir="rtl">َ</span> <strong>fetha</strong> (üst) — kısa <em>a</em> · <span dir="rtl">ِ</span> <strong>kesra</strong> (alt) — kısa <em>i</em> · <span dir="rtl">ُ</span> <strong>damme</strong> — kısa <em>u</em></li>
<li><span dir="rtl">ْ</span> <strong>sükûn</strong> — ünsüzden sonra sessizlik · <span dir="rtl">ّ</span> <strong>şedde</strong> — harfi iki kez tut</li>
<li><span dir="rtl">ً ٍ ٌ</span> <strong>tenvîn</strong> — -an / -in / -un (Kelime sonunda çoğu zaman <em>n</em> ile okunur.)</li>
<li>Mürekkep harfler (ا ل م gibi): Kur’an metninde <strong>elif, lam, mim</strong> tek tek sayılır; tecvid için bir hoca / ses kaydı şart.</li>
</ul>
<p style="margin:0;color:#444;font-size:13px;">Bu e-posta <strong>kelime kelime İngilizce gösterim</strong> + <strong>Latin harflerle okunuş</strong> verir.
<strong>Tam iʿrāb ve tefsir</strong> bu e-postada yoktur; <strong>kelime kelime TR/EN gösterimi</strong> Quran.com kaynaklıdır. Derin nahiv için Medine / Bayyinah gibi müfredat + hoca kullanın.</p>
</div>
"""

    html = [
        '<!DOCTYPE html><html><head><meta charset="utf-8"></head><body>',
        '<div style="direction:ltr;text-align:left;font-family:system-ui,sans-serif">',
        "<h2>Günlük Kur’an çalışması (okuma + kelimeler)</h2>",
        f"<p><strong>Aralık:</strong> {escape_html(range_label)}</p>",
        "<p style=\"color:#555;font-size:14px\">Ayet: alquran.cloud (Uthmani, Diyanet, Sahih intl). "
        "Kelime tablosu: api.quran.com (Latin + İngilizce gösterim + Türkçe gösterim). "
        "<strong>‘Okuma & dilbilgisi’</strong> sütunu otomatik ipuçlarıdır — hoca ile doğrulayın.</p>",
        harakat,
    ]
    for row in rows:
        sno, ano = row["surah"], row["ayah"]
        html.append(f'<hr><h3 id="{sno}-{ano}" style="direction:ltr;text-align:left">Surah {sno} — Ayah {ano}</h3>')

        html.append(
            f'<p style="direction:rtl;font-size:24px;line-height:2.2;font-family:\'Amiri\',\'Scheherazade New\',Georgia,serif">'
            f'{row["ar"]}</p>'
        )

        tl = row.get("translit_line") or ""
        if tl:
            html.append(
                f'<p style="direction:ltr;text-align:left;font-size:15px;color:#333"><strong>Latin (ayet, yaklaşık)</strong><br>'
                f'<span style="font-family:Georgia,serif">{escape_html(tl)}</span></p>'
            )

        words = row.get("words") or []
        if words:
            html.append(
                '<p style="direction:ltr"><strong>Kelime kelime</strong> '
                "(Arapça | Latin | EN gösterim | TR gösterim | okuma/nahiv ipuçları)</p>"
            )
            html.append(
                '<table border="1" cellpadding="6" cellspacing="0" '
                'style="border-collapse:collapse;font-size:13px;table-layout:fixed;width:100%">'
            )
            html.append(
                '<tr>'
                '<th style="width:32px">#</th>'
                '<th dir="rtl" style="width:14%">الكلمة</th>'
                '<th style="width:12%">Latin</th>'
                '<th style="width:15%">EN (gloss)</th>'
                '<th style="width:18%">TR (gloss)</th>'
                '<th style="width:38%">Okuma &amp; dilbilgisi (hatırlatma)</th>'
                "</tr>"
            )
            for i, w in enumerate(words, start=1):
                tips = word_reading_and_grammar_notes(
                    w.get("ar", ""),
                    w.get("lat", ""),
                    w.get("en_word", ""),
                    w.get("tr_word", ""),
                )
                tips_html = (
                    "<ul style=\"margin:4px 0;padding-left:18px;font-size:11px;line-height:1.35\">"
                    + "".join(f"<li>{escape_html(t)}</li>" for t in tips)
                    + "</ul>"
                )
                html.append(
                    "<tr>"
                    f"<td>{i}</td>"
                    f'<td dir="rtl" style="font-size:17px;word-wrap:break-word">{w.get("ar","")}</td>'
                    f"<td style=\"word-wrap:break-word\">{escape_html(w.get('lat',''))}</td>"
                    f"<td style=\"word-wrap:break-word\">{escape_html(w.get('en_word',''))}</td>"
                    f"<td style=\"word-wrap:break-word\">{escape_html(w.get('tr_word',''))}</td>"
                    f"<td style=\"vertical-align:top;background:#fafafa\">{tips_html}</td>"
                    "</tr>"
                )
            html.append("</table>")

        html.append(
            f'<p style="direction:ltr;text-align:left;margin-top:14px"><strong>English (full ayah)</strong><br>'
            f"{escape_html(row.get('en') or '')}</p>"
        )
        html.append(
            f'<p style="direction:ltr;text-align:left"><strong>Türkçe — Diyanet (tam ayet)</strong><br>'
            f"{escape_html(row.get('tr') or '')}</p>"
        )
        deep_g = build_deep_grammar_section_html(row)
        if deep_g:
            html.append(deep_g)
        html.append(build_verse_guidance_section_html(row))

    html.append(
        '<hr><p style="font-size:12px;color:#666">Tarihî sebep-i nüzul, fıkıh yorumu ve hadis isnadı bu otomatik '
        "özet içinde <strong>verilmez</strong>. Tefsir için Diyanet / İbn Kesir / okul kitabı gibi kaynaklardan "
        "hoca ile çalışınız.</p>"
    )
    html.append("</div></body></html>")
    return subject, "".join(html)


def send_mail(subject: str, html: str, text_plain: str) -> None:
    load_dotenv(ROOT / ".env")
    host = os.environ.get("SMTP_HOST", "").strip()
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER", "").strip()
    password = os.environ.get("SMTP_PASSWORD", "").strip()
    mail_from = os.environ.get("MAIL_FROM", user).strip()
    mail_to = os.environ.get("MAIL_TO", "").strip()

    if not all([host, user, mail_from, mail_to]):
        print("Missing SMTP settings. Copy config.example.env to .env and fill in values.", file=sys.stderr)
        sys.exit(1)
    if not password:
        print(
            f"SMTP_PASSWORD is empty. Edit {(ROOT / '.env').resolve()} and set your mail app password.",
            file=sys.stderr,
        )
        sys.exit(1)

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = mail_from
    msg["To"] = mail_to
    msg.set_content(text_plain)
    msg.add_alternative(html, subtype="html")

    context = ssl.create_default_context()
    with smtplib.SMTP(host, port, timeout=60) as server:
        server.starttls(context=context)
        server.login(user, password)
        server.send_message(msg)


def main() -> None:
    load_dotenv(ROOT / ".env")
    chunk = int(os.environ.get("CHUNK_SIZE", "20"))

    state = load_state()
    surah, ayah = state["surah"], state["ayah"]

    if surah > END_SURAH:
        if state.get("completion_email_sent"):
            print("Program already completed; no email sent. Delete data/progress.json to restart.")
            return
        subject = "Quran study — sequence finished"
        plain = (
            "You have completed Al-Baqarah through An-Nas. "
            "Delete data/progress.json in quran-daily-free to start again."
        )
        send_mail(
            subject,
            f"<html><body><p>{escape_html(plain)}</p></body></html>",
            plain,
        )
        state["completion_email_sent"] = True
        save_state(state)
        print("Sent completion email.")
        return

    refs, next_s, next_a = next_chunk(surah, ayah, chunk)
    if not refs:
        print("No verses in chunk; nothing to do.")
        return

    session = requests.Session()
    rows: list[dict] = []
    for i, (s, a) in enumerate(refs):
        row = fetch_ayah(session, s, a)
        time.sleep(0.6)
        try:
            row["words"] = fetch_words_qcom(session, s, a)
        except Exception as e:
            row["words"] = []
            print(f"Warning: WBW failed {s}:{a}: {e}", file=sys.stderr)
        rows.append(row)
        if i + 1 < len(refs):
            time.sleep(0.85)

    subject, html = build_html(rows)
    plain_lines = [
        subject,
        "",
        "Includes: harakat guide, Latin line, word table (AR | Latin | EN gloss | TR gloss | reading/grammar hints), full EN/TR ayah, per-verse grammar box, per-verse placement/theme/lessons summary.",
        "Sources: api.alquran.cloud, api.quran.com — not a substitute for a teacher or classical tafsir.",
        "",
    ]
    for r in sorted(rows, key=lambda x: (x["surah"], x["ayah"])):
        en = r.get("en") or ""
        if len(en) > 120:
            plain_lines.append(f"Surah {r['surah']}:{r['ayah']} | EN: {en[:120]}…")
        else:
            plain_lines.append(f"Surah {r['surah']}:{r['ayah']} | EN: {en}")
    plain = "\n".join(plain_lines)

    send_mail(subject, html, plain)

    state["surah"] = next_s
    state["ayah"] = next_a
    save_state(state)
    print(f"Sent: {subject}")


if __name__ == "__main__":
    main()
