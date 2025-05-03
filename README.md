"""
Ekranın belirli bir bölgesinden İngilizce metni çeviren interaktif bir Python aplikasyonu.
Alternatif çeviri servisleri arasında geçiş yapabilme özelliği eklenmiştir.

Özellikler:
- OCR ile seçilen bölgeden metin okuma (pyautogui + pytesseract)
- İki farklı çeviri servisi arasında geçiş yapma imkanı
  * Google Translate çevirisi (API anahtarı gerektirmez)
  * LibreTranslate çevirisi (API anahtarı gerektirmez)
- Klavye kısayolları: 
  * '1' ile çeviri başlat
  * '2' ile durdur
- Çeviri metni genişler; ekrandan taşınca alt satıra kaydırır (word-wrap)
- "Çeviri aktif" animasyonlu etiketi sağ üst köşede gösterir
- Şeffaf overlay pencere (Windows için)
- OCR ve gösterim bölgelerini çerçeveleyen overlay çizgileri: göster/gizle tuşu
- Ayar değişikliklerini JSON dosyasına kaydederek kalıcılık sağlar
- Uygulama penceresi kapandığında tüm işlemler sonlanır

Kurulum:
   
    -pip install pyautogui pytesseract googletrans==4.0.0-rc1 keyboard pillow request
   
    -LibreTranslate API için: pip install libretranslatepy
   
    -Tesseract OCR kurulu ve PATH'e ekli olmalı

Kullanım:
    python screen_translate_app.py
    Ayar penceresindeki "Güncelle" ile değişimleri kaydeder.
    '1' ile çeviriyi başlatıp, '2' ile durdurun.
    "Çerçeveleri Gizle/Göster" butonu overlay kutucuklarını kontrol eder.
"""

<!---
NotWeyn/NotWeyn is a ✨ special ✨ repository because its `README.md` (this file) appears on your GitHub profile.
You can click the Preview link to take a look at your changes.
--->
