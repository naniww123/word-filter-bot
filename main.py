import asyncio
import audioop
import io
import json
import os
import re
import sys
import threading
import time
import unicodedata
from collections import defaultdict, deque
from pathlib import Path
from janome.tokenizer import Tokenizer
import numpy as np
import soundfile as sf
import speech_recognition as sr
from discord.ext import voice_recv

# Windows環境でのコンソール文字化け対策
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

# soundfile による高速・堅牢な FLAC エンコード（外部 flac.exe 不要）
try:
    def _custom_get_flac_data(self, convert_rate=None, convert_width=None):
        raw_bytes = self.get_raw_data(convert_rate, convert_width)
        rate = self.sample_rate if convert_rate is None else convert_rate
        data = np.frombuffer(raw_bytes, dtype=np.int16)
        buf = io.BytesIO()
        sf.write(buf, data, rate, format="FLAC")
        return buf.getvalue()

    sr.AudioData.get_flac_data = _custom_get_flac_data
except Exception as e:
    print(f"[WARNING] soundfile 初期化スキップ: {e}")
speech_recognizer = sr.Recognizer()
speech_recognizer.operation_timeout = 8.0

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

# .env ファイルの読み込み
load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")

# 設定
NG_WORDS_FILE = Path(__file__).parent / "ng_words.txt"
GUILD_SETTINGS_FILE = Path(__file__).parent / "guild_settings.json"
DEFAULT_REPLACEMENT_TEXT = "うわっ⚡"
REPLACEMENT_TEXT = DEFAULT_REPLACEMENT_TEXT  # 後方互換用

# ========================================================
# Render.com / 常時起動用ヘルスチェックWebサーバー
# ========================================================
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"OK - Discord Bot is running!")

    def log_message(self, format, *args):
        pass

def run_health_check_server():
    port = int(os.getenv("PORT", 8080))
    try:
        server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
        print(f"[INFO] ヘルスチェック用Webサーバー起動 (Port: {port})")
        server.serve_forever()
    except Exception as e:
        print(f"[WARNING] ヘルスチェックサーバーの起動スキップ: {e}")

threading.Thread(target=run_health_check_server, daemon=True).start()


# 形態素解析器の初期化
print("[INFO] 形態素解析エンジン (Janome) を初期化中...")
tokenizer = Tokenizer()
# 初回ウォームアップ（辞書読み込みのオーバーヘッドを起動時に済ませる）
list(tokenizer.tokenize("テスト"))
print("[INFO] 形態素解析エンジンの準備が完了しました。")

# ローマ字（ヘボン式・訓令式）変換テーブル
ROMAJI_MAP = {
    'kya': 'きゃ', 'kyu': 'きゅ', 'kyo': 'きょ',
    'sha': 'しゃ', 'shu': 'しゅ', 'sho': 'しょ', 'sya': 'しゃ', 'syu': 'しゅ', 'syo': 'しょ',
    'cha': 'ちゃ', 'chu': 'ちゅ', 'cho': 'ちょ', 'tya': 'ちゃ', 'tyu': 'ちゅ', 'tyo': 'ちょ',
    'nya': 'にゃ', 'nyu': 'にゅ', 'nyo': 'にょ',
    'hya': 'ひゃ', 'hyu': 'ひゅ', 'hyo': 'ひょ',
    'mya': 'みゃ', 'myu': 'みゅ', 'myo': 'みょ',
    'rya': 'りゃ', 'ryu': 'りゅ', 'ryo': 'りょ',
    'gya': 'ぎゃ', 'gyu': 'ぎゅ', 'gyo': 'ぎょ',
    'ja': 'じゃ', 'ju': 'じゅ', 'jo': 'じょ', 'jya': 'じゃ', 'jyu': 'じゅ', 'jyo': 'じょ',
    'zya': 'じゃ', 'zyu': 'じゅ', 'zyo': 'じょ',
    'bya': 'びゃ', 'byu': 'びゅ', 'byo': 'びょ',
    'pya': 'ぴゃ', 'pyu': 'ぴゅ', 'pyo': 'ぴょ',
    'shi': 'し', 'si': 'し', 'chi': 'ち', 'ti': 'ち', 'tsu': 'つ', 'tu': 'つ',
    'fu': 'ふ', 'hu': 'ふ', 'ji': 'じ', 'zi': 'じ',
    'ca': 'か', 'cu': 'く', 'co': 'こ',
    'ka': 'か', 'ki': 'き', 'ku': 'く', 'ke': 'け', 'ko': 'こ',
    'sa': 'さ', 'su': 'す', 'se': 'せ', 'so': 'そ',
    'ta': 'た', 'te': 'て', 'to': 'と',
    'na': 'な', 'ni': 'に', 'nu': 'ぬ', 'ne': 'ね', 'no': 'の',
    'ha': 'は', 'hi': 'ひ', 'he': 'へ', 'ho': 'ほ',
    'ma': 'ま', 'mi': 'み', 'mu': 'む', 'me': 'め', 'mo': 'も',
    'ya': 'や', 'yu': 'ゆ', 'yo': 'よ',
    'ra': 'ら', 'ri': 'り', 'ru': 'る', 're': 'れ', 'ro': 'ろ',
    'wa': 'わ', 'wo': 'を', 'nn': 'ん',
    'ga': 'が', 'gi': 'ぎ', 'gu': 'ぐ', 'ge': 'げ', 'go': 'ご',
    'za': 'ざ', 'zu': 'ず', 'ze': 'ぜ', 'zo': 'ぞ',
    'da': 'だ', 'di': 'ぢ', 'du': 'づ', 'de': 'で', 'do': 'ど',
    'ba': 'ば', 'bi': 'び', 'bu': 'ぶ', 'be': 'べ', 'bo': 'ぼ',
    'pa': 'ぱ', 'pi': 'ぴ', 'pu': 'ぷ', 'pe': 'ぺ', 'po': 'ぽ',
    'a': 'あ', 'i': 'い', 'u': 'う', 'e': 'え', 'o': 'お',
    'n': 'ん'
}
SORTED_ROMAJI_KEYS = sorted(ROMAJI_MAP.keys(), key=len, reverse=True)

def romaji_to_hira(text: str) -> str:
    """ローマ字（ヘボン式・訓令式）をひらがなに変換する"""
    s = re.sub(r'([bcdfghjklmpqrstvwxyz])\1', r'っ\1', text.lower())
    for k in SORTED_ROMAJI_KEYS:
        s = s.replace(k, ROMAJI_MAP[k])
    return s

def kata_to_hira(text: str) -> str:
    """全角カタカナをひらがなに変換する"""
    result = []
    for char in text:
        code = ord(char)
        if 0x30A1 <= code <= 0x30F6:
            result.append(chr(code - 0x60))
        else:
            result.append(char)
    return "".join(result)

def normalize_text(text: str) -> str:
    """テキストを正規化（半角カナ→全角、全角英数→半角英数、小文字化、カタカナ→ひらがな）"""
    nfkc = unicodedata.normalize("NFKC", text).lower()
    return kata_to_hira(nfkc)

def get_reading_hira(text: str) -> str:
    """テキスト全体の読み（ひらがな）を取得する（漢字→ひらがな変換用）"""
    tokens = tokenizer.tokenize(text)
    readings = []
    for t in tokens:
        r = t.reading if t.reading != '*' else t.surface
        readings.append(kata_to_hira(r))
    return "".join(readings)

# 長音・母音の引き伸ばし正規化用文字セット
A_DAN = "あかさたなはまやらわがざだばぱぁゃ"
I_DAN = "いきしちにひみりぎじぢびぴぃ"
U_DAN = "うくすつぬふむゆるぐずづぶぷぅゅ"
E_DAN = "えけせてねへめれげぜでべぺぇ"
O_DAN = "おこそとのほもよろをごぞどぼぽぉょ"

def normalize_elongated(text: str) -> str:
    """長音（ー〜~）および各段の母音引き伸ばし（ばああか->ばか、しねええ->しね等）を正規化する"""
    s = re.sub(r'[ー〜～~―\-]+', '', text)
    s = re.sub(rf'([{A_DAN}])[あぁ]+', r'\1', s)
    s = re.sub(rf'([{I_DAN}])[いぃ]+', r'\1', s)
    s = re.sub(rf'([{U_DAN}])[うぅ]+', r'\1', s)
    s = re.sub(rf'([{E_DAN}])[えぇ]+', r'\1', s)
    s = re.sub(rf'([{O_DAN}])[おぉ]+', r'\1', s)
    s = re.sub(r'([あ-ん])\1+', r'\1', s)
    return s

