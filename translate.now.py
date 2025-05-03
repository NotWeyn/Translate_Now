#!/usr/bin/env python3
"""
Ekranın belirli bir bölgesinden İngilizce metni çeviren geliştirilmiş interaktif Python aplikasyonu.
Çoklu çeviri servisleri, servis durum göstergesi ve çevrilmemiş metin gösterimi içerir.

Özellikler:
- OCR ile seçilen bölgeden metin okuma (pyautogui + pytesseract)
- Üç çeviri servisi arasında seçim yapma imkanı:
  * Google Translate
  * LibreTranslate (alternatif sunucularla)
  * Argos Translate (tamamen offline çalışır)
- Çevrilmemiş metin gösterim bölgesi
- Çeviri servisi durum göstergesi (yükleme çubuğu)
- Klavye kısayolları: '1' ile çeviri başlat, '2' ile durdur
- Çeviri metni genişler; ekrandan taşınca alt satıra kaydırır (word-wrap)
- "Çeviri aktif" animasyonlu etiketi sağ üst köşede gösterir
- Şeffaf overlay pencere (Windows için)
- OCR ve gösterim bölgelerini çerçeveleyen overlay çizgileri: göster/gizle tuşu
- Ayar değişikliklerini JSON dosyasına kaydederek kalıcılık sağlar

Kurulum:
    pip install pyautogui pytesseract googletrans==4.0.0-rc1 keyboard pillow requests argostranslate
    # Tesseract OCR kurulu ve PATH'e ekli olmalı

Kullanım:
    python screen_translate_app.py
    Ayar penceresindeki "Güncelle" ile değişimleri kaydeder.
    '1' ile çeviriyi başlatıp, '2' ile durdurun.
    "Çerçeveleri Gizle/Göster" butonu overlay kutucuklarını kontrol eder.
"""
import threading
import time
import json
import os
import sys
import tkinter as tk
from tkinter import ttk, messagebox
import requests
import pyautogui
import pytesseract
# Manuel Tesseract yolu belirtimi (kendi kurulum yolunuza göre güncelleyin)
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
from pytesseract import TesseractNotFoundError
import keyboard

# Google Translate için
from googletrans import Translator

# Argos Translate için
try:
    import argostranslate.package
    import argostranslate.translate
    ARGOS_AVAILABLE = True
except ImportError:
    ARGOS_AVAILABLE = False

# -------------------------
# 1. KALICI AYAR DOSYASI
# -------------------------
SETTINGS_FILE = os.path.join(os.path.dirname(__file__), 'settings.json')

def load_settings():
    default = {
        'region': {'x': 100, 'y': 100, 'width': 400, 'height': 200},
        'display': {'x': 600, 'y': 100, 'width': 500, 'height': 200},
        'original_text': {'x': 100, 'y': 310, 'width': 400, 'height': 150},  # Çevrilmemiş metin bölgesi
        'interval_ms': 1000,
        'wraplength': 480,
        'source_lang': 'en',
        'target_lang': 'tr',
        'translator_service': 'google'  # Varsayılan olarak Google Translate
    }
    if os.path.exists(SETTINGS_FILE):
        try:
            data = json.load(open(SETTINGS_FILE, 'r'))
            # Yeni ayarları varsayılan ayarlarla birleştir
            for key, value in default.items():
                if key not in data:
                    data[key] = value
                elif key in ['original_text'] and key not in data:  # Yeni eklenen ayarlar
                    data[key] = value
            
            data.setdefault('wraplength', data['display']['width'] - 20)
            data.setdefault('translator_service', 'google')  # Eski ayarlar için varsayılan değer
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

# -------------------------
# 2. ÇEVİRİ SERVİSLERİ
# -------------------------
translator = Translator()

# LibreTranslate Sunucuları
LIBRE_TRANSLATE_SERVERS = [
    "https://translate.argosopentech.com/translate",
    "https://libretranslate.de/translate",
    "https://translate.terraprint.co/translate",
    "https://translate.fedilab.app/translate"
]
current_libre_server = 0  # Başlangıçta ilk sunucu

