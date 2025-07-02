import os
import queue
import random
import tkinter as tk
from tkinter import messagebox
from tkinter.scrolledtext import ScrolledText
from enum import Enum
from datetime import datetime
import threading
import time
import csv
import serial
import pynmea2
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# -------------------------------------------------
#   ZEWNĘTRZNE MODUŁY PROJEKTU
# -------------------------------------------------
from logger import Logger
from dsiserialport import DSISerialPort
from taskbutton import TaskButton


###############################################################################
# ENUM – stany DSI
###############################################################################
class TaskStateEnum(Enum):
    INIT_VALUE = 5
    START_ENGINE = 6
    TAXIING = 7
    TAKE_OFF = 8
    CLIMBING = 9
    DESCENDING = 10
    LANDING = 11
    TALKING = 12
    START_LEFT = 19
    COMMAND = 20
    REPLY = 30
    CORRECT = 50
    PARAMETERS = 60
    HOLDING_START = 70
    HOLDING_ENTRY = 80
    START_RIGHT = 90
    END1 = 100
    START2 = 110
    END2 = 120
    START3 = 130
    END3 = 140
    START4 = 150
    END4 = 160
    DIRECT = 200
    PARALLEL = 210
    TEARDROP = 220
    ENTRY_DIRECT_TURN1_START = 211
    ENTRY_DIRECT_TURN1_END = 212
    ENTRY_DIRECT_TURN2_START = 213
    ENTRY_DIRECT_TURN2_END = 214
    ENTRY_TEARDROP_TURN1_START = 222
    ENTRY_TEARDROP_TURN1_END = 225
    ENTRY_TEARDROP_TURN2_START = 230
    ENTRY_TEARDROP_TURN2_END = 235
    ENTRY_PARALLEL_TURN1_START = 237
    ENTRY_PARALLEL_TURN1_END = 240
    ENTRY_PARALLEL_TURN2_START = 243
    ENTRY_PARALLEL_TURN2_END = 245
    PAUSE = 249
    WATER = 250
    ALPHA = 251
    ERROR = 13


###############################################################################
# Dekorator snapshotu
###############################################################################
def snapshot_action(clicked_button_name=None):
    """Dekorator robiący snapshot stanu przycisków przed akcją."""

    def decorator(method):
        def wrapper(self, *args, **kwargs):
            old = self.snapshot_buttons_state()
            self.last_undo_function = lambda: self.restore_buttons_state(old)

            if clicked_button_name and clicked_button_name in self.all_buttons:
                btn = self.all_buttons[clicked_button_name]
                self.last_button_clicked = btn
                self.last_button_prev_text = btn.button.cget("text")
                self.last_button_prev_command = btn.callback

            return method(self, *args, **kwargs)

        return wrapper

    return decorator


