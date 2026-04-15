"""이메일 — IMAP 읽기 + SMTP 보내기. 비밀번호는 keychain 권장."""

from __future__ import annotations

from dataclasses import dataclass

from loguru import logger

from config.settings import get_settings
from core.secrets import get_secret


@dataclass
class EmailTool:
    def _config(self) -> dict:
        s = get_settings()
        cfg = (s.get("interfaces") or {}).get("email") or {}
        return cfg

    def list_inbox(self, n: int = 10, unread_only: bool = False) -> str:
        import imaplib, email
        cfg = self._config()
        host = cfg.get("imap_host")
        user = cfg.get("user")
        pw = get_secret("EMAIL_PASSWORD")
        if not all([host, user, pw]):
            return "이메일 설정 누락 (settings.interfaces.email + EMAIL_PASSWORD secret)"

        try:
            box = imaplib.IMAP4_SSL(host)
            box.login(user, pw)
            box.select("INBOX")
            crit = "UNSEEN" if unread_only else "ALL"
            typ, data = box.search(None, crit)
            ids = data[0].split()[-n:]
            out = []
            for mid in reversed(ids):
                _, msg_data = box.fetch(mid, "(RFC822)")
                msg = email.message_from_bytes(msg_data[0][1])
                subj = msg.get("Subject", "")
                frm = msg.get("From", "")
                out.append(f"  [{mid.decode()}] {frm} | {subj[:80]}")
            box.logout()
            return "\n".join(out) if out else "(메일 없음)"
        except Exception as e:
            return f"IMAP 오류: {e}"

    def send(self, to: str, subject: str, body: str) -> str:
        import smtplib
        from email.mime.text import MIMEText
        cfg = self._config()
        host = cfg.get("smtp_host")
        port = int(cfg.get("smtp_port", 587))
        user = cfg.get("user")
        pw = get_secret("EMAIL_PASSWORD")
        if not all([host, user, pw]):
            return "이메일 설정 누락"
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = user
        msg["To"] = to
        try:
            with smtplib.SMTP(host, port) as s:
                s.starttls()
                s.login(user, pw)
                s.send_message(msg)
            return f"메일 전송 완료: {to}"
        except Exception as e:
            return f"SMTP 오류: {e}"
