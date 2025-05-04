#!/usr/bin/env python3
import threading
import time
import json
import os
import sys
import tkinter as tk
from tkinter import ttk, messagebox, Scale, IntVar
import requests
import pyautogui
import pytesseract
from pytesseract import TesseractNotFoundError
import keyboard
from googletrans import Translator

try:
    from transformers import TrOCRProcessor, VisionEncoderDecoderModel
    from PIL import Image
    TROCR_AVAILABLE = True
except ImportError:
    TROCR_AVAILABLE = False

# DocTR için gerekli importlar
try:
    import doctr
    from doctr.io import DocumentFile
    from doctr.models import ocr_predictor
    DOCTR_AVAILABLE = True
    print("DocTR başarıyla import edildi")
except (ImportError, ModuleNotFoundError) as e:
    print(f"DocTR import hatası: {e}")
    DOCTR_AVAILABLE = False

# -----------------------------------------------------
# TESSERACT YOLU AYARI
# -----------------------------------------------------
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# -----------------------------------------------------
# AYAR DOSYASI YÖNETİMİ
# -----------------------------------------------------
SETTINGS_FILE = os.path.join(os.path.dirname(__file__), 'settings.json')

def load_settings():
    default = {
        'region': {'x': 100, 'y': 100, 'width': 400, 'height': 200},
        'display': {'x': 600, 'y': 100, 'width': 500, 'height': 200},
        'source_display': {'x': 600, 'y': 320, 'width': 500, 'height': 200},
        'interval_ms': 1000,
        'wraplength': 480,
        'source_lang': 'en',
        'target_lang': 'tr',
        'translator_service': 'google',
        'ocr_engine': 'tesseract',  # 'tesseract', 'easyocr', 'trocr', 'doctr'
        'cpu_workers': 0  # 0 = tüm çekirdekler
    }
    
    if os.path.exists(SETTINGS_FILE):
        try:
            data = json.load(open(SETTINGS_FILE, 'r'))
            # Yeni ayarları varsayılan ayarlarla birleştir
            for key, value in default.items():
                if key not in data:
                    data[key] = value
                elif key == 'source_display' and key not in data:
                    data[key] = default[key]
            
            data.setdefault('wraplength', data['display']['width'] - 20)
            data.setdefault('translator_service', 'google')
            return data
        except Exception:
            return default
    return default

def save_settings(cfg):
    try:
        cfg['wraplength'] = cfg['display']['width'] - 20
        json.dump(cfg, open(SETTINGS_FILE, 'w'), indent=4)
    except Exception as e:
        print(f"Ayarları kaydetme hatası: {e}")

config = load_settings()

# -----------------------------------------------------
# ÇEVİRİ SERVİSLERİ
# -----------------------------------------------------
# Google Translate
translator = Translator()

# LibreTranslate Bağlantıları
LIBRE_TRANSLATE_URLS = [
    "https://translate.argosopentech.com/translate",  # Argos OpenTech sunucusu genellikle daha kararlı
    "https://translate.terraprint.co/translate",      # TarraPrint sunucusu
    "https://libretranslate.de/translate",            # Alman sunucusu
    "https://translate.astian.org/translate",         # Astian sunucusu
    "https://translate.fedilab.app/translate",        # Fedilab sunucusu  
    "https://libretranslate.com/translate"            # Ana sunucu (kotalı olduğu için sona eklendi)
]
CURRENT_LIBRE_URL_INDEX = 0

# Argos Translate
try:
    import argostranslate.package
    import argostranslate.translate
    ARGOS_AVAILABLE = True
except ImportError:
    ARGOS_AVAILABLE = False

# -----------------------------------------------------
# ÇEVİRİ FONKSİYONLARI
# -----------------------------------------------------
def translate_with_google(text, source_lang="en", target_lang="tr"):
    """Google Translate API kullanarak çeviri yapar"""
    if not text:
        return ""
    max_retries = 3
    for i in range(max_retries):
        try:
            result = translator.translate(text, src=source_lang, dest=target_lang)
            return result.text
        except Exception as e:
            if i < max_retries - 1:
                time.sleep(1)
                translator = Translator()  # Yeni çevirmen nesnesi oluştur
            else:
                return f"[Çeviri Hatası: {str(e)}]"

