#!/usr/bin/env python3
# pyright: basic
# pyright: reportAttributeAccessIssue=false
# pyright: reportIncompatibleMethodOverride=false

"""
ESP32 Motor-Steuerungs-Modul
Enthält alle Klassen und Funktionen für die ESP32 Motor-Steuerung
"""

import time
import threading
import math
import serial
import serial.tools.list_ports
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton, QLabel, QHBoxLayout, QCheckBox,
    QLineEdit, QGridLayout, QGroupBox, QShortcut
)
from PyQt5.QtGui import QFont, QKeySequence
from PyQt5.QtCore import (
    Qt, 
    QTimer, 
    pyqtSignal
)


class MotorSteuerung(QWidget):
    """ESP32 Motor-Steuerungs-GUI - Für Messtafel-Positionierung."""
    
    def __init__(self):
        print("[MotorSteuerung.__init__] Initialisiere Motor-Steuerung")
        super().__init__()
        
        # Globale Schriftgröße
        font = QFont()
        font.setPointSize(12)
        self.setFont(font)
        
        self.ser = None
        self.x10_aktiv = False
        self.aktuelle_x_position = 0
        self.aktuelle_y_position = 0
        
        # Thread-Lock für serielle Kommunikation
        self.serial_lock = threading.Lock()
        
        # Begrenzungs-Variablen
        self.begrenzung_oben_links = {"x": 0, "y": 0}
        self.begrenzung_unten_links = {"x": 0, "y": 0}
        self.begrenzung_unten_rechts = {"x": 0, "y": 0}
        
        # Messtafel-Parameter
        self.anzahl_messfelder_x = 0
        self.anzahl_messfelder_y = 0
        
        # Berechnete Werte
        self.schritte_pro_feld_x = 0
        self.schritte_pro_feld_y = 0
        self.gesamte_strecke_x = 0
        self.gesamte_strecke_y = 0
        
        self.init_ui()
        print("[MotorSteuerung.__init__] Motor-Steuerung erfolgreich initialisiert")

    def init_ui(self):
        """Initialisiert das GUI-Layout."""
        main_layout = QVBoxLayout(self)
        
        # Titel
        label_titel = QLabel("MOTOR-STEUERUNG")
        title_font = QFont()
        title_font.setPointSize(16)
        title_font.setBold(True)
        label_titel.setFont(title_font)
        label_titel.setAlignment(Qt.AlignCenter)
        label_titel.setStyleSheet("background-color: #fff3e0; padding: 10px; border-radius: 5px;")
        main_layout.addWidget(label_titel)
        
        font = QFont()
        font.setPointSize(12)
        
        # Info-Text
        info_label = QLabel("Kamera-Positionierung für Messtafelmessung")
        info_label.setFont(font)
        info_label.setStyleSheet("color: #555; font-style: italic; padding: 5px;")
        main_layout.addWidget(info_label)
        
        # Status Labels
        self.label_verbindung = QLabel("Nicht verbunden")
        self.label_verbindung.setFont(font)
        self.label_verbindung.setStyleSheet("color: red; font-size: 14pt; font-weight: bold;")
        main_layout.addWidget(self.label_verbindung)
        
        self.label_position = QLabel("Position: X=0, Y=0")
        self.label_position.setFont(font)
        self.label_position.setStyleSheet("color: purple; font-size: 14pt; font-weight: bold;")
        main_layout.addWidget(self.label_position)
        
        self.label_status = QLabel("Status: Bereit - Bitte verbinden")
        self.label_status.setFont(font)
        self.label_status.setStyleSheet("color: blue; font-size: 13pt;")
        main_layout.addWidget(self.label_status)

        # Verbindungs-Buttons
        button_verbinden = QPushButton("Verbinden")
        button_verbinden.setFont(font)
        button_verbinden.setMinimumHeight(50)
        button_verbinden.setStyleSheet("background-color: lightgreen; font-weight: bold;")
        button_verbinden.clicked.connect(self.verbindung_herstellen)
        
        button_trennen = QPushButton("Trennen")
        button_trennen.setFont(font)
        button_trennen.setMinimumHeight(50)
        button_trennen.setStyleSheet("background-color: lightcoral; font-weight: bold;")
        button_trennen.clicked.connect(self.verbindung_trennen)

        verbindung_layout = QHBoxLayout()
        verbindung_layout.addWidget(button_verbinden)
        verbindung_layout.addWidget(button_trennen)
        main_layout.addLayout(verbindung_layout)

        # === MESSTAFEL KONFIGURATION ===
        messtafel_group = QGroupBox("Messtafel-Konfiguration")
        messtafel_group.setFont(font)
        messtafel_layout = QGridLayout()
        
        # Anzahl Kästen X-Richtung
        label_kaesten_x = QLabel("Kästen in X-Richtung:")
        label_kaesten_x.setFont(font)
        self.entry_kaesten_x = QLineEdit("5")
        self.entry_kaesten_x.setFont(font)
        self.entry_kaesten_x.setMinimumHeight(35)
        button_speichern_x = QPushButton("Speichern")
        button_speichern_x.setFont(font)
        button_speichern_x.setMinimumHeight(35)
        button_speichern_x.clicked.connect(self.speichere_kaesten_x)
        
        messtafel_layout.addWidget(label_kaesten_x, 0, 0)
        messtafel_layout.addWidget(self.entry_kaesten_x, 0, 1)
        messtafel_layout.addWidget(button_speichern_x, 0, 2)
        
        # Anzahl Kästen Y-Richtung
        label_kaesten_y = QLabel("Kästen in Y-Richtung:")
        label_kaesten_y.setFont(font)
        self.entry_kaesten_y = QLineEdit("3")
        self.entry_kaesten_y.setFont(font)
        self.entry_kaesten_y.setMinimumHeight(35)
        button_speichern_y = QPushButton("Speichern")
        button_speichern_y.setFont(font)
        button_speichern_y.setMinimumHeight(35)
        button_speichern_y.clicked.connect(self.speichere_kaesten_y)
        
        messtafel_layout.addWidget(label_kaesten_y, 1, 0)
        messtafel_layout.addWidget(self.entry_kaesten_y, 1, 1)
        messtafel_layout.addWidget(button_speichern_y, 1, 2)
        
        # Berechnungs-Button
        button_berechnen = QPushButton("Abstände berechnen")
        button_berechnen.setFont(font)
        button_berechnen.setMinimumHeight(40)
        button_berechnen.setStyleSheet("background-color: #ffeb3b; font-weight: bold;")
        button_berechnen.clicked.connect(self.berechne_abstaende)
        messtafel_layout.addWidget(button_berechnen, 2, 0, 1, 3)
        
        # Info-Label für Berechnungen
        self.label_berechnungen = QLabel("Berechnungen: Noch keine Daten")
        self.label_berechnungen.setFont(font)
        self.label_berechnungen.setStyleSheet("color: #666; padding: 5px; background-color: #f0f0f0; border-radius: 3px;")
        self.label_berechnungen.setWordWrap(True)
        messtafel_layout.addWidget(self.label_berechnungen, 3, 0, 1, 3)
        
        messtafel_group.setLayout(messtafel_layout)
        main_layout.addWidget(messtafel_group)

        # === BEGRENZUNGS-BUTTONS MIT ECKEN-SYMBOLEN ===
        begrenzungen_group = QGroupBox("Begrenzungen speichern")
        begrenzungen_group.setFont(font)
        begrenzungen_layout = QHBoxLayout()
        
        button_oben_links = QPushButton("┌ Oben Links")
        button_oben_links.setFont(font)
        button_oben_links.setMinimumHeight(45)
        button_oben_links.setStyleSheet("background-color: #90caf9; font-weight: bold;")
        button_oben_links.clicked.connect(self.speichere_begrenzung_oben_links)
        
        button_unten_links = QPushButton("└ Unten Links")
        button_unten_links.setFont(font)
        button_unten_links.setMinimumHeight(45)
        button_unten_links.setStyleSheet("background-color: #90caf9; font-weight: bold;")
        button_unten_links.clicked.connect(self.speichere_begrenzung_unten_links)
        
        button_unten_rechts = QPushButton("┘ Unten Rechts")
        button_unten_rechts.setFont(font)
        button_unten_rechts.setMinimumHeight(45)
        button_unten_rechts.setStyleSheet("background-color: #90caf9; font-weight: bold;")
        button_unten_rechts.clicked.connect(self.speichere_begrenzung_unten_rechts)

        begrenzungen_layout.addWidget(button_oben_links)
        begrenzungen_layout.addWidget(button_unten_links)
        begrenzungen_layout.addWidget(button_unten_rechts)
        begrenzungen_group.setLayout(begrenzungen_layout)
        main_layout.addWidget(begrenzungen_group)

        # === FADENKREUZ-STEUERUNG ===
        steuerung_group = QGroupBox("Kamera-Steuerung")
        steuerung_group.setFont(font)
        steuerung_layout = QGridLayout()
        steuerung_layout.setSpacing(5)
        
        # Pfeile im Fadenkreuz-Layout (3x3 Grid)
        # Zeile 0: Oben
        button_hoch = QPushButton("▲")
        button_hoch_font = QFont()
        button_hoch_font.setPointSize(20)
        button_hoch.setFont(button_hoch_font)
        button_hoch.setMinimumSize(80, 80)
        button_hoch.setStyleSheet("background-color: #64b5f6; font-weight: bold;")
        button_hoch.clicked.connect(self.nicken_hoch)
        steuerung_layout.addWidget(button_hoch, 0, 1)
        
        # Zeile 1: Links, Mitte, Rechts
        button_links = QPushButton("◄")
        button_links_font = QFont()
        button_links_font.setPointSize(20)
        button_links.setFont(button_links_font)
        button_links.setMinimumSize(80, 80)
        button_links.setStyleSheet("background-color: #64b5f6; font-weight: bold;")
        button_links.clicked.connect(self.schwenken_links)
        steuerung_layout.addWidget(button_links, 1, 0)
        
        # Mitte: Reset Button
        button_reset = QPushButton("⊙\nReset")
        button_reset.setFont(font)
        button_reset.setMinimumSize(80, 80)
        button_reset.setStyleSheet("background-color: #ffcc80; font-weight: bold;")
        button_reset.clicked.connect(self.reset_x_y_position)
        steuerung_layout.addWidget(button_reset, 1, 1)
        
        button_rechts = QPushButton("►")
        button_rechts_font = QFont()
        button_rechts_font.setPointSize(20)
        button_rechts.setFont(button_rechts_font)
        button_rechts.setMinimumSize(80, 80)
        button_rechts.setStyleSheet("background-color: #64b5f6; font-weight: bold;")
        button_rechts.clicked.connect(self.schwenken_rechts)
        steuerung_layout.addWidget(button_rechts, 1, 2)
        
        # Zeile 2: Unten
        button_runter = QPushButton("▼")
        button_runter_font = QFont()
        button_runter_font.setPointSize(20)
        button_runter.setFont(button_runter_font)
        button_runter.setMinimumSize(80, 80)
        button_runter.setStyleSheet("background-color: #64b5f6; font-weight: bold;")
        button_runter.clicked.connect(self.nicken_runter)
        steuerung_layout.addWidget(button_runter, 2, 1)
        
        steuerung_group.setLayout(steuerung_layout)
        main_layout.addWidget(steuerung_group)
        
        # x10 Modus Checkbox
        self.var_x10 = QCheckBox("x10 Modus (schnellere Bewegung)")
        self.var_x10.setFont(font)
        self.var_x10.stateChanged.connect(self.toggle_x10)
        main_layout.addWidget(self.var_x10)
        
        main_layout.addStretch()
        self.shortcut_bindings()

    def shortcut_bindings(self):
        """Definiert Tastatur-Shortcuts für Bewegung."""
        QShortcut(QKeySequence(Qt.Key_Up), self).activated.connect(self.nicken_hoch)
        QShortcut(QKeySequence(Qt.Key_Down), self).activated.connect(self.nicken_runter)
        QShortcut(QKeySequence(Qt.Key_Left), self).activated.connect(self.schwenken_links)
        QShortcut(QKeySequence(Qt.Key_Right), self).activated.connect(self.schwenken_rechts)
        
        # Shortcuts für Begrenzungen
        QShortcut(QKeySequence(Qt.Key_Home), self).activated.connect(self.speichere_begrenzung_oben_links)
        QShortcut(QKeySequence(Qt.Key_End), self).activated.connect(self.speichere_begrenzung_unten_links)
        QShortcut(QKeySequence(Qt.Key_PageDown), self).activated.connect(self.speichere_begrenzung_unten_rechts)

    def speichere_kaesten_x(self):
        """Speichert Anzahl Kästen in X-Richtung."""
        try:
            self.anzahl_messfelder_x = int(self.entry_kaesten_x.text())
            self.label_status.setText(f"✓ Kästen X: {self.anzahl_messfelder_x}")
            self.label_status.setStyleSheet("color: green; font-size: 13pt;")
            print(f"[MotorSteuerung.speichere_kaesten_x] Anzahl: {self.anzahl_messfelder_x}")
        except ValueError:
            self.label_status.setText("✗ Fehler: Ungültige Zahl für X")
            self.label_status.setStyleSheet("color: red; font-size: 13pt;")

    def speichere_kaesten_y(self):
        """Speichert Anzahl Kästen in Y-Richtung."""
        try:
            self.anzahl_messfelder_y = int(self.entry_kaesten_y.text())
            self.label_status.setText(f"✓ Kästen Y: {self.anzahl_messfelder_y}")
            self.label_status.setStyleSheet("color: green; font-size: 13pt;")
            print(f"[MotorSteuerung.speichere_kaesten_y] Anzahl: {self.anzahl_messfelder_y}")
        except ValueError:
            self.label_status.setText("✗ Fehler: Ungültige Zahl für Y")
            self.label_status.setStyleSheet("color: red; font-size: 13pt;")

    def berechne_abstaende(self):
        """Berechnet Abstände und Winkel aus den Begrenzungs-Koordinaten."""
        print("[MotorSteuerung.berechne_abstaende] Starte Berechnung")
        
        if (self.begrenzung_oben_links["x"] == 0 and self.begrenzung_oben_links["y"] == 0 and
            self.begrenzung_unten_links["x"] == 0 and self.begrenzung_unten_links["y"] == 0 and
            self.begrenzung_unten_rechts["x"] == 0 and self.begrenzung_unten_rechts["y"] == 0):
            self.label_berechnungen.setText("❌ Fehler: Bitte zuerst alle 3 Begrenzungen speichern!")
            self.label_berechnungen.setStyleSheet("color: red; padding: 5px; background-color: #ffebee; border-radius: 3px;")
            return
        
        if self.anzahl_messfelder_x <= 0 or self.anzahl_messfelder_y <= 0:
            self.label_berechnungen.setText("❌ Fehler: Bitte Anzahl Kästen in X und Y eingeben!")
            self.label_berechnungen.setStyleSheet("color: red; padding: 5px; background-color: #ffebee; border-radius: 3px;")
            return
        
        ol_x = self.begrenzung_oben_links["x"]
        ol_y = self.begrenzung_oben_links["y"]
        ul_x = self.begrenzung_unten_links["x"]
        ul_y = self.begrenzung_unten_links["y"]
        ur_x = self.begrenzung_unten_rechts["x"]
        ur_y = self.begrenzung_unten_rechts["y"]
        
        print(f"[MotorSteuerung.berechne_abstaende] Oben Links: ({ol_x}, {ol_y})")
        print(f"[MotorSteuerung.berechne_abstaende] Unten Links: ({ul_x}, {ul_y})")
        print(f"[MotorSteuerung.berechne_abstaende] Unten Rechts: ({ur_x}, {ur_y})")
        
        delta_y = ul_y - ol_y
        delta_x_links = ul_x - ol_x
        self.gesamte_strecke_y = math.sqrt(delta_y**2 + delta_x_links**2)
        winkel_y = math.degrees(math.atan2(delta_x_links, delta_y)) if delta_y != 0 else 0
        self.schritte_pro_feld_y = int(self.gesamte_strecke_y / self.anzahl_messfelder_y) if self.anzahl_messfelder_y > 0 else 0
        
        print(f"[MotorSteuerung.berechne_abstaende] Y-Strecke: {self.gesamte_strecke_y:.1f} Schritte")
        print(f"[MotorSteuerung.berechne_abstaende] Schritte/Feld Y: {self.schritte_pro_feld_y}")
        
        delta_x = ur_x - ul_x
        delta_y_unten = ur_y - ul_y
        self.gesamte_strecke_x = math.sqrt(delta_x**2 + delta_y_unten**2)
        winkel_x = math.degrees(math.atan2(delta_y_unten, delta_x)) if delta_x != 0 else 0
        self.schritte_pro_feld_x = int(self.gesamte_strecke_x / self.anzahl_messfelder_x) if self.anzahl_messfelder_x > 0 else 0
        
        print(f"[MotorSteuerung.berechne_abstaende] X-Strecke: {self.gesamte_strecke_x:.1f} Schritte")
        print(f"[MotorSteuerung.berechne_abstaende] Schritte/Feld X: {self.schritte_pro_feld_x}")
        
        ergebnis_text = (
            f"✓ Berechnungen erfolgreich:\n\n"
            f"Messtafel: {self.anzahl_messfelder_x} × {self.anzahl_messfelder_y} Kästen\n"
            f"Gesamt: {self.anzahl_messfelder_x * self.anzahl_messfelder_y} Messpunkte\n\n"
            f"X-Richtung (Breite):\n"
            f"  • Gesamtstrecke: {self.gesamte_strecke_x:.1f} Schritte\n"
            f"  • Pro Kasten: {self.schritte_pro_feld_x} Schritte\n"
            f"  • Winkel: {winkel_x:.2f}°\n\n"
            f"Y-Richtung (Höhe):\n"
            f"  • Gesamtstrecke: {self.gesamte_strecke_y:.1f} Schritte\n"
            f"  • Pro Kasten: {self.schritte_pro_feld_y} Schritte\n"
            f"  • Winkel: {winkel_y:.2f}°"
        )
        
        self.label_berechnungen.setText(ergebnis_text)
        self.label_berechnungen.setStyleSheet("color: green; padding: 5px; background-color: #e8f5e9; border-radius: 3px;")
        self.label_status.setText("✓ Abstände berechnet!")
        self.label_status.setStyleSheet("color: green; font-size: 13pt;")

    def speichere_begrenzung_oben_links(self):
        self.begrenzung_oben_links["x"] = self.aktuelle_x_position
        self.begrenzung_oben_links["y"] = self.aktuelle_y_position
        self.label_status.setText(f"✓ ┌ Oben Links: X={self.aktuelle_x_position}, Y={self.aktuelle_y_position}")
        self.label_status.setStyleSheet("color: green; font-size: 13pt;")
        print(f"[MotorSteuerung.speichere_begrenzung_oben_links] Position: {self.begrenzung_oben_links}")

    def speichere_begrenzung_unten_links(self):
        self.begrenzung_unten_links["x"] = self.aktuelle_x_position
        self.begrenzung_unten_links["y"] = self.aktuelle_y_position
        self.label_status.setText(f"✓ └ Unten Links: X={self.aktuelle_x_position}, Y={self.aktuelle_y_position}")
        self.label_status.setStyleSheet("color: green; font-size: 13pt;")
        print(f"[MotorSteuerung.speichere_begrenzung_unten_links] Position: {self.begrenzung_unten_links}")

    def speichere_begrenzung_unten_rechts(self):
        self.begrenzung_unten_rechts["x"] = self.aktuelle_x_position
        self.begrenzung_unten_rechts["y"] = self.aktuelle_y_position
        self.label_status.setText(f"✓ ┘ Unten Rechts: X={self.aktuelle_x_position}, Y={self.aktuelle_y_position}")
        self.label_status.setStyleSheet("color: green; font-size: 13pt;")
        print(f"[MotorSteuerung.speichere_begrenzung_unten_rechts] Position: {self.begrenzung_unten_rechts}")

    def finde_ch343_port(self):
        """Sucht automatisch den CH343 USB-Port."""
        print("[MotorSteuerung.finde_ch343_port] Suche CH343-Adapter")
        ports = serial.tools.list_ports.comports()
        for port in ports:
            if 'CH343' in port.description:
                print(f"[MotorSteuerung.finde_ch343_port] Gefunden: {port.device}")
                return port.device
        raise RuntimeError("Kein CH343-Adapter gefunden!")

    def sende_motor_befehl(self, befehl):
        """Sendet Befehl an ESP32 mit Thread-Lock zur Vermeidung von Überlappungen."""
        if self.ser is None or not self.ser.is_open:
            self.label_status.setText("Fehler: Keine Verbindung!")
            print("[MotorSteuerung.sende_motor_befehl] FEHLER: Keine Verbindung")
            return False
        
        print(f"[MotorSteuerung.sende_motor_befehl] Warte auf Lock...")
        with self.serial_lock:
            print(f"[MotorSteuerung.sende_motor_befehl] Lock erhalten, sende: {befehl}")
            try:
                if self.ser.in_waiting > 0:
                    discarded = self.ser.read(self.ser.in_waiting)
                    print(f"[MotorSteuerung.sende_motor_befehl] Verwerfe {len(discarded)} alte Bytes")
                
                self.ser.write((befehl + '\n').encode())
                self.ser.flush()
                
                start_time = time.time()
                timeout = 30.0
                
                while (time.time() - start_time) < timeout:
                    if self.ser.in_waiting > 0:
                        antwort_zeile = self.ser.readline()
                        text = antwort_zeile.decode('utf-8', errors='ignore').strip()
                        print(f"[MotorSteuerung.sende_motor_befehl] Antwort: {text}")
                        
                        if text == "OK":
                            self.label_status.setText("✓ Befehl erfolgreich")
                            self.label_status.setStyleSheet("color: blue; font-size: 13pt;")
                            print("[MotorSteuerung.sende_motor_befehl] Erfolgreich abgeschlossen")
                            return True
                    else:
                        time.sleep(0.05)
                
                print("[MotorSteuerung.sende_motor_befehl] Timeout - keine OK Antwort")
                self.label_status.setText("⚠ Timeout - Motor möglicherweise noch aktiv")
                return False
                
            except Exception as e:
                self.label_status.setText(f"Fehler: {e}")
                print(f"[MotorSteuerung.sende_motor_befehl] EXCEPTION: {e}")
                return False

    def motor_schritte_thread(self, schritte, achse):
        """Führt Motorbewegung in separatem Thread aus mit Lock."""
        def bewegung_ausfuehren():
            befehl = f"move_{achse} {schritte}"
            erfolg = self.sende_motor_befehl(befehl)
            
            if erfolg:
                if achse == 'x':
                    self.aktuelle_x_position += schritte
                elif achse == 'y':
                    self.aktuelle_y_position += schritte
                QTimer.singleShot(0, self.aktualisiere_position_anzeige)
        
        thread = threading.Thread(target=bewegung_ausfuehren)
        thread.daemon = True
        thread.start()

    def aktualisiere_position_anzeige(self):
        """Aktualisiert die Positionsanzeige."""
        self.label_position.setText(f"Position: X={self.aktuelle_x_position}, Y={self.aktuelle_y_position}")
        print(f"[MotorSteuerung.aktualisiere_position_anzeige] X={self.aktuelle_x_position}, Y={self.aktuelle_y_position}")

    def toggle_x10(self, state):
        """Schaltet x10 Modus um."""
        self.x10_aktiv = (state == Qt.CheckState.Checked)
        self.label_status.setText(f"x10 Modus: {'aktiviert' if self.x10_aktiv else 'deaktiviert'}")
        self.label_status.setStyleSheet("color: blue; font-size: 13pt;")
        print(f"[MotorSteuerung.toggle_x10] x10 Modus: {self.x10_aktiv}")

    def _bewege_achse(self, achse, basis_schritte):
        """Private Hilfsfunktion zur Ansteuerung einer Achse."""
        multiplikator = 10 if self.x10_aktiv else 1
        schritte = basis_schritte * multiplikator
        print(f"[MotorSteuerung._bewege_achse] Bewege Achse '{achse}' um {schritte} Schritte")
        self.motor_schritte_thread(schritte, achse)

    def schwenken_links(self):
        self._bewege_achse('x', -50)

    def schwenken_rechts(self):
        self._bewege_achse('x', 50)

    def nicken_hoch(self):
        """Nach oben nicken – INVERTIERT: negative Schritte."""
        self._bewege_achse('y', -50)

    def nicken_runter(self):
        """Nach unten nicken – INVERTIERT: positive Schritte."""
        self._bewege_achse('y', 50)


    def verbindung_herstellen(self):
        """Stellt Verbindung zum ESP32 her."""
        print("[MotorSteuerung.verbindung_herstellen] Starte Verbindung")
        try:
            port = self.finde_ch343_port()
            self.ser = serial.Serial(port, 115200, timeout=1)
            time.sleep(2)
            
            if self.ser.in_waiting > 0:
                discarded = self.ser.read(self.ser.in_waiting)
                print(f"[MotorSteuerung.verbindung_herstellen] Initialer Buffer geleert: {len(discarded)} Bytes")
            
            self.label_verbindung.setText(f"✓ Verbunden: {port}")
            self.label_verbindung.setStyleSheet("color: green; font-size: 14pt; font-weight: bold;")
            self.label_status.setText("Verbindung hergestellt")
            print(f"[MotorSteuerung.verbindung_herstellen] Verbunden mit {port}")
        except Exception as e:
            self.label_verbindung.setText("✗ Nicht verbunden")
            self.label_status.setText(f"Verbindungsfehler: {e}")
            print(f"[MotorSteuerung.verbindung_herstellen] FEHLER: {e}")

    def verbindung_trennen(self):
        """Trennt Verbindung zum ESP32."""
        print("[MotorSteuerung.verbindung_trennen] Trenne Verbindung")
        if self.ser and self.ser.is_open:
            self.ser.close()
            self.label_verbindung.setText("Nicht verbunden")
            self.label_verbindung.setStyleSheet("color: red; font-size: 14pt; font-weight: bold;")
            self.label_status.setText("Verbindung getrennt")
            print("[MotorSteuerung.verbindung_trennen] Verbindung getrennt")

    def reset_x_y_position(self):
        """Setzt Position auf 0,0 zurück."""
        print("[MotorSteuerung.reset_x_y_position] Setze Position zurück")
        self.aktuelle_x_position = 0
        self.aktuelle_y_position = 0
        self.aktualisiere_position_anzeige()
        self.label_status.setText("Position zurückgesetzt")

    def closeEvent(self, event):  # ← Zurück zu "event"
        """Cleanup beim Schließen."""
        print("[MotorSteuerung.closeEvent] Cleanup")
        if self.ser and self.ser.is_open:
            self.ser.close()
        event.accept()