# ネットスラング・俗語・頻出暴言の漢字読み仮名＆表記ゆれマッピング
KNOWN_KANJI_VARIANTS = {
    "陰キャ": ["いんきゃ", "いんキャ", "かげきゃ"],
    "陽キャ": ["ようきゃ", "ようキャ"],
    "キョロ充": ["きょろじゅう", "きょろジュウ", "きょろたかし"],
    "リア充": ["りあじゅう", "りあジュウ"],
    "チー牛": ["ちーぎゅう", "チーギュウ", "ちーうし"],
    "チン騎士": ["ちんきし", "チンきし"],
    "老害": ["ろうがい"],
    "黒人": ["こくじん"],
    "障害者": ["しょうがいしゃ"],
    "死ね": ["しね", "しぬ", "しねよ", "しねば", "しねや", "しっね"],
    "生きる価値無し": ["いきるかちなし", "生きる価値なし"],
    "息の根止めてやる": ["いきのねとめてやる"],
    "おな禁": ["おなきん"],
    "乙w": ["おつw", "おつ"],
    "雑魚": ["ざこ", "ざっこ"],
    "消えろ": ["きえろ", "きえれ"],
    "馬鹿": ["ばか", "ばーか"],
    "黙れ": ["だまれ", "だっまれ"],
    "晒す": ["さらす", "さらすぞ", "さらしてやる"],
    "偽善者": ["ぎぜんしゃ"],
    "気違い": ["きちがい"],
    "野獣": ["やじゅう"],
    "野獣先輩": ["やじゅうせんぱい"],
    "淫乱": ["いんらん"],
    "淫夢": ["いんむ"],
    "56す": ["ころす", "ころせ", "ころし", "ころした", "ころして", "56す", "56せ"],
    "しこ": [
        "しころー", "しころう", "しころーぜ", "しころうぜ", "しころ",
        "しこる", "しこれ", "しこり", "しこった", "しこって", "しこりてえ", "しこりてぇ", "しこりてー",
        "しっころー", "しっころう", "しっころーぜ", "しっころうぜ", "しっこる", "しっこれ", "しっこった", "しっこって",
    ],
    "しこる": [
        "しころー", "しころう", "しころーぜ", "しころうぜ", "しころ",
        "しこれ", "しこり", "しこった", "しこって", "しこりてえ", "しこりてぇ", "しこりてー",
        "しっころー", "しっころう", "しっころーぜ", "しっころうぜ", "しっこる", "しっこれ", "しっこった", "しっこって",
    ],
}

# 促音（っ）による強調表現の展開マップ
SOKUON_EXPANSIONS = {
    "ばか": ["ばーか", "ばーーか"],  # 「ばっか」は文脈判定で処理
    "くそ": ["くっそ", "くっそー"],
    "きもい": ["きっも", "きっもい"],
    "うざい": ["うっざ", "うっざい"],
    "きしょい": ["きっしょ", "きっしょい"],
    "くさい": ["くっさ", "くっさい"],
    "ざこ": ["ざっこ"],
    "よわ": ["よっわ"],
    "ださ": ["だっさ"],
    "ぶす": ["ぶっす"],
    "ぼけ": ["ぼっけ"],
    "だまれ": ["だっまれ"],
    "あほ": ["あっほ"],
    "かす": ["かっす"],
    "ごみ": ["ごっみ"],
    "死ね": ["しっね"],
    "しね": ["しっね"],
    "しこ": ["しっこ", "しっころーぜ", "しっころー", "しっころうぜ"],
}

# 安全な促音（っ）除去（「遊んでばっか」「ゲームばっか」等の副助詞用法は保護しつつ、回避用の「っ」を正規化）
def remove_sokuon_safely(text: str) -> str:
    """メッセージから検知回避用の『っ』を除去して正規化する（安全な『ばっか』『ばっかり』は保護）"""
    protected = text
    protected = re.sub(r'([てで])ばっか', r'\1_BAKKA_', protected)
    protected = re.sub(r'ばっかり', '_BAKKARI_', protected)
    protected = re.sub(r'(?:ゲーム|嘘|うそ|失敗|雨|自分|本|仕事|勉強|文句|愚痴|それ|これ|あれ|誰)ばっか', r'_SAFE_BAKKA_', protected)
    removed = re.sub(r'っ+', '', protected)
    return removed.replace('_BAKKA_', 'ばっか').replace('_BAKKARI_', 'ばっかり').replace('_SAFE_BAKKA_', 'ばっか')

# 文字間に挟まれる空白・括弧・区切り記号・装飾文字の除去用パターン（「う ん ち」「う(ん)ち」「う・ん・ち」等）
SYMBOLS_CLASS_RAW = r'[\s　\(\)（）\[\]［］\{\}｛｝【】『』「」〈〉《》〔〕・、。.,/／_\-―~～〜\*＊:;！？!\?\^#\+=&|@＠\$%¥￥w草笑○〇●]'
SYMBOLS_RE = re.compile(SYMBOLS_CLASS_RAW + "+", re.IGNORECASE)

def strip_symbols(text: str) -> str:
    """文字間に挟まれた空白・括弧・記号・装飾文字を除去して1つの連続文字列にする"""
    return SYMBOLS_RE.sub('', text)

# 英語の伏せ字・記号挟み検知パターン（f*ck, f**k, f u c k, s*x, sh*t, b!tch 等）
ENGLISH_OBSCENE_PATTERNS = [
    (re.compile(r'\bf+[\s*._\-!@#$%^&*()]*[u\*xX_0-9]+[\s*._\-!@#$%^&*()]*[c\*xX_0-9]*[\s*._\-!@#$%^&*()]*k+\b', re.I), "fuck"),
    (re.compile(r'\bf+[\*xX_!@#$%^&*()]{2,}k+\b', re.I), "fuck (obfuscated)"),
    (re.compile(r'\bf+[\s*._\-!@#$%^&*()]+u+[\s*._\-!@#$%^&*()]+c+[\s*._\-!@#$%^&*()]+k+\b', re.I), "f u c k"),
    (re.compile(r'\bs+[\s*._\-!@#$%^&*()]*[h\*xX_0-9]+[\s*._\-!@#$%^&*()]*[i\*xX_0-9!|1]+[\s*._\-!@#$%^&*()]*t+\b', re.I), "shit"),
    (re.compile(r'\bb+[\s*._\-!@#$%^&*()]*[i\*xX_0-9!|1]+[\s*._\-!@#$%^&*()]*t+[\s*._\-!@#$%^&*()]*c+[\s*._\-!@#$%^&*()]*h+\b', re.I), "bitch"),
    (re.compile(r'\bs+[\s*._\-!@#$%^&*()]*[e\*xX_0-93]+[\s*._\-!@#$%^&*()]*x+\b', re.I), "sex"),
    (re.compile(r'\bd+[\s*._\-!@#$%^&*()]*[i\*xX_0-9!|1]+[\s*._\-!@#$%^&*()]*c+[\s*._\-!@#$%^&*()]*k+\b', re.I), "dick"),
    (re.compile(r'\bp+[\s*._\-!@#$%^&*()]*u+[\s*._\-!@#$%^&*()]*s+[\s*._\-!@#$%^&*()]*s+[\s*._\-!@#$%^&*()]*y+\b', re.I), "pussy"),
    (re.compile(r'\ba+[\s*._\-!@#$%^&*()]*s+[\s*._\-!@#$%^&*()]*s+[\s*._\-!@#$%^&*()]*h+[\s*._\-!@#$%^&*()]*o+[\s*._\-!@#$%^&*()]*l+[\s*._\-!@#$%^&*()]*e+\b', re.I), "asshole"),
    (re.compile(r'\bn+[\s*._\-!@#$%^&*()]*i+[\s*._\-!@#$%^&*()]*g+[\s*._\-!@#$%^&*()]*g+[\s*._\-!@#$%^&*()]*e+[\s*._\-!@#$%^&*()]*r+\b', re.I), "nigger"),
    (re.compile(r'\bn+[\s*._\-!@#$%^&*()]*i+[\s*._\-!@#$%^&*()]*g+[\s*._\-!@#$%^&*()]*g+[\s*._\-!@#$%^&*()]*a+\b', re.I), "nigga"),
]

KANJI_RE = re.compile(r'[\u4e00-\u9fff]')

