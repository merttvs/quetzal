from flask import Flask, render_template, request, jsonify
from datetime import datetime
import serial
import time
import netifaces
from getmac import get_mac_address
import logging
import os
import threading


# === YENİ: LOGLAMA SİSTEMİ KURULUMU ===
# Dosya yolunu kullanıcının home dizinine göre dinamik olarak oluştur
log_directory = os.path.join(os.path.expanduser('~'), 'Desktop', 'web_server')
if not os.path.exists(log_directory):
    os.makedirs(log_directory) # Eğer klasör yoksa oluştur
log_file_path = os.path.join(log_directory, 'logs.txt')

# Loglama ayarlarını yap
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s.%(msecs)03d - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler(log_file_path), # Dosyaya loglama
        logging.StreamHandler() # Terminale de loglama
    ]
)


# --- SERİ PORT AYARLARI ---
# SERIAL_PORT = '/dev/ttyUSB0'
SERIAL_PORT = '/dev/serial/by-id/usb-Silicon_Labs_CP2102N_USB_to_UART_Bridge_Controller_04bbd5fec287ed119552970ca703910e-if00-port0'
BAUD_RATE = 115200

# BARKOD_SERIAL_PORT = '/dev/ttyACM0'  # GM67 hangi porta takılıysa değiştir
BARKOD_SERIAL_PORT = '/dev/serial/by-id/usb-BF_SCAN_SCAN_CDC_A-00000-if00'  # GM67 hangi porta takılıysa değiştir
BARKOD_BAUD_RATE = 9600

barkod_verisi = ""

def barkod_okuma_thread():
    global barkod_verisi
    try:
        
        barkod_ser = serial.Serial(BARKOD_SERIAL_PORT, BARKOD_BAUD_RATE, timeout=0)
        logging.info(f"BAŞARILI: GM67 barkod okuyucu {BARKOD_SERIAL_PORT} üzerinden bağlandı.")
        while True:
            veri = barkod_ser.readline().decode('utf-8').strip()
            if veri:
                barkod_verisi = veri[:5]
                logging.info(f"GM67 Barkod Okundu: {barkod_verisi}")
    except serial.SerialException as e:
        logging.error(f"HATA: GM67 barkod okuyucuya bağlanılamadı: {e}")
try:
    ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
    time.sleep(2)
    logging.info(f"BAŞARILI: Deneyap Kart ile {SERIAL_PORT} üzerinden bağlantı kuruldu.")
except serial.SerialException as e:
    logging.error(f"HATA: Seri porta bağlanılamadı: {e}")
    ser = None

# Flask uygulamasını başlat
app = Flask(__name__)
manuel_kontrol_aktif = False

# --- ANA SAYFA ve DURUM SIFIRLAMA ---
@app.route('/')
def ana_sayfa():
    """
    Kullanıcı ana sayfayı her ziyaret ettiğinde (veya yenilediğinde) bu fonksiyon çalışır.
    Böylece sunucu taraflı tüm durumlar güvenli bir şekilde sıfırlanır.
    """
    global manuel_kontrol_aktif
    
    # YENİ: Sayfa yenilendiğinde manuel kontrol durumunu sıfırla
    manuel_kontrol_aktif = False
    
    logging.info("--- Yeni Web Arayüzü Oturumu Başlatıldı (Tüm Durumlar Sıfırlandı) ---")
    
    return render_template('index.html')

# --- AĞ BİLGİLERİ API ---
@app.route('/api/network_info')
def network_info():
    try:
        ipv4, ipv6 = "Bulunamadı", "Bulunamadı"
        for interface in netifaces.interfaces():
            if interface == 'lo': continue
            addrs = netifaces.ifaddresses(interface)
            if netifaces.AF_INET in addrs:
                ipv4 = addrs[netifaces.AF_INET][0]['addr']
            if netifaces.AF_INET6 in addrs:
                ipv6 = addrs[netifaces.AF_INET6][0]['addr']
        mac = get_mac_address() or "Bulunamadı"
        return jsonify({"ipv4": ipv4, "ipv6": ipv6, "mac": mac.upper()})
    except Exception as e:
        logging.error(f"Ağ bilgileri API hatası: {e}")
        return jsonify({"error": "Bilgiler alınamadı."}), 500
@app.route('/api/barkod')
def barkod_goster():
    if ser and ser.is_open and barkod_verisi:
        logging.info(f"KARTA BARKOD GÖNDERİLDİ: {barkod_verisi}")
        ser.write(f"{barkod_verisi}\n".encode('utf-8'))
    else:
        logging.info("KARTA BARKOD VERİSİ GÖNDERİLEMEDİ!")

    return jsonify({"barkod": barkod_verisi})

# --- MANUEL KONTROL API ---
@app.route('/api/manuel_kontrol', methods=['POST'])
def manuel_kontrol_yonet():
    global manuel_kontrol_aktif
    try:
        gelen_veri = request.get_json()
        manuel_kontrol_aktif = bool(gelen_veri.get('durum'))
        durum_mesaji = "AKTİF" if manuel_kontrol_aktif else "PASİF"
        logging.info(f"Manuel kontrol durumu güncellendi -> {durum_mesaji}")
        return jsonify({"durum": "basarili"})
    except Exception as e:
        logging.error(f"Manuel kontrol API hatası: {e}")
        return jsonify({"durum": "hata", "mesaj": str(e)}), 500

# --- KOMUT ALICI API ---
@app.route('/api/komut', methods=['POST'])
def komut_alici():
    global manuel_kontrol_aktif
    try:
        alınan_komut = request.get_json().get('komut')
        logging.info(f"WEB'DEN ALINDI: {alınan_komut.upper()}")

        manuel_hareket_komutlari = ["MANUEL_ILERI", "MANUEL_GERI", "MANUEL_SOL", "MANUEL_SAG"]
        if alınan_komut in manuel_hareket_komutlari and not manuel_kontrol_aktif:
            logging.warning(f"ENGELLEDİ: Manuel kontrol pasif olduğu için '{alınan_komut}' komutu gönderilmedi.")
            return jsonify({"durum": "engellendi", "mesaj": "Manuel kontrol pasif."})

        if ser and ser.is_open:
            logging.info(f"KARTA GÖNDERİLDİ: {alınan_komut}")
            
        else:
            logging.warning(f"UYARI: Seri port kapalı. Komut '{alınan_komut}' karta gönderilemedi.")

        return jsonify({"durum": "basarili", "alınan_komut": alınan_komut})
    except Exception as e:
        logging.critical(f"KRİTİK HATA: Komut alıcıda bir hata oluştu: {e}")
        return jsonify({"durum": "hata", "mesaj": str(e)}), 500

if __name__ == '__main__':
    t = threading.Thread(target=barkod_okuma_thread, daemon=True)
    t.start()
    port_numarasi = 42421
    logging.info("======================================================")
    logging.info(" Quetzal Takımı X3 Aracı Web Sunucusu Başlatılıyor...")
    logging.info(f"Sunucu http://0.0.0.0:{port_numarasi} adresinde çalışacak.")
    logging.info(f"Tüm veri akışı '{log_file_path}' dosyasına kaydedilecek.")
    logging.info("======================================================")
    
    # 'app.run' kendi loglarını bastığı için terminali temiz tutmak adına 
    # Flask'in kendi başlangıç mesajlarını kapatabiliriz.
    # Bu satırda debug=False olması önemlidir.
    app.run(host='0.0.0.0', port=port_numarasi, debug=False)
