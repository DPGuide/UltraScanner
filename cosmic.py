import sys
import subprocess
import numpy as np
import sounddevice as sd
import winsound
import os
from PyQt5 import QtWidgets, QtCore

class UltraScanner(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Crystal Control Center (3D Peilsender)")
        self.resize(500, 650)
        
        self.fs = 44100
        self.buffer_size = 2048
        
        self.ffmpeg_process = None
        self.is_scanning = False
        
        self.hit_counter = 0
        self.last_found_idx = -1
        
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

        freq_layout = QtWidgets.QHBoxLayout()
        freq_layout.addWidget(QtWidgets.QLabel("🎯 Zielfrequenz (Hz):"))
        self.freq_spinbox = QtWidgets.QSpinBox()
        self.freq_spinbox.setRange(20, 22000)
        self.freq_spinbox.setValue(1000)
        self.freq_spinbox.setSingleStep(100)
        freq_layout.addWidget(self.freq_spinbox)
        layout.addLayout(freq_layout)

        tol_layout = QtWidgets.QHBoxLayout()
        tol_layout.addWidget(QtWidgets.QLabel("📏 Bullseye-Toleranz (+/- Hz):"))
        self.tol_spinbox = QtWidgets.QSpinBox()
        self.tol_spinbox.setRange(1, 2000)
        self.tol_spinbox.setValue(300)
        self.tol_spinbox.setSingleStep(10)
        tol_layout.addWidget(self.tol_spinbox)
        layout.addLayout(tol_layout)

        thresh_layout = QtWidgets.QHBoxLayout()
        thresh_layout.addWidget(QtWidgets.QLabel("🎚️ Empfindlichkeit (SNR):"))
        self.thresh_spinbox = QtWidgets.QDoubleSpinBox()
        self.thresh_spinbox.setRange(1.5, 100.0)
        self.thresh_spinbox.setValue(5.0)
        self.thresh_spinbox.setSingleStep(0.5)
        thresh_layout.addWidget(self.thresh_spinbox)
        layout.addLayout(thresh_layout)

        self.scan_btn = QtWidgets.QPushButton("🔍 3D AUTO-SUCHLAUF STARTEN")
        self.scan_btn.clicked.connect(self.toggle_scan)
        layout.addWidget(self.scan_btn)

        self.status_label = QtWidgets.QLabel("Status: Bereit (Stereo-Analyse)")
        self.status_label.setStyleSheet("font-size: 14px; color: #D4AF37;")
        layout.addWidget(self.status_label)

        self.log_list = QtWidgets.QListWidget()
        layout.addWidget(QtWidgets.QLabel("📜 Kristall-Logbuch (Gold=Oben, Grün=Unten):"))
        layout.addWidget(self.log_list)

    def start_ffmpeg_monitor(self):
        # 1. Den absoluten Pfad zur .exe oder zum Skript herausfinden
        if getattr(sys, 'frozen', False):
            # Wenn es als .exe läuft
            base_dir = os.path.dirname(sys.executable)
        else:
            # Wenn es als normales Python-Skript läuft
            base_dir = os.path.dirname(os.path.abspath(__file__))

        # 2. Die exakten Pfade zu FFmpeg und FFplay bauen
        ffmpeg_path = os.path.join(base_dir, "ffmpeg.exe")
        ffplay_path = os.path.join(base_dir, "ffplay.exe")

        # 3. Den Befehl mit den echten Pfaden (in Anführungszeichen, falls der Ordner Leerzeichen hat) zusammenbauen
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
        
        # 4. Der PyInstaller-Fix: Wir leiten die internen Pipes sauber um und unterdrücken Konsolen-Popups
        self.ffmpeg_process = subprocess.Popen(
            cmd, 
            shell=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW # Zwingt Windows, kein unsichtbares Fenster zu suchen
        )
        self.status_label.setText("Status: 3D-Monitor läuft (Portable Mode)")

    def toggle_scan(self):
        self.is_scanning = not self.is_scanning
        if self.is_scanning:
            self.scan_btn.setText("🛑 SUCHE STOPPEN")
            self.status_label.setText("Status: Lausche auf beiden Piezos...")
            self.hit_counter = 0
            
            # WICHTIG: channels=2 zwingt die Soundkarte, beide Piezos getrennt zu lesen!
            self.stream = sd.InputStream(callback=self.audio_callback, channels=2, 
                                        samplerate=self.fs, blocksize=self.buffer_size)
            self.stream.start()
        else:
            self.scan_btn.setText("🔍 3D AUTO-SUCHLAUF STARTEN")
            if hasattr(self, 'stream'):
                self.stream.stop()

    def audio_callback(self, indata, frames, time, status):
        if not self.is_scanning: return
        if indata.shape[1] < 2: return # Sicherheitscheck, falls Windows auf Mono zwingt
        
        # Beide Piezos mathematisch trennen
        left_ch = indata[:, 0]  # Normalerweise "Links" -> Dein Piezo Oben
        right_ch = indata[:, 1] # Normalerweise "Rechts" -> Dein Piezo Unten
        
        # FFT für beide getrennt berechnen
        fft_left = np.abs(np.fft.rfft(left_ch))[50:-50]
        fft_right = np.abs(np.fft.rfft(right_ch))[50:-50]
        
        if len(fft_left) > 0:
            # Spitzenwerte beider Piezos ermitteln
            peak_l = np.max(fft_left)
            peak_r = np.max(fft_right)
            
            # Wir nutzen das stärkere Signal für die SNR-Berechnung
            max_peak = max(peak_l, peak_r)
            combined_fft = (fft_left + fft_right) / 2
            avg_noise = np.mean(combined_fft)
            peak_idx = np.argmax(combined_fft)
            
            # GUI Werte holen
            current_threshold = self.thresh_spinbox.value()
            target_freq = self.freq_spinbox.value()
            target_tolerance = self.tol_spinbox.value()
            
            snr = max_peak / (avg_noise + 1e-9)
            current_freq = ((peak_idx + 50) * self.fs) / self.buffer_size

            # Alarm-Logik
            if snr > current_threshold:
                if abs(peak_idx - self.last_found_idx) < 5:
                    self.hit_counter += 1
                else:
                    self.hit_counter = 1
                
                self.last_found_idx = peak_idx
                
                if self.hit_counter >= 3:
                    winsound.Beep(1000, 200)
                    timestamp = QtCore.QDateTime.currentDateTime().toString("hh:mm:ss")
                    
                    # 3D PEILUNG: Welcher Piezo empfängt mehr Energie?
                    # Wir prüfen, ob einer mindestens 20% stärker ist als der andere
                    if peak_l > peak_r * 1.2:
                        direction = "⬆️ OBEN dominiert"
                    elif peak_r > peak_l * 1.2:
                        direction = "⬇️ UNTEN dominiert"
                    else:
                        direction = "⚖️ ZENTRUM (Symmetrisch)"
                    
                    is_near_target = abs(current_freq - target_freq) <= target_tolerance
                    prefix = "🎯 ZIEL" if is_near_target else "⚡ FUND"
                    
                    # Log-Ausgabe mit Peilrichtung
                    log_text = f"[{timestamp}] {prefix}: {current_freq:.0f} Hz | {direction} (SNR: {snr:.1f})"
                    self.log_list.addItem(log_text)
                    self.status_label.setText(f"Gelockt auf: {current_freq:.0f} Hz ({direction})")
                    
                    self.freq_spinbox.setValue(int(current_freq))
                    
                    self.is_scanning = False
                    self.hit_counter = 0
            else:
                self.hit_counter = 0

    def closeEvent(self, event):
        if self.ffmpeg_process:
            self.ffmpeg_process.terminate()
        event.accept()

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = UltraScanner()
    window.show()
    sys.exit(app.exec_())