# Servis durumu
SERVICE_STATUS = {
    'google': {'status': 'unknown', 'progress': 0},
    'libretranslate': {'status': 'unknown', 'progress': 0},
    'argos': {'status': 'unknown', 'progress': 0}
}

# Argos Translate Dil Paketleri Kurulumu
def setup_argos_translate():
    if not ARGOS_AVAILABLE:
        return False
    
    try:
        # Mevcut paketleri kontrol et
        available_packages = argostranslate.package.get_available_packages()
        installed_packages = argostranslate.package.get_installed_packages()
        
        # Paket yüklemesi gerekiyorsa
        if not installed_packages:
            SERVICE_STATUS['argos']['status'] = 'loading'
            SERVICE_STATUS['argos']['progress'] = 10
            # Paketleri indir
            argostranslate.package.update_package_index()
            SERVICE_STATUS['argos']['progress'] = 50
            available_packages = argostranslate.package.get_available_packages()
            
            # İlgili dil paketlerini yükle
            for package in available_packages:
                if (package.from_code == config['source_lang'] and package.to_code == config['target_lang']) or \
                   (package.from_code == 'en' and package.to_code == 'tr'):  # Varsayılan olarak
                    package.install()
                    SERVICE_STATUS['argos']['progress'] = 90
            
            SERVICE_STATUS['argos']['status'] = 'ready'
            SERVICE_STATUS['argos']['progress'] = 100
        else:
            # Zaten kuruluysa
            SERVICE_STATUS['argos']['status'] = 'ready'
            SERVICE_STATUS['argos']['progress'] = 100
        
        return True
    except Exception as e:
        SERVICE_STATUS['argos']['status'] = 'error'
        SERVICE_STATUS['argos']['progress'] = 0
        print(f"Argos Translate kurulum hatası: {e}")
        return False

# Çeviri servisleri için durumu kontrol et ve göster
def check_translator_service(service_name):
    """Belirtilen çeviri servisinin durumunu kontrol eder ve günceller"""
    if service_name == 'google':
        try:
            SERVICE_STATUS['google']['status'] = 'loading'
            SERVICE_STATUS['google']['progress'] = 50
            # Kısa bir test çevirisi yap
            test_result = translate_with_google("test", "en", "tr")
            if test_result and test_result != "[Çeviri Hatası":
                SERVICE_STATUS['google']['status'] = 'ready'
                SERVICE_STATUS['google']['progress'] = 100
            else:
                SERVICE_STATUS['google']['status'] = 'error'
                SERVICE_STATUS['google']['progress'] = 0
        except Exception:
            SERVICE_STATUS['google']['status'] = 'error'
            SERVICE_STATUS['google']['progress'] = 0
    
    elif service_name == 'libretranslate':
        global current_libre_server
        # Tüm LibreTranslate sunucularını test et
        for i, server in enumerate(LIBRE_TRANSLATE_SERVERS):
            try:
                SERVICE_STATUS['libretranslate']['status'] = 'loading'
                SERVICE_STATUS['libretranslate']['progress'] = 25 * (i + 1)
                payload = {
                    "q": "test",
                    "source": "en",
                    "target": "tr",
                    "format": "text"
                }
                response = requests.post(server, data=payload, timeout=3)
                if response.status_code == 200:
                    SERVICE_STATUS['libretranslate']['status'] = 'ready'
                    SERVICE_STATUS['libretranslate']['progress'] = 100
                    current_libre_server = i  # Çalışan sunucuyu kaydet
                    break
            except Exception:
                continue
        
        # Hiçbir sunucu çalışmazsa
        if SERVICE_STATUS['libretranslate']['status'] != 'ready':
            SERVICE_STATUS['libretranslate']['status'] = 'error'
            SERVICE_STATUS['libretranslate']['progress'] = 0
    
    elif service_name == 'argos':
        if not ARGOS_AVAILABLE:
            SERVICE_STATUS['argos']['status'] = 'error'
            SERVICE_STATUS['argos']['progress'] = 0
            return
        
        setup_argos_translate()

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
            if i < max_retries - 1:  # Son deneme değilse
                time.sleep(1)  # Biraz bekle ve tekrar dene
                # Başarısız olursa yeni bir çevirmen nesnesi oluştur
                translator = Translator()
            else:
                return f"[Çeviri Hatası: {str(e)}]"

