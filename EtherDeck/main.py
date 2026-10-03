import asyncio
import fcntl
import socket
import struct
import subprocess
import time
from glob import glob
from pathlib import Path

import decky

GADGET = Path("/sys/kernel/config/usb_gadget/deck_eth")
DECK_IP = "10.55.0.1"
HOST_IP = "10.55.0.2"
PREFIX = 24
LANG = "0x409"

# Original role of each role-switch / dwc3 mode file, so we can restore it on disable.
_saved_roles: dict[str, str] = {}


def _run(*cmd: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        return subprocess.CompletedProcess(cmd, 127, "", f"{cmd[0]}: not found")


def _w(path, value: str) -> None:
    Path(path).write_text(value)


def _r(path) -> str:
    return Path(path).read_text().strip()


# ---------------------------------------------------------------- USB role (DRD)

def _role_files() -> list[tuple[str, str, str]]:
    """Return (path, device_value, host_value) for every way we know to flip the port role."""
    files = [(p, "device", "host") for p in glob("/sys/class/usb_role/*/role")]
    if not files:
        _run("mount", "-t", "debugfs", "none", "/sys/kernel/debug")  # no-op if mounted
        for p in glob("/sys/kernel/debug/usb/*/mode"):
            try:
                if _r(p) in ("host", "device", "otg"):
                    files.append((p, "device", "host"))
            except OSError:
                pass
    return files


def _set_device_role() -> None:
    files = _role_files()
    if not files:
        raise RuntimeError("No USB role switch found (usb_role / dwc3 debugfs)")
    ok = False
    for path, dev, _ in files:
        try:
            _saved_roles.setdefault(path, _r(path))
            _w(path, dev)
            ok = True
        except OSError as e:
            decky.logger.warning(f"role write failed for {path}: {e}")
    if not ok:
        raise RuntimeError("Could not switch the USB port to device mode")


def _restore_role() -> None:
    for path, original in list(_saved_roles.items()):
        try:
            _w(path, original)
        except OSError as e:
            decky.logger.warning(f"role restore failed for {path}: {e}")
    _saved_roles.clear()


# ---------------------------------------------------------------- gadget lifecycle

def _udc_name() -> str | None:
    deadline = time.time() + 4
    while time.time() < deadline:
        udcs = sorted(p.name for p in Path("/sys/class/udc").glob("*"))
        if udcs:
            return udcs[0]
        time.sleep(0.2)
    return None


def _create_gadget(udc: str) -> None:
    g = GADGET
    g.mkdir(parents=True, exist_ok=True)
    _w(g / "idVendor", "0x1d6b")
    _w(g / "idProduct", "0x0104")
    _w(g / "bcdDevice", "0x0100")
    _w(g / "bcdUSB", "0x0200")
    # Composite device with IAD (needed for RNDIS on Windows)
    _w(g / "bDeviceClass", "0xEF")
    _w(g / "bDeviceSubClass", "0x02")
    _w(g / "bDeviceProtocol", "0x01")

    (g / "strings" / LANG).mkdir(parents=True, exist_ok=True)
    _w(g / "strings" / LANG / "serialnumber", "steamdeck-eth0")
    _w(g / "strings" / LANG / "manufacturer", "Valve")
    _w(g / "strings" / LANG / "product", "Steam Deck USB Ethernet")

    # Windows picks the first configuration (RNDIS); Linux/macOS use the second (ECM).
    rndis = g / "functions" / "rndis.usb0"
    ecm = g / "functions" / "ecm.usb0"
    rndis.mkdir(parents=True, exist_ok=True)
    ecm.mkdir(parents=True, exist_ok=True)
    _w(rndis / "host_addr", "02:de:ec:00:01:01")
    _w(rndis / "dev_addr", "02:de:ec:00:01:02")
    _w(ecm / "host_addr", "02:de:ec:00:02:01")
    _w(ecm / "dev_addr", "02:de:ec:00:02:02")

    # Microsoft OS descriptors so Windows binds the RNDIS driver automatically
    _w(g / "os_desc" / "use", "1")
    _w(g / "os_desc" / "b_vendor_code", "0xcd")
    _w(g / "os_desc" / "qw_sign", "MSFT100")
    _w(rndis / "os_desc" / "interface.rndis" / "compatible_id", "RNDIS")
    _w(rndis / "os_desc" / "interface.rndis" / "sub_compatible_id", "5162001")

    for cfg, label, func in (("c.1", "RNDIS", rndis), ("c.2", "ECM", ecm)):
        c = g / "configs" / cfg
        (c / "strings" / LANG).mkdir(parents=True, exist_ok=True)
        _w(c / "strings" / LANG / "configuration", label)
        _w(c / "MaxPower", "250")
        (c / func.name).symlink_to(func)
    (g / "os_desc" / "c.1").symlink_to(g / "configs" / "c.1")

    _w(g / "UDC", udc)


def _destroy_gadget() -> None:
    g = GADGET
    if not g.exists():
        return
    try:
        _w(g / "UDC", "\n")
    except OSError:
        pass
    for link in (g / "os_desc").glob("c.*"):
        if link.is_symlink():
            link.unlink()
    for cfg in (g / "configs").glob("c.*"):
        for item in cfg.iterdir():
            if item.is_symlink():
                item.unlink()
        s = cfg / "strings" / LANG
        if s.exists():
            s.rmdir()
        cfg.rmdir()
    for fn in (g / "functions").glob("*"):
        fn.rmdir()
    s = g / "strings" / LANG
    if s.exists():
        s.rmdir()
    g.rmdir()


def _is_enabled() -> bool:
    try:
        return GADGET.exists() and _r(GADGET / "UDC") != ""
    except OSError:
        return False


def _ifnames() -> list[str]:
    names = []
    for f in (GADGET / "functions").glob("*/ifname"):
        try:
            n = _r(f)
            if n:
                names.append(n)
        except OSError:
            pass
    return names


_up: set[str] = set()
_addr: set[str] = set()


def _iface_ip(name: str) -> str | None:
    """Primary IPv4 address currently on an interface (SIOCGIFADDR), or None."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        res = fcntl.ioctl(sock.fileno(), 0x8915, struct.pack("256s", name.encode()[:15]))
        return socket.inet_ntoa(res[20:24])
    except OSError:
        return None
    finally:
        sock.close()


def _sync_interfaces() -> list[str]:
    """Bring gadget interfaces up and keep the Deck's IP on whichever one the host activated.

    Returns the interfaces that currently have carrier (i.e. a host is attached).
    """
    active = []
    for name in _ifnames():
        if name not in _up:
            # Stop NetworkManager from managing (and wiping the address of) the gadget NIC.
            r = _run("nmcli", "device", "set", name, "managed", "no")
            decky.logger.info(f"nmcli unmanage {name}: rc={r.returncode} {r.stderr.strip()}")
            _run("ip", "link", "set", name, "up")
            _up.add(name)
        try:
            carrier = _r(f"/sys/class/net/{name}/carrier")
        except OSError:
            carrier = "0"
        if carrier == "1":
            if _iface_ip(name) != DECK_IP:
                r = _run("ip", "addr", "replace", f"{DECK_IP}/{PREFIX}", "dev", name)
                decky.logger.info(f"assigned {DECK_IP} to {name}: rc={r.returncode} {r.stderr.strip()}")
                _addr.add(name)
            active.append(name)
        elif name in _addr:
            _run("ip", "addr", "flush", "dev", name)
            _addr.discard(name)
    return active


# ---------------------------------------------------------------- tiny DHCP server
# Offers a single address (HOST_IP) to whatever is plugged in. Deliberately sends NO router
# or DNS option, so the connected computer never routes its internet traffic via the Deck.

MAGIC = b"\x63\x82\x53\x63"
LEASE_SECONDS = 3600


def _dhcp_reply(pkt: bytes) -> bytes | None:
    if len(pkt) < 240 or pkt[0] != 1 or pkt[236:240] != MAGIC:
        return None
    opts: dict[int, bytes] = {}
    i = 240
    while i < len(pkt):
        code = pkt[i]
        if code == 255:
            break
        if code == 0:
            i += 1
            continue
        if i + 1 >= len(pkt):
            break
        length = pkt[i + 1]
        opts[code] = pkt[i + 2 : i + 2 + length]
        i += 2 + length

    mtype = opts.get(53, b"\x00")[0]
    if mtype not in (1, 3):  # DISCOVER, REQUEST
        return None
    server = socket.inet_aton(DECK_IP)
    if opts.get(54) and opts[54] != server:  # request addressed to some other DHCP server
        return None

    host = socket.inet_aton(HOST_IP)
    zero = b"\x00\x00\x00\x00"
    ciaddr = pkt[12:16]
    requested = opts.get(50) or (ciaddr if ciaddr != zero else None)
    if mtype == 1:
        rtype = 2  # OFFER
    elif requested and requested != host:
        rtype = 6  # NAK
    else:
        rtype = 5  # ACK

    header = (
        bytes([2, pkt[1], pkt[2], 0])  # op=reply, htype, hlen, hops
        + pkt[4:8]  # xid
        + b"\x00\x00" + pkt[10:12]  # secs, flags
        + zero  # ciaddr
        + (host if rtype != 6 else zero)  # yiaddr
        + server  # siaddr
        + pkt[24:28]  # giaddr
        + pkt[28:44]  # chaddr
        + b"\x00" * 192  # sname + file
        + MAGIC
    )
    options = bytes([53, 1, rtype]) + bytes([54, 4]) + server
    if rtype != 6:
        options += bytes([51, 4]) + LEASE_SECONDS.to_bytes(4, "big")
        options += bytes([1, 4]) + socket.inet_aton("255.255.255.0")
    options += b"\xff"
    return header + options


def _ip_checksum(header: bytes) -> int:
    total = sum(struct.unpack("!%dH" % (len(header) // 2), header))
    while total >> 16:
        total = (total & 0xFFFF) + (total >> 16)
    return ~total & 0xFFFF


def _udp_payload_for_port(frame: bytes, port: int) -> bytes | None:
    """If an Ethernet frame is IPv4/UDP to `port`, return the UDP payload."""
    if len(frame) < 14 + 20 + 8 or frame[12:14] != b"\x08\x00":
        return None
    ihl = (frame[14] & 0x0F) * 4
    if frame[14 + 9] != 17 or len(frame) < 14 + ihl + 8:
        return None
    dport = struct.unpack("!H", frame[14 + ihl + 2 : 14 + ihl + 4])[0]
    if dport != port:
        return None
    return frame[14 + ihl + 8 :]


def _build_frame(src_mac: bytes, payload: bytes) -> bytes:
    """Ethernet+IPv4+UDP broadcast frame: DECK_IP:67 -> 255.255.255.255:68."""
    udp = struct.pack("!HHHH", 67, 68, 8 + len(payload), 0) + payload  # UDP csum 0 = none
    ip_nock = struct.pack(
        "!BBHHHBBH4s4s", 0x45, 0, 20 + len(udp), 0, 0, 64, 17, 0,
        socket.inet_aton(DECK_IP), socket.inet_aton("255.255.255.255"),
    )
    ip = ip_nock[:10] + struct.pack("!H", _ip_checksum(ip_nock)) + ip_nock[12:]
    return b"\xff" * 6 + src_mac + b"\x08\x00" + ip + udp


class _DhcpServer:
    """DHCP responder on a raw packet socket (bypasses UDP sockets / firewall / bind quirks)."""

    def __init__(self, ifname: str) -> None:
        self.ifname = ifname
        self.mac = bytes.fromhex(_r(f"/sys/class/net/{ifname}/address").replace(":", ""))
        self.sock = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(0x0800))
        self.sock.bind((ifname, 0))
        self.sock.setblocking(False)
        self.loop = asyncio.get_running_loop()
        self.loop.add_reader(self.sock.fileno(), self._on_readable)

    def _on_readable(self) -> None:
        while True:
            try:
                frame, addr = self.sock.recvfrom(2048)
            except BlockingIOError:
                return
            except OSError as e:
                decky.logger.error(f"DHCP[{self.ifname}] recv error: {e}")
                return
            if addr[2] == 4:  # PACKET_OUTGOING: our own transmissions
                continue
            payload = _udp_payload_for_port(frame, 67)
            if payload is None:
                continue
            mac = payload[28:34].hex(":") if len(payload) >= 34 else "?"
            try:
                reply = _dhcp_reply(payload)
            except Exception as e:  # noqa: BLE001
                decky.logger.warning(f"DHCP[{self.ifname}] bad packet from {mac}: {e}")
                continue
            if not reply:
                decky.logger.info(f"DHCP[{self.ifname}]: ignored packet from {mac}")
                continue
            decky.logger.info(f"DHCP[{self.ifname}]: replying type {reply[242]} to {mac}")
            try:
                self.sock.send(_build_frame(self.mac, reply))
            except OSError as e:
                decky.logger.error(f"DHCP[{self.ifname}] send error: {e}")

    def close(self) -> None:
        try:
            self.loop.remove_reader(self.sock.fileno())
        finally:
            self.sock.close()


def _state(error: str | None = None) -> dict:
    return {"enabled": _is_enabled(), "error": error, "deck_ip": DECK_IP, "host_ip": HOST_IP}


def _enable() -> None:
    _run("modprobe", "libcomposite")
    _set_device_role()
    udc = _udc_name()
    if not udc:
        raise RuntimeError("No USB device controller appeared (kernel gadget support missing?)")
    _create_gadget(udc)


def _disable() -> None:
    _up.clear()
    _addr.clear()
    _destroy_gadget()
    _restore_role()


# ---------------------------------------------------------------- Decky plugin

class Plugin:
    _watcher: asyncio.Task | None = None
    _dhcp: dict[str, "_DhcpServer"] = {}

    async def get_state(self) -> dict:
        return _state()

    async def set_enabled(self, enable: bool) -> dict:
        try:
            if enable:
                await asyncio.to_thread(_enable)
            else:
                await asyncio.to_thread(_disable)
            return _state()
        except Exception as e:  # noqa: BLE001
            decky.logger.error(f"set_enabled({enable}) failed: {e}")
            try:
                await asyncio.to_thread(_disable)
            except Exception as cleanup_err:  # noqa: BLE001
                decky.logger.error(f"cleanup failed: {cleanup_err}")
            return _state(str(e))

    async def _update_dhcp(self, active: list[str]) -> None:
        for name in active:
            if name not in Plugin._dhcp:
                try:
                    Plugin._dhcp[name] = _DhcpServer(name)
                    decky.logger.info(f"DHCP server started on {name}")
                except Exception as e:  # noqa: BLE001
                    decky.logger.error(f"could not start DHCP on {name}: {e}")
        for name in [n for n in Plugin._dhcp if n not in active]:
            Plugin._dhcp.pop(name).close()
            decky.logger.info(f"DHCP server stopped on {name}")

    async def _watch(self) -> None:
        while True:
            await asyncio.sleep(1)
            active: list[str] = []
            if _is_enabled():
                try:
                    active = await asyncio.to_thread(_sync_interfaces)
                except Exception as e:  # noqa: BLE001
                    decky.logger.error(f"interface sync failed: {e}")
            await self._update_dhcp(active)

    async def _main(self):
        Plugin._watcher = asyncio.create_task(self._watch())
        decky.logger.info("USB Ethernet Gadget loaded")

    async def _unload(self):
        if Plugin._watcher:
            Plugin._watcher.cancel()
        await self._update_dhcp([])
        await asyncio.to_thread(_disable)

    async def _uninstall(self):
        await asyncio.to_thread(_disable)
