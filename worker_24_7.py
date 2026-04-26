# 🤖 24/7 Gmail Worker (connection pool + queue + idle loop + reconnect)

import imaplib
import email
from email.header import decode_header
import time
import os
import re
import threading
from queue import Queue

# ----------------------------
# 🔐 CONFIG (use env vars in cloud)
# ----------------------------
EMAIL_ACCOUNT = os.getenv("EMAIL_ACCOUNT", "your_email@gmail.com")
APP_PASSWORD  = os.getenv("APP_PASSWORD", "your_app_password")
IMAP_SERVER   = "imap.gmail.com"

STATE_FILE = "state.txt"

POOL_SIZE = 2          # keep low for Gmail
WORKERS   = 2
BATCH_SIZE = 200       # process per cycle
IDLE_SLEEP = 30        # seconds between cycles when no work

# ----------------------------
# 🧰 helpers
# ----------------------------
def decode_text(text):
    if not text:
        return ""
    out = ""
    for part, enc in decode_header(text):
        if isinstance(part, bytes):
            try:
                enc = enc if enc and enc.lower() != "unknown-8bit" else "utf-8"
                out += part.decode(enc, errors="ignore")
            except:
                out += part.decode("utf-8", errors="ignore")
        else:
            out += part
    return out.lower()

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            return int(open(STATE_FILE).read().strip())
        except:
            return 0
    return 0

def save_state(i):
    with open(STATE_FILE, "w") as f:
        f.write(str(i))

def has_attachment(msg):
    for p in msg.walk():
        if p.get_filename():
            return True
    return False

def ensure_label(conn, label):
    try:
        conn.create(label)
    except:
        pass

def move_email(conn, eid, label):
    ensure_label(conn, label)
    conn.copy(eid, label)
    conn.store(eid, '+FLAGS', '\\Deleted')

def copy_to_label(conn, eid, label):
    ensure_label(conn, label)
    conn.copy(eid, label)

# ----------------------------
# 🧠 AIU processor (simple)
# ----------------------------
def extract_body(msg):
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype == "text/plain":
                body += part.get_payload(decode=True).decode(errors="ignore")
            elif ctype == "text/html":
                html = part.get_payload(decode=True).decode(errors="ignore")
                body += re.sub('<.*?>', '', html)
    else:
        body = msg.get_payload(decode=True).decode(errors="ignore")
    return body

def process_aiu(msg, subject, sender):
    if "@aiu.edu" not in sender:
        return
    os.makedirs("AIU2627", exist_ok=True)
    body = extract_body(msg)[:4000]
    with open("AIU2627/emails.txt", "a") as f:
        f.write(f"\n===\nSUBJECT:{subject}\nSENDER:{sender}\n\n{body[:1200]}\n")

# ----------------------------
# 🔌 IMAP pool
# ----------------------------
class IMAPPool:
    def __init__(self, n):
        self.q = Queue()
        for _ in range(n):
            self.q.put(self._new())

    def _new(self):
        m = imaplib.IMAP4_SSL(IMAP_SERVER)
        m.login(EMAIL_ACCOUNT, APP_PASSWORD)
        m.select("inbox")
        return m

    def get(self):
        return self.q.get()

    def put(self, conn):
        self.q.put(conn)

    def recycle(self, conn):
        try:
            conn.logout()
        except:
            pass
        self.q.put(self._new())

    def close_all(self):
        while not self.q.empty():
            c = self.q.get()
            try: c.logout()
            except: pass

# ----------------------------
# 🧵 worker
# ----------------------------
progress_lock = threading.Lock()
progress = {"done": 0, "total": 0, "t0": time.time()}

def show_progress():
    with progress_lock:
        done, total = progress["done"], progress["total"]
        dt = time.time() - progress["t0"]
        spd = done/dt if dt>0 else 0
        rem = total-done
        eta = int(rem/spd) if spd>0 else 0
        pct = (done/total*100) if total else 0
        print(f"📊 {done}/{total} ({pct:.1f}%) | ⚡ {spd:.2f}/s | ⏳ ETA {eta}s")

def worker(q, pool):
    while True:
        item = q.get()
        if item is None:
            break

        eid, idx = item
        conn = pool.get()

        try:
            typ, data = conn.fetch(eid, "(RFC822)")
            msg = email.message_from_bytes(data[0][1])

            subject = decode_text(msg.get("Subject"))
            sender  = decode_text(msg.get("From"))

            if has_attachment(msg):
                copy_to_label(conn, eid, "has_attachments")

            process_aiu(msg, subject, sender)

            # simple bucket
            move_email(conn, eid, "processed")

            with progress_lock:
                progress["done"] += 1
                save_state(idx)

            if progress["done"] % 50 == 0:
                show_progress()

        except Exception as e:
            print("❌ worker error:", e)
            # connection may be bad → recycle
            pool.recycle(conn)
            conn = None
        finally:
            if conn:
                pool.put(conn)
            q.task_done()

# ----------------------------
# 🔁 one cycle (batch)
# ----------------------------
def process_cycle():
    # connect to list ids
    m = imaplib.IMAP4_SSL(IMAP_SERVER)
    m.login(EMAIL_ACCOUNT, APP_PASSWORD)
    m.select("inbox")

    typ, data = m.search(None, "ALL")
    ids = data[0].split()
    total = len(ids)

    start = load_state()
    end = min(start + BATCH_SIZE, total)

    progress["total"] = end - start
    progress["done"] = 0
    progress["t0"] = time.time()

    print(f"📨 Cycle: {start} → {end} / {total}")

    q = Queue()
    pool = IMAPPool(POOL_SIZE)

    threads = []
    for _ in range(WORKERS):
        t = threading.Thread(target=worker, args=(q, pool), daemon=True)
        t.start()
        threads.append(t)

    for i in range(start, end):
        q.put((ids[i], i))

    q.join()

    # stop workers
    for _ in threads:
        q.put(None)
    for t in threads:
        t.join()

    pool.close_all()
    m.logout()

    return (end < total)  # more work?

# ----------------------------
# 🔄 main loop (24/7)
# ----------------------------
def run_forever():
    print("🟢 24/7 worker started")

    backoff = 5
    while True:
        try:
            more = process_cycle()
            if not more:
                print(f"😴 Idle... sleeping {IDLE_SLEEP}s")
                time.sleep(IDLE_SLEEP)
            backoff = 5  # reset on success

        except Exception as e:
            print("❌ main loop error:", e)
            print(f"🔁 retrying in {backoff}s")
            time.sleep(backoff)
            backoff = min(backoff * 2, 120)

if __name__ == "__main__":
    run_forever()