def translate_with_libretranslate(text, source_lang="en", target_lang="tr"):
    """LibreTranslate API kullanarak çeviri yapar"""
    if not text:
        return ""
    
    max_retries = 3
    for i in range(max_retries):
        try:
            server_url = LIBRE_TRANSLATE_SERVERS[current_libre_server]
            payload = {
                "q": text,
                "source": source_lang,
                "target": target_lang,
                "format": "text"
            }
            response = requests.post(server_url, data=payload, timeout=5)
            if response.status_code == 200:
                return response.json()["translatedText"]
            else:
                # Bir sonraki sunucuyu dene
                global current_libre_server
                current_libre_server = (current_libre_server + 1) % len(LIBRE_TRANSLATE_SERVERS)
                if i == max_retries - 1:
                    return f"[Çeviri Hatası: {response.status_code}]"
        except Exception as e:
            if i < max_retries - 1:
                time.sleep(1)
                # Bir sonraki sunucuyu dene
                global current_libre_server
                current_libre_server = (current_libre_server + 1) % len(LIBRE_TRANSLATE_SERVERS)
            else:
                return f"[Çeviri Hatası: {str(e)}]"

def translate_with_argos(text, source_lang="en", target_lang="tr"):
    """Argos Translate kullanarak offline çeviri yapar"""
    if not ARGOS_AVAILABLE:
        return "[Argos Translate kütüphanesi yüklü değil]"
    
    if not text:
        return ""
    
    try:
        # Yüklü paketleri kontrol et
        installed_languages = argostranslate.translate.get_installed_languages()
        from_lang = list(filter(lambda x: x.code == source_lang, installed_languages))
        to_lang = list(filter(lambda x: x.code == target_lang, installed_languages))
        
        if not from_lang or not to_lang:
            return f"[Dil çifti bulunamadı: {source_lang}->{target_lang}]"
        
        # Çeviri yap
        translation = from_lang[0].get_translation(to_lang[0])
        return translation.translate(text)
    except Exception as e:
        return f"[Çeviri Hatası: {str(e)}]"

def translate_text(text, source_lang="en", target_lang="tr"):
    """Seçilen çeviri motorunu kullanarak çeviri yapar"""
    if config['translator_service'] == 'google':
        return translate_with_google(text, source_lang, target_lang)
    elif config['translator_service'] == 'libretranslate':
        return translate_with_libretranslate(text, source_lang, target_lang)
    else:  # 'argos'
        return translate_with_argos(text, source_lang, target_lang)

# -------------------------
# 3. TESSERACT KONTROL
# -------------------------
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

# -------------------------
# 4. GLOBAL DURUM
# -------------------------
running = False
app_running = True
rects_visible = True

# -------------------------
# 5. TKINTER OVERLAY
# -------------------------
root = tk.Tk()
sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
root.geometry(f"{sw}x{sh}+0+0")
root.overrideredirect(True)
root.attributes('-topmost', True)
root.configure(bg='black')
root.attributes('-transparentcolor', 'black')

canvas = tk.Canvas(root, width=sw, height=sh, bg='black', highlightthickness=0)
canvas.place(x=0, y=0)
region_rect = display_rect = original_text_rect = None

