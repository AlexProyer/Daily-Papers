#!/usr/bin/env python3
"""
Paper Radar - Email delivery
Sends the daily FILTERED report (your topics) to your inbox as a nicely rendered
HTML email (with a plain-text fallback), and attaches the GENERAL report as a
self-contained .html file you can open in the browser.

Uses only the Python standard library (smtplib + a tiny Markdown->HTML converter),
so there are no external dependencies.

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
import re
import sys
import ssl
import html
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage


def today_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def filtered_has_papers(text):
    """Heuristic: the report has real papers if it contains a paper heading."""
    return "\n### " in text


# ─────────────────────────────────────────────
#  MINIMAL MARKDOWN -> HTML (tailored to the report format)
# ─────────────────────────────────────────────

def _inline(text):
    """Render inline Markdown (links, bold, code, italics) to HTML, safely."""
    text = html.escape(text)
    # [label](url)
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)',
                  r'<a href="\2" style="color:#2563eb;text-decoration:none;">\1</a>',
                  text)
    # **bold**
    text = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', text)
    # `code`
    text = re.sub(r'`([^`]+)`',
                  r'<code style="background:#f1f5f9;padding:1px 5px;border-radius:4px;'
                  r'font-family:Consolas,Menlo,monospace;font-size:0.9em;">\1</code>',
                  text)
    # _italic_ (only when bounded by non-word chars, so URLs/words are untouched)
    text = re.sub(r'(?<!\w)_([^_]+)_(?!\w)', r'<em>\1</em>', text)
    return text


def md_to_html_body(md):
    """Convert the subset of Markdown used by the reports into HTML."""
    out = []
    para, quote = [], []

    def flush_para():
        if para:
            out.append("<p style='margin:8px 0;line-height:1.5;'>"
                       + "<br>".join(_inline(p) for p in para) + "</p>")
            para.clear()

    def flush_quote():
        if quote:
            out.append(
                "<blockquote style='margin:8px 0;padding:8px 14px;border-left:4px solid "
                "#cbd5e1;background:#f8fafc;color:#475569;'>"
                + "<br>".join(_inline(q) for q in quote) + "</blockquote>")
            quote.clear()

    for raw in md.split("\n"):
        s = raw.strip()
        if not s:
            flush_para(); flush_quote()
            continue
        if s.startswith("### "):
            flush_para(); flush_quote()
            out.append("<h3 style='margin:18px 0 6px;font-size:17px;color:#0f172a;'>"
                       + _inline(s[4:]) + "</h3>")
        elif s.startswith("## "):
            flush_para(); flush_quote()
            out.append("<h2 style='margin:26px 0 8px;font-size:20px;color:#1e3a8a;"
                       "border-bottom:2px solid #e2e8f0;padding-bottom:4px;'>"
                       + _inline(s[3:]) + "</h2>")
        elif s.startswith("# "):
            flush_para(); flush_quote()
            out.append("<h1 style='margin:0 0 10px;font-size:24px;color:#0f172a;'>"
                       + _inline(s[2:]) + "</h1>")
        elif s == "---":
            flush_para(); flush_quote()
            out.append("<hr style='border:none;border-top:1px solid #e2e8f0;margin:16px 0;'>")
        elif s.startswith(">"):
            flush_para()
            quote.append(s.lstrip(">").strip())
        else:
            flush_quote()
            para.append(s)

    flush_para(); flush_quote()
    return "\n".join(out)


def wrap_html(inner, title):
    """Wrap rendered body in a minimal, email-client-friendly HTML document."""
    return f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title></head>
<body style="margin:0;background:#f1f5f9;">
<div style="max-width:760px;margin:0 auto;padding:24px;
            font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
            color:#0f172a;background:#ffffff;">
{inner}
</div></body></html>"""


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

    intro_text = (
        "Tu reporte filtrado de Paper Radar (solo tus temas, alta precisión).\n"
        "El reporte general completo va adjunto.\n"
        f"{'=' * 60}\n\n"
    )
    intro_html = (
        "<p style='margin:0 0 16px;color:#64748b;font-size:14px;'>"
        "Tu reporte filtrado de Paper Radar (solo tus temas, alta precisión). "
        "El reporte general completo va adjunto como archivo <code>.html</code>.</p>"
        "<hr style='border:none;border-top:2px solid #e2e8f0;margin:0 0 16px;'>"
    )

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = mail_from
    msg["To"] = ", ".join(mail_to)

    # Plain-text fallback (raw Markdown reads fine as text)
    msg.set_content(intro_text + filtered_md)

    # HTML alternative (this is what renders nicely in Gmail/Outlook/etc.)
    html_body = wrap_html(intro_html + md_to_html_body(filtered_md),
                          f"Paper Radar — {today}")
    msg.add_alternative(html_body, subtype="html")

    # Attach the general report as a rendered, self-contained .html file
    if os.path.exists(gen_path):
        with open(gen_path, encoding="utf-8") as f:
            general_md = f.read()
        general_html = wrap_html(md_to_html_body(general_md),
                                 f"Paper Radar General — {today}")
        msg.add_attachment(
            general_html.encode("utf-8"),
            maintype="text",
            subtype="html",
            filename=f"{today}_general.html",
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
