import os, imaplib, email, json
from email.header import decode_header

EMAIL = os.getenv("EMAIL_ACCOUNT")
APP_PASSWORD = os.getenv("APP_PASSWORD")

STATE_FILE = "state.json"

def load_state():
    try:
        return json.load(open(STATE_FILE))
    except:
        return {"seen": []}

def save_state(state):
    json.dump(state, open(STATE_FILE, "w"))

def connect():
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(EMAIL, APP_PASSWORD)
    mail.select("inbox")
    return mail

def decode(text):
    if not text:
        return ""
    parts = decode_header(text)
    return "".join(
        str(p[0], p[1] or "utf-8") if isinstance(p[0], bytes) else p[0]
        for p in parts
    )

def classify(subject, sender):
    text = (subject + sender).lower()
    if "@aiu.edu" in sender:
        return "AIU2627"
    if "security" in text:
        return "Security"
    if "verify" in text:
        return "Registration"
    if "offer" in text:
        return "Marketing"
    return "General"

def run():
    print("🟢 GitHub AI Worker running")

    state = load_state()
    mail = connect()

    status, data = mail.search(None, "ALL")
    ids = data[0].split()

    new_count = 0

    for uid in ids[-50:]:  # last 50 emails only (fast + safe)
        if uid.decode() in state["seen"]:
            continue

        _, msg_data = mail.fetch(uid, "(RFC822)")
        msg = email.message_from_bytes(msg_data[0][1])

        subject = decode(msg.get("Subject"))
        sender = decode(msg.get("From"))

        folder = classify(subject, sender)

        print(f"📩 {subject[:40]} → {folder}")

        state["seen"].append(uid.decode())
        new_count += 1

    save_state(state)
    print(f"✅ Done. New emails processed: {new_count}")

if __name__ == "__main__":
    run()