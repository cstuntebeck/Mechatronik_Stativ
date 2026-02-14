#!/usr/bin/env python3
# pyright: basic
# pyright: reportAttributeAccessIssue=false
# pyright: reportIncompatibleMethodOverride=false

"""
Haupt-Anwendung - CS-2000 & Motor-Steuerung
Kombiniert beide Module für Messtafelmessung
"""

import sys

from PyQt5.QtWidgets import QApplication, QWidget, QHBoxLayout, QSplitter
from PyQt5.QtCore import Qt as QtCore

# Importiere Module
from cs2000_module import CS2000GUI
from esp32_module import MotorSteuerung


class HauptFenster(QWidget):
	"""Kombiniertes Hauptfenster für Messtafelmessung."""

	def __init__(self):
		print("[HauptFenster.__init__] Initialisiere Hauptfenster")
		super().__init__()
		self.setWindowTitle("CS-2000 Messtafelmessung & Motor-Steuerung")
		self.resize(1800, 900)

		# Hauptlayout mit Splitter
		splitter = QSplitter(QtCore.Horizontal)

		# Erstelle Motor-Steuerung zuerst
		self.motor_gui = MotorSteuerung()

		# Erstelle CS-2000 GUI mit Motor-Referenz
		self.cs2000_gui = CS2000GUI(motor_controller=self.motor_gui)

		# Füge beide zum Splitter hinzu
		splitter.addWidget(self.cs2000_gui)
		splitter.addWidget(self.motor_gui)

		# Gleichmäßige Aufteilung
		splitter.setSizes([900, 900])

		# Hauptlayout
		layout = QHBoxLayout()
		layout.addWidget(splitter)
		self.setLayout(layout)

		print("[HauptFenster.__init__] Hauptfenster erfolgreich initialisiert")


def main():
	"""Hauptfunktion - Startet die Messtafelmessungs-Anwendung."""
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