def translate_with_libretranslate(text, source_lang="en", target_lang="tr"):
    """LibreTranslate API kullanarak çeviri yapar"""
    global CURRENT_LIBRE_URL_INDEX
    
    if not text:
        return ""
    
    # Tüm LibreTranslate URL'lerini dene
    for _ in range(len(LIBRE_TRANSLATE_URLS)):
        try:
            url = LIBRE_TRANSLATE_URLS[CURRENT_LIBRE_URL_INDEX]
            payload = {
                "q": text,
                "source": source_lang,
                "target": target_lang,
                "format": "text",
                "api_key": ""  # API anahtarı gerektiren sunucular için boş anahtar
            }
            
            headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
                "User-Agent": "OCRTranslator/1.0"  # Kullanıcı Ajanı ekleyerek bazı sunucuların engellemesini önle
            }
            
            # Yükleme çubuğunu test moduna getir
            update_progress_bar("testing")
            
            # Zaman aşımını 8 saniyeye çıkar
            response = requests.post(url, data=payload, headers=headers, timeout=8)
            
            if response.status_code == 200:
                update_progress_bar("success")
                result = response.json()
                # Bazı sunucular farklı yanıt formatı kullanabilir
                if "translatedText" in result:
                    return result["translatedText"]
                elif "translation" in result:
                    return result["translation"]
                else:
                    return str(result)  # Bilinmeyen format
            else:
                # Yanıt koduna göre özelleştirilmiş hata mesajı
                error_msg = {
                    400: "Geçersiz istek",
                    429: "Çok fazla istek, kota aşıldı",
                    500: "Sunucu hatası",
                    503: "Servis kullanılamıyor"
                }.get(response.status_code, f"Hata kodu: {response.status_code}")
                
                print(f"LibreTranslate hatası ({url}): {error_msg}")
                
                # Sonraki URL'ye geç
                CURRENT_LIBRE_URL_INDEX = (CURRENT_LIBRE_URL_INDEX + 1) % len(LIBRE_TRANSLATE_URLS)
                update_progress_bar("error")
                continue
        except requests.exceptions.Timeout:
            print(f"LibreTranslate zaman aşımı ({url})")
            CURRENT_LIBRE_URL_INDEX = (CURRENT_LIBRE_URL_INDEX + 1) % len(LIBRE_TRANSLATE_URLS)
            update_progress_bar("error")
        except requests.exceptions.ConnectionError:
            print(f"LibreTranslate bağlantı hatası ({url})")
            CURRENT_LIBRE_URL_INDEX = (CURRENT_LIBRE_URL_INDEX + 1) % len(LIBRE_TRANSLATE_URLS)
            update_progress_bar("error")
        except Exception as e:
            print(f"LibreTranslate genel hata ({url}): {str(e)}")
            # Sonraki URL'ye geç
            CURRENT_LIBRE_URL_INDEX = (CURRENT_LIBRE_URL_INDEX + 1) % len(LIBRE_TRANSLATE_URLS)
            update_progress_bar("error")
    
    # Tüm URL'ler başarısız olursa
    return f"[LibreTranslate erişilemez durumda. Başka bir çeviri servisi deneyin.]"

def translate_with_argos(text, source_lang="en", target_lang="tr"):
    """Argos Translate kullanarak çeviri yapar"""
    if not text or not ARGOS_AVAILABLE:
        return "[Argos Translate kullanılamıyor]" if not ARGOS_AVAILABLE else ""
    
    try:
        update_progress_bar("testing")
        
        try:
            # Dil kodlarını doğrula (ISO 639 uyumluluğu)
            if '-' in source_lang:  # 'zh-cn' gibi bölgesel kodlar için düzeltme
                source_lang = source_lang.split('-')[0]
            if '-' in target_lang:
                target_lang = target_lang.split('-')[0]
                
            # Dil çiftini kontrol et
            installed_packages = argostranslate.package.get_installed_packages()
            from_langs = argostranslate.translate.get_installed_languages()
            to_langs = []
            
            # Kaynak dili bul
            from_lang = None
            for lang in from_langs:
                if lang.code == source_lang:
                    from_lang = lang
                    break
            
            if from_lang is None:
                update_progress_bar("error")
                return f"[Argos için kaynak dil '{source_lang}' bulunamadı]"
            
            # Hedef dilleri kontrol et
            to_langs = from_lang.translations
            to_lang = None
            for lang in to_langs:
                if lang.code == target_lang:
                    to_lang = lang
                    break
            
            if to_lang is None:
                update_progress_bar("error")
                return f"[Argos için '{source_lang}' dilinden '{target_lang}' diline çeviri paketi bulunamadı]"
            
            # Çeviri yap
            translation = from_lang.get_translation(to_lang).translate(text)
            update_progress_bar("success")
            return translation
            
        except (AttributeError, IndexError):
            # Eski yöntem ile deneyelim (API değişimi durumunda)
            translation = argostranslate.translate.translate(text, source_lang, target_lang)
            update_progress_bar("success")
            return translation
            
    except Exception as e:
        update_progress_bar("error")
        return f"[Argos Çeviri Hatası: {str(e)}]"

