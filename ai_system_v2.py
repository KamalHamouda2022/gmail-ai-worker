import os, time, imaplib, email, json
from email.header import decode_header
from threading import Thread
from queue import Queue

# ----------------------------
# CONFIG
# ----------------------------
EMAIL_ACCOUNT = os.getenv("EMAIL_ACCOUNT")
APP_PASSWORD = os.getenv("APP_PASSWORD")

STATE_FILE = "state.json"

FOLDERS = [
    "AIU2627",
    "Security",
    "Registrations",
    "Marketing",
    "Attachments",
    "Important",
    "Unsorted"
]

# ----------------------------
# STATE
# ----------------------------
def load_state():
    if os.path.exists(STATE_FILE):
        return json.load(open(STATE_FILE))
    return {"last_index": 0, "stats": {}}

def save_state(state):
    json.dump(state, open(STATE_FILE, "w"))

state = load_state()

# ----------------------------
# DECODER
# ----------------------------
def decode(text):
    if not text:
        return ""
    out = ""
    for part, enc in decode_header(text):
        if isinstance(part, bytes):
            try:
                out += part.decode(enc or "utf-8", errors="ignore")
            except:
                out += part.decode("utf-8", errors="ignore")
        else:
            out += part
    return out.lower()

# ----------------------------
# CLASSIFIER (v2 brain)
# ----------------------------
def classify(subject, sender):
    s = subject + " " + sender

    if "@aiu.edu" in sender:
        return "AIU2627"
    if "security" in s:
        return "Security"
    if "verify" in s or "register" in s:
        return "Registrations"
    if "offer" in s or "buy" in s:
        return "Marketing"
    if "pdf" in s or "attachment" in s:
        return "Attachments"
    if "important" in s:
        return "Important"
    return "Unsorted"

# ----------------------------
# CONNECTION
# ----------------------------
def connect():
    while True:
        try:
            m = imaplib.IMAP4_SSL("imap.gmail.com")
            m.login(EMAIL_ACCOUNT, APP_PASSWORD)
            m.select("inbox")
            return m
        except:
            time.sleep(5)

# ----------------------------
# PROCESS EMAIL
# ----------------------------
def process(msg):
    subject = decode(msg.get("Subject"))
    sender = decode(msg.get("From"))

    folder = classify(subject, sender)

    print(f"📌 {subject[:40]} → {folder}")

    return folder

# ----------------------------
# WORKER
# ----------------------------
def run():
    print("🟢 AI SYSTEM v2 RUNNING 24/7")

    while True:
        mail = connect()

        _, data = mail.search(None, "ALL")
        ids = data[0].split()

        start = state["last_index"]

        if start >= len(ids):
            print("😴 Idle cycle...")
            time.sleep(30)
            continue

        for i in range(start, len(ids)):
            _, msg_data = mail.fetch(ids[i], "(RFC822)")
            msg = email.message_from_bytes(msg_data[0][1])

            folder = process(msg)

            state["last_index"] = i
            state["stats"][folder] = state["stats"].get(folder, 0) + 1

            if i % 20 == 0:
                save_state(state)

        save_state(state)

# ----------------------------
# START
# ----------------------------
if __name__ == "__main__":
    run()