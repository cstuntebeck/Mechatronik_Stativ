"""
esp32_module.py
---------------
ESP32 Motor-Steuerungs-Modul.

Dieses Modul verwaltet die serielle Kommunikation mit dem ESP32-Controller,
der für die Bewegung des Stativs (Pan/Tilt) zuständig ist.
Es stellt die Klasse `MotorSteuerung` als GUI-Widget bereit.
"""

import time
import threading
import math
import serial
import serial.tools.list_ports
import json
import os
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton, QLabel, QHBoxLayout, QCheckBox,
    QLineEdit, QGridLayout, QGroupBox, QShortcut, QComboBox, QRadioButton, QButtonGroup, QTextEdit
)
from PyQt5.QtGui import QFont, QKeySequence
from PyQt5.QtCore import (
    Qt, 
    QTimer, 
    pyqtSignal,
    QObject,
    QThread,
    QEventLoop
)
from utils import get_config_path


class SerialWorker(QObject):
    """
    Worker-Klasse für die serielle Kommunikation in einem separaten Thread.
    
    Verhindert das Blockieren der GUI während synchroner Schreib-/Leseoperationen
    auf dem seriellen Port.
    """
    response = pyqtSignal(bool, str, object)  # success, message, context

    def __init__(self, serial_port, serial_lock):
        """
        Initialisiert den Worker.
        
        Args:
            serial_port (serial.Serial): Das geöffnete Serial-Objekt.
            serial_lock (threading.Lock): Ein Lock zur Synchronisation.
        """
        super().__init__()
        self.ser = serial_port
        self.serial_lock = serial_lock

    def send_motor_command(self, command, context):
        """
        Sendet einen Befehl an den ESP32 und wartet auf die Antwort 'OK'.
        
        Args:
            command (str): Der serielle Befehl string (z.B. "move_x 100").
            context (dict): Kontextdaten für das aufrufende Signal (z.B. welche Achse).
        
        Emits:
            response (bool, str, object): Signal mit Ergebnis (Erfolg/Timeout), Nachricht und Kontext.
        """
        if self.ser is None or not self.ser.is_open:
            self.response.emit(False, "Fehler: Keine Verbindung!", context)
            print("[SerialWorker.send_motor_command] FEHLER: Keine Verbindung")
            return

        # Versuche Lock zu bekommen, um Überschneidungen zu vermeiden
        # WARNUNG: blocking=False führt dazu, dass Befehle verworfen werden, wenn der Worker busy ist!
        # Für zuverlässige Sequenzen sollte hier blocking=True sein oder eine Queue verwendet werden.
        # Da wir im Worker-Thread sind (via Signal/Slot Queue), ist blocking=True sicher,
        # solange wir nicht auf uns selbst warten.
        if not self.serial_lock.acquire(blocking=True, timeout=5.0):
            print(f"[SerialWorker.send_motor_command] Busy / Lock Timeout...")
            self.response.emit(False, "Fehler: System ausgelastet", context)
            return

        try:
            # Eingangsbuffer leeren, um alte Daten zu verwerfen
            if self.ser.in_waiting > 0:
                self.ser.read(self.ser.in_waiting)

            # Befehl senden (mit Newline)
            self.ser.write((command + '\n').encode())
            self.ser.flush()

            start_time = time.time()
            timeout = 2.0

            # Auf Antwort warten
            while (time.time() - start_time) < timeout:
                if self.ser.in_waiting > 0:
                    antwort_zeile = self.ser.readline()
                    text = antwort_zeile.decode('utf-8', errors='ignore').strip()

                    # Erwarte das spezifische ACK vom ESP32
                    if text == "OK":
                        self.response.emit(True, "✓ Befehl erfolgreich", context)
                        return
                else:
                    time.sleep(0.05)
            
            print("[SerialWorker.send_motor_command] Timeout - keine OK Antwort")
            self.response.emit(False, "Fehler: Timeout (kein OK)", context)

        except Exception as e:
            self.response.emit(False, f"Fehler: {e}", context)
            print(f"[SerialWorker.send_motor_command] EXCEPTION: {e}")
        finally:
            self.serial_lock.release()


