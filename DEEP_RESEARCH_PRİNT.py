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
        'source_display': {'x': 600, 'y': 320, 'width': 500, 'height': 200},  # Yeni: Kaynak metin bölgesi
        'interval_ms': 1000,
        'wraplength': 480,
        'source_lang': 'en',
        'target_lang': 'tr',
        'translator_service': 'google'  # 'google', 'libretranslate', 'argos'
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
running = False
app_running = True
rects_visible = True
last_text = ""
progress_value = 0

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
        if running:
            update_status_label()
        toggle_btn.config(text="Çerçeveleri Gizle")
    else:
        hide_rectangles()
        status_label.place_forget()
        progress_frame.place_forget()
        toggle_btn.config(text="Çerçeveleri Göster")

def update_status_label():
    """Durum etiketini günceller"""
    service_name = {
        'google': 'Google Translate',
        'libretranslate': 'LibreTranslate',
        'argos': 'Argos Translate'
    }.get(config['translator_service'], 'Google')
    
    status_label.config(text=f"Çeviri: {config['source_lang']} -> {config['target_lang']} ({service_name})")

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
settings.geometry('365x580')  # Daha büyük pencere
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
    ttk.Label(translator_frame, text="Kurduktan sonra dil paketlerini yüklemelisiniz.").grid(
        row=2, column=0, columnspan=3, padx=5, pady=0
    )
else:
    def install_argos_packages():
        """Mevcut dil paketlerini indirip kurar"""
        try:
            # Mevcut paketleri getir
            available_packages = argostranslate.package.get_available_packages()
            
            # İlerleme penceresi
            progress_window = tk.Toplevel()
            progress_window.title("Dil Paketi Yükleniyor")
            progress_window.geometry("400x200")
            progress_window.attributes('-topmost', True)
            
            progress_label = ttk.Label(progress_window, text="Dil paketleri indiriliyor ve kuruluyor...")
            progress_label.pack(pady=20)
            
            progress = ttk.Progressbar(progress_window, orient="horizontal", length=300, mode="indeterminate")
            progress.pack(pady=10)
            progress.start()
            
            # Hangi paketlerin kurulacağını gösteren metin kutusu
            info_text = tk.Text(progress_window, height=5, width=45)
            info_text.pack(pady=10)
            
            # Paketleri listele
            info_text.insert(tk.END, "Yüklenecek paketler:\n")
            for package in available_packages:
                info_text.insert(tk.END, f"- {package.from_code} -> {package.to_code}\n")
            
            # İşlemi başlat
            progress_window.update()
            
            # Tüm mevcut paketleri kur
            for package in available_packages:
                progress_label.config(text=f"Yükleniyor: {package.from_code} -> {package.to_code}")
                progress_window.update()
                argostranslate.package.install_from_path(package.download())
            
            progress.stop()
            progress_label.config(text="Tüm dil paketleri başarıyla kuruldu!")
            
            # Tamam butonu
            ttk.Button(
                progress_window, 
                text="Tamam", 
                command=progress_window.destroy
            ).pack(pady=10)
            
        except Exception as e:
            messagebox.showerror("Kurulum Hatası", f"Dil paketleri yüklenirken hata oluştu: {str(e)}")

    def show_installed_packages():
        """Yüklü dil paketlerini göster"""
        try:
            installed = argostranslate.package.get_installed_packages()
            
            # Paket penceresi
            pkg_window = tk.Toplevel()
            pkg_window.title("Yüklü Dil Paketleri")
            pkg_window.geometry("300x300")
            pkg_window.attributes('-topmost', True)
            
            if not installed:
                ttk.Label(pkg_window, text="Yüklü dil paketi bulunamadı.").pack(pady=20)
            else:
                ttk.Label(pkg_window, text="Yüklü Dil Paketleri:").pack(pady=10)
                
                # Liste görünümü
                tree = ttk.Treeview(pkg_window, columns=("from", "to"), show="headings")
                tree.heading("from", text="Kaynak Dil")
                tree.heading("to", text="Hedef Dil")
                tree.pack(padx=10, pady=10, fill="both", expand=True)
                
                # Paketleri listeye ekle
                for pkg in installed:
                    tree.insert("", "end", values=(pkg.from_code, pkg.to_code))
            
        except Exception as e:
            messagebox.showerror("Hata", f"Yüklü paketler listelenirken hata oluştu: {str(e)}")
    
    # Argos dil paketi yönetim butonları
    pkg_frame = ttk.Frame(translator_frame)
    pkg_frame.grid(row=1, column=0, columnspan=3, padx=5, pady=5)
    
    ttk.Button(pkg_frame, text="Dil Paketlerini Kur", command=install_argos_packages).grid(
        row=0, column=0, padx=5, pady=5
    )
    
    ttk.Button(pkg_frame, text="Yüklü Paketleri Göster", command=show_installed_packages).grid(
        row=0, column=1, padx=5, pady=5
    )

# Çeviri hızı ayarı
speed_frame = ttk.LabelFrame(settings, text='Çeviri Hızı (ms)')
speed_frame.grid(row=3, column=0, columnspan=2, padx=10, pady=5, sticky='ew')

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
control_frame.grid(row=4, column=0, columnspan=2, padx=10, pady=5, sticky='ew')

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

def translate_loop():
    """Ana çeviri döngüsü"""
    global app_running, last_text
    
    while app_running:
        if running:
            try:
                # Ekran görüntüsü al
                img = pyautogui.screenshot(region=(
                    config['region']['x'], 
                    config['region']['y'],
                    config['region']['width'], 
                    config['region']['height']
                ))
                
                # OCR ile metni çıkar
                txt = pytesseract.image_to_string(img, lang='eng').strip()
                txt = " ".join([line.strip() for line in txt.splitlines() if line.strip()])
                
                # Kaynak metni güncelle
                sl.config(text=txt)
                
                # Sadece metin değiştiyse çevir
                if txt and txt != last_text:
                    last_text = txt
                    
                    if rects_visible:
                        status_label.config(text="Çeviriliyor...")
                    
                    # Çeviri yap
                    translated = translate_text(txt, config['source_lang'], config['target_lang'])
                    tl.config(text=translated)
                    
                    if rects_visible:
                        update_status_label()
            except Exception as e:
                if rects_visible:
                    status_label.config(text=f"Hata: {str(e)}")
        
        # Ayarlanan hızda bekle
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
    global running
    running = False
    active_label.place_forget()
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