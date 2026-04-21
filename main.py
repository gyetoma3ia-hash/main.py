import requests
from bs4 import BeautifulSoup
import sqlite3
import time
import random
import os
import pandas as pd
import threading 

# --- CONFIGURACIÓN PARA RAILWAY ---
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
CHAT_ID = os.getenv('CHAT_ID')
DB_PATH = os.getenv('DB_PATH', 'precios.db') 

ERROR_PRECIO_MAX = 5.0 
DESCUENTO_MINIMO = 0.40 

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1'
}

# --- FUNCIONES DE TELEGRAM ---

def enviar_telegram_mensaje(mensaje):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": mensaje, "parse_mode": "HTML", "disable_web_page_preview": True}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Error enviando mensaje: {e}")

def enviar_telegram_documento(ruta_archivo, mensaje=""):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument"
    try:
        with open(ruta_archivo, 'rb') as archivo:
            archivos = {'document': archivo}
            datos = {'chat_id': CHAT_ID, 'caption': mensaje}
            requests.post(url, files=archivos, data=datos)
    except Exception as e:
        print(f"Error enviando documento: {e}")

def generar_y_enviar_excel():
    try:
        conn = sqlite3.connect(DB_PATH)
        query = """
            SELECT titulo, precio_viejo, precio_actual, url_producto 
            FROM historial_precios 
            WHERE precio_viejo IS NOT NULL AND precio_actual < precio_viejo
        """
        df = pd.read_sql_query(query, conn)
        conn.close()

        if df.empty:
            enviar_telegram_mensaje("No hay productos con descuento registrado aún.")
            return

        df = df.rename(columns={
            'titulo': 'Producto',
            'precio_viejo': 'Precio Original ($)',
            'precio_actual': 'Precio Oferta ($)',
            'url_producto': 'Link'
        })

        df['Descuento ($)'] = df['Precio Original ($)'] - df['Precio Oferta ($)']
        df['% Descuento'] = (df['Descuento ($)'] / df['Precio Original ($)']) * 100
        df['% Ganancia Potencial'] = ((df['Precio Original ($)'] - df['Precio Oferta ($)']) / df['Precio Oferta ($)']) * 100

        df['% Descuento'] = df['% Descuento'].round(2)
        df['% Ganancia Potencial'] = df['% Ganancia Potencial'].round(2)

        df = df.sort_values(by='% Descuento', ascending=False)
        orden_columnas = ['Producto', 'Precio Original ($)', 'Descuento ($)', 'Precio Oferta ($)', '% Descuento', '% Ganancia Potencial', 'Link']
        df = df[orden_columnas]

        nombre_archivo = "Reporte_Ofertas_PBTech.xlsx"
        df.to_excel(nombre_archivo, index=False)
        enviar_telegram_documento(nombre_archivo, "📊 ¡Acá tenés el reporte de ofertas!")
        
        if os.path.exists(nombre_archivo):
            os.remove(nombre_archivo)
    except Exception as e:
        enviar_telegram_mensaje("Error al generar el archivo Excel.")

def escuchar_comandos_telegram():
    if not TELEGRAM_TOKEN: return
    offset = None
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    
    print("Bot escuchando el comando /excel...")
    while True:
        try:
            params = {'timeout': 30, 'offset': offset}
            respuesta = requests.get(url, params=params, timeout=40).json()
            
            if respuesta.get('ok'):
                mensajes = respuesta.get('result', [])
                for msj in mensajes:
                    offset = msj['update_id'] + 1
                    
                    if 'message' in msj and 'text' in msj['message']:
                        texto = msj['message']['text'].lower()
                        chat_id_recibido = str(msj['message']['chat']['id'])
                        
                        if chat_id_recibido == CHAT_ID and texto == '/excel':
                            enviar_telegram_mensaje("Generando reporte Excel, dame un segundo...")
                            generar_y_enviar_excel()
        except Exception:
            time.sleep(5) 
            continue

# --- FUNCIONES DE SCRAPING CLÁSICO MEJORADO ---

