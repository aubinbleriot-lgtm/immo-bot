"""Fixtures partagées entre tous les tests."""
import sys
import pathlib

# S'assurer que la racine du projet est dans sys.path
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