def translate_text(text, source_lang="en", target_lang="tr"):
    """Seçilen çeviri motorunu kullanarak çeviri yapar"""
    if config['translator_service'] == 'google':
        return translate_with_google(text, source_lang, target_lang)
    elif config['translator_service'] == 'libretranslate':
        return translate_with_libretranslate(text, source_lang, target_lang)
    elif config['translator_service'] == 'argos':
        return translate_with_argos(text, source_lang, target_lang)
    else:
        return translate_with_google(text, source_lang, target_lang)  # Varsayılan olarak Google

# -----------------------------------------------------
# TESSERACT KONTROLÜ
# -----------------------------------------------------
try:
    pytesseract.get_tesseract_version()
except (TesseractNotFoundError, OSError) as e:
    tk.Tk().withdraw()
    messagebox.showerror(
        "Tesseract Hatası",
        f"Tesseract OCR bulunamadı: {e}\n"
        "Lütfen Tesseract'ı https://github.com/tesseract-ocr/tesseract adresinden yükleyin "
        "ve PATH ayarını yapıp tekrar deneyin."
    )
    sys.exit(1)

# -----------------------------------------------------
# GLOBAL DURUM DEĞİŞKENLERİ
# -----------------------------------------------------
easyocr_current_lang = None
running = False
app_running = True
rects_visible = True
last_text = ""
progress_value = 0
trocr_processor = None
trocr_model = None
doctr_predictor = None

# -----------------------------------------------------
# TKINTER ANA PENCERE VE OVERLAY KURULUMU
# -----------------------------------------------------
root = tk.Tk()
sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
root.geometry(f"{sw}x{sh}+0+0")
root.overrideredirect(True)
root.attributes('-topmost', True)
root.configure(bg='black')
root.attributes('-transparentcolor', 'black')

canvas = tk.Canvas(root, width=sw, height=sh, bg='black', highlightthickness=0)
canvas.place(x=0, y=0)

region_rect = display_rect = source_display_rect = None

# -----------------------------------------------------
# REKTANGLE VE ETİKET FONKSİYONLARI
# -----------------------------------------------------
def draw_rectangles():
    global region_rect, display_rect, source_display_rect
    if region_rect: canvas.delete(region_rect)
    if display_rect: canvas.delete(display_rect)
    if source_display_rect: canvas.delete(source_display_rect)
    
    r = config['region']
    d = config['display']
    s = config['source_display']
    
    region_rect = canvas.create_rectangle(
        r['x'], r['y'], r['x']+r['width'], r['y']+r['height'], 
        outline='white', width=2
    )
    display_rect = canvas.create_rectangle(
        d['x'], d['y'], d['x']+d['width'], d['y']+d['height'], 
        outline='white', dash=(4,2), width=2
    )
    source_display_rect = canvas.create_rectangle(
        s['x'], s['y'], s['x']+s['width'], s['y']+s['height'], 
        outline='yellow', dash=(4,2), width=2
    )

def hide_rectangles():
    global region_rect, display_rect, source_display_rect
    if region_rect: canvas.delete(region_rect)
    if display_rect: canvas.delete(display_rect)
    if source_display_rect: canvas.delete(source_display_rect)

def toggle_rects():
    global rects_visible
    rects_visible = not rects_visible
    if rects_visible:
        draw_rectangles()
        status_label.place(x=config['display']['x'], y=config['display']['y'] + config['display']['height'] + 5)
        progress_frame.place(x=config['display']['x'], y=config['display']['y'] + config['display']['height'] + 25)
        tl.place(x=config['display']['x'], y=config['display']['y'])
        sl.place(x=config['source_display']['x'], y=config['source_display']['y'])  # Kaynak metin etiketini göster
        if running:
            update_status_label()
        toggle_btn.config(text="Çerçeveleri Gizle")
    else:
        hide_rectangles()
        status_label.place_forget()
        progress_frame.place_forget()
        sl.place_forget()  # Kaynak metin etiketini gizle
        toggle_btn.config(text="Çerçeveleri Göster")

def update_status_label():
    """Durum etiketini günceller"""
    service_name = {
        'google': 'Google Translate',
        'libretranslate': 'LibreTranslate',
        'argos': 'Argos Translate'
    }.get(config['translator_service'], 'Google')
    
    ocr_name = {
        'tesseract': 'Tesseract OCR',
        'easyocr': 'EasyOCR',
        'trocr': 'TrOCR',
        'doctr': 'DocTR'
    }.get(config.get('ocr_engine', 'tesseract'), 'Tesseract OCR')
    
    status_label.config(text=f"OCR: {ocr_name} | Çeviri: {config['source_lang']} -> {config['target_lang']} ({service_name})")

# Etiketler oluştur
draw_rectangles()