class MotorSteuerung(QWidget):
    """
    GUI-Widget zur Steuerung der ESP32-Motoren und Definition der Messfeld-Begrenzungen.
    """
    
    send_command_signal = pyqtSignal(str, object)
    position_updated = pyqtSignal(int, int)
    boundaries_updated = pyqtSignal(dict, dict, dict)
    movement_finished = pyqtSignal(bool)  # Neues Signal: True=Erfolg, False=Fehler
    calculation_finished = pyqtSignal(int, int) # Signal für fertige Berechnung (rows, cols)

    def __init__(self):
        """Initialisiert das Steuerungs-Widget, Variablen und Layout."""
        print("[MotorSteuerung.__init__] Initialisiere Motor-Steuerung")
        super().__init__()
        
        # Globale Schriftgröße
        font = QFont()
        font.setPointSize(12)
        self.setFont(font)
        
        self.ser = None
        self.comm_thread = None
        self.serial_worker = None
        self.is_mock = False
        self.step_multiplier = 1 # Standard: x1
        self.aktuelle_x_position = 0
        self.aktuelle_y_position = 0
        
        # Thread-Lock für serielle Kommunikation
        self.serial_lock = threading.Lock()
        
        # Begrenzungs-Variablen
        self.begrenzung_oben_links = {"x": 0, "y": 0}
        self.begrenzung_oben_rechts = {"x": 0, "y": 0}
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
        
        self.config_file = get_config_path("config.json")
        
        self.init_ui()
        self.load_config()
        print("[MotorSteuerung.__init__] Motor-Steuerung erfolgreich initialisiert")

    def load_config(self):
        """
        Lädt die Motor-Konfiguration (Port, Begrenzungen, Rastergröße) aus der JSON-Datei.
        
        Falls eine Datei existiert, werden die Werte in die entsprechenden Variablen
        und UI-Elemente geladen und die Signale für Updates emittiert.
        """
        print(f"[MotorSteuerung.load_config] Lade Konfiguration aus {self.config_file}")
        if not os.path.exists(self.config_file):
            print("[MotorSteuerung.load_config] Konfigurationsdatei nicht gefunden.")
            return

        try:
            with open(self.config_file, 'r') as f:
                config = json.load(f)
            
            motor_config = config.get('motor', {})
            
            # Lade Port
            last_port = motor_config.get('port')
            if last_port:
                index = self.port_combobox.findData(last_port)
                if index != -1:
                    self.port_combobox.setCurrentIndex(index)
                    print(f"[MotorSteuerung.load_config] Port '{last_port}' geladen.")

            # Lade Begrenzungen
            self.begrenzung_oben_links = motor_config.get('boundary_ol', {"x": 0, "y": 0})
            self.begrenzung_oben_rechts = motor_config.get('boundary_or', {"x": 0, "y": 0})
            self.begrenzung_unten_links = motor_config.get('boundary_ul', {"x": 0, "y": 0})
            self.begrenzung_unten_rechts = motor_config.get('boundary_ur', {"x": 0, "y": 0})
            print("[MotorSteuerung.load_config] Begrenzungen geladen.")
            self.boundaries_updated.emit(self.begrenzung_oben_links, self.begrenzung_unten_links, self.begrenzung_unten_rechts)

            # Lade Anzahl Kästen
            self.anzahl_messfelder_x = motor_config.get('fields_x', 5)
            self.anzahl_messfelder_y = motor_config.get('fields_y', 3)
            self.entry_kaesten_x.setText(str(self.anzahl_messfelder_x))
            self.entry_kaesten_y.setText(str(self.anzahl_messfelder_y))
            print("[MotorSteuerung.load_config] Anzahl Kästen geladen.")

            self.label_status.setText("✓ Konfiguration geladen")
            self.label_status.setStyleSheet("color: green; font-size: 13pt;")
            
            # Berechne Abstände, falls alle Daten vorhanden sind
            self.berechne_abstaende()
            self.position_updated.emit(self.aktuelle_x_position, self.aktuelle_y_position)

        except (json.JSONDecodeError, KeyError) as e:
            self.label_status.setText(f"✗ Fehler beim Laden der Konfig: {e}")
            self.label_status.setStyleSheet("color: red; font-size: 13pt;")
            print(f"[MotorSteuerung.load_config] FEHLER: {e}")

    def save_config(self):
        """
        Speichert die aktuelle Konfiguration in die 'config.json'.
        
        Sichert:
        - Ausgewählter COM-Port
        - Begrenzungskoordinaten (OL, OR, UL, UR)
        - Rastergröße (X, Y)
        """
        print(f"[MotorSteuerung.save_config] Speichere Konfiguration in {self.config_file}")
        config = {}
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    config = json.load(f)
            except json.JSONDecodeError:
                print("[MotorSteuerung.save_config] WARNUNG: Bestehende Konfig-Datei ist korrupt.")
        
        motor_config = {
            'port': self.port_combobox.currentData(),
            'boundary_ol': self.begrenzung_oben_links,
            'boundary_or': self.begrenzung_oben_rechts,
            'boundary_ul': self.begrenzung_unten_links,
            'boundary_ur': self.begrenzung_unten_rechts,
            'fields_x': self.anzahl_messfelder_x,
            'fields_y': self.anzahl_messfelder_y
        }
        config['motor'] = motor_config
        
        try:
            with open(self.config_file, 'w') as f:
                json.dump(config, f, indent=4)
            print("[MotorSteuerung.save_config] Konfiguration erfolgreich gespeichert.")
        except Exception as e:
            self.label_status.setText(f"✗ Fehler beim Speichern der Konfig: {e}")
            self.label_status.setStyleSheet("color: red; font-size: 13pt;")
            print(f"[MotorSteuerung.save_config] FEHLER: {e}")

    def init_ui(self):
        """
        Erstellt die grafische Benutzeroberfläche.
        
        Komponenten:
        - Titel & Info
        - Verbindungs-Panel (Port-Auswahl, Connect/Disconnect)
        - Messtafel-Konfiguration (Eingabefelder für Rastergröße)
        - Steuerkreuz & Begrenzungs-Buttons (Bewegung & Setup)
        - Schrittweiten-Auswahl
        """
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

        # Port-Auswahl
        port_layout = QHBoxLayout()
        self.port_combobox = QComboBox()
        self.port_combobox.setFont(font)
        port_layout.addWidget(self.port_combobox)
        
        button_refresh_ports = QPushButton("⟳")
        button_refresh_ports.setFont(font)
        button_refresh_ports.setFixedWidth(50)
        button_refresh_ports.clicked.connect(self.refresh_ports)
        port_layout.addWidget(button_refresh_ports)
        main_layout.addLayout(port_layout)

        # Verbindungs-Buttons
        button_verbinden = QPushButton("Verbinden")
        button_verbinden.setFont(font)
        button_verbinden.setMinimumHeight(35)
        button_verbinden.setStyleSheet("background-color: lightgreen; font-weight: bold;")
        button_verbinden.clicked.connect(self.verbindung_herstellen)
        
        button_trennen = QPushButton("Trennen")
        button_trennen.setFont(font)
        button_trennen.setMinimumHeight(35)
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
        label_kaesten_x = QLabel("Kästen X:")
        label_kaesten_x.setFont(font)
        self.entry_kaesten_x = QLineEdit("5")
        self.entry_kaesten_x.setFont(font)
        self.entry_kaesten_x.setMinimumHeight(35)
        self.entry_kaesten_x.editingFinished.connect(self.speichere_kaesten_x)
        # Row 0, Col 0-1
        messtafel_layout.addWidget(label_kaesten_x, 0, 0)
        messtafel_layout.addWidget(self.entry_kaesten_x, 0, 1)
        
        # Anzahl Kästen Y-Richtung
        label_kaesten_y = QLabel("Kästen Y:")
        label_kaesten_y.setFont(font)
        self.entry_kaesten_y = QLineEdit("3")
        self.entry_kaesten_y.setFont(font)
        self.entry_kaesten_y.setMinimumHeight(35)
        self.entry_kaesten_y.editingFinished.connect(self.speichere_kaesten_y)
        # Row 0, Col 2-3 (Nebeneinander)
        messtafel_layout.addWidget(label_kaesten_y, 0, 2)
        messtafel_layout.addWidget(self.entry_kaesten_y, 0, 3)
        
        # Berechnungs-Button
        button_berechnen = QPushButton("Abstände berechnen")
        button_berechnen.setFont(font)
        button_berechnen.setMinimumHeight(40)
        button_berechnen.setStyleSheet("background-color: #ffeb3b; font-weight: bold;")
        button_berechnen.clicked.connect(self.berechne_abstaende)
        # Row 1, Span über alle 4 Spalten
        messtafel_layout.addWidget(button_berechnen, 1, 0, 1, 4)
        
        # Info-Label für Berechnungen (jetzt scrollbar mit QTextEdit)
        self.text_berechnungen = QTextEdit()
        self.text_berechnungen.setReadOnly(True)
        self.text_berechnungen.setHtml("Berechnungen: Noch keine Daten")
        self.text_berechnungen.setFont(font)
        self.text_berechnungen.setStyleSheet("color: #666; background-color: #f0f0f0; border-radius: 3px;")
        self.text_berechnungen.setMaximumHeight(100) # Begrenzte Höhe, damit es scrollt
        # Row 2, Span über alle 4 Spalten
        messtafel_layout.addWidget(self.text_berechnungen, 2, 0, 1, 4)
        
        messtafel_group.setLayout(messtafel_layout)
        main_layout.addWidget(messtafel_group)


        # === FADENKREUZ-STEUERUNG + BEGRENZUNGEN ===
        steuerung_group = QGroupBox("Kamera-Steuerung & Begrenzungen")
        steuerung_group.setFont(font)
        steuerung_layout = QGridLayout()
        steuerung_layout.setSpacing(15)
        
        # Kompaktes Layout für Begrenzungen & Reset & Pfeile (Grid wiedereingefügt)
        # Zeile 0: [OL] [  UP  ] [OR]
        # Zeile 1: [LEFT] [CENTER] [RIGHT]
        # Zeile 2: [UL] [ DOWN ] [UR]
        
        # --- ZEILE 0 ---
        # (0,0) Oben Links Setzen
        btn_ol = QPushButton("[•] OL")
        btn_ol.setToolTip("Begrenzung Oben-Links")
        btn_ol.setFixedSize(60, 60)
        btn_ol.setStyleSheet("background-color: #90caf9; font-weight: bold; border-radius: 5px;")
        btn_ol.clicked.connect(self.speichere_begrenzung_oben_links)
        steuerung_layout.addWidget(btn_ol, 0, 0)

        # (0,1) Pfeil Oben
        button_hoch = QPushButton("▲")
        button_hoch_font = QFont()
        button_hoch_font.setPointSize(20)
        button_hoch.setFont(button_hoch_font)
        button_hoch.setFixedSize(60, 60)
        button_hoch.setStyleSheet("background-color: #64b5f6; font-weight: bold; border-radius: 30px;")
        button_hoch.clicked.connect(self.nicken_hoch)
        steuerung_layout.addWidget(button_hoch, 0, 1)

        # (0,2) Oben Rechts Setzen
        btn_or = QPushButton("[•] OR")
        btn_or.setToolTip("Begrenzung Oben-Rechts")
        btn_or.setFixedSize(60, 60)
        btn_or.setStyleSheet("background-color: #90caf9; font-weight: bold; border-radius: 5px;")
        btn_or.clicked.connect(self.speichere_begrenzung_oben_rechts)
        steuerung_layout.addWidget(btn_or, 0, 2)

        # --- ZEILE 1 ---
        # (1,0) Pfeil Links
        button_links = QPushButton("◄")
        button_links.setFont(button_hoch_font)
        button_links.setFixedSize(60, 60)
        button_links.setStyleSheet("background-color: #64b5f6; font-weight: bold; border-radius: 30px;")
        button_links.clicked.connect(self.schwenken_links)
        steuerung_layout.addWidget(button_links, 1, 0)

        # (1,1) CENTER / RESET
        button_reset = QPushButton("⊙")
        button_reset.setToolTip("Zurück zur Mitte / Reset")
        button_reset.setFont(font)
        button_reset.setFixedSize(60, 60)
        button_reset.setStyleSheet("background-color: #ffcc80; font-weight: bold; border-radius: 30px;")
        button_reset.clicked.connect(self.reset_x_y_position)
        steuerung_layout.addWidget(button_reset, 1, 1)

        # (1,2) Pfeil Rechts
        button_rechts = QPushButton("►")
        button_rechts.setFont(button_hoch_font)
        button_rechts.setFixedSize(60, 60)
        button_rechts.setStyleSheet("background-color: #64b5f6; font-weight: bold; border-radius: 30px;")
        button_rechts.clicked.connect(self.schwenken_rechts)
        steuerung_layout.addWidget(button_rechts, 1, 2)

        # --- ZEILE 2 ---
        # (2,0) Unten Links Setzen
        btn_ul = QPushButton("[•] UL")
        btn_ul.setToolTip("Begrenzung Unten-Links")
        btn_ul.setFixedSize(60, 60)
        btn_ul.setStyleSheet("background-color: #90caf9; font-weight: bold; border-radius: 5px;")
        btn_ul.clicked.connect(self.speichere_begrenzung_unten_links)
        steuerung_layout.addWidget(btn_ul, 2, 0)

        # (2,1) Pfeil Unten
        button_runter = QPushButton("▼")
        button_runter.setFont(button_hoch_font)
        button_runter.setFixedSize(60, 60)
        button_runter.setStyleSheet("background-color: #64b5f6; font-weight: bold; border-radius: 30px;")
        button_runter.clicked.connect(self.nicken_runter)
        steuerung_layout.addWidget(button_runter, 2, 1)

        # (2,2) Unten Rechts Setzen
        btn_ur = QPushButton("[•] UR")
        btn_ur.setToolTip("Begrenzung Unten-Rechts")
        btn_ur.setFixedSize(60, 60)
        btn_ur.setStyleSheet("background-color: #90caf9; font-weight: bold; border-radius: 5px;")
        btn_ur.clicked.connect(self.speichere_begrenzung_unten_rechts)
        steuerung_layout.addWidget(btn_ur, 2, 2)
        
        steuerung_group.setLayout(steuerung_layout)
        main_layout.addWidget(steuerung_group)
        
        # Schrittweite Radio Buttons
        schritt_group = QGroupBox("Schrittweite Multiplikator")
        schritt_group.setFont(font)
        schritt_layout = QHBoxLayout()
        
        self.step_btn_group = QButtonGroup(self)
        
        self.rb_x05 = QRadioButton("x0.5")
        self.rb_x05.setFont(font)
        self.rb_x05.toggled.connect(lambda: self.set_step_multiplier(0.5))
        schritt_layout.addWidget(self.rb_x05)
        self.step_btn_group.addButton(self.rb_x05)

        self.rb_x1 = QRadioButton("x1")
        self.rb_x1.setFont(font)
        self.rb_x1.setChecked(True)
        self.rb_x1.toggled.connect(lambda: self.set_step_multiplier(1))
        schritt_layout.addWidget(self.rb_x1)
        self.step_btn_group.addButton(self.rb_x1)

        self.rb_x2 = QRadioButton("x2")
        self.rb_x2.setFont(font)
        self.rb_x2.toggled.connect(lambda: self.set_step_multiplier(2))
        schritt_layout.addWidget(self.rb_x2)
        self.step_btn_group.addButton(self.rb_x2)

        self.rb_x5 = QRadioButton("x5")
        self.rb_x5.setFont(font)
        self.rb_x5.toggled.connect(lambda: self.set_step_multiplier(5))
        schritt_layout.addWidget(self.rb_x5)
        self.step_btn_group.addButton(self.rb_x5)
        
        self.rb_x10 = QRadioButton("x10")
        self.rb_x10.setFont(font)
        self.rb_x10.toggled.connect(lambda: self.set_step_multiplier(10))
        schritt_layout.addWidget(self.rb_x10)
        self.step_btn_group.addButton(self.rb_x10)

        self.rb_x50 = QRadioButton("x50")
        self.rb_x50.setFont(font)
        self.rb_x50.toggled.connect(lambda: self.set_step_multiplier(50))
        schritt_layout.addWidget(self.rb_x50)
        self.step_btn_group.addButton(self.rb_x50)
        
        schritt_group.setLayout(schritt_layout)
        main_layout.addWidget(schritt_group)
        
        main_layout.addStretch()
        
        self.refresh_ports()
        self.shortcut_bindings()

    def shortcut_bindings(self):
        """
        Definiert Tastatur-Kürzel für die Steuerung.
        
        Pfeiltasten: Bewegt den Motor (Pan/Tilt).
        Pos1/Start (Home): Setzt Begrenzung Oben-Links.
        Ende (End): Setzt Begrenzung Unten-Links.
        Bild Ab (PageDown): Setzt Begrenzung Unten-Rechts.
        """
        QShortcut(QKeySequence(Qt.Key_Up), self).activated.connect(self.nicken_hoch)
        QShortcut(QKeySequence(Qt.Key_Down), self).activated.connect(self.nicken_runter)
        QShortcut(QKeySequence(Qt.Key_Left), self).activated.connect(self.schwenken_links)
        QShortcut(QKeySequence(Qt.Key_Right), self).activated.connect(self.schwenken_rechts)
        
        # Shortcuts für Begrenzungen
        QShortcut(QKeySequence(Qt.Key_Home), self).activated.connect(self.speichere_begrenzung_oben_links)
        QShortcut(QKeySequence(Qt.Key_End), self).activated.connect(self.speichere_begrenzung_unten_links)
        QShortcut(QKeySequence(Qt.Key_PageDown), self).activated.connect(self.speichere_begrenzung_unten_rechts)

    def refresh_ports(self):
        """
        Aktualisiert die Liste der verfügbaren COM-Ports.
        
        Filtert nach bekannten Vendor-IDs (ESP32, CH34x), um irrelevante Geräte auszublenden.
        Fügt immer eine "MOCK"-Option für Simulationstests hinzu.
        """
        print("[MotorSteuerung.refresh_ports] Aktualisiere Port-Liste")
        self.port_combobox.clear()
        
        # Mock-Port immer als erste Option hinzufügen
        self.port_combobox.addItem("MOCK (Simulierter Motor)", "MOCK")
        
        ports = serial.tools.list_ports.comports()
        
        port_items = []
        for port in ports:
            if port.vid is None:
                continue  # Filtere Ports ohne Vendor ID (z.B. Bluetooth)

            # Vendor IDs in hexadezimal
            ESP32_S3_VID = 0x303A
            CH34X_VID = 0x1A86

            friendly_name = "Unbekanntes USB-Gerät"
            if port.vid == ESP32_S3_VID:
                friendly_name = "ESP32-S3 Stativ"
            elif port.vid == CH34X_VID:
                friendly_name = "ESP32 (CH34x)"
            
            display_text = f"{friendly_name} ({port.device})"
            port_items.append({'text': display_text, 'data': port.device})
        
        # Sortiere die Liste: "Stativ" zuerst
        port_items.sort(key=lambda item: 'Stativ' not in item['text'])

        if not port_items:
            self.port_combobox.addItem("Keine USB-Geräte gefunden")
        else:
            for item in port_items:
                self.port_combobox.addItem(item['text'], item['data'])

    def speichere_kaesten_x(self):
        """
        Liest die gewünschte Anzahl der Kästen in X-Richtung aus dem Eingabefeld
        und speichert sie in der Konfiguration.
        """
        try:
            val = int(self.entry_kaesten_x.text())
            if val > 0:
                self.anzahl_messfelder_x = val
                self.label_status.setText(f"✓ Kästen X: {self.anzahl_messfelder_x}")
                self.label_status.setStyleSheet("color: green; font-size: 13pt;")
                print(f"[MotorSteuerung.speichere_kaesten_x] Anzahl: {self.anzahl_messfelder_x}")
                self.save_config()
            else:
                 raise ValueError("Muss > 0 sein")
        except ValueError:
            self.label_status.setText("✗ Fehler: Ungültige Zahl für X")
            self.label_status.setStyleSheet("color: red; font-size: 13pt;")

    def speichere_kaesten_y(self):
        """
        Liest die gewünschte Anzahl der Kästen in Y-Richtung aus dem Eingabefeld
        und speichert sie in der Konfiguration.
        """
        try:
            val = int(self.entry_kaesten_y.text())
            if val > 0:
                self.anzahl_messfelder_y = val
                self.label_status.setText(f"✓ Kästen Y: {self.anzahl_messfelder_y}")
                self.label_status.setStyleSheet("color: green; font-size: 13pt;")
                print(f"[MotorSteuerung.speichere_kaesten_y] Anzahl: {self.anzahl_messfelder_y}")
                self.save_config()
            else:
                 raise ValueError("Muss > 0 sein")
        except ValueError:
            self.label_status.setText("✗ Fehler: Ungültige Zahl für Y")
            self.label_status.setStyleSheet("color: red; font-size: 13pt;")

    def berechne_abstaende(self):
        """
        Berechnet die Geometrie der Messtafel basierend auf den drei Eckpunkten (OL, UL, UR).
        
        Bestimmt:
        - Gesamtbreite und Gesamthöhe in Motorschritten.
        - Schrittweite pro Kasten (X und Y).
        - Drehwinkel (Rotation der Tafel relativ zur Kamera).
        
        Logik:
        Da 'Move-To-Center' verwendet wird, teilen wir die Gesamtstrecke
        durch (Anzahl - 1), um den Abstand zwischen den Mittelpunkten zu erhalten.
        """
        print("[MotorSteuerung.berechne_abstaende] Starte Berechnung")
        
        # Explizites Update der Kästen-Anzahl vor Berechnung
        self.speichere_kaesten_x()
        self.speichere_kaesten_y()
        
        if (self.begrenzung_oben_links["x"] == 0 and self.begrenzung_oben_links["y"] == 0 and
            self.begrenzung_unten_links["x"] == 0 and self.begrenzung_unten_links["y"] == 0 and
            self.begrenzung_unten_rechts["x"] == 0 and self.begrenzung_unten_rechts["y"] == 0):
            self.text_berechnungen.setHtml("<b>❌ Fehler:</b> Bitte zuerst alle 3 Begrenzungen speichern!")
            self.text_berechnungen.setStyleSheet("color: red; background-color: #ffebee; border-radius: 3px;")
            return
        
        if self.anzahl_messfelder_x <= 0 or self.anzahl_messfelder_y <= 0:
            self.text_berechnungen.setHtml("<b>❌ Fehler:</b> Bitte Anzahl Kästen in X und Y eingeben!")
            self.text_berechnungen.setStyleSheet("color: red; background-color: #ffebee; border-radius: 3px;")
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
        
        # Berechnung basierend auf Feld-MITTEN:
        # Distanz zwischen Zentrum(0) und Zentrum(N-1) entspricht (N-1) Abständen.
        div_y = (self.anzahl_messfelder_y - 1) if self.anzahl_messfelder_y > 1 else 1
        self.schritte_pro_feld_y = int(self.gesamte_strecke_y / div_y) if self.anzahl_messfelder_y > 0 else 0
        
        print(f"[MotorSteuerung.berechne_abstaende] Y-Strecke: {self.gesamte_strecke_y:.1f} Schritte")
        print(f"[MotorSteuerung.berechne_abstaende] Schritte/Feld Y: {self.schritte_pro_feld_y} (Divisor: {div_y})")
        
        delta_x = ur_x - ul_x
        delta_y_unten = ur_y - ul_y
        self.gesamte_strecke_x = math.sqrt(delta_x**2 + delta_y_unten**2)
        winkel_x = math.degrees(math.atan2(delta_y_unten, delta_x)) if delta_x != 0 else 0
        
        div_x = (self.anzahl_messfelder_x - 1) if self.anzahl_messfelder_x > 1 else 1
        self.schritte_pro_feld_x = int(self.gesamte_strecke_x / div_x) if self.anzahl_messfelder_x > 0 else 0
        
        print(f"[MotorSteuerung.berechne_abstaende] X-Strecke: {self.gesamte_strecke_x:.1f} Schritte")
        print(f"[MotorSteuerung.berechne_abstaende] Schritte/Feld X: {self.schritte_pro_feld_x} (Divisor: {div_x})")
        
        # Kompaktere HTML-Darstellung für die Ergebnisse
        ergebnis_html = (
            f"<b>✓ Berechnungen erfolgreich:</b><br>"
            f"Messtafel: {self.anzahl_messfelder_x} x {self.anzahl_messfelder_y} ({self.anzahl_messfelder_x * self.anzahl_messfelder_y} Punkte)<br>"
            f"<table border='0' cellpadding='2' cellspacing='0'>"
            f"<tr><td><b>X-Achse (Breite):</b></td><td><b>Y-Achse (Höhe):</b></td></tr>"
            f"<tr><td>Strecke: {self.gesamte_strecke_x:.1f} Steps</td><td>Strecke: {self.gesamte_strecke_y:.1f} Steps</td></tr>"
            f"<tr><td>Schritt/Feld: <b>{self.schritte_pro_feld_x}</b></td><td>Schritt/Feld: <b>{self.schritte_pro_feld_y}</b></td></tr>"
            f"<tr><td>Winkel: {winkel_x:.1f}°</td><td>Winkel: {winkel_y:.1f}°</td></tr>"
            f"</table>"
        )
        
        self.text_berechnungen.setHtml(ergebnis_html)
        self.text_berechnungen.setStyleSheet("color: black; background-color: #e8f5e9; border-radius: 3px; font-size: 11pt;")
        self.label_status.setText("✓ Abstände berechnet!")
        self.label_status.setStyleSheet("color: green; font-size: 13pt;")
        
        # Signal senden, dass Berechnung fertig ist
        print(f"[MotorSteuerung] Sende Signal calculation_finished({self.anzahl_messfelder_y}, {self.anzahl_messfelder_x})")
        self.calculation_finished.emit(self.anzahl_messfelder_y, self.anzahl_messfelder_x)

    def speichere_begrenzung_oben_links(self):
        """Speichert die aktuelle Position als 'Oben Links' Begrenzung."""
        self.begrenzung_oben_links["x"] = self.aktuelle_x_position
        self.begrenzung_oben_links["y"] = self.aktuelle_y_position
        self.label_status.setText(f"✓ [•] Oben Links: X={self.aktuelle_x_position}, Y={self.aktuelle_y_position}")
        self.label_status.setStyleSheet("color: green; font-size: 13pt;")
        print(f"[MotorSteuerung.speichere_begrenzung_oben_links] Position: {self.begrenzung_oben_links}")
        self.boundaries_updated.emit(self.begrenzung_oben_links, self.begrenzung_unten_links, self.begrenzung_unten_rechts)
        self.save_config()

    def speichere_begrenzung_oben_rechts(self):
        """Speichert die aktuelle Position als 'Oben Rechts' Begrenzung."""
        self.begrenzung_oben_rechts["x"] = self.aktuelle_x_position
        self.begrenzung_oben_rechts["y"] = self.aktuelle_y_position
        self.label_status.setText(f"✓ [•] Oben Rechts: X={self.aktuelle_x_position}, Y={self.aktuelle_y_position}")
        self.label_status.setStyleSheet("color: green; font-size: 13pt;")
        print(f"[MotorSteuerung.speichere_begrenzung_oben_rechts] Position: {self.begrenzung_oben_rechts}")
        self.boundaries_updated.emit(self.begrenzung_oben_links, self.begrenzung_unten_links, self.begrenzung_unten_rechts)
        self.save_config()

    def speichere_begrenzung_unten_links(self):
        """Speichert die aktuelle Position als 'Unten Links' Begrenzung."""
        self.begrenzung_unten_links["x"] = self.aktuelle_x_position
        self.begrenzung_unten_links["y"] = self.aktuelle_y_position
        self.label_status.setText(f"✓ [•] Unten Links: X={self.aktuelle_x_position}, Y={self.aktuelle_y_position}")
        self.label_status.setStyleSheet("color: green; font-size: 13pt;")
        print(f"[MotorSteuerung.speichere_begrenzung_unten_links] Position: {self.begrenzung_unten_links}")
        self.boundaries_updated.emit(self.begrenzung_oben_links, self.begrenzung_unten_links, self.begrenzung_unten_rechts)
        self.save_config()

    def speichere_begrenzung_unten_rechts(self):
        """Speichert die aktuelle Position als 'Unten Rechts' Begrenzung."""
        self.begrenzung_unten_rechts["x"] = self.aktuelle_x_position
        self.begrenzung_unten_rechts["y"] = self.aktuelle_y_position
        self.label_status.setText(f"✓ [•] Unten Rechts: X={self.aktuelle_x_position}, Y={self.aktuelle_y_position}")
        self.label_status.setStyleSheet("color: green; font-size: 13pt;")
        print(f"[MotorSteuerung.speichere_begrenzung_unten_rechts] Position: {self.begrenzung_unten_rechts}")
        self.boundaries_updated.emit(self.begrenzung_oben_links, self.begrenzung_unten_links, self.begrenzung_unten_rechts)
        self.save_config()

    def finde_esp_port(self):
        """
        Sucht automatisch den seriellen Port des ESP32 (z.B. CH34x, CP210x).
        
        Returns:
            str: Name des gefundenen Ports (z.B. '/dev/ttyUSB0')
        Raises:
            RuntimeError: Wenn kein passender Port gefunden wurde.
        """
        print("[MotorSteuerung.finde_esp_port] Suche ESP32-Adapter...")
        ports = serial.tools.list_ports.comports()
        
        print(f"[MotorSteuerung.finde_esp_port] Gefundene Ports:")
        for port in ports:
            # Gebe VID/PID hexadezimal aus, falls vorhanden, sonst None
            vid_str = f"{port.vid:04X}" if port.vid is not None else "----"
            pid_str = f"{port.pid:04X}" if port.pid is not None else "----"
            print(f"  - {port.device}: {port.description} [VID:PID={vid_str}:{pid_str}]")

        for port in ports:
            # Typische Beschreibungen für ESP32 Dev-Boards (Groß-/Kleinschreibung ignorieren)
            desc = port.description.upper()
            # CH34x, CP210x, JTAG und Single Serial sind häufige Chips/Bezeichner
            if ('CH34' in desc or
                'CP210' in desc or
                'USB TO UART' in desc or
                'USB JTAG' in desc or
                'USB SINGLE SERIAL' in desc):
                print(f"[MotorSteuerung.finde_esp_port] Passender Port ausgewählt: {port.device}")
                return port.device
        
        raise RuntimeError("Kein passender ESP32-Adapter gefunden!")

    def aktualisiere_position_anzeige(self):
        """Aktualisiert das UI-Label mit der aktuellen X/Y-Position."""
        self.label_position.setText(f"Position: X={self.aktuelle_x_position}, Y={self.aktuelle_y_position}")
        print(f"[MotorSteuerung.aktualisiere_position_anzeige] X={self.aktuelle_x_position}, Y={self.aktuelle_y_position}")

    def on_command_response(self, success, message, context):
        """
        Slot, der auf das Signal des SerialWorker reagiert.
        Verarbeitet die Antwort auf einen gesendeten Befehl.
        
        Bei Erfolg: Aktualisiert interne Position und emittiert Signale.
        Bei Fehler: Zeigt Warnung im UI.
        """
        self.label_status.setText(message)
        if success:
            self.label_status.setStyleSheet("color: blue; font-size: 13pt;")
            achse = context.get('achse')
            schritte = context.get('schritte')
            if achse == 'x':
                self.aktuelle_x_position += schritte
            elif achse == 'y':
                self.aktuelle_y_position += schritte
            self.aktualisiere_position_anzeige()
            self.position_updated.emit(self.aktuelle_x_position, self.aktuelle_y_position)
            
            # Emit movement_finished if this was a movement command
            if context and 'schritte' in context:
                 self.movement_finished.emit(True)
        else:
            self.label_status.setStyleSheet("color: red; font-size: 13pt;")
            if context and 'schritte' in context:
                 self.movement_finished.emit(False)

    def set_step_multiplier(self, val):
        """
        Setzt den globalen Multiplikator für manuelle Bewegungsbefehle (Pfeiltasten).
        
        Args:
            val (int): Der Multiplikator (1, 2, 5, 10, 50).
        """
        if self.sender().isChecked(): # Nur wenn der Button aktiviert wird
            self.step_multiplier = val
            self.label_status.setText(f"Schrittweite: x{self.step_multiplier}")
            self.label_status.setStyleSheet("color: blue; font-size: 13pt;")
            print(f"[MotorSteuerung] Schrittweite gesetzt auf x{self.step_multiplier}")

    def _bewege_achse(self, achse, basis_schritte):
        """
        Interne Methode: Sendet Bewegungsbefehl über den Worker-Thread oder simuliert ihn.
        Berücksichtigt den aktuellen `step_multiplier`.
        """
        schritte = int(basis_schritte * self.step_multiplier)
        context = {'achse': achse, 'schritte': schritte}

        if self.is_mock:
            print(f"[MotorSteuerung._bewege_achse] MOCK: Bewege Achse '{achse}' um {schritte} Schritte")
            # Simuliere eine kurze Verzögerung für den Befehl
            QTimer.singleShot(50, lambda: self.on_command_response(True, "✓ Mock Befehl", context))
            return

        if self.comm_thread is None or not self.comm_thread.isRunning():
            self.label_status.setText("Fehler: Bitte zuerst verbinden!")
            self.label_status.setStyleSheet("color: red; font-size: 13pt;")
            print("[MotorSteuerung._bewege_achse] FEHLER: Keine Verbindung")
            return

        print(f"[MotorSteuerung._bewege_achse] Sende Befehl für Achse '{achse}' mit {schritte} Schritten")
        
        # Y-Achse Invertierung für Motor-Richtung (Logisch + => Physisch -)
        steps_to_send = schritte
        if achse == 'y':
            steps_to_send = -schritte
            
        befehl = f"move_{achse} {steps_to_send}"
        self.send_command_signal.emit(befehl, context)

    def move_steps(self, schritte, achse):
        """
        Öffentliche Methode, um eine bestimmte Anzahl von Schritten zu bewegen.
        Wird typischerweise von externen Klassen (MesstafelWorker) genutzt.
        
        Args:
            schritte (int): Anzahl der Schritte (positiv oder negativ).
            achse (str): 'x' oder 'y'.
        """
        print(f"[MotorSteuerung.move_steps] Anforderung: {schritte} Schritte auf Achse '{achse}'")
        context = {'achse': achse, 'schritte': schritte}

        if self.is_mock:
            # Im Mock-Modus wird die Bewegung sofort simuliert und die Antwort
            # nach einer kurzen Verzögerung gesendet.
            print(f"[MotorSteuerung.move_steps] MOCK: Simuliere Bewegung...")
            # Die Verzögerung hier ist nur symbolisch, da der Worker-Thread
            # ohnehin mit time.sleep() wartet.
            QTimer.singleShot(50, lambda: self.on_command_response(True, "✓ Mock Befehl (move_steps)", context))
            return

        if self.comm_thread is None or not self.comm_thread.isRunning():
            print(f"[MotorSteuerung.move_steps] FEHLER: Keine Verbindung")
            # Wir können hier keine GUI-Elemente direkt ändern, da dies aus einem
            # anderen Thread aufgerufen werden könnte. Stattdessen loggen wir den Fehler.
            return

        print(f"[MotorSteuerung.move_steps] Sende Befehl für Achse '{achse}' mit {schritte} Schritten")
        
        # Y-Achse Invertierung für Motor-Richtung (Logisch + => Physisch -)
        steps_to_send = schritte
        if achse == 'y':
            steps_to_send = -schritte
            
        befehl = f"move_{achse} {steps_to_send}"
        self.send_command_signal.emit(befehl, context)

    def schwenken_links(self):
        """Bewegt X-Achse nach links (negative Schritte)."""
        self._bewege_achse('x', -50)

    def schwenken_rechts(self):
        """Bewegt X-Achse nach rechts (positive Schritte)."""
        self._bewege_achse('x', 50)

    def nicken_hoch(self):
        """Nach oben nicken – Positiv (Logisch)."""
        self._bewege_achse('y', 50)

    def nicken_runter(self):
        """Nach unten nicken – Negativ (Logisch)."""
        self._bewege_achse('y', -50)


    def verbindung_herstellen(self):
        """
        Stellt Verbindung zum ESP32 (oder MOCK) her und startet den Kommunikations-Thread.
        Initialisiert den SerialWorker und verbindet Signale.
        """
        print("[MotorSteuerung.verbindung_herstellen] Starte Verbindung")

        if self.ser is not None and self.ser.is_open:
            print("[MotorSteuerung.verbindung_herstellen] Bestehende Verbindung wird getrennt...")
            self.verbindung_trennen()
            time.sleep(0.5)

        port = self.port_combobox.currentData()
        if not port:
            self.label_status.setText("Fehler: Kein Port ausgewählt!")
            self.label_status.setStyleSheet("color: red; font-size: 13pt;")
            print("[MotorSteuerung.verbindung_herstellen] FEHLER: Kein Port ausgewählt")
            return

        if port == "MOCK":
            self.is_mock = True
            self.label_verbindung.setText("✓ Verbunden: MOCK")
            self.label_verbindung.setStyleSheet("color: green; font-size: 14pt; font-weight: bold;")
            self.label_status.setText("Mock-Verbindung aktiv")
            print("[MotorSteuerung.verbindung_herstellen] Mock-Modus aktiviert")
            self.save_config()
            return
        
        self.is_mock = False
        try:
            self.ser = serial.Serial(port, 921600, timeout=1)
            
            # Non-blocking wait for 2 seconds (ESP32 Reset/Boot)
            print("[MotorSteuerung.verbindung_herstellen] Warte auf ESP32 Reset (2s)...")
            loop = QEventLoop()
            QTimer.singleShot(2000, loop.quit)
            loop.exec_()
            
            if self.ser.in_waiting > 0:
                discarded = self.ser.read(self.ser.in_waiting)
                print(f"[MotorSteuerung.verbindung_herstellen] Initialer Buffer geleert: {len(discarded)} Bytes")
            
            self.comm_thread = QThread()
            self.serial_worker = SerialWorker(self.ser, self.serial_lock)
            self.serial_worker.moveToThread(self.comm_thread)
            
            self.send_command_signal.connect(self.serial_worker.send_motor_command)
            self.serial_worker.response.connect(self.on_command_response)
            
            self.comm_thread.start()
            
            self.label_verbindung.setText(f"✓ Verbunden: {port}")
            self.label_verbindung.setStyleSheet("color: green; font-size: 14pt; font-weight: bold;")
            self.label_status.setText("Verbindung hergestellt und Worker-Thread gestartet")
            print(f"[MotorSteuerung.verbindung_herstellen] Verbunden mit {port}")
            self.save_config()
        except Exception as e:
            self.label_verbindung.setText("✗ Nicht verbunden")
            self.label_status.setText(f"Verbindungsfehler: {e}")
            print(f"[MotorSteuerung.verbindung_herstellen] FEHLER: {e}")

    def verbindung_trennen(self):
        """
        Trennt die Verbindung zum ESP32 und beendet den Kommunikations-Thread sauber.
        Setzt UI-Status zurück.
        """
        print("[MotorSteuerung.verbindung_trennen] Trenne Verbindung")
        
        self.is_mock = False

        if self.comm_thread is not None and self.comm_thread.isRunning():
            print("[MotorSteuerung.verbindung_trennen] Stoppe Worker-Thread...")
            self.comm_thread.quit()
            if not self.comm_thread.wait(2000):
                print("[MotorSteuerung.verbindung_trennen] WARNUNG: Thread reagiert nicht, wird terminiert.")
                self.comm_thread.terminate()
                self.comm_thread.wait()
            print("[MotorSteuerung.verbindung_trennen] Worker-Thread beendet.")

        if self.ser and self.ser.is_open:
            self.ser.close()
            print("[MotorSteuerung.verbindung_trennen] Serielle Verbindung getrennt")
        
        self.ser = None
        self.label_verbindung.setText("Nicht verbunden")
        self.label_verbindung.setStyleSheet("color: red; font-size: 14pt; font-weight: bold;")
        self.label_status.setText("Verbindung getrennt")

    def reset_x_y_position(self):
        """Setzt die internen Positions-Zähler auf 0,0 zurück (Reference Reset)."""
        print("[MotorSteuerung.reset_x_y_position] Setze Position zurück")
        self.aktuelle_x_position = 0
        self.aktuelle_y_position = 0
        self.aktualisiere_position_anzeige()
        self.position_updated.emit(self.aktuelle_x_position, self.aktuelle_y_position)
        self.label_status.setText("Position zurückgesetzt")

    def closeEvent(self, event):
        """Wird aufgerufen, wenn das Widget geschlossen wird -> Clean disconnect."""
        print("[MotorSteuerung.closeEvent] Cleanup")
        self.verbindung_trennen()
        event.accept()
