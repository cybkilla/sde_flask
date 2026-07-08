# check_supabase_schema.py — vérifie que le schéma Supabase est à jour
#
# Pourquoi ce script : les migrations SQL sont documentées dans
# doc/SUPABASE.md mais doivent être exécutées À LA MAIN dans l'éditeur
# Supabase (l'API REST ne permet pas le DDL). Une migration oubliée ne
# casse rien visiblement — le code retombe en mode dégradé — mais des
# fonctionnalités meurent en silence (ex. la table weekly_reports absente
# a bloqué tous les rapports hebdo pendant des semaines).
#
# Usage : python check_supabase_schema.py
# Sortie : ✓/✗ par table et colonne critique — code retour 1 si manque.

import sys


# Tables attendues → colonnes critiques ajoutées par migration (à sonder
# individuellement : une table peut exister sans ses colonnes récentes).
# À COMPLÉTER à chaque nouvelle migration documentée dans doc/SUPABASE.md.
SCHEMA_ATTENDU = {
    "users":               [],
    "watchlist":           [],
    "scores":              [],
    "ticker_snapshots":    [],
    "positions":           ["conseil_date"],
    "daily_advice":        ["signaux_actifs",                      # 2026-07-08
                            "bon_conseil_j5", "bon_conseil_j20",   # 2026-07-08
                            "gain_j20_pct"],
    "weekly_reports":      [],
    "advisor_config":      [],
    "portfolio_snapshots": [],
    "position_targets":    [],
    "auth_tokens":         [],
}


def main() -> int:
    # .env chargé explicitement : le script se lance hors app Flask
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    import db
    db._init()
    if not db.is_available():
        print("✗ Supabase injoignable — vérifier SUPABASE_URL / SUPABASE_KEY dans .env")
        return 1

    manques = []
    for table, colonnes in SCHEMA_ATTENDU.items():
        # Sonde la table : un SELECT limité suffit (PGRST205 si absente)
        try:
            db._client.table(table).select("*").limit(1).execute()
            print(f"✓ {table}")
        except Exception:
            print(f"✗ {table} — TABLE ABSENTE")
            manques.append(table)
            continue

        # Sonde chaque colonne critique (PGRST204/205 si absente)
        for col in colonnes:
            try:
                db._client.table(table).select(col).limit(1).execute()
                print(f"  ✓ {table}.{col}")
            except Exception:
                print(f"  ✗ {table}.{col} — COLONNE ABSENTE")
                manques.append(f"{table}.{col}")

    print()
    if manques:
        print(f"✗ {len(manques)} élément(s) manquant(s) : {', '.join(manques)}")
        print("  → exécuter les migrations correspondantes de doc/SUPABASE.md")
        print("    dans l'éditeur SQL Supabase, puis relancer ce script.")
        return 1
    print("✓ Schéma Supabase complet — toutes les migrations sont appliquées.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
