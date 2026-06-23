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
    app.run(debug=True, port=5000, host="0.0.0.0")
