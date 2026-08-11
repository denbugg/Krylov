"""Process-local network policy for ELITE bot runtime.

The VPS currently resolves api.telegram.org to IPv6 first while its IPv6 route is
unusable. Restrict urllib3/requests address resolution to IPv4 for this bot only,
without changing the host-wide network configuration.
"""
import socket

try:
    import urllib3.util.connection as urllib3_connection
except Exception:
    urllib3_connection = None

if urllib3_connection is not None:
    urllib3_connection.allowed_gai_family = lambda: socket.AF_INET