# Çevrilmiş metin etiketi
tl = tk.Label(
    root, text='', font=('Arial', 14, 'bold'), bg='black', fg='white', 
    wraplength=config['wraplength'], justify='left'
)
tl.place(x=config['display']['x'], y=config['display']['y'])

# Kaynak metin etiketi
sl = tk.Label(
    root, text='', font=('Arial', 10, 'bold'), bg='black', fg='yellow', 
    wraplength=config['wraplength'], justify='left'
)
sl.place(x=config['source_display']['x'], y=config['source_display']['y'])

# Çeviri aktif etiketi
active_label = tk.Label(root, text='Çeviri aktif', font=('Arial',14,'bold'), fg='lime', bg='black')
active_label.place_forget()

# Durum etiketi
status_label = tk.Label(root, text='', font=('Arial', 10, 'bold'), fg='yellow', bg='black')
status_label.place(x=config['display']['x'], y=config['display']['y'] + config['display']['height'] + 5)

# İlerleme çubuğu çerçevesi ve bileşenleri
progress_frame = tk.Frame(root, bg='black')
progress_frame.place(x=config['display']['x'], y=config['display']['y'] + config['display']['height'] + 25)

progress_bars = []
for i in range(10):  # 10 bölmeli ilerleme çubuğu
    bar = tk.Label(progress_frame, text='■', font=('Arial', 12, 'bold'), bg='black', fg='gray')
    bar.grid(row=0, column=i, padx=1)
    progress_bars.append(bar)

def update_progress_bar(status="testing"):
    """İlerleme çubuğunu günceller
    status: "testing" (gri), "success" (yeşil), "error" (kırmızı)
    """
    global progress_value
    colors = {"testing": "gray", "success": "lime", "error": "red"}
    color = colors.get(status, "gray")
    
    # Tüm barları gri yap
    if status == "testing":
        for i, bar in enumerate(progress_bars):
            if i < progress_value:
                bar.config(fg=color)
            else:
                bar.config(fg="black")
        
        # İlerleme değerini artır
        progress_value = (progress_value + 1) % (len(progress_bars) + 1)
        if progress_value == 0:
            progress_value = 1
    else:
        # Başarı veya hata durumunda tüm barları doldur
        for bar in progress_bars:
            bar.config(fg=color)
        progress_value = len(progress_bars)

# -----------------------------------------------------
# AYARLAR PENCERESİ
# -----------------------------------------------------
settings = tk.Toplevel(root)
settings.title('Bölge Ayarları')
settings.geometry('490x680')  # Daha büyük pencere
settings.attributes('-topmost', True)
settings.protocol('WM_DELETE_WINDOW', lambda: shutdown())

# Bölge ayarları
region_frame = ttk.LabelFrame(settings, text='Ekran Bölgeleri')
region_frame.grid(row=0, column=0, columnspan=2, padx=10, pady=10, sticky='ew')

# OCR Bölgesi
ocr_frame = ttk.LabelFrame(region_frame, text='OCR Bölgesi')
ocr_frame.grid(row=0, column=0, padx=10, pady=5)

# Çeviri Gösterim Bölgesi
display_frame = ttk.LabelFrame(region_frame, text='Çeviri Gösterim Bölgesi')
display_frame.grid(row=0, column=1, padx=10, pady=5)

# Kaynak Metin Gösterim Bölgesi
source_frame = ttk.LabelFrame(region_frame, text='Kaynak Metin Bölgesi')
source_frame.grid(row=1, column=0, columnspan=2, padx=10, pady=5, sticky='ew')

entries = {}
# OCR Bölgesi ayarları
for i, (label_text, sec, key) in enumerate([('X','region','x'),('Y','region','y'),('W','region','width'),('H','region','height')]):
    ttk.Label(ocr_frame, text=label_text).grid(row=i, column=0)
    e = ttk.Entry(ocr_frame, width=8)
    e.grid(row=i, column=1)
    e.insert(0, str(config[sec][key]))
    entries[(sec, key)] = e

# Çeviri Gösterim Bölgesi ayarları
for i, (label_text, sec, key) in enumerate([('X','display','x'),('Y','display','y'),('W','display','width'),('H','display','height')]):
    ttk.Label(display_frame, text=label_text).grid(row=i, column=0)
    e = ttk.Entry(display_frame, width=8)
    e.grid(row=i, column=1)
    e.insert(0, str(config[sec][key]))
    entries[(sec, key)] = e

# Kaynak Metin Gösterim Bölgesi ayarları
for i, (label_text, sec, key) in enumerate([('X','source_display','x'),('Y','source_display','y'),('W','source_display','width'),('H','source_display','height')]):
    ttk.Label(source_frame, text=label_text).grid(row=i, column=0)
    e = ttk.Entry(source_frame, width=8)
    e.grid(row=i, column=1)
    e.insert(0, str(config[sec][key]))
    entries[(sec, key)] = e

