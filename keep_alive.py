import requests
import time

URL = "https://iris-store-bot.onrender.com/"

while True:
    try:
        response = requests.get(URL)
        print(f"Ping: {response.status_code}")
    except Exception as e:
        print("Ошибка:", e)

    time.sleep(300)  # каждые 5 минут
