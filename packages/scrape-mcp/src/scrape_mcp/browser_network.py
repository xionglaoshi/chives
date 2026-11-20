"""A per-browser SOCKS dialer. Connect only to IPs approved by the existing URL policy."""
from contextlib import contextmanager, closing
from ipaddress import ip_address
import select
import socket
import socketserver
from threading import Thread

from scrape_mcp.ssrf import parse_target


def _read(sock, size):
    data = bytearray()
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise EOFError
        data.extend(chunk)
    return bytes(data)


@contextmanager
def browser_network(settings, resolver):
    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            client = self.request
            client.settimeout(8)
            try:
                version, count = _read(client, 2)
                if version != 5 or 0 not in _read(client, count):
                    return
                client.sendall(b"\x05\x00")
                version, command, _, kind = _read(client, 4)
                if version != 5 or command != 1:
                    return
                if kind == 3:
                    host = _read(client, _read(client, 1)[0]).decode('ascii')
                    if any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-' for c in host):
                        return
                elif kind in (1, 4):
                    host = str(ip_address(_read(client, 4 if kind == 1 else 16)))
                    if kind == 4:
                        host = f"[{host}]"
                else:
                    return
                port = int.from_bytes(_read(client, 2), 'big')
                target = parse_target(f"https://{host}:{port}/", resolver=resolver,
                                      allow_hosts=settings.allow_hosts, allow_loopback=settings.allow_loopback)
                remote = None
                for address in target.ips:
                    try:
                        remote = socket.create_connection((address, port), timeout=5)
                        break
                    except OSError:
                        continue
                if remote is None:
                    return
                with closing(remote):
                    client.sendall(b"\x05\x00\x00\x01"+bytes(6))
                    while True:
                        readable, _, _ = select.select([client, remote], [], [], 30)
                        if not readable:
                            return
                        for source in readable:
                            data = source.recv(65536)
                            if not data:
                                return
                            (remote if source is client else client).sendall(data)
            except (OSError, ValueError, EOFError, RuntimeError):
                return

    with socketserver.ThreadingTCPServer(('127.0.0.1', 0), Handler) as server:
        server.daemon_threads = True
        thread = Thread(target=server.serve_forever, kwargs={'poll_interval': 0.05}, daemon=True)
        thread.start()
        try:
            yield f"socks5://127.0.0.1:{server.server_address[1]}"
        finally:
            server.shutdown()
            thread.join()
