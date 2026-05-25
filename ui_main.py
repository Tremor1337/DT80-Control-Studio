import sys
import threading
import time

from PySide6.QtCore import Signal, QObject
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTextEdit, QComboBox, QGroupBox, QStackedWidget, QSpinBox, QMessageBox, QCheckBox,
    QTabWidget, QListWidget, QFileDialog
)

from dt80.transport import SerialTransport, TcpTransport
from dt80.client import DT80Client
from dt80.command_catalog import COMMANDS
from dt80.job_builder import (
    CHANNEL_TYPES, SCHEDULE_LETTERS, ChannelDef, ScheduleDef, build_job_text
)

DARK_QSS = """
QWidget { background-color: #0f1115; color: #e6e6e6; font-size: 12px; }
QLineEdit, QTextEdit, QListWidget, QComboBox, QSpinBox {
    background-color: #161a22;
    border: 1px solid #2a3142;
    border-radius: 10px;
    padding: 8px;
    selection-background-color: #2f6fed;
}
QTextEdit { font-family: Consolas, "Courier New", monospace; }
QPushButton {
    background-color: #1f2633;
    border: 1px solid #2a3142;
    border-radius: 12px;
    padding: 12px 14px;
    font-weight: 600;
}
QPushButton:hover { background-color: #252f42; }
QPushButton:pressed { background-color: #1a2030; }
QPushButton:disabled { color: #666; background-color: #141824; }
QGroupBox {
    border: 1px solid #2a3142;
    border-radius: 14px;
    margin-top: 10px;
    padding: 10px;
}
QGroupBox:title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: #b8c4ff;
}
QTabWidget::pane { border: 1px solid #2a3142; border-radius: 14px; }
QTabBar::tab {
    background: #161a22;
    border: 1px solid #2a3142;
    padding: 10px 14px;
    margin: 2px;
    border-radius: 12px;
}
QTabBar::tab:selected { background: #1f2633; border: 1px solid #3b4a6a; }
"""


class GuiBus(QObject):
    log = Signal(str)
    status = Signal(str)
    connected = Signal(bool)
    jobs_updated = Signal(list)


