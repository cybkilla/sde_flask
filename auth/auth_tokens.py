# auth/auth_tokens.py — Tokens sécurisés : activation de compte + reset de mot de passe
import os, secrets
from datetime import datetime, timedelta, timezone

_TABLE = "auth_tokens"
_BASE_URL = "https://sde-flask.onrender.com"


def _db_ok() -> bool:
    try:
        from db import is_available
        return is_available()
    except Exception:
        return False


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ── Génération / validation ──────────────────────────────────────────────────

def generate(username: str, token_type: str, hours: int = 24) -> str | None:
    """Génère et stocke un token. token_type : 'activation' | 'reset'. Retourne le token."""
    if not _db_ok():
        return None
    try:
        from db import _init, _client
        _init()
        # Invalider les tokens précédents du même type pour cet utilisateur
        _client.table(_TABLE).update({"used": True})\
            .eq("username", username).eq("type", token_type).eq("used", False).execute()
        token = secrets.token_urlsafe(32)
        _client.table(_TABLE).insert({
            "username":   username,
            "token":      token,
            "type":       token_type,
            "expires_at": (_now_utc() + timedelta(hours=hours)).isoformat(),
            "used":       False,
        }).execute()
        return token
    except Exception as e:
        print(f"[AuthTokens] generate erreur ({token_type}) : {e}", flush=True)
        return None


def validate(token: str, token_type: str) -> str | None:
    """Retourne le username si le token est valide, non expiré et non utilisé. Sinon None."""
    if not _db_ok():
        return None
    try:
        from db import _init, _client
        _init()
        rows = (
            _client.table(_TABLE)
            .select("username,expires_at")
            .eq("token", token)
            .eq("type", token_type)
            .eq("used", False)
            .limit(1)
            .execute()
            .data or []
        )
        if not rows:
            return None
        row = rows[0]
        expires = datetime.fromisoformat(row["expires_at"])
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if _now_utc() > expires:
            return None
        return row["username"]
    except Exception as e:
        print(f"[AuthTokens] validate erreur : {e}", flush=True)
        return None


def consume(token: str) -> None:
    """Marque le token comme utilisé (one-time use)."""
    if not _db_ok():
        return
    try:
        from db import _init, _client
        _init()
        _client.table(_TABLE).update({"used": True}).eq("token", token).execute()
    except Exception as e:
        print(f"[AuthTokens] consume erreur : {e}", flush=True)


# ── Envois email ─────────────────────────────────────────────────────────────

def _send(to_email: str, subject: str, body: str) -> bool:
    api_key  = os.getenv("RESEND_API_KEY", "")
    from_    = os.getenv("RESEND_FROM", "SDE StockDecisionEngine <onboarding@resend.dev>")
    if not api_key:
        print(f"[AuthTokens] RESEND_API_KEY manquante — email non envoyé", flush=True)
        return False
    try:
        import resend
        resend.api_key = api_key
        resend.Emails.send({"from": from_, "to": [to_email], "subject": subject, "html": body})
        return True
    except Exception as e:
        print(f"[AuthTokens] envoi email erreur : {e}", flush=True)
        return False


def send_activation(to_email: str, username: str, token: str) -> bool:
    url  = f"{_BASE_URL}/auth/activate/{token}"
    body = f"""
    <div style="font-family:Arial,sans-serif;max-width:480px;margin:0 auto;padding:20px">
      <div style="border-left:4px solid #1D9E75;padding-left:16px;margin-bottom:20px">
        <h2 style="margin:0 0 4px;color:#1E3A5F">Activez votre compte SDE</h2>
        <p style="margin:0;color:#6b7280;font-size:13px">StockDecisionEngine</p>
      </div>
      <p style="color:#374151;font-size:14px">Bonjour <strong>{username}</strong>,</p>
      <p style="color:#374151;font-size:14px">
        Merci pour votre inscription ! Cliquez sur le bouton ci-dessous pour activer votre compte.
      </p>
      <div style="text-align:center;margin:28px 0">
        <a href="{url}" style="background:#1D9E75;color:#fff;text-decoration:none;
           padding:12px 28px;border-radius:8px;font-weight:700;font-size:14px">
          Activer mon compte
        </a>
      </div>
      <p style="color:#9ca3af;font-size:12px">
        Ce lien expire dans <strong>24 heures</strong>.
        Si vous n'avez pas créé de compte, ignorez cet email.
      </p>
    </div>"""
    return _send(to_email, "[SDE] Activez votre compte", body)


def send_reset(to_email: str, username: str, token: str) -> bool:
    url  = f"{_BASE_URL}/auth/reset-password/{token}"
    body = f"""
    <div style="font-family:Arial,sans-serif;max-width:480px;margin:0 auto;padding:20px">
      <div style="border-left:4px solid #6366F1;padding-left:16px;margin-bottom:20px">
        <h2 style="margin:0 0 4px;color:#1E3A5F">Réinitialisation de mot de passe</h2>
        <p style="margin:0;color:#6b7280;font-size:13px">SDE · StockDecisionEngine</p>
      </div>
      <p style="color:#374151;font-size:14px">Bonjour <strong>{username}</strong>,</p>
      <p style="color:#374151;font-size:14px">
        Une demande de réinitialisation de mot de passe a été effectuée pour votre compte.
      </p>
      <div style="text-align:center;margin:28px 0">
        <a href="{url}" style="background:#6366F1;color:#fff;text-decoration:none;
           padding:12px 28px;border-radius:8px;font-weight:700;font-size:14px">
          Réinitialiser mon mot de passe
        </a>
      </div>
      <p style="color:#9ca3af;font-size:12px">
        Ce lien expire dans <strong>1 heure</strong>.
        Si vous n'avez pas fait cette demande, ignorez cet email.
      </p>
    </div>"""
    return _send(to_email, "[SDE] Réinitialisation de votre mot de passe", body)
