#!/usr/bin/env python3
# pyright: basic
# pyright: reportAttributeAccessIssue=false
# pyright: reportIncompatibleMethodOverride=false

"""
CS-2000 Spektralradiometer Mess-Modul
Enthält alle Klassen und Funktionen für die CS-2000 Messung
"""


import time
import csv
import re
import json
import os
import threading

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton, QTextEdit, QLabel,
    QHBoxLayout, QFileDialog, QMessageBox, QSplitter, QPlainTextEdit,
    QGridLayout, QFrame, QScrollBar, QComboBox, QSizePolicy, QGroupBox, QRadioButton, QButtonGroup,
    QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView
)

from PyQt5.QtGui import QFont, QPalette, QColor, QPainter, QPen, QBrush
from PyQt5.QtCore import Qt, QDateTime, QThread, pyqtSignal, QPoint, QRectF, QSize, QEventLoop, QObject, QTimer
from PyQt5.QtCore import Qt as QtCore

from utils import GridPathGenerator, get_config_path



try:
    import serial
    import serial.tools.list_ports
except ImportError:
    print("[WARNING] pyserial nicht installiert")

USE_MOCK = False  # Standard: echte Hardware, MOCK über Dropdown wählbar

try:
    from scipy.interpolate import griddata
    import numpy as np
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False
    print("[WARNING] scipy/numpy nicht verfügbar. Interpolation deaktiviert.")


class LoggingWindow(QWidget):
    """
    Ein separates Fenster zur Anzeige von Log-Nachrichten mit Zeitstempeln.
    Dient dem Debugging und der Nachverfolgung von Fehlern während der Laufzeit.
    """
    
    def __init__(self):
        """Initialisiert das Log-Fenster."""
        print("[LoggingWindow.__init__] Initialisiere Logging-Fenster")
        super().__init__()
        self.setWindowTitle("CS-2000 Log")
        self.resize(600, 400)
        layout = QVBoxLayout(self)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(1000)
        font = QFont()
        font.setPointSize(11)
        self.log_view.setFont(font)
        layout.addWidget(self.log_view)
        print("[LoggingWindow.__init__] Logging-Fenster erfolgreich initialisiert")

    def log(self, msg, level="INFO"):
        """
        Fügt eine Nachricht zum Log-Fenster hinzu.
        
        Args:
            msg (str): Die Nachricht.
            level (str): Das Log-Level (z.B. INFO, ERROR).
        """
        print(f"[LoggingWindow.log] [{level}] {msg}")
        ts = QDateTime.currentDateTime().toString("yyyy-MM-dd HH:mm:ss.zzz")
        log_line = f"[{ts}] [{level}] {msg}"
        self.log_view.appendPlainText(log_line)
        sb = self.log_view.verticalScrollBar()
        if sb is not None and sb.value() >= sb.maximum() - 10:
            sb.setValue(sb.maximum())


