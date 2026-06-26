# auth/password_policy.py — Politique de mot de passe SDE
import re

RULES = [
    (r'.{8,}',          "Au moins 8 caractères"),
    (r'[A-Z]',          "Au moins 1 lettre majuscule"),
    (r'[0-9]',          "Au moins 1 chiffre"),
    (r'[^A-Za-z0-9]',  "Au moins 1 caractère spécial (!@#$%…)"),
]


def validate(password: str) -> list[str]:
    """Retourne la liste des règles non satisfaites. Vide = mot de passe valide."""
    return [msg for pattern, msg in RULES if not re.search(pattern, password)]


def is_valid(password: str) -> bool:
    return len(validate(password)) == 0
