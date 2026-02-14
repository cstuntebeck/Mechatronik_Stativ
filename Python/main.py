"""
main.py
-------
Haupt-Einstiegspunkt der Anwendung.
Initialisiert das Hauptfenster, die Module CS-2000 und Motor-Steuerung
und verwaltet das Layout sowie den Anwendungs-Zyklus.
"""

import sys
from PyQt5.QtWidgets import QApplication, QWidget, QHBoxLayout, QSplitter
from PyQt5.QtCore import Qt as QtCore

# Importiere Module
from cs2000_module import CS2000GUI
from esp32_module import MotorSteuerung

class HauptFenster(QWidget):
    """
    Kombiniertes Hauptfenster für die Messtafelmessung.
    
    Beinhaltet:
    - Motor-Steuerung (Linke Seite)
    - CS-2000 GUI / Messablauf (Rechte Seite)
    """

    def __init__(self):
        """Initialisiert das Fenster, Layout und die Sub-Module."""
        print("[HauptFenster.__init__] Initialisiere Hauptfenster")
        super().__init__()
        self.setWindowTitle("CS-2000 Messtafelmessung & Motor-Steuerung")
        
        # Dynamische Fenstergröße basierend auf der Bildschirmauflösung
        screen = QApplication.primaryScreen()
        if screen:
            available_geometry = screen.availableGeometry()
            self.resize(int(available_geometry.width() * 0.9), int(available_geometry.height() * 0.8))
            self.move(available_geometry.center() - self.rect().center())
        else:
            self.resize(1600, 800)

        # Hauptlayout mit Splitter (trennbar)
        splitter = QSplitter(QtCore.Horizontal)

        # 1. Motor-Steuerung (Links)
        self.motor_gui = MotorSteuerung()

        # 2. CS-2000 GUI (Rechts) - erhält Referenz auf Motor
        self.cs2000_gui = CS2000GUI(motor_controller=self.motor_gui)

        splitter.addWidget(self.motor_gui)
        splitter.addWidget(self.cs2000_gui)

        # Gleichmäßige Aufteilung (50/50 Start)
        splitter.setSizes([self.width() // 2, self.width() // 2])

        layout = QHBoxLayout()
        layout.addWidget(splitter)
        self.setLayout(layout)

        print("[HauptFenster.__init__] Hauptfenster erfolgreich initialisiert")

    def closeEvent(self, event):
        """
        Wird beim Schließen des Fensters aufgerufen.
        Sorgt für sauberes Beenden, Speichern der Config und Trennen der Verbindungen.
        """
        print("[HauptFenster.closeEvent] Schließe Anwendung und trenne Verbindungen")
        
        print("[HauptFenster.closeEvent] Speichere finale Konfiguration...")
        self.motor_gui.save_config()
        self.cs2000_gui.save_config()
        
        self.motor_gui.verbindung_trennen()
        event.accept()


def main():
    """Startet die Qt-Anwendung."""
    print("=" * 80)
    print("[MAIN] Starte Messtafelmessungs-Anwendung")
    print("=" * 80)

    app = QApplication(sys.argv)
    window = HauptFenster()
    window.show()

    print("[MAIN] Anwendung läuft - Bereit für Messtafelmessung")
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