def draw_rectangles():
    global region_rect, display_rect, original_text_rect
    if region_rect: canvas.delete(region_rect)
    if display_rect: canvas.delete(display_rect)
    if original_text_rect: canvas.delete(original_text_rect)
    
    r = config['region']
    d = config['display']
    o = config['original_text']
    
    region_rect = canvas.create_rectangle(r['x'], r['y'], r['x']+r['width'], r['y']+r['height'], outline='white', width=2)
    display_rect = canvas.create_rectangle(d['x'], d['y'], d['x']+d['width'], d['y']+d['height'], outline='white', dash=(4,2), width=2)
    original_text_rect = canvas.create_rectangle(o['x'], o['y'], o['x']+o['width'], o['y']+o['height'], outline='cyan', dash=(2,2), width=2)

def hide_rectangles():
    global region_rect, display_rect, original_text_rect
    if region_rect: canvas.delete(region_rect)
    if display_rect: canvas.delete(display_rect)
    if original_text_rect: canvas.delete(original_text_rect)

def toggle_rects():
    global rects_visible
    rects_visible = not rects_visible
    if rects_visible:
        draw_rectangles()
        status_label.place(x=config['display']['x'], y=config['display']['y'] + config['display']['height'] + 5)
        progress_frame.place(x=config['display']['x'], y=config['display']['y'] + config['display']['height'] + 30)
        if running:
            update_status_label()
        toggle_btn.config(text="Çerçeveleri Gizle")
    else:
        hide_rectangles()
        status_label.place_forget()  # Durum etiketini gizle
        progress_frame.place_forget()  # İlerleme çubuğunu gizle
        toggle_btn.config(text="Çerçeveleri Göster")

def update_status_label():
    """Durum etiketini günceller"""
    service_names = {
        'google': "Google Translate",
        'libretranslate': "LibreTranslate",
        'argos': "Argos Translate (Offline)"
    }
    service_name = service_names.get(config['translator_service'], config['translator_service'])
    status_label.config(text=f"Çeviri: {config['source_lang']} -> {config['target_lang']} ({service_name})")

def update_progress_bar():
    """Servis durumuna göre ilerleme çubuğunu günceller"""
    service = config['translator_service']
    status = SERVICE_STATUS[service]['status']
    progress = SERVICE_STATUS[service]['progress']
    
    # İlerleme durumuna göre renk ayarla
    if status == 'ready':
        progress_bar['style'] = 'green.Horizontal.TProgressbar'
    elif status == 'loading':
        progress_bar['style'] = 'grey.Horizontal.TProgressbar'
    else:  # error veya unknown
        progress_bar['style'] = 'red.Horizontal.TProgressbar'
    
    progress_bar['value'] = progress
    
    if app_running:
        root.after(500, update_progress_bar)

draw_rectangles()

# Çevrilmiş metin gösterimi
tl = tk.Label(root, text='', font=('Arial',16), bg='black', fg='white', wraplength=config['wraplength'], justify='left')
tl.place(x=config['display']['x'], y=config['display']['y'])

# Çevrilmemiş metin gösterimi
original_tl = tk.Label(root, text='', font=('Arial',14), bg='black', fg='cyan', 
                       wraplength=config['original_text']['width'] - 20, justify='left')
original_tl.place(x=config['original_text']['x'], y=config['original_text']['y'])

# Aktif çeviri göstergesi
active_label = tk.Label(root, text='Çeviri aktif', font=('Arial',14,'bold'), fg='lime', bg='black')
active_label.place_forget()

# Durum etiketi
status_label = tk.Label(root, text='', font=('Arial',10), fg='yellow', bg='black')
status_label.place(x=config['display']['x'], y=config['display']['y'] + config['display']['height'] + 5)

# Servis durum göstergesi (yükleme çubuğu)
progress_frame = ttk.Frame(root)
progress_frame.place(x=config['display']['x'], y=config['display']['y'] + config['display']['height'] + 30)

# Stil tanımlamaları
style = ttk.Style()
style.configure('green.Horizontal.TProgressbar', background='green')
style.configure('red.Horizontal.TProgressbar', background='red')
style.configure('grey.Horizontal.TProgressbar', background='grey')

