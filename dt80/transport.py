import socket
from typing import Optional

class TransportError(Exception):
    pass


class BaseTransport:
    def connect(self) -> None: raise NotImplementedError
    def close(self) -> None: raise NotImplementedError
    def write_line(self, line: str) -> None: raise NotImplementedError
    def read_available(self) -> str: raise NotImplementedError
    @property
    def is_connected(self) -> bool: raise NotImplementedError


class SerialTransport(BaseTransport):
    def __init__(self, port: str, baud: int = 57600):
        self.port = port
        self.baud = baud
        self._ser = None

    def connect(self) -> None:
        try:
            import serial
            self._ser = serial.Serial(self.port, self.baud, timeout=0.1)
        except Exception as e:
            raise TransportError(f"Serial connect failed: {e}")

    def close(self) -> None:
        if self._ser:
            try:
                self._ser.close()
            finally:
                self._ser = None

    def write_line(self, line: str) -> None:
        if not self._ser:
            raise TransportError("Serial not connected")
        # DT80 executes when it receives a carriage return; we send CRLF. :contentReference[oaicite:5]{index=5}
        data = (line.rstrip("\r\n") + "\r\n").encode("ascii", errors="ignore")
        self._ser.write(data)

    def read_available(self) -> str:
        if not self._ser:
            return ""
        try:
            n = self._ser.in_waiting
            if n <= 0:
                return ""
            raw = self._ser.read(n)
            return raw.decode("ascii", errors="ignore")
        except Exception:
            return ""

    @property
    def is_connected(self) -> bool:
        return self._ser is not None


class TcpTransport(BaseTransport):
    def __init__(self, host: str, port: int = 7700):
        self.host = host
        self.port = port
        self._sock: Optional[socket.socket] = None

    def connect(self) -> None:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(3.0)
            s.connect((self.host, self.port))  # default network command port 7700 :contentReference[oaicite:6]{index=6}
            s.settimeout(0.1)
            self._sock = s
        except Exception as e:
            raise TransportError(f"TCP connect failed: {e}")

    def close(self) -> None:
        if self._sock:
            try:
                try:
                    self._sock.shutdown(socket.SHUT_RDWR)
                except Exception:
                    pass
                self._sock.close()
            finally:
                self._sock = None

    def write_line(self, line: str) -> None:
        if not self._sock:
            raise TransportError("TCP not connected")
        data = (line.rstrip("\r\n") + "\r\n").encode("ascii", errors="ignore")
        self._sock.sendall(data)

    def read_available(self) -> str:
        if not self._sock:
            return ""
        try:
            chunk = self._sock.recv(4096)
            return chunk.decode("ascii", errors="ignore") if chunk else ""
        except (socket.timeout, BlockingIOError):
            return ""
        except Exception:
            return ""

    @property
    def is_connected(self) -> bool:
        return self._sock is not None