# Dil ayarları
lang_frame = ttk.LabelFrame(settings, text='Dil Ayarları')
lang_frame.grid(row=1, column=0, columnspan=2, padx=10, pady=5, sticky='ew')

ttk.Label(lang_frame, text='Kaynak Dil:').grid(row=0, column=0, padx=5, pady=5)
source_lang_entry = ttk.Entry(lang_frame, width=10)
source_lang_entry.grid(row=0, column=1, padx=5, pady=5)
source_lang_entry.insert(0, config['source_lang'])

ttk.Label(lang_frame, text='Hedef Dil:').grid(row=0, column=2, padx=5, pady=5)
target_lang_entry = ttk.Entry(lang_frame, width=10)  
target_lang_entry.grid(row=0, column=3, padx=5, pady=5)
target_lang_entry.insert(0, config['target_lang'])

ttk.Label(lang_frame, text='Örn: en, tr, fr, de, es, ja, ko, ru, zh-cn').grid(
    row=1, column=0, columnspan=4, padx=5, pady=0
)

# Çeviri servisi seçme
# Çeviri servisi seçme
translator_frame = ttk.LabelFrame(settings, text='Çeviri Servisi')
translator_frame.grid(row=2, column=0, columnspan=2, padx=10, pady=5, sticky='ew')

translator_var = tk.StringVar(value=config['translator_service'])
google_radio = ttk.Radiobutton(translator_frame, text='Google Translate', value='google', variable=translator_var)
google_radio.grid(row=0, column=0, padx=5, pady=5)

libre_radio = ttk.Radiobutton(translator_frame, text='LibreTranslate', value='libretranslate', variable=translator_var)
libre_radio.grid(row=0, column=1, padx=5, pady=5)

argos_radio = ttk.Radiobutton(
    translator_frame, 
    text='Argos Translate' + (" (Kurulu Değil)" if not ARGOS_AVAILABLE else ""), 
    value='argos', 
    variable=translator_var,
    state=tk.NORMAL if ARGOS_AVAILABLE else tk.DISABLED
)
argos_radio.grid(row=0, column=2, padx=5, pady=5)

# Argos Translate kurulum ve dil paketi yönetimi
if not ARGOS_AVAILABLE:
    ttk.Label(translator_frame, text="Argos Translate kullanmak için: pip install argostranslate").grid(
        row=1, column=0, columnspan=3, padx=5, pady=5
    )
    
# Şimdi OCR motor seçimi ekleyelim
ocr_frame = ttk.LabelFrame(settings, text='OCR Motoru')
ocr_frame.grid(row=3, column=0, columnspan=2, padx=10, pady=5, sticky='ew')

# CPU kullanımı ayar bölümü (settings bölümünde)
cpu_frame = ttk.LabelFrame(settings, text='Çeviri Performansı')
cpu_frame.grid(row=5, column=0, columnspan=2, padx=10, pady=5, sticky='ew')

# Speed_value zaten tanımlı olduğu için sadece referans verin
ttk.Label(cpu_frame, text='Tarama Aralığı (ms):').grid(row=0, column=0, padx=5, pady=5)
ttk.Label(cpu_frame, text='ms').grid(row=0, column=1, padx=5, pady=5)

ttk.Label(cpu_frame, text='NOT: Performans sorunları yaşıyorsanız tarama aralığı değerini arttırın (1000-2000ms).').grid(
    row=1, column=0, columnspan=2, padx=5, pady=5
)

ocr_var = tk.StringVar(value=config.get('ocr_engine', 'tesseract'))
tesseract_radio = ttk.Radiobutton(ocr_frame, text='Tesseract OCR', value='tesseract', variable=ocr_var)
tesseract_radio.grid(row=0, column=0, padx=5, pady=5)

# EasyOCR kullanılabilirliğini kontrol et
EASYOCR_AVAILABLE = False
try:
    import easyocr
    import numpy as np
    EASYOCR_AVAILABLE = True
except ImportError:
    pass

easyocr_radio = ttk.Radiobutton(
    ocr_frame, 
    text='EasyOCR' + (" (Kurulu Değil)" if not EASYOCR_AVAILABLE else ""), 
    value='easyocr', 
    variable=ocr_var,
    state=tk.NORMAL if EASYOCR_AVAILABLE else tk.DISABLED
)
easyocr_radio.grid(row=0, column=1, padx=5, pady=5)

if not EASYOCR_AVAILABLE:
    ttk.Label(ocr_frame, text="EasyOCR kullanmak için: pip install easyocr numpy").grid(
        row=1, column=0, columnspan=2, padx=5, pady=5
    )

