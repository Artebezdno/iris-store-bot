import requests
import time
import threading

def auto_ping():
    while True:
        try:
            response = requests.get(
                "https://iris-store-bot.onrender.com/",
                timeout=10
            )
            print(f"Ping OK: {response.status_code}")
        except Exception as e:
            print("Ping error:", e)

        time.sleep(240)  # каждые 4 минуты

threading.Thread(target=auto_ping, daemon=True).start()
