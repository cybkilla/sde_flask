# #import config as cfg
import sys
import os

# # Get the absolute path to the directory above the current file ( afin de pouvoir importer les config dans config.py)
parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

# Add parent directory to sys.path if not already present
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# print(sys.path)