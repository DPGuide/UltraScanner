import sys
import os
import subprocess
import numpy as np
import sounddevice as sd
import winsound
import time
from PyQt5 import QtWidgets, QtCore

MORSE_CODE_DICT = {
    'A': '.-', 'B': '-...', 'C': '-.-.', 'D': '-..', 'E': '.', 'F': '..-.', 
    'G': '--.', 'H': '....', 'I': '..', 'J': '.---', 'K': '-.-', 'L': '.-..', 
    'M': '--', 'N': '-.', 'O': '---', 'P': '.--.', 'Q': '--.-', 'R': '.-.', 
    'S': '...', 'T': '-', 'U': '..-', 'V': '...-', 'W': '.--', 'X': '-..-', 
    'Y': '-.--', 'Z': '--..', '1': '.----', '2': '..---', '3': '...--', 
    '4': '....-', '5': '.....', '6': '-....', '7': '--...', '8': '---..', 
    '9': '----.', '0': '-----', ' ': '/'
}
REVERSE_MORSE = {value: key for key, value in MORSE_CODE_DICT.items()}

class UltraScanner(QtWidgets.QMainWindow):
    # ==========================================
    # NEU: Das "Funkgerät" zwischen Sound und GUI
    # ==========================================
    signal_new_log = QtCore.pyqtSignal(str)
    signal_new_decode = QtCore.pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Crystal Control Center (Dual-Core E.T. Edition)")
        self.resize(550, 800)
        
        self.fs = 44100
        self.buffer_size = 2048
        
        self.ffmpeg_process = None
        self.is_scanning = False
        
        self.hit_counter = 0
        self.last_found_idx = -1
        self.signal_blocks = 0
        self.silence_blocks = 0
        self.current_symbol = ""
        self.decoded_message = ""
        
        # Signale an die Methoden koppeln
        self.signal_new_log.connect(self.gui_add_log)
        self.signal_new_decode.connect(self.gui_update_decode)
        
        self.init_ui()
        
    def init_ui(self):
        layout = QtWidgets.QVBoxLayout()
        widget = QtWidgets.QWidget()
        widget.setLayout(layout)
        self.setCentralWidget(widget)

        self.mon_btn = QtWidgets.QPushButton("🚀 FFmpeg 3D-MONITOR STARTEN")
        self.mon_btn.setStyleSheet("background-color: #D4AF37; color: black; font-weight: bold; padding: 10px;")
        self.mon_btn.clicked.connect(self.start_ffmpeg_monitor)
        layout.addWidget(self.mon_btn)

        tx_group = QtWidgets.QGroupBox("📡 Sende-Zentrale (TX)")
        tx_layout = QtWidgets.QVBoxLayout()
        input_layout = QtWidgets.QHBoxLayout()
        self.msg_input = QtWidgets.QLineEdit()
        self.msg_input.setText("E T NACH HAUS TELEFONIEREN") 
        input_layout.addWidget(self.msg_input)
        self.send_btn = QtWidgets.QPushButton("MORSE SENDEN")
        self.send_btn.setStyleSheet("background-color: #00FF00; color: black; font-weight: bold;")
        self.send_btn.clicked.connect(self.transmit_message)
        input_layout.addWidget(self.send_btn)
        tx_layout.addLayout(input_layout)
        tx_group.setLayout(tx_layout)
        layout.addWidget(tx_group)

        rx_group = QtWidgets.QGroupBox("🔍 Empfänger-Radar (RX)")
        rx_layout = QtWidgets.QVBoxLayout()
        
        freq_layout = QtWidgets.QHBoxLayout()
        freq_layout.addWidget(QtWidgets.QLabel("🎯 Zielfrequenz (Hz):"))
        self.freq_spinbox = QtWidgets.QSpinBox()
        self.freq_spinbox.setRange(20, 22000)
        self.freq_spinbox.setValue(1000) 
        self.freq_spinbox.setSingleStep(100)
        freq_layout.addWidget(self.freq_spinbox)
        rx_layout.addLayout(freq_layout)

        tol_layout = QtWidgets.QHBoxLayout()
        tol_layout.addWidget(QtWidgets.QLabel("📏 Decoder-Toleranz (+/- Hz):"))
        self.tol_spinbox = QtWidgets.QSpinBox()
        self.tol_spinbox.setRange(1, 1000)
        self.tol_spinbox.setValue(100)
        self.tol_spinbox.setSingleStep(10)
        tol_layout.addWidget(self.tol_spinbox)
        rx_layout.addLayout(tol_layout)

        thresh_layout = QtWidgets.QHBoxLayout()
        thresh_layout.addWidget(QtWidgets.QLabel("🎚️ Squelch (SNR):"))
        self.thresh_spinbox = QtWidgets.QDoubleSpinBox()
        self.thresh_spinbox.setRange(1.5, 100.0)
        self.thresh_spinbox.setValue(8.0)
        thresh_layout.addWidget(self.thresh_spinbox)
        rx_layout.addLayout(thresh_layout)
        rx_group.setLayout(rx_layout)
        layout.addWidget(rx_group)

        self.scan_btn = QtWidgets.QPushButton("🌐 DUAL-SCANNER & DECODER STARTEN")
        self.scan_btn.setStyleSheet("padding: 10px; font-weight: bold;")
        self.scan_btn.clicked.connect(self.toggle_scan)
        layout.addWidget(self.scan_btn)

        self.status_label = QtWidgets.QLabel("Status: Bereit")
        self.status_label.setStyleSheet("font-size: 14px; color: #D4AF37;")
        layout.addWidget(self.status_label)

        self.decoded_label = QtWidgets.QLabel("👽 E.T. funkt: ")
        self.decoded_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #00FF00; background: black; padding: 5px;")
        layout.addWidget(self.decoded_label)

        self.log_list = QtWidgets.QListWidget()
        layout.addWidget(QtWidgets.QLabel("📜 Kristall-Radar (Alle Signale):"))
        layout.addWidget(self.log_list)

    # ==========================================
    # NEU: Sichere GUI-Update Methoden
    # ==========================================
    @QtCore.pyqtSlot(str)
    def gui_add_log(self, text):
        self.log_list.addItem(text)
        self.log_list.scrollToBottom()

    @QtCore.pyqtSlot(str)
    def gui_update_decode(self, text):
        self.decoded_label.setText(text)

    def start_ffmpeg_monitor(self):
        if getattr(sys, 'frozen', False):
            base_dir = os.path.dirname(sys.executable)
        else:
            base_dir = os.path.dirname(os.path.abspath(__file__))

        ffmpeg_path = os.path.join(base_dir, "ffmpeg.exe")
        ffplay_path = os.path.join(base_dir, "ffplay.exe")

        cmd = (
            f'"{ffmpeg_path}" -loglevel error -f dshow -i audio="Mikrofon (High Definition Audio Device)" '
            '-filter_complex "[0:a]highpass=f=20,asplit=4[a1][a2][a3][a4];'
            '[a1]showspectrum=s=809x500:mode=combined:color=fire:slide=scroll:scale=log[v1];'
            '[a2]showfreqs=s=809x500:mode=bar:colors=0xD4AF37|0x00FF00:ascale=log[v2];'
            '[a3]showwaves=s=809x500:mode=line:colors=0xD4AF37|0x00FF00[v3];'
            '[a4]avectorscope=s=809x500[v4];'
            '[v1][v2][v3][v4]xstack=inputs=4:layout=0_0|w0_0|0_h0|w0_h0,format=yuv420p[out]" '
            f'-map "[out]" -f nut - | "{ffplay_path}" -f nut -i - -noborder'
        )
        self.ffmpeg_process = subprocess.Popen(
            cmd, shell=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        self.status_label.setText("Status: 3D-Monitor läuft (Dual-Modus fähig)")

    def transmit_message(self):
        text = self.msg_input.text().upper()
        if not text: return
        
        freq = self.freq_spinbox.value()
        self.status_label.setText(f"SENDEN: {text} auf {freq} Hz...")
        
        dot_time = 100 
        dash_time = 300 
        
        for char in text:
            QtWidgets.QApplication.processEvents() 
            if char in MORSE_CODE_DICT:
                code = MORSE_CODE_DICT[char]
                for symbol in code:
                    if symbol == '.': winsound.Beep(freq, dot_time)
                    elif symbol == '-': winsound.Beep(freq, dash_time)
                    time.sleep(dot_time / 1000.0)
                time.sleep(dash_time / 1000.0)
            elif char == ' ':
                time.sleep(700 / 1000.0)
                
        self.status_label.setText("Status: Senden beendet.")

    def toggle_scan(self):
        self.is_scanning = not self.is_scanning
        if self.is_scanning:
            self.scan_btn.setText("🛑 DUAL-SCANNER STOPPEN")
            self.status_label.setText("Status: Radar sucht & Decoder lauscht...")
            self.decoded_message = ""
            self.decoded_label.setText("👽 E.T. funkt: ")
            self.hit_counter = 0
            self.stream = sd.InputStream(callback=self.audio_callback, channels=2, 
                                        samplerate=self.fs, blocksize=self.buffer_size)
            self.stream.start()
        else:
            self.scan_btn.setText("🌐 DUAL-SCANNER & DECODER STARTEN")
            if hasattr(self, 'stream'):
                self.stream.stop()

    def audio_callback(self, indata, frames, time_info, status):
        if not self.is_scanning or indata.shape[1] < 2: return 
        
        left_ch, right_ch = indata[:, 0], indata[:, 1]
        fft_left = np.abs(np.fft.rfft(left_ch))[50:-50]
        fft_right = np.abs(np.fft.rfft(right_ch))[50:-50]
        
        if len(fft_left) == 0: return

        peak_l, peak_r = np.max(fft_left), np.max(fft_right)
        max_peak = max(peak_l, peak_r)
        
        combined_fft = (fft_left + fft_right) / 2
        avg_noise = np.mean(combined_fft)
        peak_idx = np.argmax(combined_fft)
        
        snr = max_peak / (avg_noise + 1e-9)
        current_freq = ((peak_idx + 50) * self.fs) / self.buffer_size

        current_threshold = self.thresh_spinbox.value()
        target_freq = self.freq_spinbox.value()
        tolerance = self.tol_spinbox.value()
        is_signal_present = snr > current_threshold
        is_near_target = abs(current_freq - target_freq) <= tolerance

        timestamp = QtCore.QDateTime.currentDateTime().toString("hh:mm:ss")

        # ==========================================
        # ENGINE 1: DAS BREITBAND-RADAR
        # ==========================================
        if is_signal_present:
            if abs(peak_idx - self.last_found_idx) < 5:
                self.hit_counter += 1
            else:
                self.hit_counter = 1
            self.last_found_idx = peak_idx
            
            if self.hit_counter == 3:
                if peak_l > peak_r * 1.2: direction = "⬆️ OBEN"
                elif peak_r > peak_l * 1.2: direction = "⬇️ UNTEN"
                else: direction = "⚖️ ZENTRUM"
                
                prefix = "🎯 ZIEL" if is_near_target else "⚡ FUND"
                log_text = f"[{timestamp}] {prefix}: {current_freq:.0f} Hz | {direction} (SNR: {snr:.1f})"
                
                # Senden des sauberen Signals (statt direktem, fehleranfälligem Zugriff)
                self.signal_new_log.emit(log_text)
        else:
            self.hit_counter = 0

        # ==========================================
        # ENGINE 2: DER E.T. MORSE DECODER
        # ==========================================
        if is_signal_present and is_near_target:
            self.signal_blocks += 1
            self.silence_blocks = 0
        else:
            if self.signal_blocks > 0:
                if 1 <= self.signal_blocks <= 4:
                    self.current_symbol += "."
                elif self.signal_blocks > 4:
                    self.current_symbol += "-"
                self.signal_blocks = 0
            
            self.silence_blocks += 1
            
            if self.silence_blocks > 8 and self.current_symbol != "":
                letter = REVERSE_MORSE.get(self.current_symbol, "?")
                self.decoded_message += letter
                
                # Senden des sauberen Signals für die GUI
                self.signal_new_decode.emit(f"👽 E.T. funkt: {self.decoded_message}")
                self.current_symbol = ""

    def closeEvent(self, event):
        if self.ffmpeg_process:
            self.ffmpeg_process.terminate()
        event.accept()

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = UltraScanner()
    window.show()
    sys.exit(app.exec_())