def generate_word_variants(word: str) -> set[str]:
    """1つのNGワードから、ひらがな読み・正規化・動詞活用・促音強調などのバリエーションを汎用的に生成する"""
    variants = {word}
    norm_w = normalize_text(word)
    variants.add(norm_w)

    # 既知のスラング辞書から追加
    for key, vlist in KNOWN_KANJI_VARIANTS.items():
        if word == key or norm_w == normalize_text(key):
            for v in vlist:
                variants.add(v)
                variants.add(normalize_text(v))

    # 促音強調マップから追加
    for key, vlist in SOKUON_EXPANSIONS.items():
        if word == key or norm_w == normalize_text(key):
            for v in vlist:
                variants.add(v)
                variants.add(normalize_text(v))

    # Janomeによる読み仮名および動詞活用展開
    try:
        tokens = list(tokenizer.tokenize(word))
        readings = []
        for t in tokens:
            r = t.reading if t.reading != '*' else t.surface
            readings.append(kata_to_hira(r))
        hira_read = "".join(readings)
        variants.add(hira_read)

        # 動詞または語幹の自動活用展開（しこ、煽る、晒す、殴る、ディス等、任意の語に対応）
        stems_to_expand = []
        if tokens:
            last = tokens[-1]
            base = last.base_form if last.base_form != '*' else last.surface
            base_reading = kata_to_hira(last.reading if last.reading != '*' else base)
            prefix_read = "".join(kata_to_hira(t.reading if t.reading != '*' else t.surface) for t in tokens[:-1])
            prefix_surf = "".join(t.surface for t in tokens[:-1])

            # 動詞としての終止形（す・る・く等）
            if last.part_of_speech.startswith("動詞"):
                if base_reading.endswith("す"):
                    stems_to_expand.append((prefix_read + base_reading[:-1], prefix_surf + (base[:-1] if base.endswith("す") else ""), "su"))
                elif base_reading.endswith("る"):
                    stems_to_expand.append((prefix_read + base_reading[:-1], prefix_surf + (base[:-1] if base.endswith("る") else ""), "ru"))
                elif base_reading.endswith("く"):
                    stems_to_expand.append((prefix_read + base_reading[:-1], prefix_surf + (base[:-1] if base.endswith("く") else ""), "ku"))

        # 俗語語幹（例: 「しこ」「ディス」など）で登録された場合も動詞化（〜る、〜す）を展開
        SLANG_STEMS = {"しこ", "ディス", "でぃす", "あお", "いじめ", "さらし", "なぐり"}
        if norm_w in SLANG_STEMS or word in SLANG_STEMS:
            stems_to_expand.append((hira_read, norm_w, "ru"))
            stems_to_expand.append((hira_read, norm_w, "su"))

        for stem_r, stem_s, vtype in stems_to_expand:
            for stem in set([stem_r, stem_s]):
                if not stem:
                    continue
                # 促音語幹（例: しこ -> しっこ, あお -> あっお）
                s_stem = stem[:-1] + "っ" + stem[-1] if len(stem) >= 2 else stem
                for s in [stem, s_stem]:
                    if vtype == "ru":
                        variants.update([
                            s + "る", s + "れ", s + "れよ", s + "れや", s + "ろ", s + "ろよ",
                            s + "ろー", s + "ろう", s + "ろーぜ", s + "ろうぜ", s + "ろーや",
                            s + "り", s + "りてえ", s + "りてぇ", s + "りてー", s + "りたい",
                            s + "った", s + "って", s + "ってる", s + "ってんじゃ", s + "ってんの",
                        ])
                    elif vtype == "su":
                        variants.update([
                            s + "す", s + "せ", s + "せよ", s + "せや",
                            s + "そー", s + "そう", s + "そーぜ", s + "そうぜ",
                            s + "し", s + "してえ", s + "してぇ", s + "してー", s + "したい",
                            s + "した", s + "して", s + "してる", s + "してんじゃ", s + "してんの",
                        ])
                    elif vtype == "ku":
                        variants.update([
                            s + "く", s + "け", s + "けよ", s + "き", s + "いた", s + "いて", s + "ける",
                            s + "こー", s + "こう", s + "こーぜ", s + "こうぜ"
                        ])
                    elif vtype == "nu":
                        variants.update([s + "ぬ", s + "ね", s + "に", s + "んだ", s + "んで"])
    except Exception:
        pass

    return variants

class ContentFilter:
    """形態素解析と表記ゆれ・読み仮名・ローマ字を統合した高精度NGワードフィルター"""
    def __init__(self, raw_ng_words: list[str]):
        self.raw_words = [w.strip() for w in raw_ng_words if w.strip() and not w.startswith("#")]

        self.match_phrases: list[str] = []
        self.short_words: set[str] = set()
        self.has_shine = False
        self.has_baka = False

        for w in self.raw_words:
            variants = generate_word_variants(w)

            norm_w = normalize_text(w)
            if norm_w in ["死ね", "しね"] or "しね" in variants:
                self.has_shine = True
            if norm_w in ["ばか", "バカ", "馬鹿"]:
                self.has_baka = True

            # 各バリエーションについて登録先を決定
            for v in variants:
                v_clean = v.strip()
                if not v_clean:
                    continue
                v_len = len(v_clean)
                has_kanji = bool(KANJI_RE.search(v_clean))

                # 「死ね」系の2文字表現（しね、死ね）は短語誤爆防止および_check_shineに任せる
                if v_clean in ["しね", "死ね"]:
                    self.short_words.add(v_clean)
                    continue

                # 3文字以上、または漢字を含む単語（例: 黒人、老害、殺す、こくじん、ろうがい、ころす 等）はフレーズ一致に登録
                # 漢字を含む語は日常単語の一部に紛れ込むことはないため安全
                if v_len >= 3 or has_kanji:
                    self.match_phrases.append(v_clean)
                else:
                    # 2文字以下のひらがな・カタカナ・英字（例: あく、ちー、えろ、カス 等）
                    self.short_words.add(v_clean)

        self.match_phrases = sorted(list(set(self.match_phrases)), key=len, reverse=True)
        if self.match_phrases:
            self.phrase_pattern = re.compile("|".join(map(re.escape, self.match_phrases)))
        else:
            self.phrase_pattern = None

    def _check_shine(self, text: str) -> tuple[bool, str]:
        """「死ね / しね」の文脈付き検知（「〜ですしね」「〜ましたしね」等の誤爆を除外）"""
        if not self.has_shine:
            return False, ""

        for m in re.finditer(r'(死ね|しね[よやえー！!？\?]*|しねば)', text):
            before = text[:m.start()]
            # 語尾の丁寧語助動詞（です、ます、でした、ました、だ、た）直後の「しね」は除外
            if re.search(r'(?:です|まし|でした|ます|だ|た)$', before):
                continue
            return True, f"検知: {m.group(0)}"
        return False, ""

    def _check_bakka(self, text: str) -> tuple[bool, str]:
        """「ばっか」が愚か（バカ）の意味で使われているかを文脈付きで判定する"""
        if not self.has_baka:
            return False, ""

        for m in re.finditer(r'ばっか', text):
            start = m.start()
            end = m.end()
            before = text[:start].rstrip()
            after = text[end:].lstrip()

            if text[end:].startswith("り"):
                continue
            # 直前が動詞連用形+て/で（例: 遊んでばっか、寝てばっか）は除外
            if before.endswith("て") or before.endswith("で"):
                continue

            # 後続が「だ」「じゃ」「野郎」「やろう」「め」「死ね」「しね」など
            # 例: ばっかだな、ばっかだね、ばっかじゃん、ばっかじゃねーの、ばっか野郎
            if re.match(r'^(?:だ|じゃ|野郎|やろう|め|死ね|しね)', after):
                if not before or re.search(r'(?:あいつ|お前|おまえ|あんた|ほんと|まじ|まじで|まぢ|マジ)[\s　]*$', before):
                    return True, f"検知: {m.group(0)}{after[:2]}"
                if re.search(r'(?:は|が|も|って|のは)[\s　]*$', before):
                    return True, f"検知: {m.group(0)}{after[:2]}"
            elif not after or re.match(r'^[！!？\?ー〜～~]+$', after):
                if re.search(r'(?:ほんと|まじ|まじで|あいつ|お前)[\s　]*$', before):
                    return True, f"検知: {before[-3:]}ばっか"

        return False, ""

    def _check_separated_short_words(self, text: str) -> tuple[bool, str]:
        """「ば　か」「し・ね」「ば(か)」「く...そ」のように2文字短語の間に記号や空白を挟んだ貫通を検知"""
        for w in self.short_words:
            if len(w) == 2:
                c1, c2 = w[0], w[1]
                # 間に1〜6文字の空白・括弧・記号・装飾文字が挟まっているか
                pat = re.escape(c1) + SYMBOLS_CLASS_RAW + r'{1,6}' + re.escape(c2)
                m = re.search(pat, text, flags=re.IGNORECASE)
                if m:
                    return True, f"記号挟み短語検知: '{m.group(0)}' ({w})"
        return False, ""

    def _check_text_candidates(self, text_candidate: str) -> tuple[bool, str]:
        """与えられたテキスト候補（通常文またはローマ字変換文）に対してNG判定を行う"""
        if not text_candidate:
            return False, ""

        norm_text = normalize_text(text_candidate)
        read_text = get_reading_hira(text_candidate)
        elong_text = normalize_elongated(norm_text)
        sokuon_text = remove_sokuon_safely(norm_text)
        sokuon_elong = remove_sokuon_safely(elong_text)

        # 空白・括弧・記号除去文（「う ん ち」「う(ん)ち」「う・ん・ち」等の貫通対策）
        clean_norm = strip_symbols(norm_text)
        clean_read = strip_symbols(read_text)
        clean_elong = strip_symbols(elong_text)
        clean_sokuon = strip_symbols(sokuon_text)

        # 判定1: 「死ね / しね」のコンテキスト判定（原文・正規化文・引き伸ばし文・記号除去文）
        for txt in [text_candidate, norm_text, elong_text, sokuon_text, clean_norm, clean_elong]:
            hit_shine, reason_shine = self._check_shine(txt)
            if hit_shine:
                return True, reason_shine

        # 判定2: 「ばっか（＝バカ）」の文脈判定（ばっかだなー等の検知＆ばかり等の除外）
        for txt in [text_candidate, norm_text, clean_norm]:
            hit_bakka, reason_bakka = self._check_bakka(txt)
            if hit_bakka:
                return True, reason_bakka

        # 判定3: 2文字短語の記号・空白挟み判定（例: ば か, ば・か, 死 ね, く...そ 等）
        hit_sep, reason_sep = self._check_separated_short_words(norm_text)
        if hit_sep:
            return True, reason_sep

        # 判定4: 3文字以上の単語・フレーズ・漢字単語の照合（原文、正規化文、読み仮名文、記号除去文等）
        if self.phrase_pattern:
            for cand in [text_candidate, norm_text, read_text, elong_text, sokuon_text, sokuon_elong,
                         clean_norm, clean_read, clean_elong, clean_sokuon]:
                m = self.phrase_pattern.search(cand)
                if m:
                    return True, f"フレーズ検知: {m.group(0)}"

        # 判定5: 2文字以下の短いひらがな単語の形態素解析（ピエロ、チーズ、あくび等の誤爆を確実に防止）
        if self.short_words:
            tokens = list(tokenizer.tokenize(text_candidate))
            token_count = len(tokens)

            for i, t in enumerate(tokens):
                surf_raw = t.surface
                surf_norm = normalize_text(t.surface)
                read_norm = kata_to_hira(t.reading) if t.reading != '*' else surf_norm
                base_norm = normalize_text(t.base_form) if t.base_form != '*' else surf_norm

                for cand in [surf_raw, surf_norm, read_norm, base_norm]:
                    if cand in self.short_words:
                        return True, f"短語検知 (トークン: {t.surface}): {cand}"

                # 2トークン連続の結合判定
                if i + 1 < token_count:
                    next_t = tokens[i + 1]
                    # 助詞同士の連続（例: 〜ですしね の「し」+「ね」）は除外
                    is_both_particles = t.part_of_speech.startswith("助詞") and next_t.part_of_speech.startswith("助詞")
                    if not is_both_particles:
                        comb_surf = surf_norm + normalize_text(next_t.surface)
                        next_read = kata_to_hira(next_t.reading) if next_t.reading != '*' else normalize_text(next_t.surface)
                        comb_read = read_norm + next_read
                        for cand in [comb_surf, comb_read]:
                            if cand in self.short_words:
                                return True, f"短語結合検知: {cand}"

        return False, ""

    def is_ng(self, text: str) -> tuple[bool, str]:
        """NGワードが含まれているかを判定する（通常判定 + 英語伏せ字判定 + ローマ字変換判定）"""
        if not text:
            return False, ""

        # 1. 英語の伏せ字・記号挟み判定（f*ck, f u c k, s*x, sh*t, b!tch 等）
        if re.search(r'[a-zA-Z]', text):
            for pat, name in ENGLISH_OBSCENE_PATTERNS:
                m = pat.search(text)
                if m:
                    return True, f"英語伏せ字検知: '{m.group(0)}' ({name})"

        # 2. 通常判定（日本語テキスト・記号除去テキスト）
        is_hit, reason = self._check_text_candidates(text)
        if is_hit:
            return True, reason

        # 3. 英字が含まれる場合、ローマ字（ヘボン式・訓令式）をひらがなに変換して判定
        #    例: GAIJI / GAIZI -> がいじ, BAKA -> ばか, KUSO -> くそ 等
        if re.search(r'[a-zA-Z]', text):
            for raw_eng in [text, strip_symbols(text)]:
                romaji_converted = romaji_to_hira(raw_eng)
                if romaji_converted != raw_eng.lower():
                    is_hit_romaji, reason_romaji = self._check_text_candidates(romaji_converted)
                    if is_hit_romaji:
                        return True, f"ローマ字検知 ({reason_romaji})"

        return False, ""

