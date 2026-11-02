"""Where this machine can be reached on the home network (shown on the TV so a browser knows where to go)."""
import socket

PORT = 8090


def lan_ip():
    """The address other devices on the network use for this machine, or None when it has no network."""
    for probe in ('192.0.2.1', '10.255.255.255'):            # no packet is sent: connecting a UDP socket only picks a route
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect((probe, 9))
            ip = s.getsockname()[0]
            if ip and not ip.startswith('127.') and ip != '0.0.0.0':
                return ip
        except OSError:
            continue
        finally:
            s.close()
    return None


def studio_address(port=PORT):
    ip = lan_ip()
    return 'http://%s:%d' % (ip, port) if ip else None