###############################################################################
# GŁÓWNA KLASA APLIKACJI
###############################################################################
class Application(tk.Tk):
    """GUI symulatora + panel GPS."""


    def __init__(self):
        super().__init__()
        self.stop_event = threading.Event()

        self.log_dir = r"C:\Badania\EEG\2024 Loty\LotySymulatorHolding"
        self.logger = Logger(log_dir=self.log_dir)
        os.makedirs(self.log_dir, exist_ok=True)
        self.GNSS_CSV_FILE = os.path.join(self.log_dir, f"GNSS_Log{self.logger.get_filename_timestamp()}.csv")
        self.GNSS_FILE_ALL = os.path.join(self.log_dir, f"GNSS_All_Log{self.logger.get_filename_timestamp()}.txt")
        self.DSI_PORT = "COM20"
        self.GPS_BAUD = 9600
        self.GPS_PORT = "COM10"
        self.MAX_MAP_POINTS = 800
        self.current_dsi_message_state = TaskStateEnum.INIT_VALUE.value

        self.lons = []
        self.lats = []
        # ============ UKŁAD OKNA =============
        self.title("EEG Holding procedure – Live GPS")
        self.geometry("1200x700")

        # PanedWindow: lewo (GPS) | prawo (symulator)
        self.pw = tk.PanedWindow(self, orient=tk.HORIZONTAL, sashrelief=tk.RAISED)
        self.pw.pack(fill=tk.BOTH, expand=True)

        # --- lewa ramka: mapa + status FIX ---
        self.left_frame = tk.Frame(self.pw)
        self.pw.add(self.left_frame, minsize=350)

        # --- prawa ramka: oryginalny UI ---
        self.right_frame = tk.Frame(self.pw)
        self.pw.add(self.right_frame)

        # --------------- GPS WIDGETS ----------------
        self.fix_status = "V"

        self.position_q = queue.Queue()   #lista tupli (lat, lon)
        self.lats, self.lons = [], []

        self.fix_label = tk.Label(
            self.left_frame,
            text="GPS data await…",
            font=("Arial", 12),
        )
        self.fix_label.pack(pady=5)

        self.fig, self.ax = plt.subplots()
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.left_frame)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        # Wątek odczytu GPS + pętla odświeżania wykresu
        self.gps_thread = threading.Thread(target=self._read_gps, daemon=False)
        self.gps_thread.start()
        self.after(1000, self._update_plot)

        # --------------- ORYGINALNY UI ---------------
        self._build_original_ui()
        self.show_initial_confirmation()

        # Init DSI
        self.last_sent_state = TaskStateEnum.INIT_VALUE.value
        self.prev_sent_state = None
        self.send_signal_to_dsi(TaskStateEnum.INIT_VALUE.value)
        self.is_first_run = True
        self.holding_type_button = None
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # ======================================================================
    # ------------------------  FUNKCJE GPS  -------------------------------
    # ======================================================================

    def _read_gps(self):
        """Wątek – czytanie NMEA z GPS, log do CSV, lista pozycji."""
        try:
            with serial.Serial(self.GPS_PORT, self.GPS_BAUD, timeout=1) as ser, \
                    open(self.GNSS_CSV_FILE, "w", newline="") as csvfile, \
                    open(self.GNSS_FILE_ALL, "w") as gnss_all_file:

                writer = csv.writer(csvfile)
                writer.writerow(
                    ["timestamp", "timestampGnss", "latitude", "longitude", "gps_qual", "num_sats", "horizontal_dil", "altitude"])

                while not self.stop_event.is_set():
                    try:
                        line = ser.readline().decode("ascii", errors="replace").strip()
                        timestamp_local = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                        gnss_all_file.write(f"{timestamp_local}: {line}\n")
                        gnss_all_file.flush()

                        if line.startswith("$GPGGA"):
                            msg = pynmea2.parse(line)

                            if msg.gps_qual != 0:  # Mamy fix
                                timestamp = msg.timestamp
                                latitude = msg.latitude
                                longitude = msg.longitude
                                gps_qual = msg.gps_qual
                                num_sats = msg.num_sats
                                horizontal_dil = msg.horizontal_dil
                                altitude = msg.altitude

                                self.position_q.put((latitude, longitude))

                                timestamp_local = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                                writer.writerow(
                                    [timestamp_local, timestamp, latitude, longitude, gps_qual, num_sats, horizontal_dil, altitude])
                                csvfile.flush()

                                if msg.gps_qual != 0:  # mamy fix
                                    self.fix_status = "A"
                                else:
                                    self.fix_status = "V"

                        if line.startswith("$GPGGA"):
                            msg = pynmea2.parse(line)

                            if msg.gps_qual != 0:  # Mamy fix
                                timestamp = msg.timestamp
                                latitude = msg.latitude
                                longitude = msg.longitude
                                gps_qual = msg.gps_qual
                                num_sats = msg.num_sats
                                horizontal_dil = msg.horizontal_dil
                                altitude = msg.altitude

                                self.position_q.put((latitude, longitude))

                                timestamp_local = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                                writer.writerow(
                                    [timestamp_local, timestamp, latitude, longitude, gps_qual, num_sats,
                                     horizontal_dil, altitude])
                                csvfile.flush()

                            if msg.gps_qual != 0:  # mamy fix
                                self.fix_status = "A"
                            else:
                                self.fix_status = "V"


                    except Exception as e:
                        print("GPS parse error:", e)

        except serial.SerialException as e:
            print(f"Nie można otworzyć portu {self.GPS_PORT}: {e}")

    def _update_fix_indicator(self):
        txt = "Fix acquired" if self.fix_status == "A" else "No fix"
        col = "green" if self.fix_status == "A" else "red"
        self.fix_label.config(text=txt, fg=col)

    def _update_plot(self):
        # <-- FIX 2: odświeżamy etykietę fix w głównym wątku
        self._update_fix_indicator()

        while not self.position_q.empty():
            lat, lon = self.position_q.get()
            self.lats.append(lat)
            self.lons.append(lon)


        if (len(self.lons) > self.MAX_MAP_POINTS):
            self.lons = self.lons[-self.MAX_MAP_POINTS:]

        if (len(self.lats) > self.MAX_MAP_POINTS):
            self.lats = self.lats[-self.MAX_MAP_POINTS:]

        if(len(self.lons)>0 and len(self.lats)>0):
            self.ax.clear()
            self.ax.plot(self.lons, self.lats, marker="o", linestyle="-", color="blue")
            self.ax.set_title("GPS position (Live)")
            self.ax.set_xlabel("Longitude")
            self.ax.set_ylabel("Latitude")
            self.ax.set_aspect("equal", adjustable="datalim")
            self.ax.grid(True)
            self.canvas.draw_idle()


        self.after(1000, self._update_plot)

    # ======================================================================
    # ------------  BUDOWANIE ORYGINALNEGO UI (SKRÓCONE) -------------------
    # ======================================================================
    def _build_original_ui(self):
        rf = self.right_frame

        # --- DSI + Logger ---
        self._previous_timestamp = datetime.now()
        self.dsi = DSISerialPort(self.DSI_PORT, messagebox.showerror)
        self.dsi.initialize_serial_port()


        # Grid
        rf.grid_columnconfigure(0, weight=1)
        rf.grid_columnconfigure(1, weight=1)

        # Timer
        self.timer_label = tk.Label(rf, text="00:00:00", bg="white")
        self.timer_label.grid(row=0, column=0, columnspan=2, padx=5, pady=5)
        self.reset_timer()

        # Log display
        self.log_display = ScrolledText(rf, height=10, state="disabled")
        self.log_display.place(relx=0.5, rely=0.7, anchor="s")
        self.logger.set_log_display(self.log_display)

        # --- Przyciski (TaskButton) ---
        self.start_left_button = TaskButton(
            rf, 1, 0, "Command (s)", self.command_action, self.logger
        )
        self.direct_button = TaskButton(
            rf, 2, 0, "Direct (d)", self.direct_action, self.logger
        )
        self.direct_button.hide()
        self.parallel_button = TaskButton(
            rf, 3, 0, "Parallel (f)", self.parallel_action, self.logger
        )
        self.parallel_button.hide()
        self.teardrop_button = TaskButton(
            rf, 4, 0, "Teardrop (q)", self.teardrop_action, self.logger
        )
        self.teardrop_button.hide()

        self.start_engine_button = TaskButton(
            rf, 5, 0, "Start Engine (a)", self.start_engine_button_click, self.logger
        )

        self.start_right_button = TaskButton(
            rf, 1, 1, "Start1 (w)", self.start1_action, self.logger
        )
        self.start_right_button.hide()

        self.water_button = TaskButton(
            rf, 1, 2, "Water (e)", self.water_action, self.logger
        )
        self.pause_button = TaskButton(
            rf, 2, 2, "Pause (r)", self.pause_action, self.logger
        )
        self.alpha_button = TaskButton(
            rf, 3, 2, "Alpha (z)", self.alpha_action, self.logger
        )
        self.check_triggers_button = TaskButton(
            rf, 4, 2, "CheckTriggers (x)", self.check_triggers_action, self.logger
        )
        self.talk_button = TaskButton(
            rf, 5, 2, "Talk (c)", self.talk_action, self.logger
        )
        self.error_button = TaskButton(
            rf, 6, 2, "Error (v)", self.error_action, self.logger
        )

        # --- Słownik przycisków do snapshotu ---
        self.all_buttons = {
            "start_left_button": self.start_left_button,
            "direct_button": self.direct_button,
            "parallel_button": self.parallel_button,
            "teardrop_button": self.teardrop_button,
            "start_engine_button": self.start_engine_button,
            "start_right_button": self.start_right_button,
            "water_button": self.water_button,
            "pause_button": self.pause_button,
            "alpha_button": self.alpha_button,
            "check_triggers_button": self.check_triggers_button,
            "talk_button": self.talk_button,
            "error_button": self.error_button,
        }

        # --- Skróty klawiaturowe ---
        self.shortcut_map = {
            "a": "start_engine_button",
            "s": "start_left_button",
            "d": "direct_button",
            "f": "parallel_button",
            "q": "teardrop_button",
            "w": "start_right_button",
            "e": "water_button",
            "r": "pause_button",
            "z": "alpha_button",
            "x": "check_triggers_button",
            "c": "talk_button",
            "v": "error_button",
        }
        self.bind_all("<Key>", self.on_key_press)

        # Generated text display
        self.generated_text_display = tk.Text(
            rf, height=5, state="disabled", wrap="word"
        )
        self.generated_text_display.place(relx=0.5, rely=0.9, anchor="s")

        # Załaduj instrukcje
        self.load_instructions_from_csv(r"Exp_PilotHoldingTask\Instructions1.csv")

        # Zmienne undo
        self.last_button_clicked = None
        self.last_button_prev_text = None
        self.last_button_prev_command = None
        self.last_undo_function = None

    # ======================================================================
    # ---------------------- obsługa skrótów klawiaturowych -----------------
    # ======================================================================
    def on_key_press(self, event):
        pressed = event.char.lower()
        if pressed in self.shortcut_map:
            btn_name = self.shortcut_map[pressed]
            if btn_name in self.all_buttons and self.all_buttons[btn_name].is_visible():
                self.all_buttons[btn_name].button.invoke()

    # ======================================================================
    # ----------------------------- CSV instrukcje --------------------------
    # ======================================================================
    def load_instructions_from_csv(self, csv_filename):
        self.instructions = []
        self.current_instruction_index = 0
        try:
            with open(csv_filename, mode="r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f, delimiter=";")
                for row in reader:
                    inbound_str = row.get("Inbound [deg]", "0")
                    typ_wlotu = row.get("Typ wlotu", "D")
                    try:
                        inbound_deg = int(inbound_str)
                    except ValueError:
                        inbound_deg = 0
                    self.instructions.append(
                        {"inbound_deg": inbound_deg, "typ_wlotu": typ_wlotu}
                    )
        except FileNotFoundError:
            pass
        except Exception as e:
            print("Błąd czytania CSV:", e)

    # ======================================================================
    # ----------------- snapshot / restore przycisków -----------------------
    # ======================================================================
    def snapshot_buttons_state(self):
        state = {}
        for name, btn in self.all_buttons.items():
            state[name] = {
                "visible": btn.is_visible(),
                "text": btn.button.cget("text"),
                "callback": btn.callback,
            }
        return state

    def restore_buttons_state(self, snap):
        for name, st in snap.items():
            btn = self.all_buttons[name]
            btn.show() if st["visible"] else btn.hide()
            btn.update_button(st["text"], st["callback"])

    # =========================================================================
    #                >>>>>>  ORYGINALNE AKCJE PRZYCISKÓW  <<<<<
    # =========================================================================
    # ------------------------------------------------------------------------
    # ------------- start_engine_button_click --------------------------------
    # ------------------------------------------------------------------------
    @snapshot_action("start_engine_button")
    def start_engine_button_click(self):
        current_text = self.start_engine_button.button.cget("text")
        if "Start Engine" in current_text:
            self.send_signal_to_dsi(TaskStateEnum.START_ENGINE.value)
            self.start_engine_button.update_button(
                "Taxxing (a)", self.start_engine_button_click
            )
        elif "Taxxing" in current_text:
            self.send_signal_to_dsi(TaskStateEnum.TAXIING.value)
            self.start_engine_button.update_button(
                "Take off (a)", self.start_engine_button_click
            )
        elif "Take off" in current_text:
            self.send_signal_to_dsi(TaskStateEnum.TAKE_OFF.value)
            self.start_engine_button.update_button(
                "Climbing (a)", self.start_engine_button_click
            )
        elif "Climbing" in current_text:
            self.send_signal_to_dsi(TaskStateEnum.CLIMBING.value)
            self.start_engine_button.update_button(
                "Descending (a)", self.start_engine_button_click
            )
        elif "Descending" in current_text:
            self.send_signal_to_dsi(TaskStateEnum.DESCENDING.value)
            self.start_engine_button.update_button(
                "Landing (a)", self.start_engine_button_click
            )
        elif "Landing" in current_text:
            self.send_signal_to_dsi(TaskStateEnum.LANDING.value)
            self.start_engine_button.update_button(
                "TAXIING (a)", self.start_engine_button_click
            )
        elif "TAXIING" in current_text:
            self.start_engine_button.update_button(
                "ExperimentEnd (a)", self.start_engine_button_click
            )
        elif "ExperimentEnd" in current_text:
            self.start_engine_button.hide()

    # ------------------------------------------------------------------------
    # ------------- COMMAND / REPLY / CORRECT / PARAMETERS --------------------
    # ------------------------------------------------------------------------
    @snapshot_action("start_left_button")
    def command_action(self):
        self.send_signal_to_dsi(TaskStateEnum.COMMAND.value)
        self.generate_text()
        self.start_left_button.update_button("Reply (s)", self.reply_action)
        if not self.is_first_run:
            self.start_right_button.show()

    @snapshot_action("start_left_button")
    def reply_action(self):
        self.send_signal_to_dsi(TaskStateEnum.REPLY.value)
        self.start_left_button.update_button("Correct (s)", self.correct_action)

    @snapshot_action("start_left_button")
    def correct_action(self):
        current_state = self.get_current_dsi_state()
        self.send_signal_to_dsi(TaskStateEnum.CORRECT.value)
        time.sleep(0.01)
        self.send_signal_to_dsi(current_state)
        self.start_left_button.update_button("Parameters (s)", self.parameters_action)

        self.generated_text_display.config(state="normal")
        self.generated_text_display.delete(1.0, tk.END)
        self.generated_text_display.config(state="disabled")

    @snapshot_action("start_left_button")
    def parameters_action(self):
        current_state = self.get_current_dsi_state()
        self.send_signal_to_dsi(TaskStateEnum.PARAMETERS.value)
        time.sleep(0.01)
        self.send_signal_to_dsi(current_state)

        self.start_left_button.update_button("HoldingStart (s)", self.holding_start_action)
        self.start_left_button.hide()

        self.direct_button.show()
        self.parallel_button.update_button("Parallel (f)", self.parallel_action)
        self.parallel_button.show()
        self.teardrop_button.update_button("Teardrop (q)", self.teardrop_action)
        self.teardrop_button.show()

    # ------------------------------------------------------------------------
    # ------------------------- HOLDING START --------------------------------
    # ------------------------------------------------------------------------
    @snapshot_action("start_left_button")
    def holding_start_action(self):
        self.send_signal_to_dsi(TaskStateEnum.HOLDING_START.value)
        self.start_left_button.update_button("Command (s)", self.command_action)
        self.start_right_button.update_button("End1 (w)", self.end1_action)
        self.start_right_button.show()
        self.reset_timer()
        self.start_left_button.hide()

    # ------------------------------------------------------------------------
    # --------------------------- DIRECT -------------------------------------
    # ------------------------------------------------------------------------
    @snapshot_action("direct_button")
    def direct_action(self):
        self.direct_button.update_button("Turn1Start (d)", self.direct_turn1_start_action)
        self._hide_holding_buttons_and_set(self.direct_button)

    @snapshot_action("direct_button")
    def direct_turn1_start_action(self):
        self.send_signal_to_dsi(TaskStateEnum.ENTRY_DIRECT_TURN1_START.value)
        self.direct_button.update_button("Turn1End (d)", self.direct_turn1_end_action)

    @snapshot_action("direct_button")
    def direct_turn1_end_action(self):
        self.send_signal_to_dsi(TaskStateEnum.ENTRY_DIRECT_TURN1_END.value)
        self.direct_button.update_button("Turn2Start (d)", self.direct_turn2_start_action)

    @snapshot_action("direct_button")
    def direct_turn2_start_action(self):
        self.send_signal_to_dsi(TaskStateEnum.ENTRY_DIRECT_TURN2_START.value)
        self.direct_button.update_button("Turn2End (d)", self.direct_turn2_end_action)

    @snapshot_action("direct_button")
    def direct_turn2_end_action(self):
        self.send_signal_to_dsi(TaskStateEnum.ENTRY_DIRECT_TURN2_END.value)
        self.direct_button.update_button("Direct (d)", self.direct_action)
        self.direct_button.hide()
        self.start_left_button.show()

    # ------------------------------------------------------------------------
    # --------------------------- PARALLEL -----------------------------------
    # ------------------------------------------------------------------------
    @snapshot_action("parallel_button")
    def parallel_action(self):
        self.parallel_button.update_button("Turn1Start (f)", self.parallel_turn1_start_action)
        self._hide_holding_buttons_and_set(self.parallel_button)

    @snapshot_action("parallel_button")
    def parallel_turn1_start_action(self):
        self.send_signal_to_dsi(TaskStateEnum.ENTRY_PARALLEL_TURN1_START.value)
        self.parallel_button.update_button("Turn1End (f)", self.parallel_turn1_end_action)

    @snapshot_action("parallel_button")
    def parallel_turn1_end_action(self):
        self.send_signal_to_dsi(TaskStateEnum.ENTRY_PARALLEL_TURN1_END.value)
        self.parallel_button.update_button("Turn2Start (f)", self.parallel_turn2_start_action)

    @snapshot_action("parallel_button")
    def parallel_turn2_start_action(self):
        self.send_signal_to_dsi(TaskStateEnum.ENTRY_PARALLEL_TURN2_START.value)
        self.parallel_button.update_button("Turn2End (f)", self.parallel_turn2_end_action)

    @snapshot_action("parallel_button")
    def parallel_turn2_end_action(self):
        self.send_signal_to_dsi(TaskStateEnum.ENTRY_PARALLEL_TURN2_END.value)
        self.parallel_button.update_button("Parallel (f)", self.parallel_action)
        self.parallel_button.hide()
        self.start_left_button.show()

    # ------------------------------------------------------------------------
    # --------------------------- TEARDROP -----------------------------------
    # ------------------------------------------------------------------------
    @snapshot_action("teardrop_button")
    def teardrop_action(self):
        self.teardrop_button.update_button("Turn1Start (q)", self.teardrop_turn1_start_action)
        self._hide_holding_buttons_and_set(self.teardrop_button)

    @snapshot_action("teardrop_button")
    def teardrop_turn1_start_action(self):
        self.send_signal_to_dsi(TaskStateEnum.ENTRY_TEARDROP_TURN1_START.value)
        self.teardrop_button.update_button("Turn1End (q)", self.teardrop_turn1_end_action)

    @snapshot_action("teardrop_button")
    def teardrop_turn1_end_action(self):
        self.send_signal_to_dsi(TaskStateEnum.ENTRY_TEARDROP_TURN1_END.value)
        self.teardrop_button.update_button("Turn2Start (q)", self.teardrop_turn2_start_action)

    @snapshot_action("teardrop_button")
    def teardrop_turn2_start_action(self):
        self.send_signal_to_dsi(TaskStateEnum.ENTRY_TEARDROP_TURN2_START.value)
        self.teardrop_button.update_button("Turn2End (q)", self.teardrop_turn2_end_action)

    @snapshot_action("teardrop_button")
    def teardrop_turn2_end_action(self):
        self.send_signal_to_dsi(TaskStateEnum.ENTRY_TEARDROP_TURN2_END.value)
        self.teardrop_button.update_button("Teardrop (q)", self.teardrop_action)
        self.teardrop_button.hide()
        self.start_left_button.show()

    # ------------------------------------------------------------------------
    # --------- pomocnik: schowanie innych buttonów --------------------------
    # ------------------------------------------------------------------------
    def _hide_holding_buttons_and_set(self, btn):
        self.direct_button.hide()
        self.parallel_button.hide()
        self.teardrop_button.hide()
        self.holding_type_button = btn
        if self.is_first_run or not self.start_right_button.is_visible():
            btn.show()
        self.is_first_run = False

    # ------------------------------------------------------------------------
    # --------------------- START / END 1–4 ----------------------------------
    # ------------------------------------------------------------------------
    @snapshot_action("start_right_button")
    def start1_action(self):
        self.send_signal_to_dsi(TaskStateEnum.START_RIGHT.value)
        self.start_right_button.update_button("End1 (w)", self.end1_action)
        self.reset_timer()

    @snapshot_action("start_right_button")
    def end1_action(self):
        self.send_signal_to_dsi(TaskStateEnum.END1.value)
        self.start_right_button.update_button("Start2 (w)", self.start2_action)
        self.reset_timer()

    @snapshot_action("start_right_button")
    def start2_action(self):
        self.send_signal_to_dsi(TaskStateEnum.START2.value)
        self.start_right_button.update_button("End2 (w)", self.end2_action)
        self.reset_timer()

    @snapshot_action("start_right_button")
    def end2_action(self):
        self.send_signal_to_dsi(TaskStateEnum.END2.value)
        self.start_right_button.update_button("Start3 (w)", self.start3_action)
        self.reset_timer()

    @snapshot_action("start_right_button")
    def start3_action(self):
        self.send_signal_to_dsi(TaskStateEnum.START3.value)
        self.start_right_button.update_button("End3 (w)", self.end3_action)
        self.reset_timer()

    @snapshot_action("start_right_button")
    def end3_action(self):
        self.send_signal_to_dsi(TaskStateEnum.END3.value)
        self.start_right_button.update_button("Start4 (w)", self.start4_action, bg="red")
        self.reset_timer()
        self.start_left_button.show()
        self.start_right_button.hide()

    @snapshot_action("start_right_button")
    def start4_action(self):
        self.send_signal_to_dsi(TaskStateEnum.START4.value)
        self.start_right_button.update_button("End4 (w)", self.end4_action)
        self.reset_timer()

    @snapshot_action("start_right_button")
    def end4_action(self):
        self.send_signal_to_dsi(TaskStateEnum.END4.value)
        self.start_right_button.update_button("Start1 (w)", self.start1_action)
        if self.holding_type_button:
            self.holding_type_button.show()
        self.start_right_button.hide()
        self.reset_timer()

    # ------------------------------------------------------------------------
    # ---------------- WATER / PAUSE / ALPHA / TALK --------------------------
    # ------------------------------------------------------------------------
    @snapshot_action("water_button")
    def water_action(self):
        txt = self.water_button.button.cget("text")
        if txt == "Water (e)":
            st = self.get_current_dsi_state()
            if st not in [
                TaskStateEnum.WATER.value,
                TaskStateEnum.PAUSE.value,
                TaskStateEnum.ALPHA.value,
            ]:
                self.current_dsi_message_state = st
            self.send_signal_to_dsi(TaskStateEnum.WATER.value)
            self.water_button.update_button("Water InProgress (e)", self.water_action)
        else:
            self.send_signal_to_dsi(self.current_dsi_message_state)
            self.water_button.update_button("Water (e)", self.water_action)

    @snapshot_action("pause_button")
    def pause_action(self):
        txt = self.pause_button.button.cget("text")
        if txt == "Pause (r)":
            st = self.get_current_dsi_state()
            if st not in [
                TaskStateEnum.WATER.value,
                TaskStateEnum.PAUSE.value,
                TaskStateEnum.TALKING.value,
                TaskStateEnum.ALPHA.value,
            ]:
                self.current_dsi_message_state = st
            self.send_signal_to_dsi(TaskStateEnum.PAUSE.value)
            self.pause_button.update_button("Pause InProgress (r)", self.pause_action)
        else:
            self.send_signal_to_dsi(self.current_dsi_message_state)
            self.pause_button.update_button("Pause (r)", self.pause_action)

    @snapshot_action("alpha_button")
    def alpha_action(self):
        txt = self.alpha_button.button.cget("text")
        if txt == "Alpha (z)":
            st = self.get_current_dsi_state()
            if st not in [
                TaskStateEnum.WATER.value,
                TaskStateEnum.PAUSE.value,
                TaskStateEnum.TALKING.value,
                TaskStateEnum.ALPHA.value,
            ]:
                self.current_dsi_message_state = st
            self.send_signal_to_dsi(TaskStateEnum.ALPHA.value)
            self.alpha_button.update_button("Alpha InProgress (z)", self.alpha_action)
        else:
            self.send_signal_to_dsi(self.current_dsi_message_state)
            self.alpha_button.update_button("Alpha (z)", self.alpha_action)

    @snapshot_action("talk_button")
    def talk_action(self):
        txt = self.talk_button.button.cget("text")
        if txt == "Talk (c)":
            st = self.get_current_dsi_state()
            if st not in [
                TaskStateEnum.WATER.value,
                TaskStateEnum.PAUSE.value,
                TaskStateEnum.TALKING.value,
                TaskStateEnum.ALPHA.value,
            ]:
                self.current_dsi_message_state = st
            self.send_signal_to_dsi(TaskStateEnum.TALKING.value)
            self.talk_button.update_button("Talk InProgress (c)", self.talk_action)
        else:
            self.send_signal_to_dsi(self.current_dsi_message_state)
            self.talk_button.update_button("Talk (c)", self.talk_action)

    # ------------------------------------------------------------------------
    # -------------------- CHECK TRIGGERS ------------------------------------
    # ------------------------------------------------------------------------
    @snapshot_action("check_triggers_button")
    def check_triggers_action(self):
        self.check_triggers_button.hide()
        self.configure(bg="SystemButtonFace")
        self.after(120_000, self._show_check_triggers_button)

    def _show_check_triggers_button(self):
        self.configure(bg="green")
        self.check_triggers_button.show()

    # ------------------------------------------------------------------------
    # -------------------------- ERROR ---------------------------------------
    # ------------------------------------------------------------------------
    def error_action(self):
        self.send_signal_to_dsi(TaskStateEnum.ERROR.value)
        if self.prev_sent_state is not None:
            self.send_signal_to_dsi(self.prev_sent_state)

        if self.last_button_clicked and self.last_button_prev_text:
            self.last_button_clicked.button.config(text=self.last_button_prev_text)
            self.last_button_clicked.button.config(command=self.last_button_prev_command)
            self.last_button_clicked.callback = self.last_button_prev_command

        if self.last_undo_function:
            self.last_undo_function()

        self.last_button_clicked = self.last_button_prev_text = None
        self.last_button_prev_command = self.last_undo_function = None

    # ======================================================================
    # ------------------- METODY POMOCNICZE --------------------------------
    # ======================================================================
    def send_signal_to_dsi(self, data: int):
        self.prev_sent_state = self.last_sent_state
        self.last_sent_state = data

        data_byte = data.to_bytes(1, "big")
        now = datetime.now()
        diff = now - getattr(self, "_previous_timestamp", now)
        self._previous_timestamp = now

        log_msg = (
            f"{now.strftime('%H:%M:%S.%f')}>>{diff}\t"
            f"Sending data byte: {data_byte}, {data}, {self.int_to_enum(data)}"
        )
        self.logger.log_signal(log_msg)
        self.dsi.send_signal(data)

    def get_current_dsi_state(self):
        return self.last_sent_state

    # Timer
    def reset_timer(self):
        self.start_time = datetime.now()
        self.timer_label.config(bg="white")
        self._timer_tick()

    def _timer_tick(self):
        elapsed = datetime.now() - self.start_time
        self.timer_label.config(text=str(elapsed).split(".")[0])
        self.timer_label.config(bg="red" if elapsed.total_seconds() >= 45 else "white")
        self.after(1000, self._timer_tick)

    # Tekst generowany
    def generate_text(self):
        if not hasattr(self, "instructions"):
            txt = "Instrukcje nie wczytane."
        elif self.current_instruction_index >= len(self.instructions):
            txt = "Brak dalszych instrukcji w pliku CSV."
        else:
            instr = self.instructions[self.current_instruction_index]
            self.current_instruction_index += 1
            deg = instr["inbound_deg"]
            typ = {"D": "Direct", "P": "Parallel", "T": "Teardrop"}.get(
                instr["typ_wlotu"], "Direct"
            )
            txt = (
                "Hold over point Zulu Uniform Echo 5000 ft altitude\n"
                f"Inbound track {deg} degrees\n"
                f"{typ} entry\n"
                "Outbound time 1 minute"
            )
        self.generated_text_display.config(state="normal")
        self.generated_text_display.delete(1.0, tk.END)
        self.generated_text_display.insert(tk.END, txt)
        self.generated_text_display.config(state="disabled")
        self.logger.log_generated_text(txt)

    def show_initial_confirmation(self):
        messagebox.showinfo(
            "Confirmation",
            "Confirm data you set up and RUN data SAVE TO FILE on EEG application.",
        )
        messagebox.showinfo(
            "Confirmation",
            "Confirm that WIRELESS or WIRED triggering source is set correctly",
        )

    def int_to_enum(self, value):
        for m in TaskStateEnum:
            if m.value == value:
                return m
        return None

    def on_close(self):
        # 1) Zatrzymanie wątku GPS
        self.stop_event.set()
        if self.gps_thread.is_alive():
            self.gps_thread.join(timeout=2)  # max 2 s na zamknięcie

        # 2) Zamknięcie portu DSI
        try:
            self.dsi.close_serial_port()
        except:
            pass

        # 4) Zakończenie okna Tk
        self.destroy()


# =========================================================================
#                                  MAIN
# =========================================================================
if __name__ == "__main__":
    app = Application()
    app.mainloop()