class MesstafelVisualization(QWidget):
    """
    Visualisiert das rasterförmige Mess-Schema (Messtafel) grafisch.
    Zeigt den Status jedes Messfeldes (Offen, Messend, Fertig, Fehler) farblich an.
    Erlaubt Interaktion durch Klick auf Felder.
    """
    
    # Signal für Klick-Interaktion: (row, col)
    box_clicked = pyqtSignal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(150)
        self.setStyleSheet("background-color: white; border: 1px solid #ccc;")
        
        self.anzahl_rows = 0
        self.anzahl_cols = 0
        self.kasten_stati = {}
        self.motor_x = 0
        self.motor_y = 0
        
        self.boundaries = {}
        self.min_x = 0
        self.max_x = 100
        self.min_y = 0
        self.max_y = 100
    
    def mouseReleaseEvent(self, event):
        """
        Erkennt Mausklicks auf die Visualisierung.
        Berechnet, welches Gitterfeld (Row, Col) angeklickt wurde und emittiert das `box_clicked` Signal.
        """
        if self.anzahl_rows == 0 or self.anzahl_cols == 0:
            return

        spacing = 2
        w = self.width() - spacing * (self.anzahl_cols + 1)
        h = self.height() - spacing * (self.anzahl_rows + 1)
        kasten_w = w / self.anzahl_cols
        kasten_h = h / self.anzahl_rows
        
        mx = event.x()
        my = event.y()
        
        # Grid-Koordinate berechnen
        col_float = (mx - spacing) / (kasten_w + spacing)
        row_float = (my - spacing) / (kasten_h + spacing)
        
        col = int(col_float)
        row = int(row_float)
        
        in_col_bounds = (col >= 0 and col < self.anzahl_cols)
        in_row_bounds = (row >= 0 and row < self.anzahl_rows)
        
        if in_col_bounds and in_row_bounds:
            self.box_clicked.emit(row, col)
            print(f"[MesstafelVisualization] Klick auf Kasten [{row}, {col}]")

    def sizeHint(self):
        """Standardgröße für das Widget."""
        return QSize(400, 300)

    def setup_grid(self, anzahl_rows, anzahl_cols):
        """
        Initialisiert das Gitter mit der angegebenen Anzahl an Zeilen und Spalten.
        
        Args:
            anzahl_rows (int): Anzahl der Zeilen.
            anzahl_cols (int): Anzahl der Spalten.
        """
        print(f"[MesstafelVisualization.setup_grid] Erstelle Grid: {anzahl_rows} Zeilen × {anzahl_cols} Spalten")
        self.kasten_stati.clear()
        self.anzahl_rows = anzahl_rows
        self.anzahl_cols = anzahl_cols
        self.update()

    def set_kasten_status(self, row, col, status):
        """
        Aktualisiert den Status (Farbe) eines einzelnen Kastens.
        
        Args:
            row (int): Zeile (0-basiert).
            col (int): Spalte (0-basiert).
            status (str): 'measuring', 'done', 'error', oder 'default'.
        """
        if row >= self.anzahl_rows or col >= self.anzahl_cols:
            print(f"[MesstafelVisualization.set_kasten_status] WARNUNG: Kasten [{row},{col}] außerhalb des Grids")
            return
        self.kasten_stati[(row, col)] = status
        self.update()

    def reset_grid(self):
        """Löscht alle Statusinformationen und setzt das Gitter zurück (alles grau)."""
        print("[MesstafelVisualization.reset_grid] Setze Grid zurück")
        self.kasten_stati.clear()
        self.update()

    def update_motor_position(self, x, y):
        """
        Aktualisiert die angezeigte Position des Fadenkreuzes (rote Markierung).
        
        Args:
            x (int): Motor-X-Schritte.
            y (int): Motor-Y-Schritte.
        """
        self.motor_x = x
        self.motor_y = y
        self.update()

    def set_boundaries(self, ol, ul, ur):
        """
        Setzt die Eckpunkte des Messbereichs für die korrekte Skalierung des Fadenkreuzes.
        
        Args:
            ol (dict): Oben-Links {x, y}.
            ul (dict): Unten-Links {x, y}.
            ur (dict): Unten-Rechts {x, y}.
        """
        # Check if all boundaries are at (0,0) - meaning they're not set
        if all(p['x'] == 0 and p['y'] == 0 for p in [ol, ul, ur]):
            self.boundaries = None
            self.update()
            return

        self.boundaries = {'ol': ol, 'ul': ul, 'ur': ur}
        
        all_x = [p['x'] for p in self.boundaries.values()]
        all_y = [p['y'] for p in self.boundaries.values()]
        
        self.min_x = min(all_x)
        self.max_x = max(all_x)
        self.min_y = min(all_y)
        self.max_y = max(all_y)

        if self.max_x == self.min_x: self.max_x += 1
        if self.max_y == self.min_y: self.max_y += 1

        self.update()

    def paintEvent(self, event):
        """
        Zeichnet das Widget neu (Gitter, Statusfarben, Begrenzung, Fadenkreuz).
        Wird automatisch von Qt aufgerufen.
        """
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # 1. Grid zeichnen & Variablen initialisieren
        spacing = 2
        # Default Werte für den Fall, dass kein Grid existiert
        kasten_w = self.width() - 2 * spacing
        kasten_h = self.height() - 2 * spacing

        if self.anzahl_rows > 0 and self.anzahl_cols > 0:
            w = self.width() - spacing * (self.anzahl_cols + 1)
            h = self.height() - spacing * (self.anzahl_rows + 1)
            kasten_w = w / self.anzahl_cols
            kasten_h = h / self.anzahl_rows
            
            font = QFont()
            
            font = QFont()
            font.setPointSize(max(7, int(min(kasten_w, kasten_h) / 4)))
            painter.setFont(font)

            for row in range(self.anzahl_rows):
                for col in range(self.anzahl_cols):
                    status = self.kasten_stati.get((row, col), 'default')
                    
                    color_map = {
                        'measuring': QColor(255, 235, 59),
                        'done': QColor(129, 199, 132),
                        'error': QColor(239, 83, 80),
                        'default': QColor(200, 200, 200)
                    }
                    
                    rect_x = spacing + col * (kasten_w + spacing)
                    rect_y = spacing + row * (kasten_h + spacing)
                    rect = QRectF(rect_x, rect_y, kasten_w, kasten_h)
                    
                    painter.setPen(Qt.NoPen)
                    painter.setBrush(QBrush(color_map[status]))
                    painter.drawRect(rect)
                    
                    painter.setPen(QColor(0, 0, 0))
                    painter.drawText(rect, Qt.AlignCenter, f"[{row},{col}]")

        # 2. Begrenzungen und Fadenkreuz zeichnen
        if self.boundaries:
            def transform(motor_x, motor_y):
                range_x = self.max_x - self.min_x
                range_y = self.max_y - self.min_y
                
                if range_x == 0 or range_y == 0:
                    return QPoint(self.width() // 2, self.height() // 2)

                px = int(((motor_x - self.min_x) / range_x) * self.width())
                py = int(((motor_y - self.min_y) / range_y) * self.height())
                return QPoint(px, py)

        # 2. Begrenzungen und Fadenkreuz zeichnen - ENTFERNT (User-Wunsch)
        # if self.boundaries:
        #     ... (Code entfernt, da fehleranfällig oder unerwünscht)





class CS2000Device:
    """
    Kapselt die serielle Kommunikation mit dem Konica Minolta CS-2000.
    
    Verwaltet Verbindung, Befehlsprotokoll (Senden/Empfangen) und Parsing 
    der Messdaten (Spektralwerte und Farbmetrik).
    Unterstützt einen MOCK-Modus für Tests ohne Hardware.
    """
    
    def __init__(self, port, baudrate=115200, timeout=2, motor_controller=None):
        global USE_MOCK
        # Port "MOCK" schaltet Mock-Modus ein
        if port == "MOCK":
            USE_MOCK = True
        else:
            USE_MOCK = False

        print(f"[CS2000Device.__init__] Initialisiere Gerät auf Port {port}, Baudrate {baudrate}")
        self.motor_controller = motor_controller
        self.motor_steps = 500
        self.auto_move_enabled = False
        self.ser = None
        self.lock = threading.RLock()
        
        if not USE_MOCK:
            self.ser = serial.Serial(
                port=port,
                baudrate=baudrate,
                bytesize=serial.EIGHTBITS,
                stopbits=serial.STOPBITS_ONE,
                parity=serial.PARITY_NONE,
                timeout=timeout,
                rtscts=True
            )
            # set_buffer_size is only available in pyserial 3.5+
            try:
                self.ser.set_buffer_size(rx_size=32768, tx_size=4096)
            except AttributeError:
                print("[CS2000Device.__init__] set_buffer_size nicht verfügbar (ältere pyserial Version)")
            self.ser.reset_input_buffer()
            self.ser.reset_output_buffer()
            print("[CS2000Device.__init__] Serielle Verbindung erfolgreich aufgebaut")
        else:
            print("[CS2000Device.__init__] Mock-Modus aktiv, keine echte Verbindung")

    def send_command(self, command: str) -> str:
        """
        Sendet einen Befehl an das Gerät und wartet auf eine Antwort.
        Thread-sicher durch RLock.
        """
        with self.lock:
            print(f"[CS2000Device.send_command] Sende Befehl: {command.strip()}")
            if USE_MOCK:
                response = self.mock_response(command)
                print(f"[CS2000Device.send_command] Mock-Antwort: {response[:80]}...")
                return response
        try:
            if self.ser and self.ser.in_waiting > 0:
                discarded = self.ser.read(self.ser.in_waiting)
                print(f"[CS2000Device.send_command] Verwerfe {len(discarded)} Bytes aus Buffer")
            if not command.endswith("\r"):
                command += "\r"
            if self.ser:
                self.ser.write(command.encode('ascii'))
                time.sleep(0.05)
                response = self.ser.read_until(b'\r').decode('ascii', errors='ignore').strip()
                if response:
                    print(f"[CS2000Device.send_command] Antwort empfangen: {response[:80]}")
                    return response
                else:
                    print("[CS2000Device.send_command] Keine Antwort empfangen")
                    return ""
            return ""
        except Exception as e:
            print(f"[CS2000Device.send_command] EXCEPTION: {e}")
            return ""

    def mock_response(self, cmd: str) -> str:
        """Generiert simulierte Antworten für den Testbetrieb."""
        print(f"[CS2000Device.mock_response] Generiere Mock-Antwort für: {cmd.strip()}")
        c = cmd.strip().upper()
        if c.startswith("RMTS"): return "OK00"
        if c.startswith("SPMS"): return "OK00"
        if c.startswith("MEAS"): return "OK00,3"
        if c.startswith("MEDR"):
            if ",1,0," in c:
                block_num = int(c.split(",")[-1])
                if block_num == 4:
                    return "OK00," + ",".join([f"{0.5+0.3*((i%20)/20):.6f}" for i in range(23)])
                else:
                    return "OK00," + ",".join([f"{0.5+0.3*((i%20)/20):.6f}" for i in range(26)])
            elif ",2,0," in c:
                return "OK00,0.3127,0.3290,100.5"
        return "ER00"

    def close(self):
        """Schließt die serielle Verbindung sauber."""
        print("[CS2000Device.close] Schließe serielle Verbindung")
        with self.lock:
            if not USE_MOCK and self.ser and self.ser.is_open:
                self.ser.close()
                print("[CS2000Device.close] Verbindung erfolgreich geschlossen")

    def read_spectral_data(self):
        """
        Liest die Spektraldaten vom Gerät.
        
        Das CS-2000 sendet Spektraldaten in 4 Blöcken (via MEDR,1,0,x Befehl).
        Diese Methode fragt alle 4 Blöcke ab und setzt sie zusammen.
        
        Returns:
            list: Liste von float-Werten (Spektralradiance).
        """
        with self.lock:
            print("[CS2000Device.read_spectral_data] Beginne Auslesen der Spektraldaten")
        vals = []
        vals_extend = vals.extend
        for blk in range(1, 5):
            print(f"[CS2000Device.read_spectral_data] Lese Block {blk}/4")
            resp = self.send_command(f"MEDR,1,0,{blk}")
            if not resp.startswith("OK00,"):
                print(f"[CS2000Device.read_spectral_data] FEHLER in Block {blk}: {resp}")
                return []
            try:
                data_part = resp[5:]
                cleaned = re.sub(r'[^\d,.\-eE]', '', data_part)
                values = [float(x) for x in cleaned.split(",") if x.strip()]
                vals_extend(values)
                print(f"[CS2000Device.read_spectral_data] Block {blk}: {len(values)} Werte gelesen")
            except ValueError as e:
                print(f"[CS2000Device.read_spectral_data] Parse-Fehler in Block {blk}: {e}")
                return []
        print(f"[CS2000Device.read_spectral_data] Erfolgreich {len(vals)} Spektralwerte gelesen")
        return vals

    def read_xyY(self):
        """
        Liest die farbmetrischen Daten (x, y, Y) vom Gerät.
        Optional: Führt eine automatische Motorbewegung nach dem Lesen aus (für Scanning).
        
        Returns:
            tuple: (x, y, Y) als floats oder None bei Fehler.
        """
        with self.lock:
            print("[CS2000Device.read_xyY] Lese xyY Farbdaten")
            resp = self.send_command("MEDR,2,0,00")
        if not resp.startswith("OK00,"):
            print(f"[CS2000Device.read_xyY] FEHLER: {resp}")
            return None
        try:
            parts = resp[5:].split(",")
            if len(parts) < 3:
                print(f"[CS2000Device.read_xyY] FEHLER: Nicht genug Werte in Antwort: {resp}")
                return None
            xyY = tuple(float(parts[i]) for i in range(3))
            print(f"[CS2000Device.read_xyY] Erfolgreich: x={xyY[0]:.4f}, y={xyY[1]:.4f}, Y={xyY[2]:.2f}")
            
            # Optionaler Auto-Move nach erfolgreicher Messung
            print(f"[CS2000Device.read_xyY] Warte 0.5 Sekunden...")
            time.sleep(0.5)
            
            if self.auto_move_enabled and self.motor_controller:
                print(f"[CS2000Device.read_xyY] Auto-Move: Bewege Motor um {self.motor_steps} Schritte")
                self.motor_controller.move_steps(self.motor_steps, 'x')
            else:
                print(f"[CS2000Device.read_xyY] Auto-Move deaktiviert oder kein Motor-Controller")
            
            return xyY
        except (ValueError, IndexError) as e:
            print(f"[CS2000Device.read_xyY] Parse-Fehler: {e}, Antwort: {resp}")
            return None

    def set_motor_steps(self, steps):
        """Setzt die Schrittweite für den optionalen Auto-Move."""
        self.motor_steps = steps
        print(f"[CS2000Device.set_motor_steps] Motor-Schrittweite auf {steps} gesetzt")

    def enable_auto_move(self, enabled=True):
        """Aktiviert/Deaktiviert das automatische Weiterfahren nach Messung."""
        self.auto_move_enabled = enabled
        print(f"[CS2000Device.enable_auto_move] Auto-Move: {'aktiviert' if enabled else 'deaktiviert'}")


class MeasurementWorker(QThread):
    """
    Worker-Thread für die Durchführung einer EINZELNEN Messung.
    Läuft im Hintergrund, damit das GUI nicht blockiert.
    Implementiert Retry-Logik bei Kommunikationsfehlern.
    """
    measurement_done = pyqtSignal(str, tuple, list)
    measurement_error = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, device, patch_id, parent=None):
        """
        Initialisiert den Worker.
        
        Args:
            device (CS2000Device): Das Messgerät-Objekt.
            patch_id (str): ID oder Name des Messpunktes (z.B. "M[2,3]").
        """
        print(f"[MeasurementWorker.__init__] Erstelle Worker für '{patch_id}'")
        super().__init__(parent)
        self.device = device
        self.patch_id = patch_id

    def run(self):
        """Führt den Messablauf aus: MEAS triggern -> Warten -> Daten lesen."""
        print(f"[MeasurementWorker.run] Starte Messung für '{self.patch_id}'")
        try:
            resp = self.device.send_command("MEAS,1")
            print(f"[MeasurementWorker.run] MEAS Antwort: '{resp}'")
            m = re.match(r"^OK00(?:,(\d+))?", resp)
            if m:
                # Wartezeit aus Antwort extrahieren (Default 2s)
                t = int(m.group(1)) if m.group(1) else 2
                total_wait = t + 2.0
                print(f"[MeasurementWorker.run] Messung läuft, warte {total_wait}s ({t}s + 2.0s Puffer)...")
                time.sleep(total_wait)
                
                max_retries = 3
                retry_delay = 0.5
                
                for attempt in range(max_retries):
                    print(f"[MeasurementWorker.run] Lese Spektral- und Farbdaten (Versuch {attempt+1}/{max_retries})")
                    spec = self.device.read_spectral_data()
                    
                    if spec:
                        xyY = self.device.read_xyY()
                        if xyY:
                            print(f"[MeasurementWorker.run] Messung erfolgreich nach {attempt+1} Versuch(en): {len(spec)} Spektralwerte, xyY={xyY}")
                            self.measurement_done.emit(self.patch_id, xyY, spec)
                            return
                    
                    if attempt < max_retries - 1:
                        print(f"[MeasurementWorker.run] Daten nicht verfügbar, warte {retry_delay}s und versuche erneut...")
                        time.sleep(retry_delay)
                
                error_msg = f"Fehler: Konnte Daten nicht lesen nach {max_retries} Versuchen"
                print(f"[MeasurementWorker.run] FEHLER: {error_msg}")
                self.measurement_error.emit(error_msg)
            else:
                error_msg = f"Messbefehl fehlgeschlagen: Ungültige Antwort '{resp}'"
                print(f"[MeasurementWorker.run] FEHLER: {error_msg}")
                self.measurement_error.emit(error_msg)
        except Exception as e:
            error_msg = f"Ausnahme in Worker: {str(e)}"
            print(f"[MeasurementWorker.run] EXCEPTION: {error_msg}")
            import traceback
            traceback.print_exc()
            self.measurement_error.emit(error_msg)
        finally:
            print(f"[MeasurementWorker.run] Worker beendet")
            self.finished.emit()


