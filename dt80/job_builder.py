from dataclasses import dataclass

CHANNEL_TYPES = [
    ("V (Voltage)", "V"),
    ("TT (Thermocouple auto)", "TT"),
    ("TK (Thermocouple K)", "TK"),
    ("TJ (Thermocouple J)", "TJ"),
    ("TR (Thermocouple R)", "TR"),
    ("TS (Thermocouple S)", "TS"),
    ("TB (Thermocouple B)", "TB"),
    ("PT (Platinum RTD)", "PT"),
    ("RH (Humidity)", "RH"),
    ("A (Analog generic)", "A"),
]

SCHEDULE_LETTERS = ["A","B","C","D","E","F","G","H","I","J","K"]


@dataclass
class ChannelDef:
    ch_no: int
    ch_code: str
    label: str = ""
    extra: str = ""  # raw extra params like FF4, scaling, etc.

    def to_line(self) -> str:
        label = (self.label or "").strip()
        extra = (self.extra or "").strip()

        if not label and not extra:
            return f"{self.ch_no}{self.ch_code}"

        if label and not extra:
            return f'{self.ch_no}{self.ch_code}("{label}")'

        if not label and extra:
            return f"{self.ch_no}{self.ch_code}({extra})"

        return f'{self.ch_no}{self.ch_code}("{label}",{extra})'


@dataclass
class ScheduleDef:
    letter: str
    store: str = ""
    interval_value: int = 10
    interval_unit: str = "S"
    channel_tokens: list[str] = None

    def to_line(self) -> str:
        letter = self.letter.strip().upper()
        store = (self.store or "").strip()
        unit = self.interval_unit.strip().upper()
        tokens = self.channel_tokens or []

        head = f"R{letter}"
        if store:
            head += f"({store})"
        head += f"{self.interval_value}{unit}"
        if tokens:
            head += " " + " ".join(tokens)
        return head


def build_job_text(job_name: str, channels: list[ChannelDef], schedules: list[ScheduleDef],
                  include_logon: bool = True) -> str:
    name = (job_name or "").strip() or "Job01"
    lines = [f'BEGIN "{name}"', ""]

    if channels:
        lines.append("; === Channel Definitions ===")
        for ch in channels:
            lines.append(ch.to_line())
        lines.append("")

    if schedules:
        lines.append("; === Schedules ===")
        for sc in schedules:
            lines.append(sc.to_line())
        lines.append("")

    if include_logon:
        lines.append("; === Logging ===")
        lines.append("LOGON")
        lines.append("")

    lines.append("END")
    return "\r\n".join(lines) + "\r\n"