def inicializar_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS historial_precios (
            id_producto TEXT PRIMARY KEY,
            titulo TEXT,
            precio_viejo REAL,
            precio_actual REAL,
            url_producto TEXT
        )
    ''')
    try:
        cursor.execute("ALTER TABLE historial_precios ADD COLUMN precio_viejo REAL")
    except sqlite3.OperationalError:
        pass 
    conn.commit()
    conn.close()

def analizar_categoria_clasica(url_original):
    print(f"Scrapeando: {url_original}")
    datos_totales = []
    pagina_actual = 1
    ids_vistos = set() 
    
    # Iniciamos una sesión para guardar cookies simulando ser un navegador
    session = requests.Session()
    
    while True:
        # Lógica inteligente para armar el link de la página 2, 3, etc.
        if pagina_actual > 1:
            separador = "&" if "?" in url_original else "?"
            url_paginada = f"{url_original}{separador}pg={pagina_actual}"
        else:
            url_paginada = url_original
            
        try:
            response = session.get(url_paginada, headers=HEADERS, timeout=15)
            
            if response.status_code != 200:
                print(f"🛑 BLOQUEO. Código: {response.status_code}")
                break
                
            soup = BeautifulSoup(response.text, 'html.parser')
            productos = soup.find_all('div', class_='js-product-card')
            
            if len(productos) == 0:
                print(f"➡️ Fin de categoría detectado (cero productos en pág {pagina_actual}).")
                break
            
            nuevos_en_pagina = 0 
                
            for prod in productos:
                try:
                    elemento_titulo = prod.find('a', class_='js-product-link')
                    if not elemento_titulo: continue
                    
                    titulo = elemento_titulo.text.strip().replace('\n', ' ') 
                    
                    href = elemento_titulo['href']
                    url_prod = href if href.startswith('http') else "https://www.pbtech.co.nz/" + href.lstrip('/')
                    id_producto = href.split('/')[2] if 'product/' in href else href.split('/')[-1]
                    
                    if not id_producto or id_producto in ids_vistos:
                        continue 
                        
                    ids_vistos.add(id_producto)
                    nuevos_en_pagina += 1
                    
                    caja_precio_con_impuestos = prod.find('div', class_='ginc')
                    if caja_precio_con_impuestos:
                        texto_precio = caja_precio_con_impuestos.find('span', class_='full-price').text
                    else:
                        texto_precio = prod.find('span', class_='full-price').text
                        
                    precio_nuevo = float(texto_precio.replace('$', '').replace(',', '').strip())
                    
                    datos_totales.append((id_producto, titulo, precio_nuevo, url_prod))
                except Exception:
                    continue
            
            print(f"✅ Página {pagina_actual} extraída OK ({nuevos_en_pagina} productos).")
            
            if nuevos_en_pagina == 0:
                print(f"➡️ Fin de categoría (solo repetidos en pág {pagina_actual}).")
                break
                
            pagina_actual += 1
            if pagina_actual > 50:
                print(f"⚠️ Límite de 50 páginas alcanzado.")
                break
                
            time.sleep(2) # Pausa humana entre páginas
            
        except Exception as e:
            print(f"❌ Error procesando pág {pagina_actual}: {e}")
            break
            
    return datos_totales

def procesar_productos(productos_extraidos):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    for id_prod, titulo, precio_nuevo, url_prod in productos_extraidos:
        if not id_prod: continue 
            
        cursor.execute("SELECT precio_actual, precio_viejo FROM historial_precios WHERE id_producto = ?", (id_prod,))
        resultado = cursor.fetchone()
        
        if precio_nuevo <= ERROR_PRECIO_MAX:
            enviar_telegram_mensaje(f"🚨 <b>¡POSIBLE ERROR DE PRECIO!</b>\n{titulo}\n💰 Precio listado: <b>${precio_nuevo}</b>\n🔗 <a href='{url_prod}'>Link</a>")
            
        if resultado is None:
            cursor.execute("INSERT INTO historial_precios (id_producto, titulo, precio_actual, url_producto) VALUES (?, ?, ?, ?)", (id_prod, titulo, precio_nuevo, url_prod))
        else:
            precio_viejo_db = resultado[0] 
            
            if precio_nuevo < precio_viejo_db:
                descuento = (precio_viejo_db - precio_nuevo) / precio_viejo_db
                if descuento >= DESCUENTO_MINIMO:
                    porcentaje_txt = round(descuento * 100)
                    enviar_telegram_mensaje(f"📉 <b>¡DESCUENTO ({porcentaje_txt}%)!</b>\n{titulo}\nAntes: ${precio_viejo_db} | Ahora: <b>${precio_nuevo}</b>\n🔗 <a href='{url_prod}'>Link</a>")
                
                cursor.execute("UPDATE historial_precios SET precio_actual = ?, precio_viejo = ? WHERE id_producto = ?", (precio_nuevo, precio_viejo_db, id_prod))
            elif precio_nuevo > precio_viejo_db:
                cursor.execute("UPDATE historial_precios SET precio_actual = ?, precio_viejo = NULL WHERE id_producto = ?", (precio_nuevo, id_prod))
                
    conn.commit()
    conn.close()

def iniciar_monitoreo():
    inicializar_db()
    
    urls_originales = [
        "https://www.pbtech.co.nz/category/peripherals/monitors/gaming-monitors",
        "https://www.pbtech.co.nz/category/peripherals/monitors/home-monitors",
        "https://www.pbtech.co.nz/category/peripherals/monitors/business-monitors",
        "https://www.pbtech.co.nz/category/peripherals/monitors/ultrawide-monitors",
        "https://www.pbtech.co.nz/category/peripherals/monitors/oled-monitors",
        "https://www.pbtech.co.nz/category/computers/laptops/gaming-laptops",
        "https://www.pbtech.co.nz/category/computers/laptops/home-and-study-laptops",
        "https://www.pbtech.co.nz/category/computers/laptops/business-laptops",
        "https://www.pbtech.co.nz/category/computers/laptops/chromebooks",
        "https://www.pbtech.co.nz/category/computers/laptops/copilot-plus-pcs",
        "https://www.pbtech.co.nz/category/computers/pcs/gaming-pcs",
        "https://www.pbtech.co.nz/category/computers/pcs/home-and-study-pcs",
        "https://www.pbtech.co.nz/category/computers/pcs/business-pcs",
        "https://www.pbtech.co.nz/category/computers/pcs/compact-pcs",
        "https://www.pbtech.co.nz/category/computers/tablets/android-tablets",
        "https://www.pbtech.co.nz/category/computers/tablets/apple-tablets",
        "https://www.pbtech.co.nz/category/computers/tablets/windows-tablets",
        "https://www.pbtech.co.nz/category/computers/aiocomputer/apple-all-in-ones",
        "https://www.pbtech.co.nz/category/computers/aiocomputer/windows-all-in-ones",
        "https://www.pbtech.co.nz/category/peripherals/headsets/business-headsets",
        "https://www.pbtech.co.nz/category/peripherals/headsets/gaming-headsets",
        "https://www.pbtech.co.nz/category/peripherals/mice/gaming-mice",
        "https://www.pbtech.co.nz/category/peripherals/keyboards/gaming-keyboards",
        "https://www.pbtech.co.nz/category/peripherals/keyboards/home-and-office-keyboards",
        "https://www.pbtech.co.nz/category/peripherals/keyboards/keyboard-and-mice",
        "https://www.pbtech.co.nz/category/peripherals/hdd-external",
        "https://www.pbtech.co.nz/category/peripherals/drive-enclosures",
        "https://www.pbtech.co.nz/category/peripherals/usb-memory-cards",
        "https://www.pbtech.co.nz/category/peripherals/backup",
        "https://www.pbtech.co.nz/category/components/cpus/amd-desktop-cpu",
        "https://www.pbtech.co.nz/category/components/cpus/intel-desktop-cpu",
        "https://www.pbtech.co.nz/category/components/cpus/server-cpus",
        "https://www.pbtech.co.nz/category/components/cooling/aio-watercooling",
        "https://www.pbtech.co.nz/category/components/cooling/cpu-air-cooling",
        "https://www.pbtech.co.nz/category/components/cooling/case-fans",
        "https://www.pbtech.co.nz/category/components/cooling/watercooling-parts",
        "https://www.pbtech.co.nz/category/components/motherboards/intel-motherboards",
        "https://www.pbtech.co.nz/category/components/hdd-internal",
        "https://www.pbtech.co.nz/category/components/ssdrives",
        "https://www.pbtech.co.nz/category/components/memory/desktop-memory",
        "https://www.pbtech.co.nz/category/components/memory/laptop-memory",
        "https://www.pbtech.co.nz/category/components/memory/server-memory",
        "https://www.pbtech.co.nz/category/components/psu",
        "https://www.pbtech.co.nz/category/components/pc-cases",
        "https://www.pbtech.co.nz/category/components/case-accessories",
        "https://www.pbtech.co.nz/category/components/graphics-cards/amd-desktop-graphics-cards",
        "https://www.pbtech.co.nz/category/components/graphics-cards/nvidia-desktop-graphics-cards",
        "https://www.pbtech.co.nz/category/components/optical-drives",
        "https://www.pbtech.co.nz/category/components/io-cards",
        "https://www.pbtech.co.nz/category/components/video-capture",
        "https://www.pbtech.co.nz/category/components/other-pc-accessories",
        "https://www.pbtech.co.nz/category/consumables/furniture/chairs/gaming-chairs",
        "https://www.pbtech.co.nz/category/consumables/furniture/desks/gaming-desks",
        "https://www.pbtech.co.nz/category/consumables/furniture/chairs/home-office-chairs",
        "https://www.pbtech.co.nz/category/consumables/furniture/desks/heigh-adjustable-desks",
        "https://www.pbtech.co.nz/category/phones-gps/smartphones/android-phones",
        "https://www.pbtech.co.nz/category/phones-gps/smartphones/apple-ios-phones",
        "https://www.pbtech.co.nz/category/phones-gps/smartphones/shop-all?fs=17255771",
        "https://www.pbtech.co.nz/category/computers/exleased/mobile-phones",
        "https://www.pbtech.co.nz/category/phones-gps/phone-cases",
        "https://www.pbtech.co.nz/category/phones-gps/phone-screen-protectors",
        "https://www.pbtech.co.nz/category/phones-gps/other-phone-accessories/docks-and-stands",
        "https://www.pbtech.co.nz/category/phones-gps/other-phone-accessories/wireless-chargers",
        "https://www.pbtech.co.nz/category/phones-gps/other-phone-accessories/wall-chargers",
        "https://www.pbtech.co.nz/category/phones-gps/other-phone-accessories/bluetooth-trackers",
        "https://www.pbtech.co.nz/category/power-and-lighting/power-banks",
        "https://www.pbtech.co.nz/category/phones-gps/phone-car-mounts",
        "https://www.pbtech.co.nz/category/phones-gps/car-chargers",
        "https://www.pbtech.co.nz/category/phones-gps/smart-watches/smart-watches",
        "https://www.pbtech.co.nz/category/phones-gps/smart-watches/fitness-trackers",
        "https://www.pbtech.co.nz/category/phones-gps/smart-watches/apple-watches",
        "https://www.pbtech.co.nz/category/phones-gps/smart-watches/samsung-galaxy-watches",
        "https://www.pbtech.co.nz/category/phones-gps/smart-watches/smart-rings",
        "https://www.pbtech.co.nz/category/phones-gps/smart-watch-accessories/smart-watch-chargers-docks",
        "https://www.pbtech.co.nz/category/phones-gps/smart-watch-accessories/apple-watch-straps",
        "https://www.pbtech.co.nz/category/headphones-audio/headphones/shop-by-use/noise-cancelling",
        "https://www.pbtech.co.nz/category/headphones-audio/headphones/true-wireless-earphones",
        "https://www.pbtech.co.nz/category/headphones-audio/headphones/wireless-headphones",
        "https://www.pbtech.co.nz/category/headphones-audio/headphones/wireless-earphones",
        "https://www.pbtech.co.nz/category/headphones-audio/headphones/wired-headphones",
        "https://www.pbtech.co.nz/category/headphones-audio/headphones/wired-earphones",
        "https://www.pbtech.co.nz/category/headphones-audio/headphones/open-ear-and-bone-conduction",
        "https://www.pbtech.co.nz/category/headphones-audio/car-audio",
        "https://www.pbtech.co.nz/category/headphones-audio/portable-audio/portable-bluetooth-speakers",
        "https://www.pbtech.co.nz/category/headphones-audio/portable-audio/party-speakers",
        "https://www.pbtech.co.nz/category/headphones-audio/portable-audio/portable-wi-fi-speakers",
        "https://www.pbtech.co.nz/category/headphones-audio/portable-audio/portable-fm-radios",
        "https://www.pbtech.co.nz/category/headphones-audio/home-audio-and-hi-fi-systems/av-receivers-and-accessories",
        "https://www.pbtech.co.nz/category/headphones-audio/home-audio-and-hi-fi-systems/stereo-systems",
        "https://www.pbtech.co.nz/category/headphones-audio/home-audio-and-hi-fi-systems/turntables",
        "https://www.pbtech.co.nz/category/headphones-audio/speakers/smart-speakers",
        "https://www.pbtech.co.nz/category/headphones-audio/speakers/multi-room-speakers",
        "https://www.pbtech.co.nz/category/headphones-audio/speakers/bookshelf-speakers",
        "https://www.pbtech.co.nz/category/headphones-audio/speakers/floorstanding-speakers",
        "https://www.pbtech.co.nz/category/headphones-audio/speakers/home-theatre-systems",
        "https://www.pbtech.co.nz/category/headphones-audio/speakers/computer-speakers",
        "https://www.pbtech.co.nz/category/peripherals/headsets",
        "https://www.pbtech.co.nz/category/headphones-audio/pro-audio/microphones",
        "https://www.pbtech.co.nz/category/headphones-audio/pro-audio/recording-devices",
        "https://www.pbtech.co.nz/category/headphones-audio/dacs-amps-sound-cards",
        "https://www.pbtech.co.nz/category/peripherals/headset-accessories",
        "https://www.pbtech.co.nz/category/headphones-audio/speaker-accessories",
        "https://www.pbtech.co.nz/category/peripherals/cables/audio-cables",
        "https://www.pbtech.co.nz/category/peripherals/adapters/audio-adapters",
        "https://www.pbtech.co.nz/category/tv-av/tvs/4k-televisions",
        "https://www.pbtech.co.nz/category/tv-av/tvs/oled-televisions",
        "https://www.pbtech.co.nz/category/tv-av/tvs/qled-televisions",
        "https://www.pbtech.co.nz/category/tv-av/tvs/mini-led-televisions",
        "https://www.pbtech.co.nz/category/tv-av/tvs/tvs-for-business",
        "https://www.pbtech.co.nz/category/tv-av/tv-mounts-accessory/fixed-wall-mounts",
        "https://www.pbtech.co.nz/category/tv-av/tv-mounts-accessory/full-motion-articulating-mounts",
        "https://www.pbtech.co.nz/category/tv-av/projectors/4k-projectors",
        "https://www.pbtech.co.nz/category/tv-av/projectors/home-gaming-projectors",
        "https://www.pbtech.co.nz/category/tv-av/projectors/laser-tv-projectors",
        "https://www.pbtech.co.nz/category/tv-av/projectors/business-projectors",
        "https://www.pbtech.co.nz/category/tv-av/projectors/portable-projectors",
        "https://www.pbtech.co.nz/category/tv-av/projector-accessories/projector-mounts",
        "https://www.pbtech.co.nz/category/tv-av/projector-accessories/projector-screens",
        "https://www.pbtech.co.nz/category/tv-av/soundbars-and-home-cinema-speakers/soundbars",
        "https://www.pbtech.co.nz/category/tv-av/soundbars-and-home-cinema-speakers/surround-sound-systems",
        "https://www.pbtech.co.nz/category/tv-av/soundbars-and-home-cinema-speakers/speaker-separates",
        "https://www.pbtech.co.nz/category/tv-av/media-streaming-and-disc-players/media-sticks-and-dongles",
        "https://www.pbtech.co.nz/category/tv-av/media-streaming-and-disc-players/media-boxes",
        "https://www.pbtech.co.nz/category/tv-av/media-streaming-and-disc-players/blu-ray-players",
        "https://www.pbtech.co.nz/category/tv-av/digital-signage",
        "https://www.pbtech.co.nz/category/tv-av/digital-signage/interactive-displays",
        "https://www.pbtech.co.nz/category/peripherals/kvms",
        "https://www.pbtech.co.nz/category/uc-video-conferencing/video-conferencing",
        "https://www.pbtech.co.nz/category/peripherals/cables/hdmi-cables",
        "https://www.pbtech.co.nz/category/gaming/xbox/consoles",
        "https://www.pbtech.co.nz/category/gaming/xbox/controllers",
        "https://www.pbtech.co.nz/category/gaming/xbox/accessories",
        "https://www.pbtech.co.nz/category/gaming/playstation/consoles",
        "https://www.pbtech.co.nz/category/gaming/playstation/controllers",
        "https://www.pbtech.co.nz/category/gaming/playstation/accessories",
        "https://www.pbtech.co.nz/category/gaming/nintendo/consoles",
        "https://www.pbtech.co.nz/category/gaming/nintendo/controllers",
        "https://www.pbtech.co.nz/category/gaming/nintendo/cases-pouches-and-screen-protectors",
        "https://www.pbtech.co.nz/category/gaming/gaming-consoles",
        "https://www.pbtech.co.nz/category/gaming/game-controllers",
        "https://www.pbtech.co.nz/category/gaming/console-accessories",
        "https://www.pbtech.co.nz/category/gaming/games",
        "https://www.pbtech.co.nz/category/peripherals/hdd-external/game-drives",
        "https://www.pbtech.co.nz/category/health-fitness-and-outdoors/scooters-ebikes/electric-scooters",
        "https://www.pbtech.co.nz/category/health-fitness-and-outdoors/scooters-ebikes/helmets-safety",
        "https://www.pbtech.co.nz/category/health-fitness-and-outdoors/scooters-ebikes/scooter-and-bike-lights",
        "https://www.pbtech.co.nz/category/health-fitness-and-outdoors/scooters-ebikes/scooter-accessories",
        "https://www.pbtech.co.nz/category/cameras/camcorders/360-cameras",
        "https://www.pbtech.co.nz/category/cameras/camcorders/action-cameras",
        "https://www.pbtech.co.nz/category/cameras/camcorders/consumer-camcorders",
        "https://www.pbtech.co.nz/category/cameras/cameras/mirrorless-camera",
        "https://www.pbtech.co.nz/category/cameras/cameras/point-and-shoot",
        "https://www.pbtech.co.nz/category/cameras/cameras/dslr-camera",
        "https://www.pbtech.co.nz/category/cameras/cameras/time-lapse-cameras",
        "https://www.pbtech.co.nz/category/toys-hobbies-stem/3d-printers-cutters-engravers/3d-printers",
        "https://www.pbtech.co.nz/category/toys-hobbies-stem/3d-printers-cutters-engravers/3d-printer-filament-resins",
        "https://www.pbtech.co.nz/category/toys-hobbies-stem/3d-printers-cutters-engravers/3d-printer-parts-accessories",
        "https://www.pbtech.co.nz/category/toys-hobbies-stem/3d-printers-cutters-engravers/laser-cutters-engravers",
        "https://www.pbtech.co.nz/category/toys-hobbies-stem/3d-printers-cutters-engravers/laser-cutter-engraver-accessories",
        "https://www.pbtech.co.nz/category/toys-hobbies-stem/3d-printers-cutters-engravers/engraving-materials",
        "https://www.pbtech.co.nz/category/toys-hobbies-stem/plastic-model-kits",
        "https://www.pbtech.co.nz/category/toys-hobbies-stem/model-accessories"
    ]
    
    print(f"Bot Ninja activado. Analizando el catálogo público directamente...")
    
    while True:
        for url in urls_originales:
            productos = analizar_categoria_clasica(url)
            if productos:
                procesar_productos(productos)
            time.sleep(4)
            
        print("Catálogo completo analizado. Esperando 2 horas...")
        time.sleep(7200)

if __name__ == '__main__':
    hilo_comandos = threading.Thread(target=escuchar_comandos_telegram, daemon=True)
    hilo_comandos.start()
    
    iniciar_monitoreo()
