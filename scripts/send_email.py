#!/usr/bin/env python3
"""
Paper Radar - Email delivery
Sends the daily FILTERED report (your topics) to your inbox, with the GENERAL
report attached as a .md file. Uses only the Python standard library (smtplib).

Reads everything from environment variables so no secrets live in the repo:

    SMTP_HOST   e.g. smtp.gmail.com
    SMTP_PORT   e.g. 465   (SSL)  or 587 (STARTTLS)
    SMTP_USER   the account that authenticates (e.g. your Gmail address)
    SMTP_PASS   the password / app-password
    MAIL_FROM   optional, defaults to SMTP_USER
    MAIL_TO     comma-separated recipient(s)
    REPORTS_DIR optional, defaults to "reports"

If SMTP_HOST / SMTP_USER / SMTP_PASS / MAIL_TO are missing, the script prints a
notice and exits 0 (so local runs and unconfigured forks don't fail the build).
"""

import os
import sys
import ssl
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage


def today_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def filtered_has_papers(text):
    """Heuristic: the report has real papers if it contains a paper heading."""
    return "\n### " in text


def main():
    host = os.environ.get("SMTP_HOST", "").strip()
    port = int(os.environ.get("SMTP_PORT", "465"))
    user = os.environ.get("SMTP_USER", "").strip()
    password = os.environ.get("SMTP_PASS", "")
    mail_from = os.environ.get("MAIL_FROM", "").strip() or user
    mail_to = [a.strip() for a in os.environ.get("MAIL_TO", "").split(",") if a.strip()]

    if not (host and user and password and mail_to):
        print("ℹ️  Email no configurado (faltan SMTP_HOST/SMTP_USER/SMTP_PASS/MAIL_TO). "
              "Se omite el envío.", file=sys.stderr)
        return 0

    out_dir = os.environ.get("REPORTS_DIR", "reports")
    today = today_utc()
    filt_path = os.path.join(out_dir, f"{today}_filtrado.md")
    gen_path = os.path.join(out_dir, f"{today}_general.md")

    if not os.path.exists(filt_path):
        print(f"⚠ No existe el reporte filtrado de hoy ({filt_path}); no se envía email.",
              file=sys.stderr)
        return 0

    with open(filt_path, encoding="utf-8") as f:
        filtered_md = f.read()

    has_papers = filtered_has_papers(filtered_md)
    subject = (
        f"📡 Paper Radar — {today} · papers en tus temas"
        if has_papers
        else f"📡 Paper Radar — {today} · sin papers destacados en tus temas hoy"
    )

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = mail_from
    msg["To"] = ", ".join(mail_to)

    # Plain-text body = the filtered report (Markdown reads fine as text).
    intro = (
        "Tu reporte filtrado de Paper Radar (solo tus temas, alta precisión).\n"
        "El reporte general completo va adjunto.\n"
        f"{'=' * 60}\n\n"
    )
    msg.set_content(intro + filtered_md)

    # Attach the general report so it's there if you want the wider view.
    if os.path.exists(gen_path):
        with open(gen_path, encoding="utf-8") as f:
            general_md = f.read()
        msg.add_attachment(
            general_md.encode("utf-8"),
            maintype="text",
            subtype="markdown",
            filename=f"{today}_general.md",
        )

    context = ssl.create_default_context()
    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, context=context, timeout=30) as server:
                server.login(user, password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=30) as server:
                server.starttls(context=context)
                server.login(user, password)
                server.send_message(msg)
    except Exception as e:  # noqa: BLE001 — surface any SMTP failure clearly
        print(f"❌ Falló el envío de email: {e}", file=sys.stderr)
        return 1

    print(f"✅ Email enviado a {', '.join(mail_to)} (papers: {'sí' if has_papers else 'no'})",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
