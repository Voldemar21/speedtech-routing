"""Minimal geosite.dat / geoip.dat writer and v2fly domain-list-community parser.

No third-party dependencies: protobuf is encoded by hand.

Xray/v2fly schema (routercommon.proto):
  GeoSiteList { repeated GeoSite entry = 1; }
  GeoSite     { string country_code = 1; repeated Domain domain = 2; }
  Domain      { Type type = 1; string value = 2; }   Type: Plain=0 Regex=1 Domain=2 Full=3
  GeoIPList   { repeated GeoIP entry = 1; }
  GeoIP       { string country_code = 1; repeated CIDR cidr = 2; }
  CIDR        { bytes ip = 1; uint32 prefix = 2; }
"""
import io
import ipaddress
import re
import tarfile

RULE_TYPES = {"keyword": 0, "regexp": 1, "domain": 2, "full": 3}
_DOMAIN_RE = re.compile(r"^[a-z0-9_-]+(\.[a-z0-9_-]+)*$")


def _varint(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _len_delim(field, data):
    return _varint((field << 3) | 2) + _varint(len(data)) + data


def _uint(field, n):
    return _varint(field << 3) + _varint(n)


def encode_geosite(categories):
    """categories: {code: iterable of (type, value)} -> bytes"""
    out = bytearray()
    for code in sorted(categories):
        site = bytearray(_len_delim(1, code.upper().encode()))
        for rtype, value in sorted(categories[code]):
            t = RULE_TYPES[rtype]
            dom = (_uint(1, t) if t else b"") + _len_delim(2, value.encode())
            site += _len_delim(2, dom)
        out += _len_delim(1, bytes(site))
    return bytes(out)


def encode_geoip(categories):
    """categories: {code: iterable of ip_network} -> bytes"""
    out = bytearray()
    for code in sorted(categories):
        geo = bytearray(_len_delim(1, code.upper().encode()))
        nets = sorted(set(categories[code]), key=lambda n: (n.version, n.network_address.packed, n.prefixlen))
        for net in nets:
            geo += _len_delim(2, _len_delim(1, net.network_address.packed) + _uint(2, net.prefixlen))
        out += _len_delim(1, bytes(geo))
    return bytes(out)


def parse_rule(rule):
    """'domain:x' / 'full:x' / 'keyword:x' / 'regexp:x' / bare 'x' (= domain) -> (type, value)"""
    rtype, value = "domain", rule
    for prefix in RULE_TYPES:
        if rule.startswith(prefix + ":"):
            rtype, value = prefix, rule[len(prefix) + 1:]
            break
    if rtype in ("domain", "full"):
        value = value.strip().lower().rstrip(".")
        if value.startswith("."):
            value = value[1:]
        if not _DOMAIN_RE.match(value):
            raise ValueError(f"bad domain in rule: {rule!r}")
    elif not value:
        raise ValueError(f"empty rule: {rule!r}")
    return rtype, value


def parse_cidrs(text):
    nets = []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            nets.append(ipaddress.ip_network(line, strict=False))
    return nets


def is_covered(rtype, value, bases):
    """True if a domain/full rule equals or is a subdomain of any base domain."""
    if rtype not in ("domain", "full"):
        return False
    return any(value == b or value.endswith("." + b) for b in bases)


class V2flyData:
    """Reads data/ from a domain-list-community tarball and resolves include: lines."""

    def __init__(self, tar_gz_bytes):
        self.files = {}
        with tarfile.open(fileobj=io.BytesIO(tar_gz_bytes), mode="r:gz") as tf:
            for m in tf.getmembers():
                parts = m.name.split("/")
                if len(parts) == 3 and parts[1] == "data" and m.isfile():
                    self.files[parts[2]] = tf.extractfile(m).read().decode("utf-8")
        self._cache = {}

    def entries(self, name, _stack=()):
        """-> list of (type, value, frozenset(attrs))"""
        if name in self._cache:
            return self._cache[name]
        if name not in self.files:
            raise KeyError(f"v2fly category not found: {name}")
        if name in _stack:
            raise ValueError("include loop: " + " -> ".join(_stack + (name,)))
        result = []
        for raw in self.files[name].splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            tokens = line.split()
            rule = tokens[0]
            attrs = frozenset(t[1:] for t in tokens[1:] if t.startswith("@"))
            if rule.startswith("include:"):
                want = {a for a in attrs if not a.startswith("-")}
                drop = {a[1:] for a in attrs if a.startswith("-")}
                for t, v, a in self.entries(rule[len("include:"):], _stack + (name,)):
                    if want and not want <= a:
                        continue
                    if drop & a:
                        continue
                    result.append((t, v, a))
                continue
            t, v = parse_rule(rule)
            result.append((t, v, attrs))
        self._cache[name] = result
        return result
