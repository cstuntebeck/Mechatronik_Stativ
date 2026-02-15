"""
utils.py
--------
Hilfsfunktionen und -klassen für das Projekt.
Enthält Logik für Pfad-Generierung und Konfigurations-Dateipfade.
"""

import os
import sys

class GridPathGenerator:
    """
    Generiert Koordinaten für einen Raster-Scan im Mäander-Muster (Schlangenlinien).
    
    Verwendung:
        generator = GridPathGenerator(rows=5, cols=3)
        for row, col in generator.generate_path():
            print(row, col)
    """
    def __init__(self, rows, cols):
        """
        Initialisiert den Generator.
        
        Args:
            rows (int): Anzahl der Zeilen.
            cols (int): Anzahl der Spalten.
        """
        self.rows = rows
        self.cols = cols

    def generate_path(self):
        """
        Generator-Funktion, die die Koordinaten (row, col) in der Besuchsreihenfolge zurückgibt.
        
        Muster:
        Zeile 0: links -> rechts
        Zeile 1: rechts -> links
        Zeile 2: links -> rechts
        ...
        
        Yields:
            tuple: (row, col)
        """
        for row in range(self.rows):
            # Gerade Zeilen: Links nach Rechts
            if row % 2 == 0:
                col_range = range(self.cols)
            # Ungerade Zeilen: Rechts nach Links
            else:
                col_range = range(self.cols - 1, -1, -1)
            
            for col in col_range:
                yield (row, col)

def get_config_path(filename="config.json"):
    """
    Gibt den absoluten Pfad zur Konfigurationsdatei zurück.
    Berücksichtigt, ob das Skript als .exe (PyInstaller) oder als Skript läuft.
    
    Args:
        filename (str): Name der Datei.
        
    Returns:
        str: Absoluter Pfad zur Datei.
    """
    # Verzeichnis bestimmen, in dem das Skript/Executable liegt
    if getattr(sys, 'frozen', False):
        # Wenn kompiliert mit PyInstaller
        application_path = os.path.dirname(sys.executable)
    else:
        # Wenn als Python-Skript ausgeführt
        application_path = os.path.dirname(os.path.abspath(__file__))
    
    return os.path.join(application_path, filename)