trocr_radio = ttk.Radiobutton(
    ocr_frame, 
    text='TrOCR' + (" (Kurulu Değil)" if not TROCR_AVAILABLE else ""), 
    value='trocr', 
    variable=ocr_var,
    state=tk.NORMAL if TROCR_AVAILABLE else tk.DISABLED
)
trocr_radio.grid(row=1, column=0, padx=5, pady=5)

doctr_radio = ttk.Radiobutton(
    ocr_frame, 
    text='DocTR' + (" (Kurulu Değil)" if not DOCTR_AVAILABLE else ""), 
    value='doctr', 
    variable=ocr_var,
    state=tk.NORMAL if DOCTR_AVAILABLE else tk.DISABLED
)
doctr_radio.grid(row=1, column=1, padx=5, pady=5)

# Kurulum bilgilerini ekleyin
if not TROCR_AVAILABLE or not DOCTR_AVAILABLE:
    install_text = ""
    if not TROCR_AVAILABLE:
        install_text += "TrOCR: pip install transformers torch Pillow\n"
    if not DOCTR_AVAILABLE:
        install_text += "DocTR: pip install python-doctr"
    
    ttk.Label(ocr_frame, text=install_text.strip()).grid(
        row=2, column=0, columnspan=2, padx=5, pady=5
    )


# Çeviri hızı ayarı
speed_frame = ttk.LabelFrame(settings, text='Çeviri Hızı (ms)')
speed_frame.grid(row=4, column=0, columnspan=2, padx=10, pady=5, sticky='ew')

speed_value = IntVar(value=config['interval_ms'])
speed_scale = Scale(
    speed_frame, 
    from_=100, 
    to=5000, 
    orient=tk.HORIZONTAL, 
    length=300,
    variable=speed_value,
    resolution=100
)
speed_scale.grid(row=0, column=0, padx=10, pady=5)

# UI kontrol düğmeleri
control_frame = ttk.Frame(settings)
control_frame.grid(row=6, column=0, columnspan=2, padx=10, pady=5, sticky='ew')

toggle_btn = ttk.Button(control_frame, text='Çerçeveleri Gizle' if rects_visible else 'Çerçeveleri Göster', command=toggle_rects)
toggle_btn.grid(row=0, column=0, padx=5, pady=5)

def show_help():
    """Yardım penceresini göster"""
    help_window = tk.Toplevel()
    help_window.title("Yardım")
    help_window.geometry("600x550")
    help_window.attributes('-topmost', True)
    
    # Yardım metni için bir metin kutusu
    help_text = tk.Text(help_window, wrap="word", padx=10, pady=10)
    help_text.pack(fill="both", expand=True)
    
    # Kaydırma çubuğu ekle
    scrollbar = ttk.Scrollbar(help_text)
    scrollbar.pack(side="right", fill="y")
    help_text.config(yscrollcommand=scrollbar.set)
    scrollbar.config(command=help_text.yview)
    
    # Yardım içeriği
    help_content = """# OCR Çeviri Uygulaması Kullanım Kılavuzu

## Genel Bilgiler
Bu uygulama, ekrandan metin okuyarak (OCR) çeşitli çeviri servisleri aracılığıyla gerçek zamanlı çeviri yapmanızı sağlar.

## Bölgeler
- **OCR Bölgesi**: Metni okumak istediğiniz ekran alanı (beyaz çerçeve ile gösterilir)
- **Çeviri Gösterim Bölgesi**: Çevrilmiş metnin gösterileceği alan (kesikli beyaz çerçeve)
- **Kaynak Metin Bölgesi**: OCR ile tanınan orijinal metin (kesikli sarı çerçeve)

## Kısayol Tuşları
- **1**: Çeviriyi başlat
- **2**: Çeviriyi durdur

## Çeviri Servisleri
1. **Google Translate**:
   - En geniş dil desteği
   - İnternet bağlantısı gerektirir
   - Genellikle en doğru sonuçları verir

2. **LibreTranslate**:
   - Açık kaynaklı, ücretsiz bir çeviri servisi
   - İnternet bağlantısı gerektirir
   - Birden fazla sunucu arasında otomatik geçiş yapar

3. **Argos Translate**:
   - Tamamen çevrimdışı çalışır, internet gerektirmez
   - Dil paketlerinin önceden yüklenmesi gerekir
   - Sınırlı dil desteği ve doğruluk

## Dil Kodları
Bazı yaygın dil kodları:
- en: İngilizce
- tr: Türkçe
- de: Almanca
- fr: Fransızca
- es: İspanyolca
- ja: Japonca
- ko: Korece
- ru: Rusça
- zh-cn: Basitleştirilmiş Çince

## Sorun Giderme
1. **OCR çalışmıyor**: Tesseract'ın doğru kurulduğundan emin olun.
2. **LibreTranslate hataları**: Farklı bir LibreTranslate sunucusuna otomatik geçiş yapılacaktır.
3. **Argos çevirisi çalışmıyor**: İlgili dil paketinin yüklü olduğundan emin olun.

## İlerleme Çubuğu
- **Yeşil**: Çeviri başarılı
- **Kırmızı**: Çeviri hatası 
- **Gri**: Çeviri servisi test ediliyor

Daha fazla yardım için https://github.com/pytesseract/tesseract adresini ziyaret edin.
"""
    
    # Metin kutusuna yardım içeriğini ekle
    help_text.insert("1.0", help_content)
    help_text.config(state="disabled")  # Salt okunur yap
    
    # Tamam butonu
    ttk.Button(help_window, text="Kapat", command=help_window.destroy).pack(pady=10)

