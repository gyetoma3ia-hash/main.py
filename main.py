import requests
from bs4 import BeautifulSoup
import time
import json
import os

# --- CONFIGURACIÓN ---
TOKEN = "8602355022:AAGBkYayZjJCYlPcv0tc5ci6mffBWX2cWxI"
CHAT_ID = "8781459612"
# Categorías principales de PB Tech
URLS = {
    "Laptops": "https://www.pbtech.co.nz/category/computers/laptops",
    "Phones": "https://www.pbtech.co.nz/category/phones-gps/smartphones",
    "PC Parts": "https://www.pbtech.co.nz/category/components"
}
DATA_FILE = "prices_history.json"
UMBRAL_ANOMALIA = 0.20  # Alerta si el precio baja más del 20%

def send_telegram_msg(message):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Error enviando a Telegram: {e}")

def get_pbtech_prices(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
    }
    products = []
    try:
        response = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Buscamos los contenedores de productos (esto puede variar si PB Tech actualiza su web)
        items = soup.find_all('div', class_='product_list_item')
        
        for item in items:
            name = item.find('a', class_='item_name').text.strip()
            price_text = item.find('span', class_='price').text.replace('$', '').replace(',', '').strip()
            price = float(price_text)
            link = "https://www.pbtech.co.nz" + item.find('a', class_='item_name')['href']
            products.append({"name": name, "price": price, "link": link})
    except Exception as e:
        print(f"Error scrapeando {url}: {e}")
    return products

def check_for_anomalies():
    # Cargar historial
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r') as f:
            history = json.load(f)
    else:
        history = {}

    for cat_name, url in URLS.items():
        print(f"Revisando {cat_name}...")
        current_products = get_pbtech_prices(url)
        
        for prod in current_products:
            p_id = prod['name']
            current_price = prod['price']
            
            if p_id in history:
                old_price = history[p_id]
                # Lógica de anomalía: caída repentina de precio
                if current_price < old_price * (1 - UMBRAL_ANOMALIA):
                    msg = f"🚨 *OFERTA DETECTADA* 🚨\n\n📦 {prod['name']}\n💰 Antes: ${old_price}\n🔥 Ahora: ${current_price}\n🔗 [Ver producto]({prod['link']})"
                    send_telegram_msg(msg)
            
            # Actualizar historial
            history[p_id] = current_price

    with open(DATA_FILE, 'w') as f:
        json.dump(history, f)

if __name__ == "__main__":
    print("Bot iniciado...")
    while True:
        check_for_anomalies()
        # Esperar 1 hora y media (5400 segundos)
        time.sleep(5400)
