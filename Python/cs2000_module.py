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

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton, QTextEdit, QLabel,
    QHBoxLayout, QFileDialog, QMessageBox, QSplitter, QPlainTextEdit,
    QGridLayout, QFrame, QScrollBar, QComboBox
)

from PyQt5.QtGui import QFont, QPalette, QColor
from PyQt5.QtCore import Qt, QDateTime, QThread, pyqtSignal
from PyQt5.QtCore import Qt as QtCore

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    print("[WARNING] pyserial nicht installiert")

USE_MOCK = False  # Standard: echte Hardware, MOCK über Dropdown wählbar


class LoggingWindow(QWidget):
    """Separates Fenster zur Anzeige detaillierter Log-Nachrichten mit Zeitstempeln."""
    
    def __init__(self):
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
        print(f"[LoggingWindow.log] [{level}] {msg}")
        ts = QDateTime.currentDateTime().toString("yyyy-MM-dd HH:mm:ss.zzz")
        log_line = f"[{ts}] [{level}] {msg}"
        self.log_view.appendPlainText(log_line)
        sb = self.log_view.verticalScrollBar()
        if sb is not None and sb.value() >= sb.maximum() - 10:
            sb.setValue(sb.maximum())


class MesstafelVisualization(QWidget):
    """Grafische Anzeige der Messtafel mit Fortschritt - Matrix-Schema."""
    
    def __init__(self, parent=None):
        print("[MesstafelVisualization.__init__] Initialisiere Messtafel-Visualisierung")
        super().__init__(parent)
        self.grid_layout = QGridLayout(self)
        self.grid_layout.setSpacing(2)
        self.kasten_widgets = {}
        self.anzahl_rows = 0
        self.anzahl_cols = 0
        print("[MesstafelVisualization.__init__] Messtafel-Visualisierung erfolgreich initialisiert")

    def setup_grid(self, anzahl_rows, anzahl_cols):
        """Erstellt Grid mit Kästen nach Matrix-Schema."""
        print(f"[MesstafelVisualization.setup_grid] Erstelle Grid: {anzahl_rows} Zeilen × {anzahl_cols} Spalten")
        
        for i in reversed(range(self.grid_layout.count())):
            item = self.grid_layout.itemAt(i)
            if item is not None:
                widget = item.widget()
                if widget is not None:
                    widget.setParent(None)
        
        self.kasten_widgets.clear()
        self.anzahl_rows = anzahl_rows
        self.anzahl_cols = anzahl_cols
        
        max_width = 600
        max_height = 400
        kasten_size = min(max_width // anzahl_cols, max_height // anzahl_rows, 60)
        kasten_size = max(kasten_size, 20)
        
        for row in range(anzahl_rows):
            for col in range(anzahl_cols):
                kasten = QFrame()
                kasten.setFrameShape(QFrame.Box)
                kasten.setLineWidth(2)
                kasten.setFixedSize(kasten_size, kasten_size)
                
                kasten.setAutoFillBackground(True)
                palette = kasten.palette()
                palette.setColor(QPalette.Window, QColor(200, 200, 200))
                kasten.setPalette(palette)
                
                label = QLabel(f"[{row},{col}]", kasten)
                label.setAlignment(QtCore.AlignCenter)
                label_font = QFont()
                label_font.setPointSize(max(7, kasten_size // 10))
                label.setFont(label_font)
                label.setGeometry(0, 0, kasten_size, kasten_size)
                
                self.grid_layout.addWidget(kasten, row, col)
                self.kasten_widgets[(row, col)] = kasten
        
        print(f"[MesstafelVisualization.setup_grid] Grid erstellt: {len(self.kasten_widgets)} Kästen")

    def set_kasten_status(self, row, col, status):
        """Setzt Status eines Kastens."""
        if (row, col) not in self.kasten_widgets:
            print(f"[MesstafelVisualization.set_kasten_status] WARNUNG: Kasten [{row},{col}] nicht gefunden")
            return
        
        kasten = self.kasten_widgets[(row, col)]
        palette = kasten.palette()
        
        if status == 'measuring':
            palette.setColor(QPalette.Window, QColor(255, 235, 59))
            print(f"[MesstafelVisualization.set_kasten_status] Kasten [{row},{col}]: MESSEND (gelb)")
        elif status == 'done':
            palette.setColor(QPalette.Window, QColor(129, 199, 132))
            print(f"[MesstafelVisualization.set_kasten_status] Kasten [{row},{col}]: FERTIG (grün)")
        elif status == 'error':
            palette.setColor(QPalette.Window, QColor(239, 83, 80))
            print(f"[MesstafelVisualization.set_kasten_status] Kasten [{row},{col}]: FEHLER (rot)")
        
        kasten.setPalette(palette)
        kasten.update()

    def reset_grid(self):
        """Setzt alle Kästen auf grau zurück."""
        print("[MesstafelVisualization.reset_grid] Setze Grid zurück")
        for (row, col), kasten in self.kasten_widgets.items():
            palette = kasten.palette()
            palette.setColor(QPalette.Window, QColor(200, 200, 200))
            kasten.setPalette(palette)
            kasten.update()


class SpectrumPlot(FigureCanvas):
    """Optimiertes Matplotlib-Plot für spektrale Datenvisualisierung."""
    
    def __init__(self, parent=None):
        print("[SpectrumPlot.__init__] Initialisiere Spektrum-Plot")
        fig = Figure(figsize=(5, 2.5))
        self.ax = fig.add_subplot(111)
        super().__init__(fig)
        self.setParent(parent)
        self.ax.set_title("Spektrale Verteilung", fontsize=12)
        self.ax.set_xlabel("Wellenlänge [nm]", fontsize=11)
        self.ax.set_ylabel("Rel. Intensität", fontsize=11)
        self.ax.tick_params(labelsize=10)
        self.ax.grid(True)
        
        wavelengths = [380 + i * 4 for i in range(101)]
        self.line, = self.ax.plot(wavelengths, [0]*101)
        self.ax.set_xlim(380, 780)
        self.ax.set_ylim(0, 1.2)
        self.draw()
        print("[SpectrumPlot.__init__] Spektrum-Plot erfolgreich initialisiert")

    def update_spectrum(self, values):
        print(f"[SpectrumPlot.update_spectrum] Aktualisiere Spektrum mit {len(values)} Datenpunkten")
        if len(values) != 101:
            print(f"[SpectrumPlot.update_spectrum] WARNUNG: {len(values)} Werte statt 101, passe an")
            if len(values) < 101:
                values = list(values) + [values[-1]] * (101 - len(values))
            else:
                values = values[:101]
        self.line.set_ydata(values)
        max_val = max(values) if values else 1.0
        self.ax.set_ylim(0, max_val * 1.1)
        self.draw_idle()
        print(f"[SpectrumPlot.update_spectrum] Spektrum aktualisiert, Max-Wert: {max_val:.3f}")


class CS2000Device:
    """Kommunikationsklasse für CS-2000 Spektralradiometer."""
    
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
            self.ser.set_buffer_size(rx_size=32768, tx_size=4096)
            self.ser.reset_input_buffer()
            self.ser.reset_output_buffer()
            print("[CS2000Device.__init__] Serielle Verbindung erfolgreich aufgebaut")
        else:
            print("[CS2000Device.__init__] Mock-Modus aktiv, keine echte Verbindung")

    def send_command(self, command: str) -> str:
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
            elif ",2,0,2" in c:
                return "OK00,0.3127,0.3290,100.5"
        return "ER00"

    def close(self):
        print("[CS2000Device.close] Schließe serielle Verbindung")
        if not USE_MOCK and self.ser and self.ser.is_open:
            self.ser.close()
            print("[CS2000Device.close] Verbindung erfolgreich geschlossen")

    def read_spectral_data(self):
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
            
            print(f"[CS2000Device.read_xyY] Warte 0.5 Sekunden...")
            time.sleep(0.5)
            
            if self.auto_move_enabled and self.motor_controller:
                print(f"[CS2000Device.read_xyY] Auto-Move: Bewege Motor um {self.motor_steps} Schritte")
                self.motor_controller.motor_schritte_thread(self.motor_steps, 'x')
            else:
                print(f"[CS2000Device.read_xyY] Auto-Move deaktiviert oder kein Motor-Controller")
            
            return xyY
        except (ValueError, IndexError) as e:
            print(f"[CS2000Device.read_xyY] Parse-Fehler: {e}, Antwort: {resp}")
            return None

    def set_motor_steps(self, steps):
        self.motor_steps = steps
        print(f"[CS2000Device.set_motor_steps] Motor-Schrittweite auf {steps} gesetzt")

    def enable_auto_move(self, enabled=True):
        self.auto_move_enabled = enabled
        print(f"[CS2000Device.enable_auto_move] Auto-Move: {'aktiviert' if enabled else 'deaktiviert'}")


class MeasurementWorker(QThread):
    """Worker-Thread für nicht-blockierende Messungen mit Retry-Mechanismus."""
    measurement_done = pyqtSignal(str, tuple, list)
    measurement_error = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, device, patch_id, parent=None):
        print(f"[MeasurementWorker.__init__] Erstelle Worker für '{patch_id}'")
        super().__init__(parent)
        self.device = device
        self.patch_id = patch_id

    def run(self):
        print(f"[MeasurementWorker.run] Starte Messung für '{self.patch_id}'")
        try:
            resp = self.device.send_command("MEAS,1")
            print(f"[MeasurementWorker.run] MEAS Antwort: '{resp}'")
            m = re.match(r"^OK00(?:,(\d+))?", resp)
            if m:
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
    """Worker-Thread für automatische Messtafelmessung mit Matrix-Schema."""
    measurement_done = pyqtSignal(str, tuple, list)
    measurement_error = pyqtSignal(str)
    progress_update = pyqtSignal(int, int, str)
    kasten_status_update = pyqtSignal(int, int, str)
    finished = pyqtSignal()

    def __init__(self, device, motor_controller, parent=None):
        print("[MesstafelWorker.__init__] Erstelle Messtafel-Worker")
        super().__init__(parent)
        self.device = device
        self.motor = motor_controller
        self.is_running = True

    def run(self):
        print("[MesstafelWorker.run] Starte Messtafelmessung")
        
        if self.motor.schritte_pro_feld_x == 0 or self.motor.schritte_pro_feld_y == 0:
            self.measurement_error.emit("Fehler: Bitte zuerst Abstände berechnen!")
            self.finished.emit()
            return
        
        anzahl_cols = self.motor.anzahl_messfelder_x
        anzahl_rows = self.motor.anzahl_messfelder_y
        total_messungen = anzahl_cols * anzahl_rows
        
        print(f"[MesstafelWorker.run] Matrix: {anzahl_rows} Zeilen × {anzahl_cols} Spalten = {total_messungen} Messpunkte")
        
        self.progress_update.emit(0, total_messungen, "Fahre zu Startposition [0,0]...")
        ol_x = self.motor.begrenzung_oben_links["x"]
        ol_y = self.motor.begrenzung_oben_links["y"]
        delta_x = ol_x - self.motor.aktuelle_x_position
        delta_y = ol_y - self.motor.aktuelle_y_position
        
        print(f"[MesstafelWorker.run] Fahre zu [0,0]: Delta X={delta_x}, Delta Y={delta_y}")
        if delta_x != 0:
            self.motor.motor_schritte_thread(delta_x, 'x')
            time.sleep(abs(delta_x) / 500 + 1)
        if delta_y != 0:
            self.motor.motor_schritte_thread(delta_y, 'y')
            time.sleep(abs(delta_y) / 500 + 1)
        
        offset_x = self.motor.schritte_pro_feld_x // 2
        offset_y = self.motor.schritte_pro_feld_y // 2
        
        print(f"[MesstafelWorker.run] Offset zur Kastenmitte: X={offset_x}, Y={offset_y}")
        self.progress_update.emit(0, total_messungen, "Positioniere auf [0,0] Mitte...")
        self.motor.motor_schritte_thread(offset_x, 'x')
        time.sleep(1)
        self.motor.motor_schritte_thread(offset_y, 'y')
        time.sleep(1)
        
        messung_nr = 0
        
        for row in range(anzahl_rows):
            if not self.is_running:
                break
            
            if row % 2 == 0:
                col_range = range(anzahl_cols)
                print(f"[MesstafelWorker.run] Zeile {row}: Links → Rechts")
            else:
                col_range = range(anzahl_cols - 1, -1, -1)
                print(f"[MesstafelWorker.run] Zeile {row}: Rechts ← Links")
            
            for col in col_range:
                if not self.is_running:
                    break
                
                messung_nr += 1
                patch_id = f"M[{row},{col}]"
                
                self.kasten_status_update.emit(row, col, 'measuring')
                
                self.progress_update.emit(messung_nr, total_messungen, 
                                         f"Messe {patch_id} ({messung_nr}/{total_messungen})")
                print(f"[MesstafelWorker.run] Starte Messung {messung_nr}/{total_messungen}: {patch_id}")
                
                try:
                    resp = self.device.send_command("MEAS,1")
                    m = re.match(r"^OK00(?:,(\d+))?", resp)
                    if m:
                        t = int(m.group(1)) if m.group(1) else 2
                        time.sleep(t + 2.0)

                        max_retries = 3
                        retry_success = False
                        
                        for attempt in range(max_retries):
                            spec = self.device.read_spectral_data()
                            if spec:
                                xyY = self.device.read_xyY()
                                if xyY:
                                    self.measurement_done.emit(patch_id, xyY, spec)
                                    self.kasten_status_update.emit(row, col, 'done')
                                    print(f"[MesstafelWorker.run] {patch_id} erfolgreich gemessen nach {attempt+1} Versuch(en)")
                                    retry_success = True
                                    break
                            
                            if attempt < max_retries - 1:
                                time.sleep(0.5)
                        
                        if not retry_success:
                            self.measurement_error.emit(f"Datenfehler bei {patch_id}")
                            self.kasten_status_update.emit(row, col, 'error')
                    else:
                        self.measurement_error.emit(f"Messfehler bei {patch_id}")
                        self.kasten_status_update.emit(row, col, 'error')
                except Exception as e:
                    self.measurement_error.emit(f"Exception bei {patch_id}: {str(e)}")
                    self.kasten_status_update.emit(row, col, 'error')
                
                if not (row == anzahl_rows - 1 and col == col_range[-1]):
                    if row % 2 == 0:
                        if col < anzahl_cols - 1:
                            self.motor.motor_schritte_thread(self.motor.schritte_pro_feld_x, 'x')
                            time.sleep(1)
                    else:
                        if col > 0:
                            self.motor.motor_schritte_thread(-self.motor.schritte_pro_feld_x, 'x')
                            time.sleep(1)
                    
                    if col == col_range[-1] and row < anzahl_rows - 1:
                        self.motor.motor_schritte_thread(self.motor.schritte_pro_feld_y, 'y')
                        time.sleep(1)
        
        print(f"[MesstafelWorker.run] Messtafelmessung abgeschlossen: {messung_nr} Messungen")
        self.finished.emit()

    def stop(self):
        print("[MesstafelWorker.stop] Stoppe Messtafelmessung")
        self.is_running = False


class CS2000GUI(QWidget):
    """CS-2000 Mess-GUI - Mit Matrix-Schema."""
    
    def __init__(self, motor_controller=None):
        print("[CS2000GUI.__init__] Initialisiere CS-2000 Mess-GUI")
        super().__init__()
        
        self.motor_controller = motor_controller
        self.messtafel_worker = None
        
        font = QFont()
        font.setPointSize(12)
        self.setFont(font)
        
        main_layout = QVBoxLayout(self)
        
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

        # COM-Port Auswahl inkl. MOCK
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
        
        info_label = QLabel("Messtafelmessung - Matrix-Schema [Zeile, Spalte]")
        info_label.setFont(font)
        info_label.setStyleSheet("color: #555; font-style: italic; padding: 5px;")
        lyt.addWidget(info_label)
        
        btns = QVBoxLayout()
        
        self.btn_connect = QPushButton("Verbindung aufbauen")
        self.btn_connect.setFont(font)
        self.btn_connect.setMinimumHeight(50)
        self.btn_connect.setStyleSheet("background-color: #81c784; font-weight: bold;")
        self.btn_connect.clicked.connect(self.connect_device)
        btns.addWidget(self.btn_connect)
        
        self.btn_manual = QPushButton("Einzelmessung starten")
        self.btn_manual.setFont(font)
        self.btn_manual.setMinimumHeight(50)
        self.btn_manual.setStyleSheet("background-color: #64b5f6; font-weight: bold;")
        self.btn_manual.clicked.connect(self.manual_measurement)
        btns.addWidget(self.btn_manual)
        
        self.btn_messtafelmessung = QPushButton("Messtafelmessung starten")
        self.btn_messtafelmessung.setFont(font)
        self.btn_messtafelmessung.setMinimumHeight(50)
        self.btn_messtafelmessung.setStyleSheet("background-color: #ffb74d; font-weight: bold;")
        self.btn_messtafelmessung.clicked.connect(self.messtafelmessung)
        btns.addWidget(self.btn_messtafelmessung)
        
        self.btn_csv = QPushButton("CSV speichern")
        self.btn_csv.setFont(font)
        self.btn_csv.setMinimumHeight(50)
        self.btn_csv.setStyleSheet("background-color: #ba68c8; font-weight: bold;")
        self.btn_csv.clicked.connect(self.save_csv)
        btns.addWidget(self.btn_csv)
        
        lyt.addLayout(btns)

        viz_label = QLabel("Messtafel Fortschritt (Matrix-Schema):")
        viz_label.setFont(font)
        viz_label.setStyleSheet("font-weight: bold; padding: 5px;")
        lyt.addWidget(viz_label)
        
        self.messtafel_viz = MesstafelVisualization()
        lyt.addWidget(self.messtafel_viz)

        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setFont(font)
        self.output.setMaximumHeight(200)
        lyt.addWidget(self.output)
        
        self.spectrum_plot = SpectrumPlot(self)
        lyt.addWidget(self.spectrum_plot)
        splitter.addWidget(left)

        self.log_window = LoggingWindow()
        splitter.addWidget(self.log_window)

        main_layout.addWidget(splitter)

        self.device = None
        self.results = []
        self.current_worker = None
        self.measurement_counter = 0

        self.refresh_ports()
        print("[CS2000GUI.__init__] CS-2000 Mess-GUI erfolgreich initialisiert")

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
        else:
            self.log_window.log(f"Verbindungsfehler: {resp}", level="ERROR")
            self.output.append("✗ Verbindungsfehler!")

    def manual_measurement(self):
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
        print("[CS2000GUI.messtafelmessung] Button 'Messtafelmessung' gedrückt")
        
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
            
            self.messtafel_worker = MesstafelWorker(self.device, self.motor_controller)
            self.messtafel_worker.measurement_done.connect(self.on_measurement_done)
            self.messtafel_worker.measurement_error.connect(self.on_measurement_error)
            self.messtafel_worker.progress_update.connect(self.on_progress_update)
            self.messtafel_worker.kasten_status_update.connect(self.on_kasten_status_update)
            self.messtafel_worker.finished.connect(self.on_messtafelmessung_finished)
            self.messtafel_worker.start()

    def on_progress_update(self, current, total, status):
        self.log_window.log(f"[{current}/{total}] {status}")

    def on_kasten_status_update(self, row, col, status):
        """Update Kasten-Status in Visualisierung mit Matrix-Koordinaten."""
        self.messtafel_viz.set_kasten_status(row, col, status)

    def on_messtafelmessung_finished(self):
        self.output.append(f"\n{'='*50}")
        self.output.append(f"✅ Messtafelmessung abgeschlossen!")
        self.output.append(f"   Gesamt: {len(self.results)} Messungen")
        self.output.append(f"{'='*50}\n")
        self.log_window.log("Messtafelmessung abgeschlossen")
        
        self.btn_messtafelmessung.setEnabled(True)
        self.btn_manual.setEnabled(True)

    def on_measurement_done(self, patch_id, xyY, spec):
        print(f"[CS2000GUI.on_measurement_done] Messung '{patch_id}' abgeschlossen")
        self.spectrum_plot.update_spectrum(spec)
        x, y, Y = xyY
        
        self.results.append((patch_id, 0, 0, 0, x, y, Y, *spec))
        
        self.output.append(f"✓ {patch_id}: x={x:.4f}, y={y:.4f}, Y={Y:.2f} cd/m²")
        self.log_window.log(f"Messung {patch_id} abgeschlossen: x={x:.4f}, y={y:.4f}, Y={Y:.2f}")

    def on_measurement_error(self, error_msg):
        print(f"[CS2000GUI.on_measurement_error] Fehler: {error_msg}")
        self.log_window.log(error_msg, level="ERROR")
        self.output.append(f"✗ Fehler: {error_msg}")

    def on_worker_finished(self):
        """Wird aufgerufen wenn Worker-Thread beendet ist."""
        print("[CS2000GUI.on_worker_finished] Worker-Thread beendet")
        self.log_window.log("✓ Messung abgeschlossen")

    def save_csv(self):
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
                    hdr = ["ID", "L", "A", "B", "x", "y", "Y"] + [f"S{380+i}" for i in range(401)]
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
