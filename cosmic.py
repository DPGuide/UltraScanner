import sys
import os
import subprocess
import numpy as np
import sounddevice as sd
import winsound
import time
from PyQt5 import QtWidgets, QtCore

# Das offizielle Morse-Alphabet
MORSE_CODE_DICT = {
    'A': '.-', 'B': '-...', 'C': '-.-.', 'D': '-..', 'E': '.', 'F': '..-.', 
    'G': '--.', 'H': '....', 'I': '..', 'J': '.---', 'K': '-.-', 'L': '.-..', 
    'M': '--', 'N': '-.', 'O': '---', 'P': '.--.', 'Q': '--.-', 'R': '.-.', 
    'S': '...', 'T': '-', 'U': '..-', 'V': '...-', 'W': '.--', 'X': '-..-', 
    'Y': '-.--', 'Z': '--..', '1': '.----', '2': '..---', '3': '...--', 
    '4': '....-', '5': '.....', '6': '-....', '7': '--...', '8': '---..', 
    '9': '----.', '0': '-----', ' ': '/'
}
# Umgekehrte Liste für den Empfänger (Code -> Buchstabe)
REVERSE_MORSE = {value: key for key, value in MORSE_CODE_DICT.items()}

class UltraScanner(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Crystal Control Center (Morse-Modem Edition)")
        self.resize(500, 750)
        
        self.fs = 44100
        self.buffer_size = 2048
        
        self.ffmpeg_process = None
        self.is_scanning = False
        
        # Morse-Decoder Variablen
        self.signal_blocks = 0
        self.silence_blocks = 0
        self.current_symbol = ""
        self.decoded_message = ""
        
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

        # --- NEU: Sende-Zentrale (TX) ---
        tx_group = QtWidgets.QGroupBox("📡 Sende-Zentrale (TX)")
        tx_layout = QtWidgets.QVBoxLayout()
        
        input_layout = QtWidgets.QHBoxLayout()
        self.msg_input = QtWidgets.QLineEdit()
        self.msg_input.setPlaceholderText("TEXT EINGEBEN (z.B. HALLO)")
        input_layout.addWidget(self.msg_input)
        
        self.send_btn = QtWidgets.QPushButton("MORSE SENDEN")
        self.send_btn.setStyleSheet("background-color: #00FF00; color: black; font-weight: bold;")
        self.send_btn.clicked.connect(self.transmit_message)
        input_layout.addWidget(self.send_btn)
        tx_layout.addLayout(input_layout)
        tx_group.setLayout(tx_layout)
        layout.addWidget(tx_group)

        # --- Empfänger-Einstellungen (RX) ---
        freq_layout = QtWidgets.QHBoxLayout()
        freq_layout.addWidget(QtWidgets.QLabel("🎯 Zielfrequenz (Hz):"))
        self.freq_spinbox = QtWidgets.QSpinBox()
        self.freq_spinbox.setRange(20, 22000)
        self.freq_spinbox.setValue(1000) # 1000 Hz ist Standard für Morse-Töne
        self.freq_spinbox.setSingleStep(100)
        freq_layout.addWidget(self.freq_spinbox)
        layout.addLayout(freq_layout)

        thresh_layout = QtWidgets.QHBoxLayout()
        thresh_layout.addWidget(QtWidgets.QLabel("🎚️ Squelch (SNR):"))
        self.thresh_spinbox = QtWidgets.QDoubleSpinBox()
        self.thresh_spinbox.setRange(1.5, 100.0)
        self.thresh_spinbox.setValue(8.0)
        thresh_layout.addWidget(self.thresh_spinbox)
        layout.addLayout(thresh_layout)

        self.scan_btn = QtWidgets.QPushButton("🔍 MORSE-DECODER STARTEN (RX)")
        self.scan_btn.clicked.connect(self.toggle_scan)
        layout.addWidget(self.scan_btn)

        self.status_label = QtWidgets.QLabel("Status: Bereit")
        self.status_label.setStyleSheet("font-size: 14px; color: #D4AF37;")
        layout.addWidget(self.status_label)

        # --- NEU: Live-Text Decoder ---
        self.decoded_label = QtWidgets.QLabel("Eingehende Nachricht: ")
        self.decoded_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #00FF00; background: black; padding: 5px;")
        layout.addWidget(self.decoded_label)

        self.log_list = QtWidgets.QListWidget()
        layout.addWidget(QtWidgets.QLabel("📜 Kristall-Logbuch:"))
        layout.addWidget(self.log_list)

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
        self.status_label.setText("Status: 3D-Monitor läuft")

    def transmit_message(self):
        text = self.msg_input.text().upper()
        if not text: return
        
        freq = self.freq_spinbox.value()
        self.status_label.setText(f"SENDEN: {text} auf {freq} Hz...")
        QtWidgets.QApplication.processEvents() # UI updaten
        
        # Einstellungen für die Morse-Geschwindigkeit
        dot_time = 100 # ms
        dash_time = 300 # ms
        
        for char in text:
            if char in MORSE_CODE_DICT:
                code = MORSE_CODE_DICT[char]
                for symbol in code:
                    if symbol == '.':
                        winsound.Beep(freq, dot_time)
                    elif symbol == '-':
                        winsound.Beep(freq, dash_time)
                    time.sleep(dot_time / 1000.0) # Pause zwischen Signalen
                time.sleep(dash_time / 1000.0) # Pause zwischen Buchstaben
            elif char == ' ':
                time.sleep(700 / 1000.0) # Wortpause
                
        self.status_label.setText("Status: Senden beendet.")
        self.msg_input.clear()

    def toggle_scan(self):
        self.is_scanning = not self.is_scanning
        if self.is_scanning:
            self.scan_btn.setText("🛑 DECODER STOPPEN")
            self.status_label.setText("Status: Lausche auf Morse-Code...")
            self.decoded_message = ""
            self.decoded_label.setText("Eingehende Nachricht: ")
            self.stream = sd.InputStream(callback=self.audio_callback, channels=2, 
                                        samplerate=self.fs, blocksize=self.buffer_size)
            self.stream.start()
        else:
            self.scan_btn.setText("🔍 MORSE-DECODER STARTEN (RX)")
            if hasattr(self, 'stream'):
                self.stream.stop()

    def audio_callback(self, indata, frames, time_info, status):
        if not self.is_scanning: return
        if indata.shape[1] < 2: return 
        
        mono_mix = np.mean(indata, axis=1)
        fft_data = np.abs(np.fft.rfft(mono_mix))[50:-50]
        
        if len(fft_data) > 0:
            avg_noise = np.mean(fft_data)
            max_peak = np.max(fft_data)
            peak_idx = np.argmax(fft_data)
            
            current_threshold = self.thresh_spinbox.value()
            target_freq = self.freq_spinbox.value()
            
            snr = max_peak / (avg_noise + 1e-9)
            current_freq = ((peak_idx + 50) * self.fs) / self.buffer_size

            # Prüfen, ob wir ein Signal auf unserer Frequenz (+/- 100 Hz) haben
            if snr > current_threshold and abs(current_freq - target_freq) < 100:
                self.signal_blocks += 1
                self.silence_blocks = 0
            else:
                # Signal ist weg, war vorher eins da?
                if self.signal_blocks > 0:
                    # 1 bis 3 Blöcke = Punkt (Dot)
                    if 1 <= self.signal_blocks <= 4:
                        self.current_symbol += "."
                    # Mehr als 4 Blöcke = Strich (Dash)
                    elif self.signal_blocks > 4:
                        self.current_symbol += "-"
                    
                    self.signal_blocks = 0
                
                self.silence_blocks += 1
                
                # Wenn lange genug Stille ist, Buchstabe decodieren
                if self.silence_blocks > 8 and self.current_symbol != "":
                    letter = REVERSE_MORSE.get(self.current_symbol, "?")
                    self.decoded_message += letter
                    self.decoded_label.setText(f"Eingehende Nachricht: {self.decoded_message}")
                    self.log_list.addItem(f"Decodiert: {self.current_symbol} -> {letter}")
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