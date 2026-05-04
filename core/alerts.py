"""
Système d'alertes : Telegram pour les pépites immédiates,
email digest quotidien via SendGrid.
"""

import json
import logging
import requests

log = logging.getLogger("alerts")

_VERDICT_EMOJI = {
    "PÉPITE":           "🏆",
    "TRÈS INTÉRESSANT": "🌟",
    "À SURVEILLER":     "👀",
    "MOYEN":            "⚠️",
    "À ÉVITER":         "❌",
    "ERREUR":           "🔴",
}


# ── Telegram ──────────────────────────────────────────────────────────────────

def envoyer_telegram(token: str, chat_id: str, annonce: dict) -> bool:
    """Envoie une alerte Telegram pour une annonce haute priorité."""
    if not token or not chat_id:
        log.warning("Telegram non configuré (TELEGRAM_TOKEN / TELEGRAM_CHAT_ID manquants)")
        return False

    emoji = _VERDICT_EMOJI.get(annonce.get("verdict", ""), "🏠")
    score = annonce.get("score_final", 0)
    prix = f"{annonce['prix']:,}".replace(",", " ") + " €" if annonce.get("prix") else "N/A"
    surface = f"{annonce['surface']} m²" if annonce.get("surface") else "N/A"
    prix_m2 = f"{int(annonce['prix']/annonce['surface'])} €/m²" if annonce.get("prix") and annonce.get("surface") else "N/A"

    points_forts = json.loads(annonce.get("points_forts") or "[]")
    points_forts_txt = "\n".join(f"  ✅ {p}" for p in points_forts[:3])

    vigilances = json.loads(annonce.get("points_vigilance") or "[]")
    vigilances_txt = "\n".join(f"  ⚠️ {v}" for v in vigilances[:2])

    msg = f"""{emoji} *{annonce.get('verdict', 'ANNONCE')} — Score {score}/100*

🏠 *{annonce.get('titre', '')[:80]}*
📍 {annonce.get('ville', '')} · {annonce.get('source', '').upper()}
💰 {prix} · {surface} · {prix_m2}
🔋 DPE : {annonce.get('dpe', 'N/A')}

{annonce.get('resume_ia', '')}

*Points forts :*
{points_forts_txt}

*Vigilances :*
{vigilances_txt}

🔗 [Voir l'annonce]({annonce.get('url', '')})"""

    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id":    chat_id,
                "text":       msg,
                "parse_mode": "Markdown",
                "disable_web_page_preview": False,
            },
            timeout=10,
        )
        if resp.status_code == 200:
            log.info(f"Telegram OK : {annonce.get('titre', '')[:50]}")
            return True
        else:
            log.warning(f"Telegram HTTP {resp.status_code} : {resp.text[:200]}")
    except Exception as e:
        log.error(f"Telegram erreur : {e}")
    return False


# ── Email digest ───────────────────────────────────────────────────────────────

def envoyer_digest(settings, annonces: list) -> bool:
    """Envoie le digest quotidien des meilleures annonces par email."""
    if not settings.SENDGRID_API_KEY or not settings.EMAIL_TO:
        log.warning("SendGrid non configuré — digest ignoré")
        return False

    if not annonces:
        log.info("Aucune annonce à envoyer dans le digest")
        return True

    html = _build_html_digest(annonces)

    from datetime import date
    subject = f"🏠 Immo Bot — {len(annonces)} opportunités du {date.today().strftime('%d/%m/%Y')}"

    try:
        resp = requests.post(
            "https://api.sendgrid.com/v3/mail/send",
            headers={
                "Authorization": f"Bearer {settings.SENDGRID_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "personalizations": [{"to": [{"email": settings.EMAIL_TO}]}],
                "from": {"email": settings.EMAIL_FROM, "name": "Immo Bot"},
                "subject": subject,
                "content": [{"type": "text/html", "value": html}],
            },
            timeout=15,
        )
        if resp.status_code in (200, 202):
            log.info(f"Digest email envoyé → {settings.EMAIL_TO}")
            return True
        log.warning(f"SendGrid HTTP {resp.status_code} : {resp.text[:300]}")
    except Exception as e:
        log.error(f"Email erreur : {e}")
    return False


def _build_html_digest(annonces: list) -> str:
    cards = ""
    for a in annonces:
        score = a.get("score_final", 0)
        emoji = _VERDICT_EMOJI.get(a.get("verdict", ""), "🏠")
        prix = f"{a['prix']:,}".replace(",", " ") + " €" if a.get("prix") else "N/A"
        surface = f"{a['surface']} m²" if a.get("surface") else "N/A"
        prix_m2 = f"{int(a['prix']/a['surface'])} €/m²" if a.get("prix") and a.get("surface") else ""
        color = "#16a34a" if score >= 75 else "#d97706" if score >= 60 else "#6b7280"

        points_forts = json.loads(a.get("points_forts") or "[]")
        pf_html = "".join(f"<li>✅ {p}</li>" for p in points_forts[:3])

        cards += f"""
        <div style="border:1px solid #e5e7eb;border-radius:12px;padding:20px;margin-bottom:20px;background:#fff;">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
            <span style="font-size:20px;font-weight:700;color:{color};">{emoji} {score}/100</span>
            <span style="background:#f3f4f6;padding:4px 10px;border-radius:20px;font-size:12px;color:#6b7280;">{a.get('source','').upper()}</span>
          </div>
          <h3 style="margin:0 0 8px;font-size:16px;color:#111827;">{a.get('titre','')[:100]}</h3>
          <p style="margin:0 0 8px;color:#6b7280;font-size:14px;">📍 {a.get('ville','')} &nbsp;|&nbsp; 💰 {prix} &nbsp;|&nbsp; 📐 {surface} &nbsp;|&nbsp; {prix_m2}</p>
          <p style="margin:0 0 12px;color:#374151;font-size:14px;">{a.get('resume_ia','')}</p>
          <ul style="margin:0 0 12px;padding-left:20px;font-size:13px;color:#374151;">{pf_html}</ul>
          <a href="{a.get('url','')}" style="display:inline-block;background:#1d4ed8;color:#fff;padding:8px 16px;border-radius:8px;text-decoration:none;font-size:14px;">Voir l'annonce →</a>
        </div>"""

    return f"""<!DOCTYPE html><html><body style="font-family:system-ui,sans-serif;max-width:680px;margin:0 auto;padding:20px;background:#f9fafb;">
<h1 style="color:#111827;">🏠 Immo Bot — Opportunités du jour</h1>
<p style="color:#6b7280;">{len(annonces)} annonce(s) au-dessus du seuil · générées automatiquement</p>
{cards}
<p style="color:#9ca3af;font-size:12px;margin-top:20px;">Bot immobilier autonome · GitHub Actions · Données {', '.join(set(a.get('source','') for a in annonces))}</p>
</body></html>"""