class MesstafelWorker(QThread):
    """
    Worker-Thread für die vollautomatische Messung einer ganzen Messtafel.
    Fährt alle Gitterpunkte nacheinander an (Snake-Path) und führt Messungen durch.
    
    Unterstützt:
    - Pfadberechnung (Snake/ZigZag)
    - Interpolation der Positionen (Scipy griddata), falls Korrekturpunkte vorhanden sind
    - Pause/Resume Funktionalität
    - Fehlerbehandlung und Retry-Logik
    """
    measurement_done = pyqtSignal(str, tuple, list)
    measurement_error = pyqtSignal(str)
    progress_update = pyqtSignal(int, int, str)
    kasten_status_update = pyqtSignal(int, int, str)
    finished = pyqtSignal()

    def __init__(self, device, motor_controller, correction_points=None, parent=None):
        """
        Initialisiert den Worker.
        
        Args:
            device: CS2000Device Instanz.
            motor_controller: MotorSteuerung Widget/Instanz.
            correction_points: Dict mit manuellen Korrekturen {(row, col): (x, y)}.
        """
        print("[MesstafelWorker.__init__] Erstelle Messtafel-Worker")
        super().__init__(parent)
        self.device = device
        self.motor = motor_controller
        self.correction_points = correction_points if correction_points else {}
        self.is_running = True
        self.is_paused = False

    def prepare_interpolation_model(self):
        """
        Bereitet das Interpolationsmodell vor.
        Nutzt Eckpunkte (OL, UL, UR) und alle manuellen Korrekturpunkte als Stützstellen
        für `scipy.interpolate.griddata`.
        Dadurch werden Zwischenpositionen "elastisch" angepasst.
        """
        # === Interpolation Vorbereitung ===
        known_points = []
        known_values_x = []
        known_values_y = []
        
        # Begrenzungen (als Referenzpunkte)
        ol = self.motor.begrenzung_oben_links
        ul = self.motor.begrenzung_unten_links
        ur = self.motor.begrenzung_unten_rechts
        or_real = self.motor.begrenzung_oben_rechts
        
        anzahl_cols = self.motor.anzahl_messfelder_x
        anzahl_rows = self.motor.anzahl_messfelder_y

        # Stützstellen hinzufügen: (row, col) -> x, y
        known_points.append((0, 0))
        known_values_x.append(ol['x'])
        known_values_y.append(ol['y'])
        
        if anzahl_rows > 1:
            known_points.append((anzahl_rows-1, 0))
            known_values_x.append(ul['x'])
            known_values_y.append(ul['y'])
            
        if anzahl_rows > 1 and anzahl_cols > 1:
            known_points.append((anzahl_rows-1, anzahl_cols-1))
            known_values_x.append(ur['x'])
            known_values_y.append(ur['y'])
            
        if anzahl_cols > 1:
            known_points.append((0, anzahl_cols-1))
            # Nutze echten Punkt, falls gesetzt (nicht 0,0), sonst berechnet
            if or_real['x'] != 0 or or_real['y'] != 0:
                known_values_x.append(or_real['x'])
                known_values_y.append(or_real['y'])
            else:
                # Fallback: Parallel-Verschiebung berechnen
                calc_or_x = ol['x'] + (ur['x'] - ul['x'])
                calc_or_y = ol['y'] + (ur['y'] - ul['y'])
                known_values_x.append(calc_or_x)
                known_values_y.append(calc_or_y)
            
        # Manuelle Korrekturpunkte hinzufügen
        for (r, c), (kx, ky) in self.correction_points.items():
            known_points.append((r, c))
            known_values_x.append(kx)
            known_values_y.append(ky)

        # Scipy Vorbereiten
        self.interp_points = None
        self.interp_values_x = None
        self.interp_values_y = None
        self.use_interpolation = SCIPY_AVAILABLE and len(known_points) >= 3
        
        if self.use_interpolation:
            try:
                self.interp_points = np.array(known_points)
                self.interp_values_x = np.array(known_values_x)
                self.interp_values_y = np.array(known_values_y)
                # print(f"[MesstafelWorker] Interpolationsmodell aktualisiert ({len(known_points)} Punkte)")
            except Exception as e:
                print(f"[MesstafelWorker] Fehler bei Interpolations-Update: {e}")
                self.use_interpolation = False

    def run(self):
        """Hauptschleife des Workers: Fährt alle Punkte ab und misst."""
        print("[MesstafelWorker.run] Starte Messtafelmessung")
        
        if self.motor.schritte_pro_feld_x == 0 or self.motor.schritte_pro_feld_y == 0:
            self.measurement_error.emit("Fehler: Bitte zuerst Abstände berechnen!")
            self.finished.emit()
            return
        
        anzahl_cols = self.motor.anzahl_messfelder_x
        anzahl_rows = self.motor.anzahl_messfelder_y
        total_messungen = anzahl_cols * anzahl_rows
        
        print(f"[MesstafelWorker.run] Matrix: {anzahl_rows} Zeilen × {anzahl_cols} Spalten = {total_messungen} Messpunkte")
        
        # Initiale Modell-Berechnung
        self.prepare_interpolation_model()
        
        # === Ziel Position Berechnen ===
        def get_target_pos(r, c):
             if self.use_interpolation:
                 try:
                     xi = np.array([[r, c]])
                     # linear für glatte Übergänge
                     tx = griddata(self.interp_points, self.interp_values_x, xi, method='linear')
                     ty = griddata(self.interp_points, self.interp_values_y, xi, method='linear')
                     
                     if np.isnan(tx) or np.isnan(ty):
                         tx = griddata(self.interp_points, self.interp_values_x, xi, method='nearest')
                         ty = griddata(self.interp_points, self.interp_values_y, xi, method='nearest')
                     
                     return int(tx[0]), int(ty[0])
                 except Exception as e:
                     print(f"[MesstafelWorker] Interpolations-Fehler: {e}")
            
             # Fallback
             # Fallback: Vektor-basierte Berechnung (Urspung: OL)
             # Wir nutzen OL, UL und OR (Oben-Rechts), da diese meistens gesetzt sind.
             start_x = self.motor.begrenzung_oben_links["x"]
             start_y = self.motor.begrenzung_oben_links["y"]
             
             ul_x = self.motor.begrenzung_unten_links["x"]
             ul_y = self.motor.begrenzung_unten_links["y"]
             
             or_x = self.motor.begrenzung_oben_rechts["x"]
             or_y = self.motor.begrenzung_oben_rechts["y"]
             
             # Horizontaler Schritt-Vektor (pro Spalte): OL -> OR
             if anzahl_cols > 1:
                 step_vec_x = (or_x - start_x) / (anzahl_cols - 1)
                 # Y-Verschiebung durch X-Achse (falls schief/gedreht)
                 step_vec_x_y = (or_y - start_y) / (anzahl_cols - 1)
             else:
                 step_vec_x = 0
                 step_vec_x_y = 0
                 
             # Vertikaler Schritt-Vektor (pro Zeile): OL -> UL
             if anzahl_rows > 1:
                 step_vec_y = (ul_y - start_y) / (anzahl_rows - 1)
                 # X-Verschiebung durch Y-Achse (falls schief/Scherung)
                 step_vec_y_x = (ul_x - start_x) / (anzahl_rows - 1) 
             else:
                 step_vec_y = 0
                 step_vec_y_x = 0

             # Ziel = Start + (col * vec_x) + (row * vec_y)
             # Hier summieren wir Vektoren:
             # Pos = Start + col * (step_vec_x, step_vec_x_y) + row * (step_vec_y_x, step_vec_y)
             target_x = start_x + (c * step_vec_x) + (r * step_vec_y_x)
             target_y = start_y + (c * step_vec_x_y) + (r * step_vec_y)
             
             return int(target_x), int(target_y)

        # Start (0,0) anfahren
        print(f"[MesstafelWorker.run] Fahre zu Startposition [0,0]...")
        tx, ty = get_target_pos(0, 0)
        
        delta_x = tx - self.motor.aktuelle_x_position
        delta_y = ty - self.motor.aktuelle_y_position
        
        if delta_x != 0: 
            self.motor.move_steps(delta_x, 'x')
            self.wait_for_movement()
        if delta_y != 0: 
            self.motor.move_steps(delta_y, 'y')
            self.wait_for_movement()
        
        generator = GridPathGenerator(anzahl_rows, anzahl_cols)
        
        self.measurement_nr = 0
        
        # Loop über alle Felder
        first_point = True
        
        for row, col in generator.generate_path():
            if not self.is_running: break
            
            # Pause Check
            while self.is_paused:
                time.sleep(0.1)
                if not self.is_running: break
            if not self.is_running: break

            # === DYNAMISCHE INTERPOLATION ===
            # Wir berechnen vor jedem Schritt die Interpolationsdaten neu,
            # damit Änderungen an Korrekturpunkten (z.B. während Pause)
            # sofort wirksam werden.
            self.prepare_interpolation_model()
            
            # Ziel anfahren
            tx, ty = get_target_pos(row, col)
            
            # Fortschritt
            self.measurement_nr += 1
            self.current_row = row
            self.current_col = col

            target_x, target_y = get_target_pos(row, col)
            
            # Delta Berechnen
            curr_x = self.motor.aktuelle_x_position
            curr_y = self.motor.aktuelle_y_position
            
            dx = target_x - curr_x
            dy = target_y - curr_y
            
            if dx != 0 or dy != 0:
                print(f"[MesstafelWorker] Fahre zu [{row},{col}] -> ({target_x}, {target_y})")
                if dy != 0:
                    self.motor.move_steps(dy, 'y')
                    self.wait_for_movement()
                
                # Check Pause after Y-Move
                if self._check_pause(): break

                if dx != 0:
                    self.motor.move_steps(dx, 'x')
                    self.wait_for_movement()

                # Check Pause after X-Move
                if self._check_pause(): break
            
            # Check Pause before Measurement
            if self._check_pause(): break

            # Messung
            self.measurement_nr += 1
            patch_id = f"M[{row},{col}]"
            
            self.kasten_status_update.emit(row, col, 'measuring')
            self.progress_update.emit(self.measurement_nr, total_messungen, f"Messe {patch_id}")
            
            success = self.perform_measurement_with_retries(patch_id)
            
            if success:
                self.kasten_status_update.emit(row, col, 'done')
            else:
                self.kasten_status_update.emit(row, col, 'error')
                
        print("[MesstafelWorker.run] Fertig")
        self.finished.emit()

    def _check_pause(self):
        """
        Prüft, ob pausiert wurde. Blockiert, solange Pause aktiv ist.
        Gibt True zurück, wenn der Worker gestoppt wurde (Abbruch).
        """
        while self.is_paused:
            time.sleep(0.1)
            if not self.is_running:
                return True
        return not self.is_running

    def wait_for_movement(self):
        """Wartet auf das Fertig-Signal vom Motor mit Polling, um Stop/Pause zu erlauben."""
        # Wir warten maximal 10 Sekunden (Safety Timeout)
        timeout = 10.0
        start_time = time.time()
        
        self.motor_move_finished = False
        
        # Callback für Signal
        def on_finished(success):
            self.motor_move_finished = True

        self.motor.movement_finished.connect(on_finished)
        
        try:
            while not self.motor_move_finished:
                if not self.is_running:
                    print("[MesstafelWorker] wait_for_movement abgebrochen (User Stop).")
                    break
                    
                if time.time() - start_time > timeout:
                    print("[MesstafelWorker] WARNUNG: Motor-Move Timeout!")
                    break
                
                # Kurzes Schlafen, um CPU nicht zu blockieren und Flags zu checken
                time.sleep(0.05) 
                
        finally:
            try:
                self.motor.movement_finished.disconnect(on_finished)
            except:
                pass

    def perform_measurement_with_retries(self, patch_id):
        """Führt eine Messung durch inklusive Retries bei Fehlern."""
        try:
            # Locking happens inside device methods
            resp = self.device.send_command("MEAS,1")
            m = re.match(r"^OK00(?:,(\d+))?", resp)
            
            if m:
                t = int(m.group(1)) if m.group(1) else 2
                
                # Wartezeit mit Abbruch-Check
                wait_time = t + 2.0
                start_wait = time.time()
                while time.time() - start_wait < wait_time:
                    if not self.is_running:
                        return False
                    time.sleep(0.1)

                max_retries = 3
                for attempt in range(max_retries):
                    spec = self.device.read_spectral_data()
                    if spec:
                        xyY = self.device.read_xyY()
                        if xyY:
                            self.measurement_done.emit(patch_id, xyY, spec)
                            return True
                    
                    if attempt < max_retries - 1:
                        time.sleep(0.5)
                
                self.measurement_error.emit(f"Datenfehler bei {patch_id}")
                return False
            else:
                self.measurement_error.emit(f"Messfehlerbei {patch_id}")
                return False
        except Exception as e:
             self.measurement_error.emit(f"Exception bei {patch_id}: {str(e)}")
             return False

    def pause(self):
        """Pausiert den Messablauf (nach Abschluss der aktuellen Aktion)."""
        self.is_paused = True
        print("[MesstafelWorker.pause] Pause requested.")

    def resume(self):
        """Setzt den Messablauf fort."""
        self.is_paused = False
        print("[MesstafelWorker.resume] Resume requested.")

    def stop(self):
        """Stoppt den Messablauf endgültig."""
        print("[MesstafelWorker.stop] Stoppe Messtafelmessung")
        self.is_running = False
        self.is_paused = False