progress_bar = ttk.Progressbar(
    progress_frame, 
    orient='horizontal', 
    length=200, 
    mode='determinate',
    style='grey.Horizontal.TProgressbar'
)
progress_bar.pack(side='left', padx=5)

# -------------------------
# 6. AYARLAR PENCERESİ
# -------------------------
settings = tk.Toplevel(root)
settings.title('Bölge Ayarları')
settings.geometry('550x530')  # Genişletilmiş pencere
settings.attributes('-topmost', True)
settings.protocol('WM_DELETE_WINDOW', lambda: shutdown())

# Bölge ayarları
region_frame = ttk.LabelFrame(settings, text='Bölge Ayarı')
region_frame.grid(row=0, column=0, columnspan=3, padx=10, pady=10, sticky='ew')

ocr_frame = ttk.LabelFrame(region_frame, text='OCR Bölgesi')
display_frame = ttk.LabelFrame(region_frame, text='Çeviri Gösterim Bölgesi')
original_frame = ttk.LabelFrame(region_frame, text='Çevrilmemiş Metin Bölgesi')

ocr_frame.grid(row=0, column=0, padx=10, pady=10)
display_frame.grid(row=0, column=1, padx=10, pady=10)
original_frame.grid(row=0, column=2, padx=10, pady=10)

entries = {}
for i, (label_text, sec, key) in enumerate([('X','region','x'),('Y','region','y'),('W','region','width'),('H','region','height')]):
    ttk.Label(ocr_frame, text=label_text).grid(row=i, column=0)
    e = ttk.Entry(ocr_frame, width=8)
    e.grid(row=i, column=1)
    e.insert(0, str(config[sec][key]))
    entries[(sec, key)] = e

for i, (label_text, sec, key) in enumerate([('X','display','x'),('Y','display','y'),('W','display','width'),('H','display','height')]):
    ttk.Label(display_frame, text=label_text).grid(row=i, column=0)
    e = ttk.Entry(display_frame, width=8)
    e.grid(row=i, column=1)
    e.insert(0, str(config[sec][key]))
    entries[(sec, key)] = e

for i, (label_text, sec, key) in enumerate([('X','original_text','x'),('Y','original_text','y'),('W','original_text','width'),('H','original_text','height')]):
    ttk.Label(original_frame, text=label_text).grid(row=i, column=0)
    e = ttk.Entry(original_frame, width=8)
    e.grid(row=i, column=1)
    e.insert(0, str(config[sec][key]))
    entries[(sec, key)] = e

# Dil ayarları ekle
lang_frame = ttk.LabelFrame(settings, text='Dil Ayarları')
lang_frame.grid(row=1, column=0, columnspan=3, padx=10, pady=5, sticky='ew')

ttk.Label(lang_frame, text='Kaynak Dil:').grid(row=0, column=0, padx=5, pady=5)
source_lang_entry = ttk.Entry(lang_frame, width=10)
source_lang_entry.grid(row=0, column=1, padx=5, pady=5)
source_lang_entry.insert(0, config['source_lang'])

ttk.Label(lang_frame, text='Hedef Dil:').grid(row=0, column=2, padx=5, pady=5)
target_lang_entry = ttk.Entry(lang_frame, width=10)  
target_lang_entry.grid(row=0, column=3, padx=5, pady=5)
target_lang_entry.insert(0, config['target_lang'])

ttk.Label(lang_frame, text='Örn: en, tr, fr, de, es, ja, ko, ru, zh-cn').grid(row=1, column=0, columnspan=4, padx=5, pady=0)

# Çeviri servisi seçme
translator_frame = ttk.LabelFrame(settings, text='Çeviri Servisi')
translator_frame.grid(row=2, column=0, columnspan=3, padx=10, pady=5, sticky='ew')

translator_var = tk.StringVar(value=config['translator_service'])
google_radio = ttk.Radiobutton(translator_frame, text='Google Translate (Çevrimiçi)', value='google', variable=translator_var)
google_radio.grid(row=0, column=0, padx=5, pady=5, sticky='w')

