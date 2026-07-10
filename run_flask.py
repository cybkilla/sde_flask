# run_flask.py — point d'entrée Flask
# Lancer : python run_flask.py
#           ou en prod : gunicorn "flask_app:create_app()"

import sys
from pathlib import Path

# Permet d'importer les modules pipeline/analysis/data depuis la racine
sys.path.insert(0, str(Path(__file__).parent))

from flask_app import create_app

app = create_app()

if __name__ == "__main__":
    # debug opt-in (FLASK_DEBUG=1 dans .env) : la console Werkzeug du mode
    # debug permet d'EXÉCUTER du code arbitraire — combinée à host=0.0.0.0
    # (nécessaire pour accéder à l'app depuis l'hôte du conteneur), elle
    # serait exposée à tout le réseau local si activée par défaut.
    import os
    debug = os.getenv("FLASK_DEBUG", "0") == "1"
    app.run(debug=debug, port=5000, host="0.0.0.0")