class CS2000GUI(QWidget):
    """
    Das Haupt-GUI für die Steuerung der CS-2000 Messungen.
    
    Funktionalitäten:
    - Verbindungsaufbau zum CS-2000 (inkl. Port-Scan)
    - Einzelmessungen / Manuelle Messungen
    - Automatische Matrix-Messung (Messtafel)
    - Visualisierung des Fortschritts und Status
    - Feinjustierung der Motorposition und Navigation
    - Speichern von CSV-Daten
    - Verwaltung von Korrekturpunkten
    """
    
    def __init__(self, motor_controller=None):
        """
        Initialisiert das GUI.
        
        Args:
            motor_controller: Referenz auf das MotorSteuerung-Objekt (für Bewegungen).
        """
        print("[CS2000GUI.__init__] Initialisiere CS-2000 Mess-GUI")
        super().__init__()
        
        self.motor_controller = motor_controller
        self.messtafel_worker = None
        self.results = []
        
        font = QFont()
        font.setPointSize(12)
        self.setFont(font)
        
        main_layout = QVBoxLayout(self)
        
        # Titel
        title = QLabel("CS-2000 MESSUNG")
        title_font = QFont()
        title_font.setPointSize(16)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setAlignment(QtCore.AlignCenter)
        title.setStyleSheet("background-color: #e0f7fa; padding: 10px; border-radius: 5px;")
        main_layout.addWidget(title)
        
        splitter = QSplitter(QtCore.Horizontal)
        left = QWidget()
        lyt = QVBoxLayout(left)

        # COM-Port Auswahl
        port_row = QHBoxLayout()
        lbl_port = QLabel("CS-2000 COM-Port:")
        lbl_port.setFont(font)
        self.combo_port = QComboBox()
        self.combo_port.setFont(font)
        self.combo_port.setMinimumWidth(180)
        self.btn_refresh_ports = QPushButton("Ports aktualisieren")
        self.btn_refresh_ports.setFont(font)
        self.btn_refresh_ports.clicked.connect(self.refresh_ports)
        port_row.addWidget(lbl_port)
        port_row.addWidget(self.combo_port)
        port_row.addWidget(self.btn_refresh_ports)
        lyt.addLayout(port_row)
        
        # === LAYOUT MESSUNG & KORREKTUR ===
        layout_measure = lyt
        
        info_label = QLabel("Messtafelmessung - Matrix-Schema [Zeile, Spalte]")
        info_label.setFont(font)
        info_label.setStyleSheet("color: #555; font-style: italic; padding: 5px;")
        layout_measure.addWidget(info_label)
        
        # Haupt-Aktionsknöpfe (jetzt Horizontal nebeneinander)
        main_btns = QHBoxLayout()
        
        self.btn_connect = QPushButton("Verbinden")
        self.btn_connect.setFont(font)
        self.btn_connect.setMinimumHeight(35)
        self.btn_connect.setStyleSheet("background-color: #81c784; font-weight: bold;")
        self.btn_connect.clicked.connect(self.connect_device)
        main_btns.addWidget(self.btn_connect)
        
        self.btn_manual = QPushButton("Einzel")
        self.btn_manual.setFont(font)
        self.btn_manual.setMinimumHeight(35)
        self.btn_manual.setStyleSheet("background-color: #64b5f6;")
        self.btn_manual.clicked.connect(self.manual_measurement)
        main_btns.addWidget(self.btn_manual)
        
        self.btn_csv = QPushButton("CSV")
        self.btn_csv.setFont(font)
        self.btn_csv.setMinimumHeight(35)
        self.btn_csv.setStyleSheet("background-color: #ba68c8;")
        self.btn_csv.clicked.connect(self.save_csv)
        main_btns.addWidget(self.btn_csv)
        
        layout_measure.addLayout(main_btns)
        
        # Steuerung für automatische Messung
        scan_group = QGroupBox("Automatische Messung")
        scan_group.setFont(font)
        scan_layout = QHBoxLayout()

        self.btn_messtafelmessung = QPushButton("Start")
        self.btn_messtafelmessung.setFont(font)
        self.btn_messtafelmessung.setMinimumHeight(35)
        self.btn_messtafelmessung.setStyleSheet("background-color: #ffb74d; font-weight: bold;")
        self.btn_messtafelmessung.clicked.connect(self.messtafelmessung)
        scan_layout.addWidget(self.btn_messtafelmessung)

        self.btn_pause_resume = QPushButton("Pause")
        self.btn_pause_resume.setFont(font)
        self.btn_pause_resume.setMinimumHeight(35)
        self.btn_pause_resume.setStyleSheet("background-color: #fff176;")
        self.btn_pause_resume.setEnabled(False)
        self.btn_pause_resume.clicked.connect(self.toggle_pause_resume)
        scan_layout.addWidget(self.btn_pause_resume)

        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setFont(font)
        self.btn_stop.setMinimumHeight(35)
        self.btn_stop.setStyleSheet("background-color: #e57373; font-weight: bold;")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_messtafelmessung)
        scan_layout.addWidget(self.btn_stop)

        scan_group.setLayout(scan_layout)
        layout_measure.addWidget(scan_group)
        
        # Viz und Output
        viz_label = QLabel("Messtafel Fortschritt (Matrix-Schema):")
        viz_label.setFont(font)
        viz_label.setStyleSheet("font-weight: bold; padding: 5px;")
        layout_measure.addWidget(viz_label)
        
        self.messtafel_viz = MesstafelVisualization()
        self.messtafel_viz.box_clicked.connect(self.on_box_clicked)
        layout_measure.addWidget(self.messtafel_viz)

        layout_measure.addStretch()
        
        # === FEINJUSTIERUNG & NAVIGATION ===
        adjust_group = QGroupBox("Feinjustierung & Navigation")
        adjust_group.setFont(font)
        adjust_layout = QVBoxLayout()

        # Navigation
        nav_layout = QHBoxLayout()
        nav_layout.addWidget(QLabel("Zeile:"))
        self.spin_nav_row = QComboBox() 
        self.spin_nav_row.setEditable(True)
        self.spin_nav_row.setEditText("0")
        self.spin_nav_row.setFixedWidth(50)
        nav_layout.addWidget(self.spin_nav_row)

        nav_layout.addWidget(QLabel("Spalte:"))
        self.spin_nav_col = QComboBox() 
        self.spin_nav_col.setEditable(True)
        self.spin_nav_col.setEditText("0")
        self.spin_nav_col.setFixedWidth(50)
        nav_layout.addWidget(self.spin_nav_col)

        self.btn_goto = QPushButton("Fahre zu Kasten")
        self.btn_goto.clicked.connect(self.go_to_box)
        nav_layout.addWidget(self.btn_goto)
        adjust_layout.addLayout(nav_layout)

        # Feinjustierung (Nur Navigation zu Zeile/Spalte, keine Pfeile mehr)
        adjust_layout.addLayout(nav_layout)
        adjust_group.setLayout(adjust_layout)
        layout_measure.addWidget(adjust_group)
        
        # -> KORREKTUR PUNKTE VERWALTUNG
        correction_manage_group = QGroupBox("Korrekturpunkte bearbeiten")
        correction_manage_group.setFont(font)
        cm_layout = QVBoxLayout()
        
        self.btn_save_correction = QPushButton("Aktuelle Position als Korrektur speichern")
        self.btn_save_correction.setStyleSheet("background-color: #ffd54f;")
        self.btn_save_correction.clicked.connect(self.save_correction_point)
        cm_layout.addWidget(self.btn_save_correction)
        
        self.table_corrections = QTableWidget()
        self.table_corrections.setColumnCount(4)
        self.table_corrections.setHorizontalHeaderLabels(["Zeile", "Spalte", "X", "Y"])
        self.table_corrections.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        cm_layout.addWidget(self.table_corrections)
        
        self.btn_delete_correction = QPushButton("Ausgewählten Punkt löschen")
        self.btn_delete_correction.setStyleSheet("background-color: #ef9a9a;")
        self.btn_delete_correction.clicked.connect(self.delete_correction_point)
        cm_layout.addWidget(self.btn_delete_correction)
        
        correction_manage_group.setLayout(cm_layout)
        layout_measure.addWidget(correction_manage_group)

        splitter.addWidget(left)

        # --- RECHTE SEITE (LOGS) ---
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        
        # Output (Text Log) - Oben
        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setFont(font)
        self.output.setMaximumHeight(200)
        right_layout.addWidget(self.output)
        
        # Log Table (Unten)
        self.log_window = LoggingWindow()
        right_layout.addWidget(self.log_window)
        
        splitter.addWidget(right_widget)
        main_layout.addWidget(splitter)

        self.device = None
        self.results = []
        self.current_worker = None
        self.measurement_counter = 0
        self.config_file = get_config_path("config.json")
        self.nudge_step_size = 1
        
        self.correction_points = {} # Key: (row, col), Value: (x, y)

        self.refresh_ports()
        self.load_config()
        
        if self.motor_controller:
            self.motor_controller.position_updated.connect(self.on_motor_position_updated)
            self.motor_controller.boundaries_updated.connect(self.on_motor_boundaries_updated)
            self.motor_controller.calculation_finished.connect(self.on_calculation_finished)
            
        print("[CS2000GUI.__init__] CS-2000 Mess-GUI erfolgreich initialisiert")

    def load_config(self):
        """Lädt den zuletzt verwendeten COM-Port und Korrekturpunkte aus der Konfigurationsdatei."""
        print(f"[CS2000GUI.load_config] Lade Konfiguration aus {self.config_file}")
        if not os.path.exists(self.config_file):
            print("[CS2000GUI.load_config] Konfigurationsdatei nicht gefunden.")
            return

        try:
            with open(self.config_file, 'r') as f:
                config = json.load(f)
            
            cs2000_config = config.get('cs2000', {})
            last_port = cs2000_config.get('port')
            
            if last_port:
                index = self.combo_port.findData(last_port)
                if index != -1:
                    self.combo_port.setCurrentIndex(index)
                    print(f"[CS2000GUI.load_config] Port '{last_port}' geladen.")
        except (json.JSONDecodeError, KeyError, OSError) as e:
            self.log_window.log(f"Fehler beim Laden der Konfig: {e}", level="ERROR")
            print(f"[CS2000GUI.load_config] FEHLER: {e}")

    def save_config(self):
        """Speichert den aktuellen COM-Port und Korrekturpunkte in der Konfigurationsdatei."""
        print(f"[CS2000GUI.save_config] Speichere Konfiguration in {self.config_file}")
        config = {}
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    config = json.load(f)
            except json.JSONDecodeError:
                print("[CS2000GUI.save_config] WARNUNG: Bestehende Konfig-Datei ist korrupt.")
        
        cs2000_config = {
            'port': self.combo_port.itemData(self.combo_port.currentIndex()),
        }
        config['cs2000'] = cs2000_config
        
        try:
            with open(self.config_file, 'w') as f:
                json.dump(config, f, indent=4)
            print("[CS2000GUI.save_config] Konfiguration erfolgreich gespeichert.")
        except Exception as e:
            self.log_window.log(f"Fehler beim Speichern der Konfig: {e}", level="ERROR")
            print(f"[CS2000GUI.save_config] FEHLER: {e}")

    def save_correction_point(self):
        """Speichert die aktuelle Position als Korrektur für die ausgewählte Kasten-Koordinate."""
        if not self.motor_controller:
            return
            
        try:
            row = int(self.spin_nav_row.currentText())
            col = int(self.spin_nav_col.currentText())
            
            x = self.motor_controller.aktuelle_x_position
            y = self.motor_controller.aktuelle_y_position
            
            self.correction_points[(row, col)] = (x, y)
            self.update_correction_table()
            
            self.log_window.log(f"Korrekturbunkt gespeichert: [{row},{col}] -> ({x}, {y})")
            self.output.append(f"✓ Korrektur gespeichert für [{row},{col}]")
            
        except ValueError:
            self.log_window.log("Ungültige Kasten-Auswahl", level="ERROR")

    def delete_correction_point(self):
        """Löscht den ausgewählten Korrekturpunkt."""
        row_idx = self.table_corrections.currentRow()
        if row_idx < 0:
            return
            
        try:
            r_item = self.table_corrections.item(row_idx, 0)
            c_item = self.table_corrections.item(row_idx, 1)
            
            if r_item and c_item:
                r = int(r_item.text())
                c = int(c_item.text())
                
                if (r, c) in self.correction_points:
                    del self.correction_points[(r, c)]
                    self.update_correction_table()
                    self.log_window.log(f"Korrekturpunkt gelöscht: [{r},{c}]")
        except Exception as e:
            print(f"Fehler beim Löschen: {e}")

    def update_correction_table(self):
        """Aktualisiert die Tabelle der Korrekturpunkte."""
        self.table_corrections.setRowCount(0)
        
        for (r, c), (x, y) in sorted(self.correction_points.items()):
            row_idx = self.table_corrections.rowCount()
            self.table_corrections.insertRow(row_idx)
            
            self.table_corrections.setItem(row_idx, 0, QTableWidgetItem(str(r)))
            self.table_corrections.setItem(row_idx, 1, QTableWidgetItem(str(c)))
            self.table_corrections.setItem(row_idx, 2, QTableWidgetItem(str(x)))
            self.table_corrections.setItem(row_idx, 3, QTableWidgetItem(str(y)))

    def refresh_ports(self):
        """Lädt verfügbare serielle Ports in das Dropdown und fügt MOCK hinzu."""
        self.combo_port.clear()
        ports = list(serial.tools.list_ports.comports())
        for p in ports:
            text = f"{p.device}  ({p.description})"
            self.combo_port.addItem(text, p.device)

        # Immer Mock-Port anbieten
        self.combo_port.addItem("MOCK (Simulierter CS-2000)", "MOCK")
        print("[CS2000GUI.refresh_ports] Ports aktualisiert")

    def connect_device(self):
        """Baut die serielle Verbindung zum ausgewählten Port auf."""
        print("[CS2000GUI.connect_device] Button 'Verbindung aufbauen' gedrückt")

        idx = self.combo_port.currentIndex()
        port = self.combo_port.itemData(idx)
        if not port:
            QMessageBox.warning(self, "Fehler", "Bitte zuerst einen COM-Port im Dropdown auswählen.")
            return

        try:
            self.device = CS2000Device(port=port, motor_controller=self.motor_controller)
        except Exception as e:
            QMessageBox.critical(self, "Verbindungsfehler", f"CS-2000 konnte nicht geöffnet werden:\n{e}")
            return

        resp = self.device.send_command("RMTS,1")
        if resp.startswith("OK00"):
            self.log_window.log(f"Gerät auf {port} verbunden. Schneller Modus aktivieren...")
            self.device.send_command("SPMS,4,01,2")
            self.log_window.log("Multi-Fast Mode aktiviert.")
            self.output.append(f"✓ Verbindung erfolgreich hergestellt auf {port}")
            self.output.append("  CS-2000 bereit für Messtafelmessung")
            print("[CS2000GUI.connect_device] Verbindung erfolgreich")
            self.save_config()
        else:
            self.log_window.log(f"Verbindungsfehler: {resp}", level="ERROR")
            self.output.append("✗ Verbindungsfehler!")

    def on_box_clicked(self, row, col):
        """Handler für Klicks auf die Messtafel (Signal aus Visualization)."""
        self.log_window.log(f"Visualisierung: Kasten [{row}, {col}] ausgewählt.")
        self.spin_nav_row.setCurrentText(str(row))
        self.spin_nav_col.setCurrentText(str(col))

    def manual_measurement(self):
        """Startet eine einzelne Messung ohne automatische Bewegung."""
        print("[CS2000GUI.manual_measurement] Button 'Einzelmessung' gedrückt")
        if not self.device:
            QMessageBox.warning(self, "Fehler", "Bitte zuerst eine Verbindung zum CS-2000 aufbauen.")
            return

        self.measurement_counter += 1
        patch_id = f"Messpunkt_{self.measurement_counter}"
        
        self.log_window.log(f"Starte Einzelmessung: {patch_id}")
        self.output.append(f"⏳ Starte Messung {self.measurement_counter}...")
        
        self.device.enable_auto_move(False)
        
        self.current_worker = MeasurementWorker(self.device, patch_id)
        self.current_worker.measurement_done.connect(self.on_measurement_done)
        self.current_worker.measurement_error.connect(self.on_measurement_error)
        self.current_worker.finished.connect(self.on_worker_finished)
        self.current_worker.start()

    def messtafelmessung(self):
        """
        Startet die automatische Messtafelmessung.
        Überprüft Voraussetzungen (Verbindung, Motor, Grid-Berechnung) und
        initialisiert den MesstafelWorker.
        """
        print("[CS2000GUI.messtafelmessung] Button 'Messtafelmessung' gedrückt")
        
        # Ergebnisse zurücksetzen für neue Messung
        self.results = []
        self.output.append("--- Neue Messung gestartet, alte Daten gelöscht ---")
        
        if not self.device:
            QMessageBox.warning(self, "Fehler", "Bitte zuerst eine Verbindung zum CS-2000 aufbauen.")
            return
        
        if not self.motor_controller:
            QMessageBox.warning(self, "Fehler", "Keine Motor-Steuerung verfügbar!")
            return
        
        if self.motor_controller.schritte_pro_feld_x == 0 or self.motor_controller.schritte_pro_feld_y == 0:
            QMessageBox.warning(self, "Fehler", 
                               "Bitte zuerst Abstände berechnen!\n\n"
                               "1. Begrenzungen speichern\n"
                               "2. Anzahl Kästen eingeben\n"
                               "3. 'Abstände berechnen' klicken")
            return
        
        anzahl_cols = self.motor_controller.anzahl_messfelder_x
        anzahl_rows = self.motor_controller.anzahl_messfelder_y
        total = anzahl_cols * anzahl_rows
        
        self.messtafel_viz.setup_grid(anzahl_rows, anzahl_cols)
        
        reply = QMessageBox.question(self, "Messtafelmessung starten?",
                                     f"Starte automatische Messung von {total} Messpunkten?\n\n"
                                     f"Matrix: {anzahl_rows} Zeilen × {anzahl_cols} Spalten\n"
                                     f"Mäander-Muster (minimaler Verfahrweg)",
                                     QMessageBox.Yes | QMessageBox.No)
        
        if reply == QMessageBox.Yes:
            self.output.append(f"\n{'='*50}")
            self.output.append(f"🚀 Starte Messtafelmessung: {total} Messpunkte")
            self.output.append(f"   Matrix: {anzahl_rows} Zeilen × {anzahl_cols} Spalten")
            self.output.append(f"{'='*50}\n")
            self.log_window.log(f"Starte Messtafelmessung: Matrix {anzahl_rows}×{anzahl_cols}")
            
            self.btn_messtafelmessung.setEnabled(False)
            self.btn_manual.setEnabled(False)
            self.btn_pause_resume.setText("Pause")
            self.btn_pause_resume.setEnabled(True)
            self.btn_stop.setEnabled(True)
            
            self.messtafel_worker = MesstafelWorker(
                self.device, 
                self.motor_controller, 
                correction_points=self.correction_points
            )
            self.messtafel_worker.measurement_done.connect(self.on_measurement_done)
            self.messtafel_worker.measurement_error.connect(self.on_measurement_error)
            self.messtafel_worker.progress_update.connect(self.on_progress_update)
            self.messtafel_worker.kasten_status_update.connect(self.on_kasten_status_update)
            self.messtafel_worker.finished.connect(self.on_messtafelmessung_finished)
            self.messtafel_worker.start()

    def toggle_pause_resume(self):
        """Schaltet zwischen Pause und Fortsetzen der automatischen Messung um."""
        if not self.messtafel_worker:
            return
        
        if self.btn_pause_resume.text() == "Pause":
            self.messtafel_worker.pause()
            self.btn_pause_resume.setText("Resume")
            self.log_window.log("Messtafelmessung pausiert.")
            self.output.append("⏸️ Messung pausiert.")
        else:
            self.messtafel_worker.resume()
            self.btn_pause_resume.setText("Pause")
            self.log_window.log("Messtafelmessung fortgesetzt.")
            self.output.append("▶️ Messung fortgesetzt.")

    def stop_messtafelmessung(self):
        """Stoppt die automatische Messung nach Bestätigung."""
        if not self.messtafel_worker:
            return
        
        reply = QMessageBox.question(self, "Messung stoppen?",
                                     "Möchten Sie die automatische Messung wirklich abbrechen?",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.messtafel_worker.stop()
            self.log_window.log("Messtafelmessung wird gestoppt...")
            self.output.append("⏹️ Messung wird gestoppt...")

    def on_progress_update(self, current, total, status):
        """Slot für Fortschritts-Updates vom MesstafelWorker."""
        self.log_window.log(f"[{current}/{total}] {status}")

    def on_kasten_status_update(self, row, col, status):
        """Update Kasten-Status in Visualisierung mit Matrix-Koordinaten."""
        self.messtafel_viz.set_kasten_status(row, col, status)

    def on_messtafelmessung_finished(self):
        """Wird aufgerufen, wenn die vollautomatische Messung komplett beendet ist."""
        self.output.append(f"\n{'='*50}")
        self.output.append(f"✅ Messtafelmessung abgeschlossen!")
        self.output.append(f"   Gesamt: {len(self.results)} Messungen")
        self.output.append(f"{'='*50}\n")
        self.log_window.log("Messtafelmessung abgeschlossen")
        
        self.btn_messtafelmessung.setEnabled(True)
        self.btn_manual.setEnabled(True)
        self.btn_pause_resume.setText("Pause")
        self.btn_pause_resume.setEnabled(False)
        self.btn_stop.setEnabled(False)

    def on_measurement_done(self, patch_id, xyY, spec):
        """
        Slot: Wird aufgerufen, wenn eine Einzelmessung (innerhalb oder außerhalb der Automatik) fertig ist.
        Speichert das Ergebnis und aktualisiert Logs.
        """
        print(f"[CS2000GUI.on_measurement_done] Messung '{patch_id}' abgeschlossen")
        x, y, Y = xyY
        
        self.results.append((patch_id, 0, 0, 0, x, y, Y, *spec))
        
        self.output.append(f"✓ {patch_id}: x={x:.4f}, y={y:.4f}, Y={Y:.2f} cd/m²")
        self.log_window.log(f"Messung {patch_id} abgeschlossen: x={x:.4f}, y={y:.4f}, Y={Y:.2f}")

    def on_measurement_error(self, error_msg):
        """Slot: Fehler bei einer Messung."""
        print(f"[CS2000GUI.on_measurement_error] Fehler: {error_msg}")
        self.log_window.log(error_msg, level="ERROR")
        self.output.append(f"✗ Fehler: {error_msg}")

    def on_worker_finished(self):
        """Wird aufgerufen wenn der Einzel-MeasurementWorker beendet ist."""
        print("[CS2000GUI.on_worker_finished] Worker-Thread beendet")
        self.log_window.log("✓ Messung abgeschlossen")

    def save_csv(self):
        """
        Exportiert alle gesammelten Ergebnisse in eine CSV-Datei.
        Sortiert die Ergebnisse numerisch nach Matrix-Index.
        """
        print("[CS2000GUI.save_csv] Button 'CSV speichern' gedrückt")
        
        if not self.results:
            QMessageBox.warning(self, "Keine Daten", "Keine Messdaten vorhanden.")
            return
        
        path, _ = QFileDialog.getSaveFileName(
            self, 
            "CSV speichern", 
            "messtafel_messung.csv"
        )
        
        if path:
            try:
                def extract_matrix_coords(patch_id):
                    match = re.search(r'M\[(\d+),(\d+)\]', str(patch_id))
                    if match:
                        row = int(match.group(1))
                        col = int(match.group(2))
                        return (row, col)
                    return (999, 999)
                
                sorted_results = sorted(
                    self.results,
                    key=extract_matrix_coords
                )
                
                with open(path, "w", newline="") as f:
                    w = csv.writer(f, delimiter=";")
                    # Spectral data: 101 values from 380nm to 780nm in 4nm steps
                    hdr = ["ID", "L", "A", "B", "x", "y", "Y"] + [f"S{380+i*4}" for i in range(101)]
                    w.writerow(hdr)
                    
                    for r in sorted_results:
                        w.writerow(r)
                
                self.log_window.log(f"CSV gespeichert: {path}")
                self.output.append(f"✓ CSV gespeichert: {path}")
                self.output.append(f"  {len(sorted_results)} Messungen exportiert")
                self.output.append(f"  (Sortiert: zeilenweise von oben-links nach unten-rechts)")
                print(f"[CS2000GUI.save_csv] CSV gespeichert: {path}")
                
            except Exception as e:
                self.log_window.log(f"CSV-Fehler: {e}", level="ERROR")
                self.output.append(f"✗ CSV-Fehler: {e}")
                print(f"[CS2000GUI.save_csv] FEHLER: {e}")

    def on_motor_position_updated(self, x, y):
        """Slot, der auf Positionsänderungen des Motors reagiert."""
        self.messtafel_viz.update_motor_position(x, y)

    def on_motor_boundaries_updated(self, ol, ul, ur):
        """Slot, der auf Änderungen der Begrenzungen reagiert."""
        self.messtafel_viz.set_boundaries(ol, ul, ur)

    def on_calculation_finished(self, rows, cols):
        """Slot: Wird aufgerufen, wenn Motor-Steuerung Berechnung fertig hat."""
        print(f"[CS2000GUI] Empfange Berechnungs-Daten: {rows}x{cols}")
        self.messtafel_viz.setup_grid(rows, cols)
        self.log_window.log(f"Visualisierung aktualisiert: {rows}x{cols}")
    def go_to_box(self):
        """
        Fährt direkt zur Mitte eines bestimmten Kastens.
        Nutzt dieselbe Interpolationslogik wie die automatische Messung, um Konsistenz zu gewährleisten.
        """
        if not self.motor_controller:
            self.log_window.log("Kein Motor-Controller verbunden!", level="ERROR")
            return

        try:
            target_row = int(self.spin_nav_row.currentText())
            target_col = int(self.spin_nav_col.currentText())
        except ValueError:
            self.log_window.log("Ungültige Zeile/Spalte Eingabe", level="ERROR")
            return

        # Basis-Informationen holen
        start_x = self.motor_controller.begrenzung_oben_links["x"]
        start_y = self.motor_controller.begrenzung_oben_links["y"]
        steps_x = self.motor_controller.schritte_pro_feld_x
        steps_y = self.motor_controller.schritte_pro_feld_y
        offset_x = steps_x // 2
        offset_y = steps_y // 2

        if self.motor_controller.schritte_pro_feld_x == 0 or self.motor_controller.schritte_pro_feld_y == 0:
             self.log_window.log("Berechnen Sie zuerst die Abstände in der Motorsteuerung!", level="ERROR")
             return

        # Verwende Interpolation analog zum Worker, falls verfügbar, sonst einfache Berechnung
        # Hole alle bekannten Punkte (Eckpunkte + Korrekturen)
        known_points = []
        known_values_x = []
        known_values_y = []
        
        # Eckdaten
        rows = self.motor_controller.anzahl_messfelder_y
        cols = self.motor_controller.anzahl_messfelder_x
        
        # Begrenzungen
        ol = self.motor_controller.begrenzung_oben_links
        ul = self.motor_controller.begrenzung_unten_links
        ur = self.motor_controller.begrenzung_unten_rechts
        
        # Ecken als Stützstellen (Row, Col) -> (MotorX, MotorY)
        # Oben-Links: (0, 0)
        # Unten-Links: (rows-1, 0)
        # Unten-Rechts: (rows-1, cols-1)
        # Oben-Rechts (berechnet): (0, cols-1) 
        #   -> Nehmen wir an, ist parallel zu unten. 
        #   Delta X oben ≈ Delta X unten: ur.x - ul.x
        #   Delta Y oben ≈ Delta Y unten: ur.y - ul.y (meist 0)
        #   or_x = ol.x + (ur.x - ul.x)
        #   or_y = ol.y + (ur.y - ul.y)
        
        or_x = ol['x'] + (ur['x'] - ul['x'])
        or_y = ol['y'] + (ur['y'] - ul['y'])

        # Stützstellen hinzufügen: (row, col) -> x, y
        # ObenLinks
        known_points.append((0, 0))
        known_values_x.append(ol['x'])
        known_values_y.append(ol['y'])
        
        # UntenLinks
        if rows > 1:
            known_points.append((rows-1, 0))
            known_values_x.append(ul['x'])
            known_values_y.append(ul['y'])
            
        # UntenRechts
        if rows > 1 and cols > 1:
            known_points.append((rows-1, cols-1))
            known_values_x.append(ur['x'])
            known_values_y.append(ur['y'])
            
        # ObenRechts
        if cols > 1:
            known_points.append((0, cols-1))
            known_values_x.append(or_x)
            known_values_y.append(or_y)
            
        # Korrekturpunkte hinzufügen
        for (r, c), (kx, ky) in self.correction_points.items():
            known_points.append((r, c))
            known_values_x.append(kx)
            known_values_y.append(ky)

        target_x_pos = 0
        target_y_pos = 0

        if SCIPY_AVAILABLE and len(known_points) >= 3: # Min 3 Punkte für Interpolation
             # Interpoliere X und Y separat
             points = np.array(known_points) # (N, 2)
             values_x = np.array(known_values_x)
             values_y = np.array(known_values_y)
             
             # Zielpunkt
             xi = np.array([[target_row, target_col]])
             
             # Griddata (linear)
             interp_x = griddata(points, values_x, xi, method='linear')
             interp_y = griddata(points, values_y, xi, method='linear')
             
             if np.isnan(interp_x) or np.isnan(interp_y):
                 # Fallback 'nearest' falls außerhalb convex hull (sollte bei Grid nicht passieren, wenn Ecken da sind)
                 interp_x = griddata(points, values_x, xi, method='nearest')
                 interp_y = griddata(points, values_y, xi, method='nearest')
                 
             target_x_pos = int(interp_x[0])
             target_y_pos = int(interp_y[0])
             
             # Offset für Mitte (optional, Schritte/Feld gelten nur lokal grob, vllt weglassen bei absoluter Pos? 
             # Nein, wir interpolieren Raster-Eckpunkte. Wir wollen aber KASTEN-MITTE.
             # Das Raster oben bezog sich auf Kasten-INDICES.
             # Wenn wir (0,0) interpolieren, meinen wir die Position von Kasten 0,0. 
             # Soll das die Ecke oben-links sein oder die Mitte?
             # Bisher war "Begrenzung Oben Links" die LINKER OBERE ECKE des ersten Kastens? 
             # Oder die Mitte? Meist Kalibriert man auf die Mitte des ersten Kastens.
             # Angenommen, die Kalibrierpunkte SIND die Messpunkte (Mitten).
             # Dann passt die Interpolation direkt.
             
        else:
            # Fallback Legacy Calculation
            start_x = self.motor_controller.begrenzung_oben_links["x"]
            start_y = self.motor_controller.begrenzung_oben_links["y"]
            steps_x = self.motor_controller.schritte_pro_feld_x
            steps_y = self.motor_controller.schritte_pro_feld_y
            offset_x = steps_x // 2
            offset_y = steps_y // 2
             # Alte Logik addierte Offset, weil Begrenzung als "Ecke" verstanden wurde? 
             # In "MesstafelWorker.run" wurde delta zum Start berechnet und dann Offset zur Mitte.
             # Wenn wir annehmen user speichert MITTE, dann kein Offset.
             # Lassen wir Offset erstmal weg, wenn man auf Punkt fährt.
             
            # Legacy Target Calculation (ohne Offset hier für go_to_box, um konsistent mit Interpolation zu sein?)
            # MOMENT: go_to_box (alt) hatte offset.
            # "target_x_pos = start_x + (target_col * steps_x) + offset_x"
            # Das heißt Begrenzung war linke obere Ecke.
            
            # Für Interpolation nehmen wir an, Korrekturpunkte sind die ZIELPUNKTE (Mitten).
            # Auch die Ecken (Begrenzung) sind eigentlich Mitten der Eck-Kästen, wenn man es genau nimmt?
            # Oder Ecken des Rasters.
            # Um es einfach zu halten: Wir interpolieren das, was gespeichert wurde.
            # Wenn User [0,0] korrigiert, speichert er die exakte Position für [0,0].
            # Also interpolieren wir direkt zu Zielkoordinaten.
            
            target_x_pos = start_x + (target_col * steps_x) + offset_x
            target_y_pos = start_y + (target_row * steps_y) + offset_y

        # Delta berechnen
        current_x = self.motor_controller.aktuelle_x_position
        current_y = self.motor_controller.aktuelle_y_position
        
        delta_x = target_x_pos - current_x
        delta_y = target_y_pos - current_y

        self.log_window.log(f"Fahre zu Kasten [{target_row},{target_col}] (Delta: X={delta_x}, Y={delta_y})")
        
        if delta_x != 0:
            self.motor_controller.move_steps(delta_x, 'x')
            if delta_y != 0:
                # Nutze QTimer für Sequenzierung ohne GUI-Blockade
                QTimer.singleShot(700, lambda: self.motor_controller.move_steps(delta_y, 'y'))
        elif delta_y != 0:
            self.motor_controller.move_steps(delta_y, 'y')