help_btn = ttk.Button(control_frame, text='Yardım', command=show_help)
help_btn.grid(row=0, column=1, padx=5, pady=5)

def apply_settings():
    try:
        for (sec, key), ent in entries.items():
            config[sec][key] = int(ent.get())
        
        config['wraplength'] = config['display']['width'] - 20
        config['source_lang'] = source_lang_entry.get()
        config['target_lang'] = target_lang_entry.get()
        config['translator_service'] = translator_var.get()
        config['interval_ms'] = speed_value.get()
        config['ocr_engine'] = ocr_var.get()
        # cpu_workers referansını kaldırın
        
        # Etiketleri doğru konumlara yerleştir
        tl.place(x=config['display']['x'], y=config['display']['y'])
        tl.config(wraplength=config['wraplength'])
        
        sl.place(x=config['source_display']['x'], y=config['source_display']['y'])
        sl.config(wraplength=config['wraplength'])
        
        if rects_visible:
            status_label.place(x=config['display']['x'], y=config['display']['y'] + config['display']['height'] + 5)
            progress_frame.place(x=config['display']['x'], y=config['display']['y'] + config['display']['height'] + 25)
            draw_rectangles()
            update_status_label()
        
        save_settings(config)
    except Exception as e:
        messagebox.showerror("Ayar Hatası", f"Ayarları güncellerken hata: {str(e)}")

apply_btn = ttk.Button(control_frame, text='Ayarları Kaydet', command=apply_settings)
apply_btn.grid(row=0, column=1, padx=5, pady=5)

# -----------------------------------------------------
# ÇEVİRİ VE ANİMASYON
# -----------------------------------------------------
def blink():
    """Aktif durum göstergesini yanıp söndürür"""
    if running:
        if active_label.winfo_ismapped():
            active_label.place_forget()
        else:
            active_label.place(relx=1.0, rely=0.0, anchor='ne')
    else:
        active_label.place_forget()
    
    if app_running:
        root.after(500, blink)

# Import alanında gerekli modülleri ekleyelim (dosyanın başına)
try:
    import easyocr
    import numpy as np
    EASYOCR_AVAILABLE = True
except ImportError:
    EASYOCR_AVAILABLE = False

# EasyOCR Reader nesnesini global olarak tanımlayalım
easyocr_reader = None
easyocr_current_lang = None  # Mevcut dili takip etmek için