# 単語リストとサーバー別フィルターキャッシュ
base_ng_words: list[str] = []
default_filter: ContentFilter | None = None
guild_settings: dict[str, dict] = {}
guild_filters: dict[int, ContentFilter] = {}

# 後方互換用
ng_words: list[str] = []
content_filter: ContentFilter | None = None

def load_guild_settings() -> dict:
    """guild_settings.json から各サーバーの設定を読み込む"""
    global guild_settings
    if GUILD_SETTINGS_FILE.exists():
        try:
            with open(GUILD_SETTINGS_FILE, "r", encoding="utf-8") as f:
                guild_settings = json.load(f)
        except Exception as e:
            print(f"[WARNING] サーバー設定ファイルの読み込みに失敗しました: {e}")
            guild_settings = {}
    else:
        guild_settings = {}
    return guild_settings

def save_guild_settings() -> None:
    """各サーバーの設定を guild_settings.json に保存する"""
    try:
        with open(GUILD_SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(guild_settings, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[ERROR] サーバー設定ファイルの保存に失敗しました: {e}")

def get_guild_setting(guild_id: int | None) -> dict:
    """指定されたサーバーの設定辞書を取得する（未設定の場合はデフォルトで初期化）"""
    if not guild_id:
        return {
            "replacement_text": DEFAULT_REPLACEMENT_TEXT,
            "custom_words": [],
            "disabled_base_words": []
        }
    gid_str = str(guild_id)
    if gid_str not in guild_settings:
        guild_settings[gid_str] = {
            "replacement_text": DEFAULT_REPLACEMENT_TEXT,
            "custom_words": [],
            "disabled_base_words": []
        }
    else:
        # 必要なキーが存在することを保証
        guild_settings[gid_str].setdefault("replacement_text", DEFAULT_REPLACEMENT_TEXT)
        guild_settings[gid_str].setdefault("custom_words", [])
        guild_settings[gid_str].setdefault("disabled_base_words", [])
    return guild_settings[gid_str]

def get_replacement_text(guild_id: int | None) -> str:
    """サーバー設定の置換テキストを取得する（未設定時は DEFAULT_REPLACEMENT_TEXT）"""
    if not guild_id:
        return DEFAULT_REPLACEMENT_TEXT
    setting = get_guild_setting(guild_id)
    text = setting.get("replacement_text")
    return text if text else DEFAULT_REPLACEMENT_TEXT

def get_guild_filter(guild_id: int | None) -> ContentFilter:
    """サーバー固有の有効NGワードで構成された ContentFilter を取得する（キャッシュ対応）"""
    if not guild_id:
        return default_filter or ContentFilter(base_ng_words)
    if guild_id in guild_filters:
        return guild_filters[guild_id]

    setting = get_guild_setting(guild_id)
    custom_words = set(setting.get("custom_words", []))
    disabled_words = set(setting.get("disabled_base_words", []))

    # 有効なNGワード = (基本NGワード - 無効化ワード) + サーバー独自追加ワード
    active_words = (set(base_ng_words) - disabled_words) | custom_words
    cf = ContentFilter(sorted(list(active_words)))
    guild_filters[guild_id] = cf
    return cf

def invalidate_guild_filter(guild_id: int | None) -> None:
    """サーバーの設定変更時にフィルターキャッシュを破棄する"""
    if guild_id is not None:
        guild_filters.pop(guild_id, None)

def load_ng_words() -> list[str]:
    """ng_words.txt からNGワードを読み込み、基本フィルターを再構築する"""
    global base_ng_words, default_filter, ng_words, content_filter
    if not NG_WORDS_FILE.exists():
        default_words = [
            "ばか", "アホ", "死ね", "クソ", "カス", "ゴミ",
            "あなる", "うんこ", "生きる価値無し", "いじめてやる", "息の根止めてやる",
            "あく", "ちー", "陰キャ", "キョロ充", "黒人", "障害者",
            "にがー", "いんきゃ", "殺す", "ぶちのめす", "えろ", "えろいな",
            "きもい", "きえろ", "おちんちん", "ちんこ", "ガイジ", "がいじ"
        ]
        NG_WORDS_FILE.write_text("\n".join(default_words) + "\n", encoding="utf-8")
        print(f"[INFO] {NG_WORDS_FILE.name} を新しく作成しました。")

    words = []
    with open(NG_WORDS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            word = line.strip()
            if word and not word.startswith("#"):
                words.append(word)

    base_ng_words = sorted(list(set(words)))
    default_filter = ContentFilter(base_ng_words)
    # 後方互換用
    ng_words = base_ng_words
    content_filter = default_filter

    # 全サーバーのキャッシュをクリア（基本ワード更新のため）
    guild_filters.clear()
    print(f"[INFO] 基本NGワードを {len(base_ng_words)} 件読み込みました。（形態素解析・漢字読み仮名・ローマ字・誤爆防止が有効）")
    return base_ng_words

def save_ng_words(words: list[str]) -> None:
    """NGワードを ng_words.txt に保存する（基本辞書の更新）"""
    sorted_words = sorted(list(set(words)))
    with open(NG_WORDS_FILE, "w", encoding="utf-8") as f:
        f.write("# 1行に1つ、置き換え対象にしたいワード（NGワード）を記入してください。\n")
        f.write("# 先頭に「#」をつけるとコメントとして扱われます。\n")
        f.write("# 漢字・ひらがな・カタカナ・ローマ字は自動で読み仮名や表記ゆれが考慮されます。\n\n")
        for w in sorted_words:
            f.write(f"{w}\n")
    load_ng_words()

# 初回読み込み
load_ng_words()
load_guild_settings()

# Bot設定 (メッセージ内容およびボイス状態の取得権限を有効化)
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Webhookのキャッシュ (channel_id -> Webhook)
webhook_cache: dict[int, discord.Webhook] = {}

async def get_or_create_webhook(channel: discord.TextChannel | discord.Thread | discord.VoiceChannel | discord.StageChannel) -> discord.Webhook | None:
    """チャンネルまたは親チャンネルに対応するWebhookを取得または作成する"""
    target_channel: discord.TextChannel | discord.VoiceChannel | discord.StageChannel
    if isinstance(channel, discord.Thread):
        if isinstance(channel.parent, (discord.TextChannel, discord.VoiceChannel)):
            target_channel = channel.parent
        else:
            return None
    elif isinstance(channel, (discord.TextChannel, discord.VoiceChannel, discord.StageChannel)):
        target_channel = channel
    else:
        return None

    if target_channel.id in webhook_cache:
        cached_wh = webhook_cache[target_channel.id]
        try:
            return cached_wh
        except Exception:
            del webhook_cache[target_channel.id]

    try:
        webhooks = await target_channel.webhooks()
        bot_webhook = next((wh for wh in webhooks if wh.user == bot.user), None)
        if not bot_webhook:
            bot_webhook = await target_channel.create_webhook(name="CensorWebhook")

        webhook_cache[target_channel.id] = bot_webhook
        return bot_webhook
    except discord.Forbidden:
        print(f"[ERROR] チャンネル '{target_channel.name}' でのWebhook操作権限がありません（Manage Webhooksが必要です）。")
        return None
    except discord.HTTPException as e:
        print(f"[ERROR] Webhookの取得・作成に失敗しました: {e}")
        return None


# ========================================================
# ボイスチャット・VCテキスト NGワード監視＆ペナルティ管理
# ========================================================

# ユーザーごとの警告管理
# key: (guild_id, user_id) -> {"count": int, "last_warned": float}
user_warnings: dict[tuple[int, int], dict] = {}
# ミュート自動解除タスクの追跡
# key: (guild_id, user_id) -> asyncio.Task
active_mute_tasks: dict[tuple[int, int], asyncio.Task] = {}

def get_warning_count(guild_id: int, user_id: int) -> int:
    """指定ユーザーの現在の警告回数を取得（1時間以上空いていればリセット）"""
    key = (guild_id, user_id)
    data = user_warnings.get(key)
    if not data:
        return 0
    if time.time() - data["last_warned"] > 3600:
        del user_warnings[key]
        return 0
    return data["count"]

def add_warning(guild_id: int, user_id: int) -> int:
    """警告回数をインクリメントして最新回数を返す"""
    key = (guild_id, user_id)
    count = get_warning_count(guild_id, user_id) + 1
    user_warnings[key] = {"count": count, "last_warned": time.time()}
    return count

def reset_warning(guild_id: int, user_id: int):
    """指定ユーザーの警告回数をリセット"""
    user_warnings.pop((guild_id, user_id), None)

async def handle_violation(
    guild: discord.Guild,
    member: discord.Member,
    channel: discord.abc.Messageable,
    detected_text: str,
    reason: str,
    source: str
):
    """NGワード検知時の警告通知および3回警告時の5分間マイクミュート"""
    count = add_warning(guild.id, member.id)

    if count < 3:
        embed = discord.Embed(
            title="⚠️ NGワード警告",
            description=f"{member.mention} さんがNGワードを発言しました。（{source}）",
            color=discord.Color.yellow()
        )
        embed.add_field(name="検知内容", value=f"「{detected_text}」", inline=False)
        embed.add_field(name="判定理由", value=reason, inline=True)
        embed.add_field(name="警告状況", value=f"**{count} / 3 回**", inline=True)
        embed.set_footer(text="※3回警告されると、5分間のマイクミュートが適用されます。")
        try:
            await channel.send(content=member.mention, embed=embed)
        except Exception as e:
            print(f"[ERROR] 警告メッセージ送信失敗: {e}")
    else:
        # 3回警告に達したためリセットして5分ミュート
        reset_warning(guild.id, member.id)
        embed = discord.Embed(
            title="🚨 ペナルティ適用（5分間マイクミュート）",
            description=f"{member.mention} さんの警告が3回に達したため、**5分間マイクミュート**されました。",
            color=discord.Color.red()
        )
        embed.add_field(name="検知内容", value=f"「{detected_text}」", inline=False)
        embed.add_field(name="判定理由", value=reason, inline=True)
        embed.add_field(name="ペナルティ", value="5分後に自動解除されます", inline=True)
        try:
            await channel.send(content=f"🚨 {member.mention}", embed=embed)
        except Exception as e:
            print(f"[ERROR] ミュート通知メッセージ送信失敗: {e}")

        key = (guild.id, member.id)
        if key in active_mute_tasks:
            active_mute_tasks[key].cancel()

        try:
            await member.edit(mute=True, reason="NGワード3回検知によるペナルティ（5分間マイクミュート）")
            task = asyncio.create_task(schedule_unmute(guild.id, member.id, channel, 300))
            active_mute_tasks[key] = task
        except discord.Forbidden:
            await channel.send(
                f"❌ {member.mention} をミュートできませんでした。\n"
                "※Botに「メンバーをミュート（Mute Members）」権限が付与されているか、およびBotの役職が対象ユーザーより上位にあるか確認してください。"
            )
        except Exception as e:
            print(f"[ERROR] サーバーミュート実行失敗: {e}")

async def schedule_unmute(guild_id: int, user_id: int, channel: discord.abc.Messageable, delay_seconds: int):
    """指定秒数後にサーバーミュートを解除する"""
    await asyncio.sleep(delay_seconds)
    key = (guild_id, user_id)
    active_mute_tasks.pop(key, None)

    guild = bot.get_guild(guild_id)
    if not guild:
        return
    member = guild.get_member(user_id)
    if not member:
        return

    try:
        await member.edit(mute=False, reason="5分間ペナルティ終了による自動解除")
        embed = discord.Embed(
            title="🔊 マイクミュート解除",
            description=f"{member.mention} さんの5分間ペナルティが終了し、マイクミュートが解除されました。",
            color=discord.Color.green()
        )
        await channel.send(content=member.mention, embed=embed)
    except Exception as e:
        print(f"[INFO] ミュート自動解除処理（既に退出済み等の可能性）: {e}")


# ========================================================
# 音声受信・音声認識（Speech-to-Text）マネージャー
# ========================================================

class VoiceDataManager:
    def __init__(self):
        self.buffers: dict[tuple[int, int], dict] = {}
        self.lock = threading.Lock()

    def add_packet(self, guild_id: int, user: discord.User | discord.Member, pcm: bytes, vc_channel_id: int):
        if not user or user.bot or not pcm:
            return
        now = time.time()
        key = (guild_id, user.id)
        with self.lock:
            if key not in self.buffers:
                self.buffers[key] = {
                    "pcm": bytearray(),
                    "last_time": now,
                    "vc_channel_id": vc_channel_id,
                    "guild_id": guild_id,
                    "user_id": user.id,
                }
            buf = self.buffers[key]
            buf["pcm"].extend(pcm)
            buf["last_time"] = now

    def pop_ready_buffers(self) -> list[dict]:
        now = time.time()
        ready = []
        with self.lock:
            for key, buf in list(self.buffers.items()):
                pcm_len = len(buf["pcm"])
                elapsed_since_last = now - buf["last_time"]

                # 48kHz, 16bit, 2ch -> 1秒 = 192,000 bytes
                # 0.4秒 = 76,800 bytes
                # 6.0秒 = 1,152,000 bytes
                is_silence_timeout = (elapsed_since_last >= 0.8) and (pcm_len >= 76800)
                is_max_length = pcm_len >= 1152000

                if is_silence_timeout or is_max_length:
                    ready.append({
                        "guild_id": buf["guild_id"],
                        "user_id": buf["user_id"],
                        "vc_channel_id": buf["vc_channel_id"],
                        "pcm": bytes(buf["pcm"]),
                    })
                    del self.buffers[key]
                elif elapsed_since_last >= 1.5:
                    del self.buffers[key]
        return ready

voice_data_manager = VoiceDataManager()

def transcribe_pcm(pcm_bytes: bytes) -> str | None:
    """ステレオ48kHz PCMデータをモノラル16kHzに変換してGoogle音声認識を実行"""
    try:
        mono_pcm = audioop.tomono(pcm_bytes, 2, 0.5, 0.5)
        resampled_pcm, _ = audioop.ratecv(mono_pcm, 2, 1, 48000, 16000, None)
        audio = sr.AudioData(resampled_pcm, 16000, 2)
        text = speech_recognizer.recognize_google(audio, language="ja-JP")
        return text.strip() if text else None
    except sr.UnknownValueError:
        return None
    except sr.RequestError as e:
        print(f"[WARNING] Google Speech Recognition API エラー: {e}")
        return None
    except Exception as e:
        print(f"[ERROR] 音声認識処理中の予期せぬ例外: {e}")
        return None

async def process_single_speech(item: dict):
    guild_id = item["guild_id"]
    user_id = item["user_id"]
    channel_id = item["vc_channel_id"]
    pcm = item["pcm"]

    guild = bot.get_guild(guild_id)
    if not guild:
        return
    member = guild.get_member(user_id)
    if not member:
        return
    channel = guild.get_channel(channel_id)
    if not isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
        return

    text = await asyncio.to_thread(transcribe_pcm, pcm)
    if not text:
        return

    active_filter = get_guild_filter(guild_id)
    is_ng, reason = active_filter.is_ng(text)
    if is_ng:
        print(f"[VC CENSOR] [{guild.name}] 通話音声NG検知: {reason} | 発言者: {member.display_name} | 認識文: 「{text}」")
        await handle_violation(
            guild=guild,
            member=member,
            channel=channel,
            detected_text=text,
            reason=reason,
            source="通話音声"
        )

async def voice_processor_loop():
    """定期的に完了した音声バッファを認識ワーカーに投げてNGチェックするループ"""
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            ready_list = voice_data_manager.pop_ready_buffers()
            for item in ready_list:
                asyncio.create_task(process_single_speech(item))
        except Exception as e:
            print(f"[ERROR] voice_processor_loop エラー: {e}")
        await asyncio.sleep(0.2)

class BotVoiceSink(voice_recv.AudioSink):
    def __init__(self, guild_id: int, channel_id: int):
        super().__init__()
        self.guild_id = guild_id
        self.channel_id = channel_id

    def wants_opus(self) -> bool:
        return False

    def write(self, user: discord.User | discord.Member | None, data: voice_recv.VoiceData):
        if user is None or (bot.user and user.id == bot.user.id):
            return
        voice_data_manager.add_packet(self.guild_id, user, data.pcm, self.channel_id)

    def cleanup(self):
        pass

@bot.event
async def on_ready():
    print("=" * 50)
    print(f"ログイン成功: {bot.user.name} (ID: {bot.user.id})")
    print(f"デフォルト置換フレーズ: 「{DEFAULT_REPLACEMENT_TEXT}」")
    print(f"サーバー個別設定読み込み済み: {len(guild_settings)} サーバー")
    print("形態素解析・ローマ字検知・ボイス監視・誤爆防止フィルター稼働中⚡")
    print("=" * 50)

    # 音声監視ループタスクを起動
    if not hasattr(bot, "_voice_processor_started"):
        bot._voice_processor_started = True
        asyncio.create_task(voice_processor_loop())
        print("[INFO] ボイスチャット音声認識エンジンが待機開始しました。")

    # サーバー固有（ギルド）コマンドの重複を削除してグローバルコマンドに一本化
    for guild in bot.guilds:
        try:
            bot.tree.clear_commands(guild=guild)
            await bot.tree.sync(guild=guild)
            print(f"[INFO] サーバー『{guild.name}』の重複ギルドコマンドを削除しました。")
        except Exception as e:
            print(f"[WARNING] サーバー『{guild.name}』のギルドコマンド削除スキップ: {e}")

    # グローバルコマンドを同期
    try:
        global_synced = await bot.tree.sync()
        print(f"[INFO] グローバルコマンド {len(global_synced)} 件を同期しました。")
    except Exception as e:
        print(f"[WARNING] グローバルコマンド同期失敗: {e}")

@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    """ボイスチャンネルにBot以外の参加者がいなくなった場合は自動で退出する"""
    voice_client = member.guild.voice_client
    if voice_client and voice_client.channel:
        non_bot_members = [m for m in voice_client.channel.members if not m.bot]
        if len(non_bot_members) == 0:
            print(f"[VC INFO] {voice_client.channel.name} の参加者が0人になったため自動退出しました。")
            if hasattr(voice_client, "is_listening") and voice_client.is_listening():
                voice_client.stop_listening()
            await voice_client.disconnect()



# ユーザーごとの直近短文メッセージキャッシュ（「う」「ん」「ち」等の分割連投による貫通対策）
# key: (channel_id, user_id) -> deque of {"msg": discord.Message, "text": str, "time": float}
SPLIT_WORD_MAX_HISTORY = 8
SPLIT_WORD_EXPIRATION_SEC = 25.0  # 25秒以内の短文連投を追跡
recent_user_messages: dict[tuple[int, int], deque] = defaultdict(lambda: deque(maxlen=SPLIT_WORD_MAX_HISTORY))

@bot.event
async def on_message(message: discord.Message):
    # Bot自身やWebhookのメッセージは無視（無限ループ防止）
    if message.author.bot or message.webhook_id:
        return

    # メッセージ本文が存在しない場合は何もしない
    if not message.content:
        await bot.process_commands(message)
        return

    channel = message.channel
    if not isinstance(channel, (discord.TextChannel, discord.Thread, discord.VoiceChannel, discord.StageChannel)):
        await bot.process_commands(message)
        return

    guild_id = message.guild.id if message.guild else None
    active_filter = get_guild_filter(guild_id)
    replacement_text = get_replacement_text(guild_id)

    now = time.time()
    user_key = (channel.id, message.author.id)
    history = recent_user_messages[user_key]

    # 有効期限切れ（25秒以上前）の履歴を破棄
    while history and (now - history[0]["time"] > SPLIT_WORD_EXPIRATION_SEC):
        history.popleft()

    # 1. メッセージ単体でのNG判定
    is_ng, reason = active_filter.is_ng(message.content)
    past_messages_to_delete: list[discord.Message] = []

    # 2. 単体でNGにならなかった場合、直近の短文履歴と結合して判定（「う」「ん」「ち」等の分割貫通対策）
    if not is_ng and history:
        # 直近の履歴を末尾から順に遡って結合パターンを検証
        # 例: 履歴 [「う」, 「ん」] + 今回「ち」 -> 「うんち」で検知
        combined_text = message.content
        temp_past_msgs = []
        for item in reversed(history):
            combined_text = item["text"] + combined_text
            temp_past_msgs.insert(0, item["msg"])
            hit_split, reason_split = active_filter.is_ng(combined_text)
            if hit_split:
                is_ng = True
                reason = f"分割連投検知 ({reason_split}) [結合文: '{combined_text}']"
                past_messages_to_delete = temp_past_msgs
                break

    if is_ng:
        history.clear()
        guild_name = message.guild.name if message.guild else "DM"
        print(f"[CENSOR] [{guild_name}] メッセージ検知・置換実行: {reason} | 投稿者: {message.author.display_name}")

        # 過去の分割パーツメッセージも削除
        for past_msg in past_messages_to_delete:
            try:
                await past_msg.delete()
            except Exception:
                pass

        # 今回のメッセージを削除
        try:
            await message.delete()
        except discord.Forbidden:
            print(f"[ERROR] メッセージ削除権限がありません（Manage Messagesが必要です）。チャンネル: {channel}")
            return
        except discord.NotFound:
            pass

        # Webhookを取得・作成して投稿（サーバー設定の replacement_text を投稿）
        webhook = await get_or_create_webhook(channel)
        if webhook:
            thread_arg = channel if isinstance(channel, discord.Thread) else discord.utils.MISSING
            display_name = message.author.display_name
            avatar_url = message.author.display_avatar.url

            try:
                await webhook.send(
                    content=replacement_text,
                    username=display_name,
                    avatar_url=avatar_url,
                    thread=thread_arg,
                    allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=True)
                )
            except discord.HTTPException as e:
                print(f"[ERROR] Webhookからのメッセージ送信に失敗しました: {e}")
        else:
            await channel.send(
                f"**{message.author.display_name}**: {replacement_text}"
            )

        # ボイスチャンネル（VoiceChannel または StageChannel）内のチャット発言の場合は、警告＆ペナルティ（3回で5分ミュート）も適用
        if isinstance(channel, (discord.VoiceChannel, discord.StageChannel)) and message.guild and isinstance(message.author, discord.Member):
            await handle_violation(
                guild=message.guild,
                member=message.author,
                channel=channel,
                detected_text=message.content,
                reason=reason,
                source="VCチャット"
            )
        return

    # NGではなかった場合、短文（空白除いて4文字以下）なら履歴に追加
    stripped_text = re.sub(r'\s+', '', message.content)
    if 0 < len(stripped_text) <= 4:
        history.append({"msg": message, "text": stripped_text, "time": now})
    else:
        # 長文が挟まった場合は分割連投の文脈が途切れたとみなしてリセット
        history.clear()

    await bot.process_commands(message)

# ================================
# スラッシュコマンド（NGワード＆メッセージ管理）
# ================================

@bot.tree.command(name="ng_list", description="このサーバーのNGワード一覧と置換メッセージ設定を表示します")
async def cmd_ng_list(interaction: discord.Interaction):
    if not interaction.guild:
        await interaction.response.send_message("このコマンドはサーバー内でのみ使用できます。", ephemeral=True)
        return

    guild_id = interaction.guild.id
    setting = get_guild_setting(guild_id)
    rep_text = get_replacement_text(guild_id)
    custom_words = setting.get("custom_words", [])
    disabled_words = setting.get("disabled_base_words", [])

    active_words = sorted(list((set(base_ng_words) - set(disabled_words)) | set(custom_words)))

    lines = [
        f"⚙️ **【{interaction.guild.name}】のNGワード設定**",
        f"💬 **現在の置換メッセージ**: 「**{rep_text}**」",
        f"📊 **有効なNGワード総数**: {len(active_words)} 件（基本: {len(base_ng_words) - len(disabled_words)}件 / サーバー追加: {len(custom_words)}件）\n"
    ]

    if custom_words:
        custom_str = ", ".join(f"`{w}`" for w in sorted(custom_words))
        lines.append(f"➕ **このサーバー専用の追加NGワード ({len(custom_words)}件):**\n{custom_str}\n")
    else:
        lines.append("➕ **このサーバー専用の追加NGワード**: なし\n")

    if disabled_words:
        disabled_str = ", ".join(f"`{w}`" for w in sorted(disabled_words))
        lines.append(f"🚫 **このサーバーで無効化されている基本NGワード ({len(disabled_words)}件):**\n{disabled_str}\n")

    lines.append("💡 **便利なコマンド:**")
    lines.append("・`/ng_add <単語>`: このサーバーにNGワードを追加")
    lines.append("・`/ng_remove <単語>`: このサーバーからNGワードを削除・除外")
    lines.append("・`/ng_message <テキスト>`: 検知時の置換メッセージを変更（例: 「うわっ⚡」など）")
    lines.append("・`/ng_message_reset`: 置換メッセージをデフォルトに戻す")

    result_text = "\n".join(lines)
    if len(result_text) > 1900:
        result_text = result_text[:1850] + "\n...(文字数制限のため一部省略)..."

    await interaction.response.send_message(result_text, ephemeral=True)

@bot.tree.command(name="ng_add", description="このサーバーに新しいNGワードを追加します")
@app_commands.describe(word="追加したいNGワード")
@app_commands.checks.has_permissions(manage_messages=True)
async def cmd_ng_add(interaction: discord.Interaction, word: str):
    if not interaction.guild:
        await interaction.response.send_message("このコマンドはサーバー内でのみ使用できます。", ephemeral=True)
        return

    word = word.strip()
    if not word:
        await interaction.response.send_message("有効な単語を指定してください。", ephemeral=True)
        return

    guild_id = interaction.guild.id
    setting = get_guild_setting(guild_id)
    custom_words = setting.setdefault("custom_words", [])
    disabled_words = setting.setdefault("disabled_base_words", [])

    # 無効化リストに入っていた場合は復帰
    if word in disabled_words:
        disabled_words.remove(word)
        save_guild_settings()
        invalidate_guild_filter(guild_id)
        await interaction.response.send_message(
            f"無効化されていた「`{word}`」をこのサーバーのNGワードとして再有効化しました！",
            ephemeral=True
        )
        return

    if word in custom_words or (word in base_ng_words and word not in disabled_words):
        await interaction.response.send_message(
            f"「`{word}`」は既にこのサーバーのNGワードとして登録されています。",
            ephemeral=True
        )
        return

    custom_words.append(word)
    save_guild_settings()
    invalidate_guild_filter(guild_id)
    await interaction.response.send_message(
        f"このサーバーのNGワードに「`{word}`」を追加しました！⚡\n（漢字・ひらがな・カタカナ・ローマ字等の表記ゆれも自動判定されます）",
        ephemeral=True
    )

@cmd_ng_add.error
async def cmd_ng_add_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("このコマンドを実行するには「メッセージの管理」権限が必要です。", ephemeral=True)
    else:
        await interaction.response.send_message(f"エラーが発生しました: {error}", ephemeral=True)

@bot.tree.command(name="ng_remove", description="このサーバーからNGワードを削除・除外します")
@app_commands.describe(word="削除したいNGワード")
@app_commands.checks.has_permissions(manage_messages=True)
async def cmd_ng_remove(interaction: discord.Interaction, word: str):
    if not interaction.guild:
        await interaction.response.send_message("このコマンドはサーバー内でのみ使用できます。", ephemeral=True)
        return

    word = word.strip()
    if not word:
        await interaction.response.send_message("有効な単語を指定してください。", ephemeral=True)
        return

    guild_id = interaction.guild.id
    setting = get_guild_setting(guild_id)
    custom_words = setting.setdefault("custom_words", [])
    disabled_words = setting.setdefault("disabled_base_words", [])

    if word in custom_words:
        custom_words.remove(word)
        save_guild_settings()
        invalidate_guild_filter(guild_id)
        await interaction.response.send_message(f"このサーバーの追加NGワードから「`{word}`」を削除しました。", ephemeral=True)
        return

    if word in base_ng_words:
        if word not in disabled_words:
            disabled_words.append(word)
            save_guild_settings()
            invalidate_guild_filter(guild_id)
            await interaction.response.send_message(f"基本NGワード「`{word}`」をこのサーバーで無効化しました。", ephemeral=True)
        else:
            await interaction.response.send_message(f"「`{word}`」は既にこのサーバーで無効化されています。", ephemeral=True)
        return

    await interaction.response.send_message(f"「`{word}`」はNGワードに登録されていません。", ephemeral=True)

@cmd_ng_remove.error
async def cmd_ng_remove_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("このコマンドを実行するには「メッセージの管理」権限が必要です。", ephemeral=True)
    else:
        await interaction.response.send_message(f"エラーが発生しました: {error}", ephemeral=True)

@bot.tree.command(name="ng_message", description="このサーバーでNGワード検知時に置き換える文字を変更します")
@app_commands.describe(text="置き換え後のテキスト（例: うわっ⚡、暴言はダメ！、など）")
@app_commands.checks.has_permissions(manage_messages=True)
async def cmd_ng_message(interaction: discord.Interaction, text: str):
    if not interaction.guild:
        await interaction.response.send_message("このコマンドはサーバー内でのみ使用できます。", ephemeral=True)
        return

    text = text.strip()
    if not text:
        await interaction.response.send_message("有効なテキストを指定してください。", ephemeral=True)
        return

    if len(text) > 100:
        await interaction.response.send_message("置換テキストは100文字以内で指定してください。", ephemeral=True)
        return

    guild_id = interaction.guild.id
    setting = get_guild_setting(guild_id)
    old_text = get_replacement_text(guild_id)
    setting["replacement_text"] = text
    save_guild_settings()

    await interaction.response.send_message(
        f"✅ このサーバーでの置換メッセージを変更しました！\n"
        f"・変更前: 「{old_text}」\n"
        f"・変更後: 「**{text}**」\n\n"
        f"※元に戻したい場合は `/ng_message_reset` を実行してください。",
        ephemeral=True
    )

@cmd_ng_message.error
async def cmd_ng_message_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("このコマンドを実行するには「メッセージの管理」権限が必要です。", ephemeral=True)
    else:
        await interaction.response.send_message(f"エラーが発生しました: {error}", ephemeral=True)

@bot.tree.command(name="ng_message_reset", description="このサーバーの置換メッセージを初期設定（うわっ⚡）に戻します")
@app_commands.checks.has_permissions(manage_messages=True)
async def cmd_ng_message_reset(interaction: discord.Interaction):
    if not interaction.guild:
        await interaction.response.send_message("このコマンドはサーバー内でのみ使用できます。", ephemeral=True)
        return

    guild_id = interaction.guild.id
    setting = get_guild_setting(guild_id)
    setting["replacement_text"] = DEFAULT_REPLACEMENT_TEXT
    save_guild_settings()

    await interaction.response.send_message(
        f"✅ このサーバーでの置換メッセージをデフォルトの「**{DEFAULT_REPLACEMENT_TEXT}**」に戻しました。",
        ephemeral=True
    )

@cmd_ng_message_reset.error
async def cmd_ng_message_reset_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("このコマンドを実行するには「メッセージの管理」権限が必要です。", ephemeral=True)
    else:
        await interaction.response.send_message(f"エラーが発生しました: {error}", ephemeral=True)

@bot.tree.command(name="ng_reload", description="ng_words.txt とサーバー設定を再読み込みします")
@app_commands.checks.has_permissions(manage_messages=True)
async def cmd_ng_reload(interaction: discord.Interaction):
    load_ng_words()
    load_guild_settings()
    guild_filters.clear()
    await interaction.response.send_message(
        f"NGワードおよび全サーバー設定を再読み込みしました（基本NGワード: {len(base_ng_words)}件）。",
        ephemeral=True
    )

@cmd_ng_reload.error
async def cmd_ng_reload_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("このコマンドを実行するには「メッセージの管理」権限が必要です。", ephemeral=True)
    else:
        await interaction.response.send_message(f"エラーが発生しました: {error}", ephemeral=True)

# ========================================================
# スラッシュコマンド（ボイスチャット監視・警告・ミュート管理）
# ========================================================

@bot.tree.command(name="vc_join", description="実行者が参加しているボイスチャンネルに参加し、NGワード音声監視を開始します")
async def cmd_vc_join(interaction: discord.Interaction):
    if not interaction.guild:
        await interaction.response.send_message("このコマンドはサーバー内でのみ使用できます。", ephemeral=True)
        return

    member = interaction.guild.get_member(interaction.user.id)
    if not member or not member.voice or not member.voice.channel:
        await interaction.response.send_message("❌ 先にボイスチャンネルに参加してから実行してください。", ephemeral=True)
        return

    target_channel = member.voice.channel
    voice_client = interaction.guild.voice_client

    await interaction.response.defer()

    try:
        if voice_client:
            if voice_client.channel.id == target_channel.id and hasattr(voice_client, "is_listening") and voice_client.is_listening():
                await interaction.followup.send(f"✅ すでに **{target_channel.name}** で音声監視中です！")
                return
            await voice_client.move_to(target_channel)
        else:
            voice_client = await target_channel.connect(cls=voice_recv.VoiceRecvClient)

        if hasattr(voice_client, "is_listening") and voice_client.is_listening():
            voice_client.stop_listening()

        sink = BotVoiceSink(interaction.guild.id, target_channel.id)
        voice_client.listen(sink)

        embed = discord.Embed(
            title="🔊 ボイスチャット監視開始",
            description=f"**{target_channel.name}** に参加しました！\n通話音声＆VCチャットでのNGワードを監視します。",
            color=discord.Color.green()
        )
        embed.add_field(name="ペナルティ規則", value="NGワードを言うと警告が行き、**3回警告されると5分間マイクミュート**されます。", inline=False)
        embed.set_footer(text="退出させるには /vc_leave を実行してください。")
        await interaction.followup.send(embed=embed)
    except discord.Forbidden:
        await interaction.followup.send("❌ ボイスチャンネルへの接続権限または発言権限がありません。Botの権限を確認してください。")
    except Exception as e:
        print(f"[ERROR] vc_join 失敗: {e}")
        await interaction.followup.send(f"❌ ボイスチャンネルへの参加中にエラーが発生しました: {e}")

@bot.tree.command(name="vc_leave", description="ボイスチャンネルから退出します")
async def cmd_vc_leave(interaction: discord.Interaction):
    if not interaction.guild:
        await interaction.response.send_message("このコマンドはサーバー内でのみ使用できます。", ephemeral=True)
        return

    voice_client = interaction.guild.voice_client
    if not voice_client:
        await interaction.response.send_message("❌ Botはボイスチャンネルに参加していません。", ephemeral=True)
        return

    channel_name = voice_client.channel.name if voice_client.channel else "ボイスチャンネル"
    if hasattr(voice_client, "is_listening") and voice_client.is_listening():
        voice_client.stop_listening()
    await voice_client.disconnect()
    await interaction.response.send_message(f"👋 **{channel_name}** から退出しました。音声監視を停止します。")

@bot.tree.command(name="vc_status", description="ボイスチャット監視状態や現在の警告・ミュート状況を表示します")
async def cmd_vc_status(interaction: discord.Interaction):
    if not interaction.guild:
        await interaction.response.send_message("このコマンドはサーバー内でのみ使用できます。", ephemeral=True)
        return

    guild = interaction.guild
    voice_client = guild.voice_client
    embed = discord.Embed(title="📊 ボイスチャット監視ステータス", color=discord.Color.blue())

    if voice_client and voice_client.channel:
        embed.add_field(name="接続中のVC", value=f"🔊 {voice_client.channel.name} (監視稼働中)", inline=False)
    else:
        embed.add_field(name="接続中のVC", value="未接続（/vc_join で接続）", inline=False)

    # 警告中のユーザー
    warned_users = []
    now = time.time()
    for (gid, uid), data in list(user_warnings.items()):
        if gid == guild.id:
            m = guild.get_member(uid)
            name = m.display_name if m else f"User {uid}"
            remain = max(0, int(3600 - (now - data["last_warned"])))
            warned_users.append(f"・{name}: **{data['count']}/3 回** (リセットまで残り {remain // 60}分)")

    embed.add_field(
        name="現在の警告リスト",
        value="\n".join(warned_users) if warned_users else "現在警告を受けているユーザーはいません。",
        inline=False
    )

    # ミュート管理中
    muted_users = []
    for (gid, uid) in list(active_mute_tasks.keys()):
        if gid == guild.id:
            m = guild.get_member(uid)
            name = m.display_name if m else f"User {uid}"
            muted_users.append(f"・{name} (5分ペナルティ中)")

    embed.add_field(
        name="ペナルティ（ミュート）中のユーザー",
        value="\n".join(muted_users) if muted_users else "現在ミュートペナルティ中のユーザーはいません。",
        inline=False
    )

    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="vc_warn_reset", description="指定ユーザーのNGワード警告回数を0にリセットします")
@app_commands.describe(user="警告をリセットするユーザー")
@app_commands.checks.has_permissions(manage_messages=True)
async def cmd_vc_warn_reset(interaction: discord.Interaction, user: discord.Member):
    if not interaction.guild:
        await interaction.response.send_message("このコマンドはサーバー内でのみ使用できます。", ephemeral=True)
        return

    reset_warning(interaction.guild.id, user.id)
    await interaction.response.send_message(f"✅ {user.mention} さんのNGワード警告回数をリセット（0回）にしました。", ephemeral=True)

@cmd_vc_warn_reset.error
async def cmd_vc_warn_reset_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("このコマンドを実行するには「メッセージの管理」権限が必要です。", ephemeral=True)
    else:
        await interaction.response.send_message(f"エラーが発生しました: {error}", ephemeral=True)

@bot.tree.command(name="vc_unmute", description="ペナルティ等でマイクミュートされたユーザーのミュートを手動解除します")
@app_commands.describe(user="ミュートを解除するユーザー")
@app_commands.checks.has_permissions(manage_messages=True)
async def cmd_vc_unmute(interaction: discord.Interaction, user: discord.Member):
    if not interaction.guild:
        await interaction.response.send_message("このコマンドはサーバー内でのみ使用できます。", ephemeral=True)
        return

    key = (interaction.guild.id, user.id)
    if key in active_mute_tasks:
        active_mute_tasks[key].cancel()
        del active_mute_tasks[key]

    try:
        await user.edit(mute=False, reason="管理者による手動ミュート解除")
        await interaction.response.send_message(f"🔊 {user.mention} さんのマイクミュートを手動解除しました。")
    except discord.Forbidden:
        await interaction.response.send_message("❌ Botに「メンバーをミュート」権限がないか、対象ユーザーより権限が低いため解除できませんでした。", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ 解除中にエラーが発生しました: {e}", ephemeral=True)

@cmd_vc_unmute.error
async def cmd_vc_unmute_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("このコマンドを実行するには「メッセージの管理」権限が必要です。", ephemeral=True)
    else:
        await interaction.response.send_message(f"エラーが発生しました: {error}", ephemeral=True)

# 起動チェック
if __name__ == "__main__":
    if not TOKEN or TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("\n" + "!" * 60)
        print("【設定エラー】Discord Botトークンが設定されていません！")
        print("同一フォルダ内の `.env` ファイルを開き、")
        print("DISCORD_BOT_TOKEN=ここにあなたのBotトークン を入力してください。")
        print("!" * 60 + "\n")
        sys.exit(1)

    try:
        bot.run(TOKEN)
    except discord.LoginFailure:
        print("\n[ERROR] 不正なトークンです。`.env` の DISCORD_BOT_TOKEN を確認してください。\n")
    except Exception as e:
        print(f"\n[ERROR] Bot起動時にエラーが発生しました: {e}\n")
