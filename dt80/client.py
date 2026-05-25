import time
from dataclasses import dataclass
from typing import Callable, Optional
from .transport import BaseTransport


@dataclass
class RunResult:
    sent: str
    received_lines: list[str]


class DT80Client:
    def __init__(self, transport: BaseTransport, on_log: Optional[Callable[[str], None]] = None):
        self.t = transport
        self.on_log = on_log

    def log(self, msg: str):
        if self.on_log:
            self.on_log(msg)

    def connect(self):
        self.t.connect()
        self.log("Connected.")

    def close(self):
        self.t.close()
        self.log("Disconnected.")

    def run(self, command_line: str, read_window_s: float = 0.6) -> RunResult:
        """
        Sends one command line and reads whatever comes back for a short window.
        """
        cmd = command_line.strip()
        self.t.write_line(cmd)
        self.log(f"→ {cmd}")

        deadline = time.time() + read_window_s
        buf = ""
        while time.time() < deadline:
            chunk = self.t.read_available()
            if chunk:
                buf += chunk
            time.sleep(0.02)

        lines = [ln.rstrip() for ln in buf.splitlines() if ln.strip()]
        for ln in lines:
            self.log(f"← {ln}")
        return RunResult(sent=cmd, received_lines=lines)

    def send_block(self, text: str, per_line_delay_ms: int = 30):
        """
        Send multi-line BEGIN...END blocks line-by-line.
        """
        for ln in text.splitlines():
            ln = ln.strip()
            if not ln:
                continue
            self.run(ln, read_window_s=0.2)
            time.sleep(per_line_delay_ms / 1000.0)

    # ---------------- Operator-friendly helpers ----------------
    def list_jobs(self) -> list[str]:
        """
        Uses DIRJOBS output; returns clean job names.
        DT80 output may include markers like * or + ; we'll strip them.
        """
        res = self.run("DIRJOBS", read_window_s=1.2)
        jobs = []
        for line in res.received_lines:
            s = line.strip()
            if not s:
                continue
            s = s.replace("*", "").replace("+", "").strip()
            # ignore prompt-like or headings if any
            if s.upper().startswith("DT80"):
                continue
            jobs.append(s)

        # de-dup preserve order
        out = []
        for j in jobs:
            if j not in out:
                out.append(j)
        return out

    def start_all_schedules(self):
        self.run("G", read_window_s=0.6)

    def stop_all_schedules(self):
        self.run("H", read_window_s=0.6)

    def start_logging(self):
        self.run("LOGON", read_window_s=0.8)

    def stop_logging(self):
        self.run("LOGOFF", read_window_s=0.8)

    def run_job(self, job_name: str):
        job = (job_name or "").strip().strip('"')
        return self.run(f'RUNJOB "{job}"', read_window_s=1.2)

    # ---------------- System / Info ----------------
    def ver(self):
        return self.run("VER", read_window_s=1.2)

    def help(self):
        return self.run("HELP", read_window_s=1.6)

    def free(self):
        return self.run("FREE", read_window_s=1.2)

    def restart(self):
        # Soft restart (device reboots / reconnect needed after)
        return self.run("RESTART", read_window_s=0.8)

    def reset(self):
        # Hard reset (stronger than restart; reconnect needed after)
        return self.run("RESET", read_window_s=0.8)

    def get_time(self):
        return self.run("TIME", read_window_s=1.2)

    def set_time(self, timestr: str):
        # timestr format depends on DT80 manual (often YYYY-MM-DDThh:mm:ss or similar)
        return self.run(f"SETTIME {timestr}", read_window_s=1.2)

    # ---------------- Profiles ----------------
    def profile_save(self):
        return self.run("PROFILE SAVE", read_window_s=1.4)

    def profile_load(self):
        return self.run("PROFILE LOAD", read_window_s=1.4)

    def profile_default(self):
        return self.run("PROFILE DEFAULT", read_window_s=1.4)

    def profile_copy(self, src: str, dst: str):
        # Example style: PROFILE COPY src dst  (depends on DT80 syntax; we keep it generic)
        src = (src or "").strip()
        dst = (dst or "").strip()
        return self.run(f"PROFILE COPY {src} {dst}", read_window_s=1.6)

    # ---------------- Schedule-specific control ----------------
    def start_schedule(self, letter: str):
        letter = (letter or "").strip().upper()
        return self.run(f"G{letter}", read_window_s=0.8)

    def stop_schedule(self, letter: str):
        letter = (letter or "").strip().upper()
        return self.run(f"H{letter}", read_window_s=0.8)

    # ---------------- Job management ----------------
    def show_prog(self, job_name: str):
        job = (job_name or "").strip().strip('"')
        return self.run(f'SHOWPROG "{job}"', read_window_s=1.8)

    def lock_job(self, job_name: str):
        job = (job_name or "").strip().strip('"')
        return self.run(f'LOCKJOB "{job}"', read_window_s=1.2)

    def unlock_job(self, job_name: str):
        job = (job_name or "").strip().strip('"')
        return self.run(f'UNLOCKJOB "{job}"', read_window_s=1.2)

    def del_job(self, job_name: str):
        job = (job_name or "").strip().strip('"')
        return self.run(f'DELJOB "{job}"', read_window_s=1.6)

    # ---------------- Data / unload ----------------
    def listd(self):
        return self.run("LISTD", read_window_s=2.2)

    def deld(self, options: str):
        opt = (options or "").strip()
        cmd = "DELD" + ((" " + opt) if opt else "")
        return self.run(cmd, read_window_s=2.2)

    def cancel_unload(self):
        return self.run("Q", read_window_s=0.8)

    def copyd_stream(self, options: str, max_s: float = 120.0, idle_end_s: float = 1.2) -> str:
        """
        COPYD to dest=stream can be large. We capture until:
          - no incoming data for idle_end_s seconds (after first data arrives), OR
          - max_s seconds total (safety cutoff)
        """
        cmd = "COPYD" + ((" " + options.strip()) if options.strip() else "")
        self.t.write_line(cmd)
        self.log(f"→ {cmd}")

        start = time.time()
        buf = ""
        saw_data = False
        last_data_t = time.time()

        while True:
            chunk = self.t.read_available()
            if chunk:
                buf += chunk
                saw_data = True
                last_data_t = time.time()
                # optional preview log (avoid too noisy on huge exports)
                for ln in chunk.splitlines()[:20]:
                    ln = ln.rstrip()
                    if ln.strip():
                        self.log(f"← {ln}")

            now = time.time()
            if now - start > max_s:
                self.log("COPYD capture stopped (max time).")
                break

            # If we already started receiving unload stream, stop when idle for a bit
            if saw_data and (now - last_data_t) > idle_end_s:
                self.log("COPYD capture complete (idle).")
                break

            time.sleep(0.02)

        return buf

