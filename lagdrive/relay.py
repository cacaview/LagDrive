"""Echo Relay — TCP relay server that echoes data back verbatim.

The foundation of LagDrive's real storage: data is sent to the relay,
which echoes it back. While data is "on the wire," it exists in the
network pipe — the BDP of that pipe is the storage capacity.

Wire protocol:
    +----------+--------+----------+------+
    | magic(2) | type(1)| length(4)| body |
    +----------+--------+----------+------+

    MAGIC = b'LD' (0x4C44)
    TYPE: 0x01=WRITE, 0x02=ECHO
    Header = 7 bytes (struct: !2sBI)
    WRITE/ECHO body: block_id(u64) + offset(u64) + data
"""

import socket
import socketserver
import struct
import threading
import time

# --- Protocol constants ---

MAGIC = b'\x4c\x44'  # "LD"
TYPE_WRITE = 0x01
TYPE_ECHO = 0x02

_HEADER_FMT = '!2sBI'
_HEADER_SIZE = struct.calcsize(_HEADER_FMT)  # 7 bytes
_MAX_BODY_SIZE = 1024 * 1024  # 1 MB safety limit

_HEADER_STRUCT = struct.Struct(_HEADER_FMT)
_BLOCK_HEADER_FMT = '!QQ'
_BLOCK_HEADER_STRUCT = struct.Struct(_BLOCK_HEADER_FMT)


class LagDriveProtocol:
    """Wire protocol encoder/decoder for LagDrive frames."""

    @staticmethod
    def encode_frame(frame_type: int, body: bytes) -> bytes:
        """Pack a frame: 7-byte header + body."""
        header = _HEADER_STRUCT.pack(MAGIC, frame_type, len(body))
        return header + body

    @staticmethod
    def encode_write(block_id: int, offset: int, data: bytes) -> bytes:
        """Pack a WRITE/ECHO frame body."""
        body = _BLOCK_HEADER_STRUCT.pack(block_id, offset) + data
        return LagDriveProtocol.encode_frame(TYPE_WRITE, body)

    @staticmethod
    def decode_frame(sock: socket.socket) -> tuple[int, bytes] | None:
        """Read one frame from socket. Returns (type, body) or None on close."""
        header = _recv_exact(sock, _HEADER_SIZE)
        if header is None:
            return None
        magic, frame_type, length = _HEADER_STRUCT.unpack(header)
        if magic != MAGIC:
            return None
        if length > _MAX_BODY_SIZE:
            return None
        if length == 0:
            return frame_type, b''
        body = _recv_exact(sock, length)
        if body is None:
            return None
        return frame_type, body

    @staticmethod
    def decode_block_body(body: bytes) -> tuple[int, int, bytes] | None:
        """Unpack block_id + offset + data from a WRITE/ECHO body."""
        if len(body) < _BLOCK_HEADER_STRUCT.size:
            return None
        block_id, offset = _BLOCK_HEADER_STRUCT.unpack_from(body)
        data = body[_BLOCK_HEADER_STRUCT.size:]
        return block_id, offset, data


def _recv_exact(sock: socket.socket, n: int) -> bytes | None:
    """Read exactly n bytes from socket. Returns None on disconnect."""
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)


# --- Echo Relay Server ---


class _EchoHandler(socketserver.StreamRequestHandler):
    """Handle one client connection: read WRITE frames, send back ECHO."""

    def handle(self) -> None:
        delay = getattr(self.server, 'echo_delay', 0.0)
        try:
            while True:
                result = LagDriveProtocol.decode_frame(self.request)
                if result is None:
                    break
                frame_type, body = result
                if frame_type != TYPE_WRITE:
                    continue
                if delay > 0:
                    time.sleep(delay)
                echo = LagDriveProtocol.encode_frame(TYPE_ECHO, body)
                self.request.sendall(echo)
        except (ConnectionResetError, BrokenPipeError, OSError):
            pass


class EchoRelay:
    """TCP echo relay server for LagDrive storage.

    Usage:
        # Blocking (CLI)
        relay = EchoRelay("0.0.0.0", 9527)
        relay.serve_forever()

        # Background thread
        relay = EchoRelay("127.0.0.1", 9527)
        relay.start()
        ...
        relay.stop()
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 9527,
                 echo_delay: float = 0.0) -> None:
        self.host = host
        self.port = port
        self.echo_delay = echo_delay
        self._server: socketserver.ThreadingTCPServer | None = None
        self._thread: threading.Thread | None = None

    def _create_server(self) -> socketserver.ThreadingTCPServer:
        server = socketserver.ThreadingTCPServer((self.host, self.port), _EchoHandler)
        server.allow_reuse_address = True
        server.daemon_threads = True
        server.echo_delay = self.echo_delay
        return server

    def start(self) -> None:
        """Start relay in a background thread."""
        if self._server is not None:
            return
        self._server = self._create_server()
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the relay server."""
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=2.0)
            self._server = None
            self._thread = None

    def serve_forever(self) -> None:
        """Start relay in blocking mode (for CLI)."""
        self._server = self._create_server()
        try:
            self._server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            self._server.server_close()

    @property
    def address(self) -> tuple[str, int]:
        return (self.host, self.port)