libre_radio = ttk.Radiobutton(translator_frame, text='LibreTranslate (Çevrimiçi)', value='libretranslate', variable=translator_var)
libre_radio.grid(row=1, column=0, padx=5, pady=5, sticky='w')

argos_radio = ttk.Radiobutton(translator_frame, text='Argos Translate (Çevrimdışı)', value='argos', variable=translator_var)
argos_radio.grid(row=2, column=0, padx=5, pady=5, sticky='w')

# Servis test butonları
def test_service():
    service = translator_var.get()
    check_translator_service(service)
    update_progress_bar()
    
    # Test sonuçlarını göster
    status_text = {
        'ready': 'Hazır',
        'loading': 'Yükleniyor...',
        'error': 'Hata',
        'unknown': 'Bilinmiyor'
    }
    
    status = SERVICE_STATUS[service]['status']
    messagebox.showinfo('Servis Test Sonucu', f"{service} servisi durum: {status_text.get(status, status)}")

test_btn = ttk.Button(translator_frame, text='Seçili Servisi Test Et', command=test_service)
test_btn.grid(row=3, column=0, pady=5, sticky='w')

toggle_btn = ttk.Button(settings, text='Çerçeveleri Gizle', command=toggle_rects)
toggle_btn.grid(row=4, column=0, columnspan=3, pady=5)

def apply_settings():
    try:
        # Bölge ayarlarını güncelle
        for (sec, key), ent in entries.items():
            config[sec][key] = int(ent.get())
        
        # Dil ayarlarını güncelle
        config['wraplength'] = config['display']['width'] - 20
        config['source_lang'] = source_lang_entry.get()
        config['target_lang'] = target_lang_entry.get()
        
        # Çeviri servisini güncelle
        old_service = config['translator_service']
        new_service = translator_var.get()
        config['translator_service'] = new_service
        
        # Etiketleri yeniden konumlandır
        tl.place(x=config['display']['x'], y=config['display']['y'])
        tl.config(wraplength=config['wraplength'])
        
        original_tl.place(x=config['original_text']['x'], y=config['original_text']['y'])
        original_tl.config(wraplength=config['original_text']['width'] - 20)
        
        status_label.place(x=config['display']['x'], y=config['display']['y'] + config['display']['height'] + 5)
        progress_frame.place(x=config['display']['x'], y=config['display']['y'] + config['display']['height'] + 30)
        
        # Çerçeveleri yeniden çiz
        if rects_visible:
            draw_rectangles()
            update_status_label()
        
        # Servis değiştiyse test et
        if old_service != new_service:
            check_translator_service(new_service)
        
        save_settings(config)
    except Exception as e:
        messagebox.showerror("Ayar Hatası", f"Ayarları güncellerken hata: {str(e)}")

apply_btn = ttk.Button(settings, text='Güncelle', command=apply_settings)
apply_btn.grid(row=5, column=0, columnspan=3, pady=10)

# Uygulama hakkında bilgi
info_text = """
Ekran Çeviri Uygulaması:
- OCR bölgesi: Ekrandaki metni okur (beyaz çerçeve)
- Çeviri gösterim: Çevrilen metni gösterir (beyaz kesikli çerçeve)
- Çevrilmemiş metin: Orijinal metni gösterir (mavi kesikli çerçeve)
- '1' tuşu: Çeviriyi başlat
- '2' tuşu: Çeviriyi durdur

Çeviri Servisleri:
- Google Translate: Çevrimiçi, güvenilir
- LibreTranslate: Çevrimiçi, açık kaynak (alternatif sunucular)
- Argos Translate: Çevrimdışı, dil paketi indirir

İlerleme çubuğu renkleri:
- Yeşil: Servis hazır
- Gri: Yükleniyor/Test ediliyor
- Kırmızı: Hata/Kullanılamaz
"""

info_frame = ttk.LabelFrame(settings, text='Kullanım Bilgisi')
info_frame.grid(row=6, column=0, columnspan=3, padx=10, pady=5, sticky='