class DT80Session:
    def __init__(self, bus: GuiBus):
        self.bus = bus
        self.client: DT80Client | None = None
        self._lock = threading.Lock()

    def _set_status(self, msg: str):
        self.bus.status.emit(msg)

    def _log(self, msg: str):
        self.bus.log.emit(msg)

    def _get_client(self) -> DT80Client | None:
        with self._lock:
            return self.client

    def connect_serial(self, port: str, baud: int):
        def task():
            try:
                t = SerialTransport(port, baud)
                c = DT80Client(t, on_log=self._log)
                c.connect()
                with self._lock:
                    self.client = c
                self.bus.connected.emit(True)
                self._set_status("Connected (Serial)")
                self.refresh_jobs()
            except Exception as e:
                self.bus.connected.emit(False)
                self._set_status(f"Connect failed: {e}")
        threading.Thread(target=task, daemon=True).start()

    def connect_tcp(self, host: str, port: int):
        def task():
            try:
                t = TcpTransport(host, port)
                c = DT80Client(t, on_log=self._log)
                c.connect()
                with self._lock:
                    self.client = c
                self.bus.connected.emit(True)
                self._set_status("Connected (TCP)")
                self.refresh_jobs()
            except Exception as e:
                self.bus.connected.emit(False)
                self._set_status(f"Connect failed: {e}")
        threading.Thread(target=task, daemon=True).start()

    def alarms_show(self, callback_text):
        def task():
            c = self._get_client()
            if not c:
                self._set_status("Not connected")
                return
            try:
                res = c.run("ALARMS", read_window_s=1.8)
                if callback_text:
                    callback_text("\n".join(res.received_lines))
                self._set_status("ALARMS OK")
            except Exception as e:
                self._set_status(f"ALARMS failed: {e}")

        threading.Thread(target=task, daemon=True).start()

    def alarms_ack(self):
        self.run_command("ACKALARMS", 1.2)

    def alarms_clear(self):
        self.run_command("CLEARALARMS", 1.2)

    # ---------------- System actions ----------------
    def sys_ver(self):
        self.run_command("VER", 1.2)

    def sys_help(self):
        self.run_command("HELP", 1.6)

    def sys_free(self):
        self.run_command("FREE", 1.2)

    def sys_time(self):
        self.run_command("TIME", 1.2)

    def sys_settime(self, timestr: str):
        ts = (timestr or "").strip()
        if not ts:
            self._set_status("SETTIME requires a value")
            return
        self.run_command(f"SETTIME {ts}", 1.2)

    def sys_restart(self):
        # After restart, connection will drop — user reconnects.
        self.run_command("RESTART", 0.8)

    def sys_reset(self):
        self.run_command("RESET", 0.8)

    # ---------------- Profile actions ----------------
    def profile_save(self):
        self.run_command("PROFILE SAVE", 1.4)

    def profile_load(self):
        self.run_command("PROFILE LOAD", 1.4)

    def profile_default(self):
        self.run_command("PROFILE DEFAULT", 1.4)

    def profile_copy(self, src: str, dst: str):
        s = (src or "").strip()
        d = (dst or "").strip()
        if not s or not d:
            self._set_status("PROFILE COPY needs src and dst")
            return
        self.run_command(f"PROFILE COPY {s} {d}", 1.6)

    # ---------------- Schedule letter actions ----------------
    def op_start_letter(self, letter: str):
        L = (letter or "").strip().upper()
        if not L:
            self._set_status("Pick a schedule letter")
            return
        self.run_command(f"G{L}", 0.8)

    def op_stop_letter(self, letter: str):
        L = (letter or "").strip().upper()
        if not L:
            self._set_status("Pick a schedule letter")
            return
        self.run_command(f"H{L}", 0.8)

    def set_startup_run(self, mode: str):
        """
        PROFILE STARTUP RUN can be CURRENT_JOB, NONE, or a job name. :contentReference[oaicite:3]{index=3}
        """
        mode = (mode or "").strip()
        self.run_command(f"PROFILE STARTUP RUN {mode}", 1.4)

    def runjob_oninsert(self, job_name: str):
        """
        Writes A:\\serialnum\\ONINSERT.DXC from job text. :contentReference[oaicite:4]{index=4}
        """
        j = (job_name or "").strip().strip('"')
        self.run_command(f'RUNJOBONINSERT "{j}"', 2.2)

    def runjob_oninsert_all(self, job_name: str):
        """
        Writes A:\\ONINSERT.DXC from job text. :contentReference[oaicite:5]{index=5}
        """
        j = (job_name or "").strip().strip('"')
        self.run_command(f'RUNJOBONINSERTALL "{j}"', 2.2)

    def del_oninsert(self):
        """Deletes A:\\serialnum\\ONINSERT.DXC. :contentReference[oaicite:6]{index=6}"""
        self.run_command("DELONINSERT", 2.0)

    def del_oninsert_all(self):
        """Deletes A:\\ONINSERT.DXC. :contentReference[oaicite:7]{index=7}"""
        self.run_command("DELONINSERTALL", 2.0)

    def op_unlock_all_jobs(self):
        self.run_command("UNLOCKJOB*", 1.8)

    def op_del_all_jobs(self):
        def task():
            c = self._get_client()
            if not c:
                self._set_status("Not connected")
                return
            try:
                # DELALLJOBS deletes current + other jobs/log data (except locked jobs). :contentReference[oaicite:3]{index=3}
                c.run("DELALLJOBS", read_window_s=2.5)
                time.sleep(0.6)
                self.refresh_jobs()
                self._set_status("DELALLJOBS sent ✅ (check console for progress)")
            except Exception as e:
                self._set_status(f"DELALLJOBS failed: {e}")

        threading.Thread(target=task, daemon=True).start()

    def disconnect(self):
        def task():
            with self._lock:
                c = self.client
                self.client = None
            try:
                if c:
                    c.close()
            finally:
                self.bus.connected.emit(False)
                self.bus.jobs_updated.emit([])
                self._set_status("Disconnected")
        threading.Thread(target=task, daemon=True).start()

    def run_command(self, cmd: str, read_window_s: float = 1.0):
        def task():
            c = self._get_client()
            if not c:
                self._set_status("Not connected")
                return
            try:
                c.run(cmd, read_window_s=read_window_s)
            except Exception as e:
                self._set_status(f"Command failed: {e}")
        threading.Thread(target=task, daemon=True).start()

    def run_command_capture(self, cmd: str, callback_text, read_window_s: float = 1.5):
        """
        Runs a command and sends back received lines to a callback (UI textbox).
        """
        def task():
            c = self._get_client()
            if not c:
                self._set_status("Not connected")
                return
            try:
                res = c.run(cmd, read_window_s=read_window_s)
                # res may contain received_lines depending on your DT80Client implementation
                lines = getattr(res, "received_lines", None)
                if lines is None:
                    callback_text("(No captured output — check Console tab)")
                else:
                    callback_text("\n".join(lines))
                self._set_status(f"OK: {cmd}")
            except Exception as e:
                self._set_status(f"Command failed: {e}")

        threading.Thread(target=task, daemon=True).start()


    def refresh_jobs(self):
        def task():
            c = self._get_client()
            if not c:
                return
            try:
                jobs = c.list_jobs()
                self.bus.jobs_updated.emit(jobs)
                self._set_status(f"Jobs loaded: {len(jobs)}")
            except Exception as e:
                self._set_status(f"DIRJOBS failed: {e}")
        threading.Thread(target=task, daemon=True).start()
    # ---------------- Diagnostics actions ----------------
    def diag_version(self): self.run_command("VERSION", 1.2)
    def diag_serialno(self): self.run_command("SERIALNO", 1.2)
    def diag_time(self): self.run_command("TIME", 1.2)
    def diag_date(self): self.run_command("DATE", 1.2)
    def diag_mem(self): self.run_command("MEM", 1.6)
    def diag_profile_show(self): self.run_command("PROFILE SHOW", 2.0)

    def diag_set_time(self, hhmmss: str):
        """
        Sets time. Expected: HH:MM:SS
        """
        t = (hhmmss or "").strip()
        if not t:
            self._set_status("Missing time")
            return
        self.run_command(f"SETTIME {t}", 1.4)

    def diag_set_date(self, yyyymmdd: str):
        """
        Sets date. Expected: YYYY-MM-DD (or device accepted format)
        """
        d = (yyyymmdd or "").strip()
        if not d:
            self._set_status("Missing date")
            return
        self.run_command(f"SETDATE {d}", 1.4)


    # ---------------- Operator actions ----------------
    def op_status(self): self.run_command("STATUS", 1.2)
    def op_curjob(self): self.run_command("CURJOB", 1.2)
    def op_start_logging(self): self.run_command("LOGON", 0.8)
    def op_stop_logging(self): self.run_command("LOGOFF", 0.8)
    def op_start_all(self): self.run_command("G", 0.6)
    def op_stop_all(self): self.run_command("H", 0.6)

    def op_run_job(self, job_name: str):
        clean = (job_name or "").strip().strip('"')
        self.run_command(f'RUNJOB "{clean}"', 1.2)

    def op_upload_job(self, job_text: str, delay_ms: int = 35, run_after: bool = False,
                      job_name: str = "", start_logging: bool = False, start_sched: bool = False):
        def task():
            c = self._get_client()
            if not c:
                self._set_status("Not connected")
                return
            try:
                c.send_block(job_text, per_line_delay_ms=delay_ms)
                if run_after and job_name.strip():
                    c.run_job(job_name)
                if start_logging:
                    c.start_logging()
                if start_sched:
                    c.start_all_schedules()
                self.refresh_jobs()
                self._set_status("Job uploaded ✅")
            except Exception as e:
                self._set_status(f"Upload failed: {e}")
        threading.Thread(target=task, daemon=True).start()

    # ---------------- Stored Job actions ----------------
    def job_action(self, action: str, job_name: str, callback_text=None):
        """
        action: RUN / SHOW / LOCK / UNLOCK / DEL
        """
        def task():
            c = self._get_client()
            if not c:
                self._set_status("Not connected")
                return
            job = (job_name or "").strip().strip('"')
            try:
                if action == "RUN":
                    c.run_job(job)
                elif action == "SHOW":
                    res = c.show_prog(job)
                    if callback_text:
                        callback_text("\n".join(res.received_lines))
                elif action == "LOCK":
                    c.lock_job(job)
                elif action == "UNLOCK":
                    c.unlock_job(job)
                elif action == "DEL":
                    c.del_job(job)
                self.refresh_jobs()
                self._set_status(f"{action} OK")
            except Exception as e:
                self._set_status(f"{action} failed: {e}")

        threading.Thread(target=task, daemon=True).start()

    # ---------------- Data actions ----------------
    def data_listd(self, callback_text):
        def task():
            c = self._get_client()
            if not c:
                self._set_status("Not connected")
                return
            try:
                res = c.listd()
                callback_text("\n".join(res.received_lines))
                self._set_status("LISTD OK")
            except Exception as e:
                self._set_status(f"LISTD failed: {e}")
        threading.Thread(target=task, daemon=True).start()

    def data_copyd_export(self, options: str, save_path: str, capture_s: float = 10.0):
        def task():
            c = self._get_client()
            if not c:
                self._set_status("Not connected")
                return
            try:
                text = c.copyd_stream(options, capture_s=capture_s)
                with open(save_path, "w", encoding="utf-8", newline="") as f:
                    f.write(text)
                self._set_status(f"COPYD saved: {save_path}")
            except Exception as e:
                self._set_status(f"COPYD failed: {e}")
        threading.Thread(target=task, daemon=True).start()

    def data_deld(self, options: str):
        def task():
            c = self._get_client()
            if not c:
                self._set_status("Not connected")
                return
            try:
                c.deld(options)
                self._set_status("DELD OK")
            except Exception as e:
                self._set_status(f"DELD failed: {e}")
        threading.Thread(target=task, daemon=True).start()

    def data_cancel(self):
        def task():
            c = self._get_client()
            if not c:
                self._set_status("Not connected")
                return
            try:
                c.cancel_unload()
                self._set_status("Unload cancelled (Q)")
            except Exception as e:
                self._set_status(f"Q failed: {e}")
        threading.Thread(target=task, daemon=True).start()


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DT80 Control Studio — Full Prototype")
        self.resize(1200, 800)
        self.setStyleSheet(DARK_QSS)

        self.bus = GuiBus()
        self.bus.log.connect(self.append_console)
        self.bus.status.connect(self.set_status)
        self.bus.connected.connect(self.on_connected)
        self.bus.jobs_updated.connect(self.update_jobs_everywhere)

        self.session = DT80Session(self.bus)

        # Job Builder internal state
        self._jb_channels: list[ChannelDef] = []
        self._jb_schedules: list[ScheduleDef] = []
        self._jb_schedule_tokens: list[str] = []
        self._built_job_text = ""

        root = QVBoxLayout(self)
        root.addWidget(self._connection_box())

        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)

        self.tabs.addTab(self._operator_tab(), "Operator Panel")
        self.tabs.addTab(self._stored_jobs_tab(), "Stored Jobs")
        self.tabs.addTab(self._job_builder_tab(), "Job Builder")
        self.tabs.addTab(self._data_tab(), "Data")
        self.tabs.addTab(self._diagnostics_tab(), "Diagnostics")
        self.tabs.addTab(self._file_manager_tab(), "Files")
        self.tabs.addTab(self._system_profiles_tab(), "System & Profiles")
        self.tabs.addTab(self._advanced_tab(), "Advanced")
        self.tabs.addTab(self._startup_usb_tab(), "Startup & USB")
        self.tabs.addTab(self._alarms_tab(), "Alarms")
        self.tabs.addTab(self._console_tab(), "Console")

        self.on_conn_type_changed(0)

    def _alarms_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        box = QGroupBox("Alarm Panel (No Typing)")
        bl = QVBoxLayout(box)

        row = QHBoxLayout()

        self.btn_alarms = QPushButton("Show Alarms (ALARMS)")
        self.btn_alarms.clicked.connect(self.alarms_show_clicked)
        row.addWidget(self.btn_alarms)

        self.btn_ackalarms = QPushButton("Acknowledge (ACKALARMS)")
        self.btn_ackalarms.clicked.connect(self.session.alarms_ack)
        row.addWidget(self.btn_ackalarms)

        self.btn_clearalarms = QPushButton("Clear (CLEARALARMS)")
        self.btn_clearalarms.setStyleSheet("QPushButton{border:1px solid #7a2c2c;}")
        self.btn_clearalarms.clicked.connect(self.alarms_clear_clicked)
        row.addWidget(self.btn_clearalarms)

        row.addStretch(1)
        bl.addLayout(row)

        self.alarms_view = QTextEdit()
        self.alarms_view.setReadOnly(True)
        self.alarms_view.setPlaceholderText("Alarm output will appear here…")
        bl.addWidget(self.alarms_view, 1)

        layout.addWidget(box, 1)
        return tab

    def _system_profiles_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # -------- System Info --------
        sys_box = QGroupBox("System (No Typing)")
        sl = QHBoxLayout(sys_box)

        btn_ver = QPushButton("VER")
        btn_ver.clicked.connect(self.session.sys_ver)
        sl.addWidget(btn_ver)

        btn_help = QPushButton("HELP")
        btn_help.clicked.connect(self.session.sys_help)
        sl.addWidget(btn_help)

        btn_free = QPushButton("FREE")
        btn_free.clicked.connect(self.session.sys_free)
        sl.addWidget(btn_free)

        btn_time = QPushButton("TIME")
        btn_time.clicked.connect(self.session.sys_time)
        sl.addWidget(btn_time)

        layout.addWidget(sys_box)

        # -------- Set Time --------
        time_box = QGroupBox("Set Device Time (SETTIME)")
        tl = QHBoxLayout(time_box)

        self.settime_input = QLineEdit()
        self.settime_input.setPlaceholderText("Example: 2026-02-13T14:30:00  (follow DT80 manual format)")
        tl.addWidget(self.settime_input, 3)

        btn_settime = QPushButton("Apply SETTIME")
        btn_settime.clicked.connect(lambda: self.session.sys_settime(self.settime_input.text()))
        tl.addWidget(btn_settime, 1)

        layout.addWidget(time_box)

        # -------- Restart / Reset --------
        rr_box = QGroupBox("Restart / Reset (Connection will drop)")
        rl = QHBoxLayout(rr_box)

        btn_restart = QPushButton("RESTART")
        btn_restart.clicked.connect(self._confirm_restart)
        rl.addWidget(btn_restart)

        btn_reset = QPushButton("RESET")
        btn_reset.setStyleSheet("QPushButton{border:1px solid #ff4d4d; font-weight:800;}")
        btn_reset.clicked.connect(self._confirm_reset)
        rl.addWidget(btn_reset)

        rl.addStretch(1)
        layout.addWidget(rr_box)

        # -------- Profile Controls --------
        prof_box = QGroupBox("Profiles")
        pl = QVBoxLayout(prof_box)

        row1 = QHBoxLayout()
        btn_psave = QPushButton("PROFILE SAVE")
        btn_psave.clicked.connect(self.session.profile_save)
        row1.addWidget(btn_psave)

        btn_pload = QPushButton("PROFILE LOAD")
        btn_pload.clicked.connect(self.session.profile_load)
        row1.addWidget(btn_pload)

        btn_pdef = QPushButton("PROFILE DEFAULT")
        btn_pdef.clicked.connect(self.session.profile_default)
        row1.addWidget(btn_pdef)

        row1.addStretch(1)
        pl.addLayout(row1)

        row2 = QHBoxLayout()
        self.profile_src = QLineEdit()
        self.profile_src.setPlaceholderText("COPY src (profile name/id)")
        row2.addWidget(self.profile_src, 2)

        self.profile_dst = QLineEdit()
        self.profile_dst.setPlaceholderText("COPY dst (profile name/id)")
        row2.addWidget(self.profile_dst, 2)

        btn_pcopy = QPushButton("PROFILE COPY")
        btn_pcopy.clicked.connect(lambda: self.session.profile_copy(self.profile_src.text(), self.profile_dst.text()))
        row2.addWidget(btn_pcopy, 1)

        pl.addLayout(row2)
        layout.addWidget(prof_box)

        # -------- Schedule Letter Control --------
        sched_box = QGroupBox("Start/Stop Specific Schedule (GA/HA etc.)")
        sbl = QHBoxLayout(sched_box)

        self.sched_letter = QComboBox()
        self.sched_letter.addItems(list("ABCDEFGHIJK"))
        sbl.addWidget(QLabel("Letter:"))
        sbl.addWidget(self.sched_letter, 1)

        btn_gx = QPushButton("Start (Gx)")
        btn_gx.clicked.connect(lambda: self.session.op_start_letter(self.sched_letter.currentText()))
        sbl.addWidget(btn_gx)

        btn_hx = QPushButton("Stop (Hx)")
        btn_hx.clicked.connect(lambda: self.session.op_stop_letter(self.sched_letter.currentText()))
        sbl.addWidget(btn_hx)

        sbl.addStretch(1)
        layout.addWidget(sched_box)

        layout.addStretch(1)
        return tab

    def alarms_show_clicked(self):
        self.session.alarms_show(callback_text=self.alarms_view.setPlainText)

    def alarms_clear_clicked(self):
        ok = QMessageBox.question(
            self,
            "Confirm CLEARALARMS",
            "This may clear alarms/records depending on device state.\n\nContinue?",
            QMessageBox.Yes | QMessageBox.No
        )
        if ok == QMessageBox.Yes:
            self.session.alarms_clear()

    # ---------------- File Manager Tab ----------------
    def _file_manager_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        quick = QGroupBox("Quick Locations")
        ql = QHBoxLayout(quick)

        self.btn_dir_jobs = QPushButton("DIR B:\\JOBS")
        self.btn_dir_jobs.clicked.connect(lambda: self.fm_dir("B:\\JOBS"))
        ql.addWidget(self.btn_dir_jobs)

        self.btn_dir_b = QPushButton("DIR B:\\")
        self.btn_dir_b.clicked.connect(lambda: self.fm_dir("B:\\"))
        ql.addWidget(self.btn_dir_b)

        self.btn_dir_usb = QPushButton("DIR A:\\ (USB)")
        self.btn_dir_usb.clicked.connect(lambda: self.fm_dir("A:\\"))
        ql.addWidget(self.btn_dir_usb)

        layout.addWidget(quick)

        box = QGroupBox("File Commands (No Typing)")
        bl = QVBoxLayout(box)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Path:"))
        self.fm_path = QLineEdit()
        self.fm_path.setPlaceholderText(r'B:\JOBS  or  A:\  or  B:\JOBS\MyJob.dxc')
        row1.addWidget(self.fm_path, 4)

        self.btn_fm_dir = QPushButton("DIR")
        self.btn_fm_dir.clicked.connect(lambda: self.fm_dir(self.fm_path.text()))
        row1.addWidget(self.btn_fm_dir, 1)

        self.btn_fm_type = QPushButton("TYPE (View Text)")
        self.btn_fm_type.clicked.connect(lambda: self.fm_type(self.fm_path.text()))
        row1.addWidget(self.btn_fm_type, 1)

        bl.addLayout(row1)

        self.fm_output = QTextEdit()
        self.fm_output.setReadOnly(True)
        self.fm_output.setPlaceholderText("DIR / TYPE output will appear here…")
        bl.addWidget(self.fm_output, 1)

        layout.addWidget(box, 1)
        layout.addStretch(1)
        return tab

    def fm_dir(self, path: str):
        p = (path or "").strip()
        if not p:
            p = r"B:\JOBS"
        # Use quotes to be safe with spaces
        cmd = f'DIR "{p}"'
        self.session.run_command_capture(cmd, self.fm_output.setPlainText, read_window_s=2.0)

    def fm_type(self, file_path: str):
        p = (file_path or "").strip()
        if not p:
            QMessageBox.information(self, "Missing file", "Enter a file path to view, e.g. A:\\ONINSERT.DXC")
            return
        cmd = f'TYPE "{p}"'
        self.session.run_command_capture(cmd, self.fm_output.setPlainText, read_window_s=2.0)


    # ---------------- Connection UI ----------------
    def _connection_box(self) -> QGroupBox:
        box = QGroupBox("Connection")
        l = QHBoxLayout(box)

        self.conn_type = QComboBox()
        self.conn_type.addItems(["Serial (COM)", "Ethernet (TCP/IP)"])
        self.conn_type.currentIndexChanged.connect(self.on_conn_type_changed)
        l.addWidget(QLabel("Type:"))
        l.addWidget(self.conn_type, 2)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._serial_panel())
        self.stack.addWidget(self._tcp_panel())
        l.addWidget(self.stack, 6)

        self.btn_connect = QPushButton("Connect")
        self.btn_connect.clicked.connect(self.connect_clicked)
        l.addWidget(self.btn_connect, 1)

        self.btn_disconnect = QPushButton("Disconnect")
        self.btn_disconnect.setEnabled(False)
        self.btn_disconnect.clicked.connect(self.session.disconnect)
        l.addWidget(self.btn_disconnect, 1)

        self.status_lbl = QLabel("Status: idle")
        self.status_lbl.setStyleSheet("color:#b8c4ff; padding-left:10px;")
        l.addWidget(self.status_lbl, 3)

        return box

    def _startup_usb_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # -------- Startup Job --------
        gb_start = QGroupBox("Startup Job (after hard reset)")
        sl = QVBoxLayout(gb_start)

        info = QLabel(
            "DT80 can auto-load a job after a hard reset.\n"
            "Controlled by: PROFILE STARTUP RUN = CURRENT_JOB / NONE / jobname."
        )
        info.setStyleSheet("color:#cfd6ff; padding:6px;")
        info.setWordWrap(True)
        sl.addWidget(info)

        row = QHBoxLayout()
        row.addWidget(QLabel("Mode:"))

        self.startup_mode = QComboBox()
        self.startup_mode.addItems(["CURRENT_JOB", "NONE", "Specific Job…"])
        row.addWidget(self.startup_mode, 2)

        self.startup_job = QComboBox()
        self.startup_job.setEditable(True)
        self.startup_job.setPlaceholderText("Job name (from DIRJOBS)")
        row.addWidget(self.startup_job, 3)

        self.btn_apply_startup = QPushButton("Apply Startup Setting")
        self.btn_apply_startup.clicked.connect(self.apply_startup_clicked)
        row.addWidget(self.btn_apply_startup, 2)

        sl.addLayout(row)
        layout.addWidget(gb_start)



        # -------- USB ONINSERT --------
        gb_usb = QGroupBox("USB Auto-Programming (ONINSERT.DXC)")
        ul = QVBoxLayout(gb_usb)

        info2 = QLabel(
            "When a USB stick is inserted, DT80 looks for:\n"
            "1) A:\\serialnum\\ONINSERT.DXC then 2) A:\\ONINSERT.DXC\n"
            "If found, commands inside run as if typed via comms."
        )
        info2.setStyleSheet("color:#cfd6ff; padding:6px;")
        info2.setWordWrap(True)
        ul.addWidget(info2)

        rowu = QHBoxLayout()
        rowu.addWidget(QLabel("Source Job:"))
        self.oninsert_job = QComboBox()
        self.oninsert_job.setEditable(True)
        self.oninsert_job.setPlaceholderText("Pick a job to copy into ONINSERT.DXC")
        rowu.addWidget(self.oninsert_job, 3)

        self.btn_make_serial = QPushButton("Create Serial-Specific ONINSERT")
        self.btn_make_serial.clicked.connect(self.make_oninsert_serial_clicked)
        rowu.addWidget(self.btn_make_serial, 2)

        self.btn_make_all = QPushButton("Create Global ONINSERT (All DT80)")
        self.btn_make_all.clicked.connect(self.make_oninsert_all_clicked)
        rowu.addWidget(self.btn_make_all, 2)
        ul.addLayout(rowu)

        rowd = QHBoxLayout()
        self.btn_del_serial = QPushButton("Delete Serial ONINSERT (DELONINSERT)")
        self.btn_del_serial.clicked.connect(self.del_oninsert_serial_clicked)
        rowd.addWidget(self.btn_del_serial, 2)

        self.btn_del_all = QPushButton("Delete Global ONINSERT (DELONINSERTALL)")
        self.btn_del_all.clicked.connect(self.del_oninsert_all_clicked)
        rowd.addWidget(self.btn_del_all, 2)

        rowd.addStretch(1)
        ul.addLayout(rowd)

        layout.addWidget(gb_usb)
        layout.addStretch(1)
        return tab
    # ---------------- Diagnostics Tab ----------------
    def _diagnostics_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        quick = QGroupBox("Quick Diagnostics (No Typing)")
        ql = QHBoxLayout(quick)

        self.btn_diag_version = QPushButton("VERSION")
        self.btn_diag_version.clicked.connect(self.session.diag_version)
        ql.addWidget(self.btn_diag_version)

        self.btn_diag_serial = QPushButton("SERIALNO")
        self.btn_diag_serial.clicked.connect(self.session.diag_serialno)
        ql.addWidget(self.btn_diag_serial)

        self.btn_diag_time = QPushButton("TIME")
        self.btn_diag_time.clicked.connect(self.session.diag_time)
        ql.addWidget(self.btn_diag_time)

        self.btn_diag_date = QPushButton("DATE")
        self.btn_diag_date.clicked.connect(self.session.diag_date)
        ql.addWidget(self.btn_diag_date)

        self.btn_diag_mem = QPushButton("MEM")
        self.btn_diag_mem.clicked.connect(self.session.diag_mem)
        ql.addWidget(self.btn_diag_mem)

        self.btn_diag_profile = QPushButton("PROFILE SHOW")
        self.btn_diag_profile.clicked.connect(self.session.diag_profile_show)
        ql.addWidget(self.btn_diag_profile)

        layout.addWidget(quick)

        setters = QGroupBox("Set Device Clock (Optional)")
        sl = QVBoxLayout(setters)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Set Time (HH:MM:SS):"))
        self.in_set_time = QLineEdit()
        self.in_set_time.setPlaceholderText("14:30:00")
        row1.addWidget(self.in_set_time, 2)

        self.btn_set_time = QPushButton("SETTIME")
        self.btn_set_time.clicked.connect(lambda: self.session.diag_set_time(self.in_set_time.text()))
        row1.addWidget(self.btn_set_time, 1)
        sl.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Set Date (YYYY-MM-DD):"))
        self.in_set_date = QLineEdit()
        self.in_set_date.setPlaceholderText("2026-02-09")
        row2.addWidget(self.in_set_date, 2)

        self.btn_set_date = QPushButton("SETDATE")
        self.btn_set_date.clicked.connect(lambda: self.session.diag_set_date(self.in_set_date.text()))
        row2.addWidget(self.btn_set_date, 1)
        sl.addLayout(row2)

        layout.addWidget(setters)
        layout.addStretch(1)
        return tab


    def apply_startup_clicked(self):
        mode = self.startup_mode.currentText()
        if mode == "Specific Job…":
            job = (self.startup_job.currentText() or "").strip()
            if not job:
                QMessageBox.warning(self, "Missing job", "Select a job name for startup.")
                return
            self.session.set_startup_run(job)
        else:
            self.session.set_startup_run(mode)

    def make_oninsert_serial_clicked(self):
        job = (self.oninsert_job.currentText() or "").strip()
        if not job:
            QMessageBox.warning(self, "Missing job", "Select a job to copy into ONINSERT.")
            return
        self.session.runjob_oninsert(job)

    def make_oninsert_all_clicked(self):
        job = (self.oninsert_job.currentText() or "").strip()
        if not job:
            QMessageBox.warning(self, "Missing job", "Select a job to copy into ONINSERT.")
            return
        self.session.runjob_oninsert_all(job)

    def del_oninsert_serial_clicked(self):
        ok = QMessageBox.question(
            self, "Confirm DELONINSERT",
            "Delete serial-specific A:\\serialnum\\ONINSERT.DXC from the inserted USB?\n\nContinue?",
            QMessageBox.Yes | QMessageBox.No
        )
        if ok == QMessageBox.Yes:
            self.session.del_oninsert()

    def del_oninsert_all_clicked(self):
        ok = QMessageBox.question(
            self, "Confirm DELONINSERTALL",
            "Delete global A:\\ONINSERT.DXC from the inserted USB?\n\nContinue?",
            QMessageBox.Yes | QMessageBox.No
        )
        if ok == QMessageBox.Yes:
            self.session.del_oninsert_all()

    def _serial_panel(self) -> QWidget:
        w = QWidget()
        l = QHBoxLayout(w)
        self.serial_port = QLineEdit()
        self.serial_port.setPlaceholderText("COM5")
        self.serial_baud = QSpinBox()
        self.serial_baud.setRange(300, 115200)
        self.serial_baud.setValue(57600)
        l.addWidget(QLabel("Port:"))
        l.addWidget(self.serial_port, 2)
        l.addWidget(QLabel("Baud:"))
        l.addWidget(self.serial_baud, 1)
        return w

    def _tcp_panel(self) -> QWidget:
        w = QWidget()
        l = QHBoxLayout(w)
        self.tcp_host = QLineEdit()
        self.tcp_host.setPlaceholderText("192.168.1.50")
        self.tcp_port = QSpinBox()
        self.tcp_port.setRange(1, 65535)
        self.tcp_port.setValue(7700)
        l.addWidget(QLabel("IP/Host:"))
        l.addWidget(self.tcp_host, 2)
        l.addWidget(QLabel("Port:"))
        l.addWidget(self.tcp_port, 1)
        return w

    def _confirm_restart(self):
        ok = QMessageBox.question(
            self, "Confirm RESTART",
            "DT80 will restart and your connection will drop.\n\nContinue?",
            QMessageBox.Yes | QMessageBox.No
        )
        if ok == QMessageBox.Yes:
            self.session.sys_restart()

    def _confirm_reset(self):
        ok = QMessageBox.question(
            self, "Confirm RESET",
            "RESET is more disruptive than RESTART.\n"
            "Connection will drop and current activity may stop.\n\nContinue?",
            QMessageBox.Yes | QMessageBox.No
        )
        if ok == QMessageBox.Yes:
            self.session.sys_reset()

    def on_conn_type_changed(self, idx: int):
        self.stack.setCurrentIndex(idx)

    def connect_clicked(self):
        idx = self.conn_type.currentIndex()
        self.set_status("Connecting…")
        if idx == 0:
            port = self.serial_port.text().strip()
            if not port:
                QMessageBox.warning(self, "Missing COM", "Enter COM port like COM5.")
                return
            self.session.connect_serial(port, int(self.serial_baud.value()))
        else:
            host = self.tcp_host.text().strip()
            if not host:
                QMessageBox.warning(self, "Missing IP", "Enter DT80 IP address.")
                return
            self.session.connect_tcp(host, int(self.tcp_port.value()))

    # ---------------- Operator Panel ----------------
    def _operator_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        top = QGroupBox("Quick Controls (No Typing)")
        tl = QHBoxLayout(top)

        self.btn_status = QPushButton("STATUS")
        self.btn_status.clicked.connect(self.session.op_status)
        tl.addWidget(self.btn_status)

        self.btn_curjob = QPushButton("Current Job")
        self.btn_curjob.clicked.connect(self.session.op_curjob)
        tl.addWidget(self.btn_curjob)

        self.btn_refresh_jobs = QPushButton("Refresh Jobs")
        self.btn_refresh_jobs.clicked.connect(self.session.refresh_jobs)
        tl.addWidget(self.btn_refresh_jobs)

        self.btn_logon = QPushButton("Start Logging")
        self.btn_logon.clicked.connect(self.session.op_start_logging)
        tl.addWidget(self.btn_logon)

        self.btn_logoff = QPushButton("Stop Logging")
        self.btn_logoff.clicked.connect(self.session.op_stop_logging)
        tl.addWidget(self.btn_logoff)

        self.btn_start_sched = QPushButton("Start Schedules (G)")
        self.btn_start_sched.clicked.connect(self.session.op_start_all)
        tl.addWidget(self.btn_start_sched)

        self.btn_stop_sched = QPushButton("STOP / HALT (H)")
        self.btn_stop_sched.setStyleSheet("QPushButton{border:1px solid #7a2c2c;}")
        self.btn_stop_sched.clicked.connect(self.session.op_stop_all)
        tl.addWidget(self.btn_stop_sched)

        layout.addWidget(top)

        jobbox = QGroupBox("Run a Stored Job")
        jl = QHBoxLayout(jobbox)
        jl.addWidget(QLabel("Job:"))
        self.jobs_dropdown = QComboBox()
        jl.addWidget(self.jobs_dropdown, 2)
        self.btn_run_job = QPushButton("Run Job")
        self.btn_run_job.clicked.connect(self.run_selected_job)
        jl.addWidget(self.btn_run_job, 1)
        layout.addWidget(jobbox)

        layout.addStretch(1)
        return tab

    def run_selected_job(self):
        job = (self.jobs_dropdown.currentText() or "").strip()
        if not job:
            return
        self.session.op_run_job(job)

    # ---------------- Stored Jobs Tab ----------------
    def _stored_jobs_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        box = QGroupBox("Stored Jobs (No Typing)")
        bl = QVBoxLayout(box)

        top_row = QHBoxLayout()
        self.btn_jobs_refresh = QPushButton("Refresh (DIRJOBS)")
        self.btn_jobs_refresh.clicked.connect(self.session.refresh_jobs)
        top_row.addWidget(self.btn_jobs_refresh)

        self.btn_jobs_show = QPushButton("Show Program (SHOWPROG)")
        self.btn_jobs_show.clicked.connect(self.jobs_showprog_clicked)
        top_row.addWidget(self.btn_jobs_show)

        self.btn_jobs_run = QPushButton("Run Job (RUNJOB)")
        self.btn_jobs_run.clicked.connect(self.jobs_run_clicked)
        top_row.addWidget(self.btn_jobs_run)

        self.btn_jobs_lock = QPushButton("Lock")
        self.btn_jobs_lock.clicked.connect(self.jobs_lock_clicked)
        top_row.addWidget(self.btn_jobs_lock)

        self.btn_jobs_unlock = QPushButton("Unlock")
        self.btn_jobs_unlock.clicked.connect(self.jobs_unlock_clicked)
        top_row.addWidget(self.btn_jobs_unlock)

        self.btn_jobs_delete = QPushButton("Delete (DELJOB)")
        self.btn_jobs_delete.setStyleSheet("QPushButton{border:1px solid #7a2c2c;}")
        self.btn_jobs_delete.clicked.connect(self.jobs_delete_clicked)
        top_row.addWidget(self.btn_jobs_delete)

        bl.addLayout(top_row)

        mid = QHBoxLayout()
        self.jobs_list = QListWidget()
        self.jobs_list.setMinimumWidth(280)
        mid.addWidget(self.jobs_list, 1)

        self.jobs_prog_view = QTextEdit()
        self.jobs_prog_view.setReadOnly(True)
        self.jobs_prog_view.setPlaceholderText("SHOWPROG output will appear here…")
        mid.addWidget(self.jobs_prog_view, 2)

        bl.addLayout(mid, 1)
        layout.addWidget(box, 1)
        danger = QGroupBox("Danger Zone (Be Careful)")
        dl = QHBoxLayout(danger)

        self.btn_unlock_all = QPushButton("Unlock ALL Jobs (UNLOCKJOB*)")
        self.btn_unlock_all.clicked.connect(self.session.op_unlock_all_jobs)
        dl.addWidget(self.btn_unlock_all)

        self.btn_del_all_jobs = QPushButton("DELETE ALL JOBS (DELALLJOBS)")
        self.btn_del_all_jobs.setStyleSheet("QPushButton{border:1px solid #ff4d4d; font-weight:800;}")
        self.btn_del_all_jobs.clicked.connect(self.del_all_jobs_clicked)
        dl.addWidget(self.btn_del_all_jobs)

        layout.addWidget(danger)

        return tab

    def _selected_job(self) -> str:
        if self.jobs_list.currentItem():
            return self.jobs_list.currentItem().text().strip().replace("*", "").replace("+", "").strip()
        if self.jobs_dropdown.currentText():
            return self.jobs_dropdown.currentText().strip()
        return ""

    def jobs_showprog_clicked(self):
        job = self._selected_job()
        if not job:
            QMessageBox.information(self, "No job selected", "Select a job first.")
            return
        self.session.job_action("SHOW", job, callback_text=self.jobs_prog_view.setPlainText)

    def jobs_run_clicked(self):
        job = self._selected_job()
        if not job:
            QMessageBox.information(self, "No job selected", "Select a job first.")
            return
        self.session.job_action("RUN", job)

    def jobs_lock_clicked(self):
        job = self._selected_job()
        if not job:
            QMessageBox.information(self, "No job selected", "Select a job first.")
            return
        self.session.job_action("LOCK", job)

    def jobs_unlock_clicked(self):
        job = self._selected_job()
        if not job:
            QMessageBox.information(self, "No job selected", "Select a job first.")
            return
        self.session.job_action("UNLOCK", job)

    def jobs_delete_clicked(self):
        job = self._selected_job()
        if not job:
            QMessageBox.information(self, "No job selected", "Select a job first.")
            return
        ok = QMessageBox.question(
            self,
            "Confirm DELJOB",
            f'Delete job "{job}"?\n\nThis cannot be undone.',
            QMessageBox.Yes | QMessageBox.No
        )
        if ok == QMessageBox.Yes:
            self.session.job_action("DEL", job)

    # ---------------- Job Builder Tab ----------------
    def _job_builder_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        header = QGroupBox("Job Setup")
        hl = QHBoxLayout(header)
        hl.addWidget(QLabel("Job Name:"))
        self.jb_job_name = QLineEdit()
        self.jb_job_name.setPlaceholderText("Boiler01")
        hl.addWidget(self.jb_job_name, 2)

        self.jb_logon = QCheckBox("Include LOGON")
        self.jb_logon.setChecked(True)
        hl.addWidget(self.jb_logon)
        layout.addWidget(header)

        row = QHBoxLayout()

        # Channels
        ch_box = QGroupBox("Channels")
        ch_l = QVBoxLayout(ch_box)

        ch_form = QHBoxLayout()
        self.jb_ch_no = QSpinBox()
        self.jb_ch_no.setRange(1, 60)
        self.jb_ch_no.setValue(1)

        self.jb_ch_type = QComboBox()
        for label, code in CHANNEL_TYPES:
            self.jb_ch_type.addItem(label, code)

        ch_form.addWidget(QLabel("No"))
        ch_form.addWidget(self.jb_ch_no, 1)
        ch_form.addWidget(QLabel("Type"))
        ch_form.addWidget(self.jb_ch_type, 3)
        ch_l.addLayout(ch_form)

        self.jb_ch_label = QLineEdit()
        self.jb_ch_label.setPlaceholderText('Label (e.g., Temp)')
        ch_l.addWidget(self.jb_ch_label)

        self.jb_ch_extra = QLineEdit()
        self.jb_ch_extra.setPlaceholderText("Extra params (optional) e.g. FF4")
        ch_l.addWidget(self.jb_ch_extra)

        ch_btns = QHBoxLayout()
        self.btn_jb_add_ch = QPushButton("Add Channel")
        self.btn_jb_add_ch.clicked.connect(self.jb_add_channel)
        ch_btns.addWidget(self.btn_jb_add_ch)

        self.btn_jb_remove_ch = QPushButton("Remove Selected")
        self.btn_jb_remove_ch.clicked.connect(self.jb_remove_channel)
        ch_btns.addWidget(self.btn_jb_remove_ch)
        ch_l.addLayout(ch_btns)

        self.jb_channel_list = QListWidget()
        ch_l.addWidget(self.jb_channel_list, 1)
        row.addWidget(ch_box, 1)

        # Schedules
        sc_box = QGroupBox("Schedules")
        sc_l = QVBoxLayout(sc_box)

        sc_form1 = QHBoxLayout()
        self.jb_sc_letter = QComboBox()
        self.jb_sc_letter.addItems(SCHEDULE_LETTERS)
        self.jb_sc_store = QLineEdit()
        self.jb_sc_store.setPlaceholderText("Store (optional) e.g. DATA:2MB")
        sc_form1.addWidget(QLabel("Letter"))
        sc_form1.addWidget(self.jb_sc_letter, 1)
        sc_form1.addWidget(QLabel("Store"))
        sc_form1.addWidget(self.jb_sc_store, 3)
        sc_l.addLayout(sc_form1)

        sc_form2 = QHBoxLayout()
        self.jb_sc_int_val = QSpinBox()
        self.jb_sc_int_val.setRange(1, 9999)
        self.jb_sc_int_val.setValue(10)
        self.jb_sc_int_unit = QComboBox()
        self.jb_sc_int_unit.addItems(["S", "M", "H", "MS"])
        sc_form2.addWidget(QLabel("Interval"))
        sc_form2.addWidget(self.jb_sc_int_val, 1)
        sc_form2.addWidget(self.jb_sc_int_unit, 1)
        sc_form2.addStretch(1)
        sc_l.addLayout(sc_form2)

        sc_pick = QHBoxLayout()
        self.btn_jb_use_sel = QPushButton("Use Selected Channels →")
        self.btn_jb_use_sel.clicked.connect(self.jb_use_selected_channels)
        sc_pick.addWidget(self.btn_jb_use_sel)

        self.btn_jb_use_all = QPushButton("Use All Channels")
        self.btn_jb_use_all.clicked.connect(self.jb_use_all_channels)
        sc_pick.addWidget(self.btn_jb_use_all)
        sc_l.addLayout(sc_pick)

        self.jb_sc_preview = QLineEdit()
        self.jb_sc_preview.setReadOnly(True)
        self.jb_sc_preview.setPlaceholderText("Schedule channels: e.g. 1V 2TK")
        sc_l.addWidget(self.jb_sc_preview)

        sc_btns = QHBoxLayout()
        self.btn_jb_add_sc = QPushButton("Add Schedule")
        self.btn_jb_add_sc.clicked.connect(self.jb_add_schedule)
        sc_btns.addWidget(self.btn_jb_add_sc)

        self.btn_jb_remove_sc = QPushButton("Remove Selected")
        self.btn_jb_remove_sc.clicked.connect(self.jb_remove_schedule)
        sc_btns.addWidget(self.btn_jb_remove_sc)
        sc_l.addLayout(sc_btns)

        self.jb_schedule_list = QListWidget()
        sc_l.addWidget(self.jb_schedule_list, 1)

        row.addWidget(sc_box, 1)
        layout.addLayout(row, 2)

        actions = QGroupBox("Build & Upload")
        al = QHBoxLayout(actions)

        self.btn_jb_generate = QPushButton("Generate Job Text")
        self.btn_jb_generate.clicked.connect(self.jb_generate_job)
        al.addWidget(self.btn_jb_generate)

        self.jb_run_after = QCheckBox("Run after upload")
        self.jb_run_after.setChecked(True)
        al.addWidget(self.jb_run_after)

        self.jb_start_log = QCheckBox("Start logging")
        self.jb_start_log.setChecked(False)
        al.addWidget(self.jb_start_log)

        self.jb_start_sched = QCheckBox("Start schedules")
        self.jb_start_sched.setChecked(False)
        al.addWidget(self.jb_start_sched)

        self.jb_delay = QSpinBox()
        self.jb_delay.setRange(0, 500)
        self.jb_delay.setValue(35)
        al.addWidget(QLabel("Delay/line ms:"))
        al.addWidget(self.jb_delay)

        self.btn_jb_upload = QPushButton("Upload to DT80")
        self.btn_jb_upload.clicked.connect(self.jb_upload)
        al.addWidget(self.btn_jb_upload)

        layout.addWidget(actions)

        layout.addWidget(QLabel("Generated Job Preview"))
        self.jb_output = QTextEdit()
        layout.addWidget(self.jb_output, 1)

        return tab

    def jb_add_channel(self):
        ch = ChannelDef(
            ch_no=int(self.jb_ch_no.value()),
            ch_code=self.jb_ch_type.currentData(),
            label=self.jb_ch_label.text(),
            extra=self.jb_ch_extra.text(),
        )
        self._jb_channels.append(ch)
        self.jb_channel_list.addItem(ch.to_line())
        if self.jb_ch_no.value() < self.jb_ch_no.maximum():
            self.jb_ch_no.setValue(self.jb_ch_no.value() + 1)

    def jb_remove_channel(self):
        row = self.jb_channel_list.currentRow()
        if row >= 0:
            self.jb_channel_list.takeItem(row)
            self._jb_channels.pop(row)

    def jb_use_selected_channels(self):
        selected = self.jb_channel_list.selectedItems()
        tokens = [self._extract_token(it.text()) for it in selected]
        self._jb_schedule_tokens = [t for t in tokens if t]
        self.jb_sc_preview.setText(" ".join(self._jb_schedule_tokens))

    def jb_use_all_channels(self):
        tokens = [self._extract_token(ch.to_line()) for ch in self._jb_channels]
        self._jb_schedule_tokens = [t for t in tokens if t]
        self.jb_sc_preview.setText(" ".join(self._jb_schedule_tokens))

    def jb_add_schedule(self):
        sc = ScheduleDef(
            letter=self.jb_sc_letter.currentText(),
            store=self.jb_sc_store.text(),
            interval_value=int(self.jb_sc_int_val.value()),
            interval_unit=self.jb_sc_int_unit.currentText(),
            channel_tokens=list(self._jb_schedule_tokens),
        )
        self._jb_schedules.append(sc)
        self.jb_schedule_list.addItem(sc.to_line())

    def jb_remove_schedule(self):
        row = self.jb_schedule_list.currentRow()
        if row >= 0:
            self.jb_schedule_list.takeItem(row)
            self._jb_schedules.pop(row)

    def jb_generate_job(self):
        name = self.jb_job_name.text().strip() or "Job01"
        text = build_job_text(name, self._jb_channels, self._jb_schedules, include_logon=self.jb_logon.isChecked())
        self._built_job_text = text
        self.jb_output.setPlainText(text)

    def jb_upload(self):
        if not self.jb_output.toPlainText().strip():
            self.jb_generate_job()

        job_name = self.jb_job_name.text().strip() or "Job01"
        self.session.op_upload_job(
            job_text=self.jb_output.toPlainText().strip(),
            delay_ms=int(self.jb_delay.value()),
            run_after=self.jb_run_after.isChecked(),
            job_name=job_name,
            start_logging=self.jb_start_log.isChecked(),
            start_sched=self.jb_start_sched.isChecked(),
        )

    @staticmethod
    def _extract_token(line: str) -> str:
        s = line.strip()
        if not s:
            return ""
        cut = len(s)
        for i, ch in enumerate(s):
            if ch in ("(", " ", "\t"):
                cut = i
                break
        return s[:cut].strip()

    # ---------------- Data Tab ----------------
    def _data_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        box = QGroupBox("Data Tools (No Typing)")
        bl = QVBoxLayout(box)

        # Row 1: LISTD refresh + cancel
        row1 = QHBoxLayout()
        self.btn_listd = QPushButton("Refresh Store List (LISTD)")
        self.btn_listd.clicked.connect(self.data_listd_clicked)
        row1.addWidget(self.btn_listd)

        self.btn_cancel_unload = QPushButton("Cancel Unload (Q)")
        self.btn_cancel_unload.clicked.connect(self.session.data_cancel)
        row1.addWidget(self.btn_cancel_unload)

        row1.addStretch(1)
        bl.addLayout(row1)

        # ---------------- EXPORT (COPYD) WIZARD ----------------
        export_box = QGroupBox("Export Wizard (COPYD)")
        el = QVBoxLayout(export_box)

        row2 = QHBoxLayout()
        self.data_job = QComboBox()
        self.data_job.addItem("(current job)", "")
        row2.addWidget(QLabel("Job:"))
        row2.addWidget(self.data_job, 2)

        self.data_sched = QComboBox()
        self.data_sched.setEditable(True)
        self.data_sched.setPlaceholderText("A or AB or XABCDEFGHIJK")
        self.data_sched.addItem("(all schedules)", "")
        row2.addWidget(QLabel("Schedules:"))
        row2.addWidget(self.data_sched, 2)
        el.addLayout(row2)

        row3 = QHBoxLayout()
        self.chk_data = QCheckBox("Include Data")
        self.chk_data.setChecked(True)
        row3.addWidget(self.chk_data)

        self.chk_alarms = QCheckBox("Include Alarms")
        self.chk_alarms.setChecked(True)
        row3.addWidget(self.chk_alarms)

        self.chk_live = QCheckBox("Live stores")
        self.chk_live.setChecked(True)
        row3.addWidget(self.chk_live)

        self.chk_archive = QCheckBox("Archive stores")
        self.chk_archive.setChecked(False)
        row3.addWidget(self.chk_archive)

        row3.addStretch(1)
        el.addLayout(row3)

        row4 = QHBoxLayout()
        self.start_opt = QLineEdit()
        self.start_opt.setPlaceholderText('start= (optional) e.g. -30T or new')
        row4.addWidget(QLabel("Start:"))
        row4.addWidget(self.start_opt, 2)

        self.end_opt = QLineEdit()
        self.end_opt.setPlaceholderText('end= (optional) e.g. -1D or 2026-02-01T00:00:00')
        row4.addWidget(QLabel("End:"))
        row4.addWidget(self.end_opt, 2)

        self.step_opt = QLineEdit()
        self.step_opt.setPlaceholderText("step= (optional) e.g. 10 or 2.5")
        row4.addWidget(QLabel("Step:"))
        row4.addWidget(self.step_opt, 1)
        el.addLayout(row4)

        row5 = QHBoxLayout()
        self.format_box = QComboBox()
        self.format_box.addItems(["csv", "fixed", "free", "dbd"])
        row5.addWidget(QLabel("Format:"))
        row5.addWidget(self.format_box, 1)

        self.merge_box = QComboBox()
        self.merge_box.addItems(["Y (single file)", "N (separate files)"])
        row5.addWidget(QLabel("Merge:"))
        row5.addWidget(self.merge_box, 1)

        self.dest_box = QComboBox()
        self.dest_box.addItems(["stream (to this app)", "B: (internal)", "A: (USB)"])
        row5.addWidget(QLabel("Dest:"))
        row5.addWidget(self.dest_box, 2)
        el.addLayout(row5)

        row6 = QHBoxLayout()
        self.copyd_preview = QLineEdit()
        self.copyd_preview.setReadOnly(True)
        self.copyd_preview.setPlaceholderText("COPYD command will be generated here…")
        row6.addWidget(self.copyd_preview, 3)

        self.btn_build_copyd = QPushButton("Build COPYD")
        self.btn_build_copyd.clicked.connect(self.data_build_copyd_preview)
        row6.addWidget(self.btn_build_copyd)

        self.btn_export = QPushButton("Export Now → Save File")
        self.btn_export.clicked.connect(self.data_export_wizard_clicked)
        row6.addWidget(self.btn_export)
        el.addLayout(row6)

        # ---------------- DELETE (DELD) WIZARD ----------------
        delete_box = QGroupBox("Delete Wizard (DELD) — with Preview")
        dl = QVBoxLayout(delete_box)

        rowd1 = QHBoxLayout()
        self.deld_end = QLineEdit()
        self.deld_end.setPlaceholderText('end= (optional) e.g. -30T (delete older than 30 days) or delete-all')
        rowd1.addWidget(QLabel("Delete older than (end=):"))
        rowd1.addWidget(self.deld_end, 3)

        self.deld_id = QSpinBox()
        self.deld_id.setRange(0, 999999)
        self.deld_id.setValue(0)
        rowd1.addWidget(QLabel("id="))
        rowd1.addWidget(self.deld_id, 1)
        dl.addLayout(rowd1)

        rowd2 = QHBoxLayout()
        self.btn_build_deld = QPushButton("Build DELD")
        self.btn_build_deld.clicked.connect(self.data_build_deld_preview)
        rowd2.addWidget(self.btn_build_deld)

        self.btn_preview_listd = QPushButton("Preview Selection (LISTD)")
        self.btn_preview_listd.clicked.connect(self.data_preview_listd_clicked)
        rowd2.addWidget(self.btn_preview_listd)

        self.btn_delete_now = QPushButton("DELETE NOW (DELD)")
        self.btn_delete_now.setStyleSheet("QPushButton{border:1px solid #7a2c2c;}")
        self.btn_delete_now.clicked.connect(self.data_delete_wizard_clicked)
        rowd2.addWidget(self.btn_delete_now)

        rowd2.addStretch(1)
        dl.addLayout(rowd2)

        self.deld_preview = QLineEdit()
        self.deld_preview.setReadOnly(True)
        self.deld_preview.setPlaceholderText("DELD command will be generated here…")
        dl.addWidget(self.deld_preview)

        # LISTD output viewer (shared)
        self.listd_view = QTextEdit()
        self.listd_view.setReadOnly(True)
        self.listd_view.setPlaceholderText("LISTD output (and preview) will appear here…")

        bl.addWidget(export_box)
        bl.addWidget(delete_box)
        bl.addWidget(self.listd_view, 1)

        layout.addWidget(box, 1)
        return tab





    # ---------------- Advanced Tab ----------------
    def _advanced_tab(self) -> QWidget:
        tab = QWidget()
        layout = QHBoxLayout(tab)

        left = QGroupBox("Catalog")
        ll = QVBoxLayout(left)
        self.cmd_list = QListWidget()
        for key in COMMANDS.keys():
            self.cmd_list.addItem(key)
        self.cmd_list.currentTextChanged.connect(self.on_cmd_selected)
        ll.addWidget(self.cmd_list, 1)

        self.cmd_desc = QLabel("Select a command.")
        self.cmd_desc.setWordWrap(True)
        self.cmd_desc.setStyleSheet("color:#cfd6ff; padding:6px;")
        ll.addWidget(self.cmd_desc)
        layout.addWidget(left, 1)

        right = QGroupBox("Advanced Runner (Optional)")
        rl = QVBoxLayout(right)

        self.cmd_input = QLineEdit()
        self.cmd_input.setPlaceholderText("Type a DT80 command (advanced)")
        rl.addWidget(self.cmd_input)

        btn_row = QHBoxLayout()
        self.btn_adv_run = QPushButton("Run")
        self.btn_adv_run.clicked.connect(lambda: self.session.run_command(self.cmd_input.text().strip(), 1.2))
        btn_row.addWidget(self.btn_adv_run)

        self.btn_example = QPushButton("Insert Example")
        self.btn_example.clicked.connect(self.insert_example)
        btn_row.addWidget(self.btn_example)
        btn_row.addStretch(1)
        rl.addLayout(btn_row)

        self.example_lbl = QLabel("Example: —")
        self.example_lbl.setStyleSheet("color:#b8c4ff; padding:6px;")
        rl.addWidget(self.example_lbl)

        layout.addWidget(right, 2)
        return tab

    def on_cmd_selected(self, name: str):
        info = COMMANDS.get(name)
        if info:
            self.cmd_desc.setText(info.description)
            self.example_lbl.setText(f"Example: {info.example}")

    def insert_example(self):
        item = self.cmd_list.currentItem()
        if not item:
            return
        info = COMMANDS.get(item.text())
        if info:
            self.cmd_input.setText(info.example)

    # ---------------- Console Tab ----------------
    def _console_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.console = QTextEdit()
        self.console.setReadOnly(True)
        layout.addWidget(self.console, 1)

        row = QHBoxLayout()
        btn_clear = QPushButton("Clear Console")
        btn_clear.clicked.connect(self.console.clear)
        row.addWidget(btn_clear)
        row.addStretch(1)
        layout.addLayout(row)
        return tab

    # ---------------- Shared UI updates ----------------
    def append_console(self, line: str):
        self.console.append(line)

    def set_status(self, msg: str):
        self.status_lbl.setText(f"Status: {msg}")

    def on_connected(self, ok: bool):
        self.btn_connect.setEnabled(not ok)
        self.btn_disconnect.setEnabled(ok)

        # enable/disable common buttons if they exist
        for attr in [
            "btn_status", "btn_curjob", "btn_refresh_jobs", "btn_logon", "btn_logoff",
            "btn_start_sched", "btn_stop_sched", "btn_run_job",
            "btn_jobs_refresh", "btn_jobs_show", "btn_jobs_run", "btn_jobs_lock",
            "btn_jobs_unlock", "btn_jobs_delete",
            "btn_unlock_all", "btn_del_all_jobs",
            "btn_jb_generate", "btn_jb_upload",
            "btn_alarms", "btn_ackalarms", "btn_clearalarms",
            "btn_diag_version", "btn_diag_serial", "btn_diag_time", "btn_diag_date",
            "btn_diag_mem", "btn_diag_profile", "btn_set_time", "btn_set_date",
            "btn_listd", "btn_cancel_unload", "btn_build_copyd", "btn_export",
            "btn_build_deld", "btn_preview_listd", "btn_delete_now",
            "btn_dir_jobs", "btn_dir_b", "btn_dir_usb", "btn_fm_dir", "btn_fm_type",
            "btn_apply_startup", "btn_make_serial", "btn_make_all", "btn_del_serial", "btn_del_all",
            "btn_adv_run", "btn_example"
        ]:
            if hasattr(self, attr):
                getattr(self, attr).setEnabled(ok)

        if ok:
            self.session.refresh_jobs()
        else:
            if hasattr(self, "jobs_dropdown"):
                self.jobs_dropdown.clear()
            if hasattr(self, "jobs_list"):
                self.jobs_list.clear()

    def update_jobs_everywhere(self, jobs: list):
        if hasattr(self, "jobs_dropdown"):
            current = self.jobs_dropdown.currentText()
            self.jobs_dropdown.blockSignals(True)
            self.jobs_dropdown.clear()
            self.jobs_dropdown.addItems(jobs)
            if current and current in jobs:
                self.jobs_dropdown.setCurrentText(current)
            self.jobs_dropdown.blockSignals(False)

        if hasattr(self, "jobs_list"):
            self.jobs_list.clear()
            self.jobs_list.addItems(jobs)

        # Startup/USB tab dropdowns
        if hasattr(self, "startup_job"):
            cur = self.startup_job.currentText()
            self.startup_job.blockSignals(True)
            self.startup_job.clear()
            self.startup_job.addItems(jobs)
            if cur and cur in jobs:
                self.startup_job.setCurrentText(cur)
            self.startup_job.blockSignals(False)

        if hasattr(self, "oninsert_job"):
            cur = self.oninsert_job.currentText()
            self.oninsert_job.blockSignals(True)
            self.oninsert_job.clear()
            self.oninsert_job.addItems(jobs)
            if cur and cur in jobs:
                self.oninsert_job.setCurrentText(cur)
            self.oninsert_job.blockSignals(False)

    def _parse_listd(self, text: str):
        """
        Parses LISTD output. Based on manual example, rows start with job name.
        We’ll extract:
          - job
          - schedule letter (A, B, etc)
          - type (Data/Alarm)
          - file class (Live/Arc)
          - first/last timestamps if present
        """
        stores = []
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        for ln in lines:
            # Example data row in manual:
            # *SAMPLE B Alarm Live Y Y N 3 1455
            # We'll accept rows that begin with '*' or a job name token.
            tokens = ln.split()
            if len(tokens) < 4:
                continue

            job_tok = tokens[0]
            # strip leading markers like * or +
            job = job_tok.replace("*", "").replace("+", "").strip()
            sch = tokens[1] if len(tokens) > 1 else ""
            typ = tokens[2] if len(tokens) > 2 else ""
            live_arc = tokens[3] if len(tokens) > 3 else ""

            # accept only reasonable schedule letters
            if not sch or len(sch) != 1:
                continue

            # accept Data/Alarm stores
            if typ.lower() not in ("data", "alarm"):
                continue

            if live_arc.lower() not in ("live", "arc"):
                continue

            stores.append({
                "job": job,
                "sched": sch.upper(),
                "type": typ.capitalize(),
                "class": "Live" if live_arc.lower() == "live" else "Arc",
            })

        # unique jobs + schedules
        jobs = sorted({s["job"] for s in stores})
        scheds = sorted({s["sched"] for s in stores})
        return stores, jobs, scheds

    def data_listd_clicked(self):
        # Ask session for LISTD; when it returns, update dropdowns automatically
        def on_text(txt: str):
            self.listd_view.setPlainText(txt)
            stores, jobs, scheds = self._parse_listd(txt)

            # populate job dropdown
            self.data_job.blockSignals(True)
            self.data_job.clear()
            self.data_job.addItem("(current job)", "")
            for j in jobs:
                self.data_job.addItem(j, j)
            self.data_job.blockSignals(False)

            # populate schedules hint list (still editable)
            self.data_sched.blockSignals(True)
            self.data_sched.clear()
            self.data_sched.addItem("(all schedules)", "")
            for s in scheds:
                self.data_sched.addItem(s, s)
            self.data_sched.blockSignals(False)

            self.data_build_copyd_preview()

        self.session.data_listd(callback_text=on_text)

    def data_build_copyd_preview(self):
        # Build COPYD options from UI (no typing)
        opts = []

        # job=
        job_val = self.data_job.currentData()
        if job_val:
            opts.append(f'job="{job_val}"')

        # sched=
        sched_val = (self.data_sched.currentText() or "").strip()
        if sched_val and not sched_val.startswith("("):
            opts.append(f"sched={sched_val}")

        # data/alarms/live/archive
        opts.append(f"data={'Y' if self.chk_data.isChecked() else 'N'}")
        opts.append(f"alarms={'Y' if self.chk_alarms.isChecked() else 'N'}")
        opts.append(f"live={'Y' if self.chk_live.isChecked() else 'N'}")
        opts.append(f"archive={'Y' if self.chk_archive.isChecked() else 'N'}")

        # range
        st = self.start_opt.text().strip()
        if st:
            opts.append(f"start={st}")
        en = self.end_opt.text().strip()
        if en:
            opts.append(f"end={en}")
        step = self.step_opt.text().strip()
        if step:
            opts.append(f"step={step}")

        # format / merge / dest
        fmt = self.format_box.currentText().strip()
        opts.append(f"format={fmt}")

        merge = "Y" if self.merge_box.currentIndex() == 0 else "N"
        opts.append(f"merge={merge}")

        dest_choice = self.dest_box.currentText()
        if dest_choice.startswith("stream"):
            opts.append("dest=stream")
        elif dest_choice.startswith("B:"):
            opts.append("dest=B:")
        elif dest_choice.startswith("A:"):
            opts.append("dest=A:")

        cmd = "COPYD " + " ".join(opts)
        self.copyd_preview.setText(cmd)

    def data_export_wizard_clicked(self):
        self.data_build_copyd_preview()
        cmdline = self.copyd_preview.text().strip()
        if not cmdline.startswith("COPYD"):
            QMessageBox.warning(self, "COPYD not ready", "Press Build COPYD first.")
            return

        # For stream export, we capture stream & save to PC file
        if "dest=stream" in cmdline.lower():
            path, _ = QFileDialog.getSaveFileName(
                self, "Save Export", "dt80_export.csv", "CSV Files (*.csv);;All Files (*)"
            )
            if not path:
                return
            # send only the options part to the session method
            options = cmdline[len("COPYD"):].strip()
            self.session.data_copyd_export(options=options, save_path=path, capture_s=120.0)
        else:
            # For B:/A: destinations, just run it (file written on device/USB)
            self.session.run_command(cmdline, read_window_s=1.2)
            QMessageBox.information(
                self, "COPYD started",
                "COPYD has been sent.\n\nSince destination is not stream, the file will be created on the device/USB."
            )

    def _build_store_selection_options(self) -> list[str]:
        """
        These options are shared between LISTD/COPYD/DELD store-selection:
        job=, sched=, data=, alarms=, live=, archive=.
        Manual: DELD store-selection options are identical to LISTD (different defaults). :contentReference[oaicite:4]{index=4}
        """
        opts = []

        job_val = self.data_job.currentData()
        if job_val:
            opts.append(f'job="{job_val}"')

        sched_val = (self.data_sched.currentText() or "").strip()
        if sched_val and not sched_val.startswith("("):
            opts.append(f"sched={sched_val}")

        opts.append(f"data={'Y' if self.chk_data.isChecked() else 'N'}")
        opts.append(f"alarms={'Y' if self.chk_alarms.isChecked() else 'N'}")
        opts.append(f"live={'Y' if self.chk_live.isChecked() else 'N'}")
        opts.append(f"archive={'Y' if self.chk_archive.isChecked() else 'N'}")
        return opts

    def data_build_deld_preview(self):
        """
        DELD supports end= but NOT start=. :contentReference[oaicite:5]{index=5}
        """
        opts = self._build_store_selection_options()

        end_val = (self.deld_end.text() or "").strip()
        if end_val:
            # user can type "-30T" or full timestamp or "delete-all"
            if end_val.lower() in ("delete-all", "deleteall", "all"):
                opts.append("end=delete-all")
            # user-friendly alias (you can remove if you prefer)
            else:
                opts.append(f"end={end_val}")

        # id= exists for tracking last unload time logic. :contentReference[oaicite:6]{index=6}
        id_val = int(self.deld_id.value())
        opts.append(f"id={id_val}")

        cmd = "DELD " + " ".join(opts)
        self.deld_preview.setText(cmd)

    def data_preview_listd_clicked(self):
        """
        Safety preview: show which stores match selection using LISTD.
        Manual: same store-selection options as LISTD. :contentReference[oaicite:7]{index=7}
        """
        opts = self._build_store_selection_options()
        cmd = "LISTD " + " ".join(opts)
        txt = self.session.run_command_capture(cmd, read_window_s=2.0)
        self.listd_view.setPlainText(txt)

    def data_delete_wizard_clicked(self):
        """
        Sends DELD with confirmation.
        - Default archive is N, so user must tick Archive stores if they want that. :contentReference[oaicite:8]{index=8}
        """
        self.data_build_deld_preview()
        cmdline = self.deld_preview.text().strip()
        if not cmdline.startswith("DELD"):
            QMessageBox.warning(self, "DELD not ready", "Press Build DELD first.")
            return

        archive_checked = self.chk_archive.isChecked()
        end_val = (self.deld_end.text() or "").strip()

        warn = []
        warn.append("This will permanently delete logged records.")
        if not end_val:
            warn.append("⚠ No end= set → this may delete ALL records in the selected stores.")
        if not archive_checked:
            warn.append("Note: archive=N → archive files will NOT be deleted unless you tick 'Archive stores'.")

        ok = QMessageBox.question(
            self,
            "Confirm DELD",
            "\n".join(warn) + "\n\nStrongly recommended: click 'Preview Selection (LISTD)' first.",
            QMessageBox.Yes | QMessageBox.No
        )
        if ok != QMessageBox.Yes:
            return

        # Send only options to the DT80Session helper (it prepends DELD)
        options = cmdline[len("DELD"):].strip()
        self.session.data_deld(options)

    def del_all_jobs_clicked(self):
        msg = (
            "DELALLJOBS will:\n"
            "• halt and delete the current job (including any logged data and alarms)\n"
            "• delete all other stored jobs and logged data under B:\\JOBS\n\n"
            "IMPORTANT:\n"
            "• Locked jobs will NOT be deleted. Use UNLOCKJOB first.\n\n"
            "Type DELETE to confirm:"
        )
        text, ok = QMessageBox.getText(self, "Confirm DELALLJOBS", msg)
        if not ok:
            return
        if (text or "").strip().upper() != "DELETE":
            QMessageBox.information(self, "Cancelled", "Confirmation text did not match. Nothing deleted.")
            return

        self.session.op_del_all_jobs()


def main():
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
