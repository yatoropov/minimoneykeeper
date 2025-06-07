import os
import openai
from fastapi import FastAPI, Request
from pydantic import BaseModel
from telegram import Bot
from google.oauth2 import service_account
from googleapiclient.discovery import build

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_SHEETS_ID = os.getenv("GOOGLE_SHEETS_ID")
GOOGLE_SERVICE_ACCOUNT = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")  # шлях до credentials.json

bot = Bot(token=TELEGRAM_TOKEN)
openai.api_key = OPENAI_API_KEY

app = FastAPI()

# ====== DATA CLASSES ======
class TelegramMessage(BaseModel):
    message: dict

# ====== UTILS ======
def ask_openai(message: str):
    prompt = f"""
Ти — фінансовий асистент. Проаналізуй український текст і поверни поля у JSON:
{{
  "client": "...",
  "amount": ...,
  "amount_words": "...",
  "date": "...",
  "service": "..."
}}
Дата: якщо "сьогодні" — форматуй як "7 червня 2025 р."
Сума прописом — українською. Якщо послуга не вказана — залиш поле пустим.
Текст: \"\"\"{message}\"\"\"
"""
    completion = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "Ти фінансовий асистент."},
            {"role": "user", "content": prompt}
        ],
        temperature=0,
        max_tokens=256
    )
    reply = completion.choices[0].message.content
    import re, json
    match = re.search(r"\{[\s\S]*?\}", reply)
    if match:
        return json.loads(match.group())
    else:
        raise Exception("OpenAI не повернув валідний JSON: " + reply)

def get_gsheets_service():
    creds = service_account.Credentials.from_service_account_file(
        GOOGLE_SERVICE_ACCOUNT,
        scopes=['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    )
    return build('sheets', 'v4', credentials=creds)

def find_client(name, service):
    sheet = service.spreadsheets()
    result = sheet.values().get(
        spreadsheetId=GOOGLE_SHEETS_ID,
        range="clients!A:C"  # припустимо, клієнти зберігаються тут
    ).execute()
    rows = result.get('values', [])
    for row in rows[1:]:
        if row[0].strip().lower() == name.strip().lower():
            return row
    return None

def get_default_service(service):
    sheet = service.spreadsheets()
    result = sheet.values().get(
        spreadsheetId=GOOGLE_SHEETS_ID,
        range="services!A1"
    ).execute()
    return result.get('values', [['']])[0][0]

# ====== MAIN ENDPOINT ======
@app.post("/")
async def telegram_webhook(req: Request):
    data = await req.json()
    message = data.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "")

    if "рахунок" in text or "акт" in text:
        try:
            parsed = ask_openai(text)
            gs_service = get_gsheets_service()
            client_data = find_client(parsed["client"], gs_service)
            if not client_data:
                bot.send_message(chat_id, f"Не знайшов клієнта '{parsed['client']}' у таблиці.")
                return {"ok": True}

            service = parsed.get("service") or get_default_service(gs_service)
            if not parsed.get("service"):
                bot.send_message(chat_id, "Яке найменування послуги для рахунку/акту?")
                # тут треба зберігати стан чату (redis, файл, dict...), щоб дочекатися відповіді
                return {"ok": True}

            # =========== Далі логіка генерації PDF (DOCX) ===============
            # Можна підключити python-docx, згенерувати файл, зберегти в Google Drive через API
            # або просто надіслати посилання на Google Диск
            # Або навіть надіслати doc/pdf одразу в Telegram

            bot.send_message(chat_id, f"Рахунок і акт на {parsed['client']} на суму {parsed['amount']} ({parsed['amount_words']}) створено! (PDF-лінк тут...)")
        except Exception as e:
            bot.send_message(chat_id, f"Помилка: {str(e)}")
    else:
        bot.send_message(chat_id, "Щоб виставити рахунок, напишіть фразу типу:\nВистав рахунок та акт на <клієнта> на суму <сума> грн сьогоднішньою датою")
    return {"ok": True}
