"""Client certificates for logging in without a password (SASL EXTERNAL / CertFP).

Make New writes one .pem with the certificate and its private key into the settings folder (certs\\<network>.pem).
The key is never sent anywhere: the server only sees the certificate during the SSL handshake."""
from __future__ import annotations

import datetime
import re
from pathlib import Path

from PySide6.QtCore import QCryptographicHash
from PySide6.QtNetwork import QSsl, QSslCertificate, QSslKey


def safe_name(network: str) -> str:
    name = re.sub(r"[^\w.-]+", "_", network).strip("._") or "network"
    return name[:60]


def make(path: Path, common_name: str) -> Path:
    """A new key + self-signed certificate (EC P-256, 10 years) in one .pem. An old file of that name is replaced."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, (common_name or "BChat")[:64])])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=3650)).sign(key, hashes.SHA256()))
    path.parent.mkdir(parents=True, exist_ok=True)
    data = cert.public_bytes(serialization.Encoding.PEM) + key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    path.write_bytes(data)
    return path


def _read(path: str) -> bytes:
    try:
        return Path(path).read_bytes() if path else b""
    except OSError:
        return b""


def load(path: str) -> tuple[QSslCertificate, QSslKey] | None:
    """The certificate and key from one .pem (or a .crt with a .key next to it). None when either is missing."""
    data = _read(path)
    if not data:
        return None
    certs = QSslCertificate.fromData(data, QSsl.EncodingFormat.Pem)
    if not certs or certs[0].isNull():
        return None
    key_data = data if b"PRIVATE KEY" in data else _read(str(Path(path).with_suffix(".key")))
    for algo in (QSsl.KeyAlgorithm.Ec, QSsl.KeyAlgorithm.Rsa, QSsl.KeyAlgorithm.Dsa):
        key = QSslKey(key_data, algo, QSsl.EncodingFormat.Pem)
        if not key.isNull():
            return certs[0], key
    return None


def fingerprint(cert: QSslCertificate, algo=QCryptographicHash.Algorithm.Sha256) -> str:
    """aa:bb:cc... the way services show it."""
    return ":".join(f"{b:02x}" for b in bytes(cert.digest(algo)))


def short(fp: str) -> str:
    parts = fp.split(":")
    return fp if len(parts) <= 8 else ":".join(parts[:4]) + ":…:" + ":".join(parts[-2:])


def describe(path: str) -> tuple[str, str, str] | None:
    """(file name, made date, SHA-256 fingerprint) for the Edit Network window."""
    pair = load(path)
    if pair is None:
        return None
    cert = pair[0]
    return Path(path).name, cert.effectiveDate().toString("d MMM yyyy"), fingerprint(cert)