def translate_loop():
    """Ana çeviri döngüsü"""
    global app_running, last_text, easyocr_reader, easyocr_current_lang
    
    # İlk çalıştırmada EasyOCR okuyucusunu başlat
    if easyocr_current_lang != config['source_lang']:
        try:
            print(f"EasyOCR dil güncellemesi: {config['source_lang']}")
            # num_workers parametresini kaldır
            easyocr_reader = easyocr.Reader([config['source_lang']], gpu=False)
            easyocr_current_lang = config['source_lang']
        except Exception as e:
            print(f"EasyOCR dil değiştirme hatası: {e}")
    
    last_check_time = time.time()  # Son işlem zamanını takip et
    min_interval = 0.1  # Minimum işlem aralığı (saniye)
    
    while app_running:
        if running:
            current_time = time.time()
            # Minimum aralıktan daha kısa süre geçtiyse bekle
            if current_time - last_check_time < min_interval:
                time.sleep(0.01)  # Kısa bir süre bekle
                continue

            try:
                # Ekran görüntüsü al
                img = pyautogui.screenshot(region=(
                    config['region']['x'], 
                    config['region']['y'],
                    config['region']['width'], 
                    config['region']['height']
                ))
                
                # Seçilen OCR motoruna göre metin çıkar
                txt = ""
                ocr_engine = config.get('ocr_engine', 'tesseract')

                if ocr_engine == 'easyocr' and EASYOCR_AVAILABLE and easyocr_reader:
                    # EasyOCR ile metni çıkar
                    try:
                        img_array = np.array(img)
                        results = easyocr_reader.readtext(img_array, detail=0)
                        txt = " ".join(results).strip()
                    except Exception as e:
                        print(f"EasyOCR okuma hatası: {e}")
                        txt = ""  # Hata durumunda boş metin döndür, otomatik geçiş yok
                        
                elif ocr_engine == 'trocr' and TROCR_AVAILABLE:
                    # TrOCR ile metni çıkar
                    global trocr_processor, trocr_model
                    
                    try:
                        # Model ve işlemci yüklü değilse yükle (ilk kullanımda)
                        if trocr_processor is None or trocr_model is None:
                            trocr_processor = TrOCRProcessor.from_pretrained("microsoft/trocr-base-handwritten")
                            trocr_model = VisionEncoderDecoderModel.from_pretrained("microsoft/trocr-base-handwritten")
                            print("TrOCR modeli yüklendi")
                        
                        # Görüntüyü işle
                        pixel_values = trocr_processor(images=img, return_tensors="pt").pixel_values
                        generated_ids = trocr_model.generate(pixel_values)
                        generated_text = trocr_processor.batch_decode(generated_ids, skip_special_tokens=True)[0]
                        txt = generated_text.strip()
                    except Exception as e:
                        print(f"TrOCR okuma hatası: {e}")
                        txt = ""
                        
                elif ocr_engine == 'doctr' and DOCTR_AVAILABLE:
                    # DocTR ile metni çıkar
                    global doctr_predictor
                    
                    try:
                        # Tahmin edici yüklü değilse yükle (ilk kullanımda)
                        if doctr_predictor is None:
                            doctr_predictor = ocr_predictor(pretrained=True)
                            print("DocTR modeli yüklendi")
                        
                        # Mutlak yol kullanarak görüntüyü kaydet
                        temp_img_path = os.path.abspath(os.path.join(os.path.dirname(__file__), 'temp_ocr_img.png'))
                        img.save(temp_img_path)
                        print(f"Görüntü kaydedildi: {temp_img_path}")
                        
                        # DocTR belge işleme - normalleştirilmiş yol kullanarak
                        doc = DocumentFile.from_images([temp_img_path])
                        result = doctr_predictor(doc)
                        
                        # Sonuçları metin olarak çıkar
                        txt = result.render()
                        print(f"DocTR sonucu: {txt}")
                        
                        # Geçici dosyayı sil
                        try:
                            os.remove(temp_img_path)
                        except Exception as e:
                            print(f"Geçici dosya silinemedi: {e}")
                    except Exception as e:
                        print(f"DocTR okuma hatası: {e}")
                        txt = ""
                
                # Metin değiştiyse ve boş değilse çeviri yap
                if txt and txt != last_text:
                    sl.config(text=txt)  # Kaynak metni güncelle
                    
                    # Çeviri yap
                    update_progress_bar("testing")
                    trans_text = translate_text(txt, config['source_lang'], config['target_lang'])
                    
                    if trans_text:
                        tl.config(text=trans_text)  # Çeviriyi göster
                        update_progress_bar("success")
                    else:
                        update_progress_bar("error")
                    
                    last_text = txt  # Son metni güncelle
                    last_check_time = time.time()  # Son işlem zamanını güncelle
            except Exception as e:
                print(f"Çeviri döngüsünde hata: {e}")
                update_progress_bar("error")
                
        # CPU yükünü azaltmak için daha uzun aralıklarla çalıştır
        time.sleep(config['interval_ms'] / 1000)

# Çeviri işlemini arka planda başlat
threading.Thread(target=translate_loop, daemon=True).start()

# -----------------------------------------------------
# KISAYOLLAR VE PROGRAM KAPATMA
# -----------------------------------------------------
def start():
    """Çeviriyi başlat"""
    global running
    running = True
    active_label.place(relx=1.0, rely=0.0, anchor='ne')
    if rects_visible:
        update_status_label()
    save_settings(config)

def stop():
    """Çeviriyi durdur"""
    global running, last_text
    running = False
    active_label.place_forget()
    tl.config(text='')  # Çeviri metnini temizle
    sl.config(text='')  # Kaynak metni temizle
    last_text = ""      # Son metni sıfırla
    if rects_visible:
        status_label.config(text='')

def shutdown():
    """Programı kapat"""
    global app_running
    app_running = False
    save_settings(config)
    root.destroy()
    os._exit(0)

# Kısayol tuşları
keyboard.add_hotkey('1', start)  # Başlat
keyboard.add_hotkey('2', stop)   # Durdur

# Yanıp sönme animasyonunu başlat
blink()

# Ayarlar penceresini başlat
settings.update()

# Kullanıcı arayüzünü başlat
root.mainloop()
