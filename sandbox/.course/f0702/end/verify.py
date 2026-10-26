"""One-time codes: sent and checked by our code, never the model."""
import os
import secrets
import smtplib
import time
from email.message import EmailMessage

from ledgerline import connection

ON_FILE = """SELECT c.email_addr, c.mkt_cd
FROM ledgerline.ll_ord_hdr h JOIN ledgerline.ll_cust c
ON c.cust_id = h.cust_id WHERE h.ord_no = :order_no"""


def send_code(session, order_number):
    """Mail a code to the address stored with the order."""
    cursor = connection.cursor()
    cursor.execute(ON_FILE, order_no=order_number)
    row = cursor.fetchone()
    if row is None:
        return {"error": "no such order"}
    email, market = row
    code = f"{secrets.randbelow(1_000_000):06d}"
    session["pending"] = {"email": email, "market": market,
                          "code": code, "tries": 5,
                          "until": time.time() + 600}
    mail = EmailMessage()
    mail["From"] = "DemoStore <no-reply@demostore.example>"
    mail["To"] = email
    mail["Subject"] = "Your DemoStore code"
    mail.set_content(f"Your code: {code}. It works for ten minutes.")
    with smtplib.SMTP(os.environ["MAIL_SMTP_HOST"],
                      int(os.environ["MAIL_SMTP_PORT"])) as smtp:
        smtp.send_message(mail)
    return {"sent": "a code to the email stored with the order"}


def check_code(session, code):
    """The right code, in time, within five tries: verified."""
    pending = session.get("pending")
    if pending is None or pending["tries"] == 0:
        return False
    pending["tries"] -= 1
    if time.time() > pending["until"] or code != pending["code"]:
        return False
    session["customer"] = pending["email"]
    session["market"] = pending["market"]
    del session["pending"]
    return True
