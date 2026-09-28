#!/usr/bin/env python3
"""Strict protobuf decoder for v2ray/xray geoip.dat and geosite.dat.

Usage: python build/inspect_dat.py geoip|geosite FILE [--show N]
Checks wire types and field numbers against routercommon.proto, reports
unknown fields, trailing bytes, IP lengths, prefixes and country_code case.
"""
import argparse
import ipaddress
import sys


class DecodeError(Exception):
    pass


def read_varint(buf, pos):
    result = shift = 0
    while True:
        if pos >= len(buf):
            raise DecodeError(f"truncated varint at {pos}")
        b = buf[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not b & 0x80:
            return result, pos
        shift += 7
        if shift > 63:
            raise DecodeError(f"varint too long at {pos}")


def fields(buf):
    """Yield (field_no, wire_type, value) for a message; value is int or bytes."""
    pos = 0
    while pos < len(buf):
        key, pos = read_varint(buf, pos)
        field, wt = key >> 3, key & 7
        if field == 0:
            raise DecodeError(f"field number 0 at {pos}")
        if wt == 0:
            val, pos = read_varint(buf, pos)
        elif wt == 2:
            ln, pos = read_varint(buf, pos)
            if pos + ln > len(buf):
                raise DecodeError(f"length {ln} overruns buffer at {pos}")
            val, pos = buf[pos:pos + ln], pos + ln
        else:
            raise DecodeError(f"unexpected wire type {wt} for field {field} at {pos}")
        yield field, wt, val


def expect(field, wt, allowed, where, problems):
    if (field, wt) not in allowed:
        problems.append(f"{where}: unexpected field {field} wire type {wt}")
        return False
    return True


def inspect_geoip(buf, show):
    problems, cats = [], []
    for f, wt, entry in fields(buf):
        if not expect(f, wt, {(1, 2)}, "GeoIPList", problems):
            continue
        code, cidrs, rev = None, [], None
        for g, gwt, gv in fields(entry):
            if not expect(g, gwt, {(1, 2), (2, 2), (3, 0)}, "GeoIP", problems):
                continue
            if g == 1:
                code = gv.decode("utf-8")
            elif g == 3:
                rev = gv
            else:
                ip, prefix = None, None
                for c, cwt, cv in fields(gv):
                    if not expect(c, cwt, {(1, 2), (2, 0)}, "CIDR", problems):
                        continue
                    if c == 1:
                        ip = cv
                    else:
                        prefix = cv
                if ip is None or len(ip) not in (4, 16):
                    problems.append(f"{code}: bad ip length {None if ip is None else len(ip)}")
                    continue
                prefix = prefix or 0
                maxp = 32 if len(ip) == 4 else 128
                if prefix > maxp:
                    problems.append(f"{code}: prefix {prefix} > {maxp}")
                cidrs.append((ip, prefix))
        cats.append((code, cidrs, rev))
    print(f"GeoIPList: {len(cats)} entries")
    for code, cidrs, rev in cats:
        v4 = sum(1 for ip, _ in cidrs if len(ip) == 4)
        case = "UPPER" if code == code.upper() else ("lower" if code == code.lower() else "Mixed")
        print(f"  {code!r:24} case={case:5} cidrs={len(cidrs)} (v4={v4}, v6={len(cidrs) - v4})"
              f"{'' if rev is None else f' reverse_match={rev}'}")
        for ip, p in cidrs[:show]:
            print(f"      {ipaddress.ip_address(ip)}/{p}")
    return problems


def inspect_geosite(buf, show):
    problems, cats = [], []
    for f, wt, entry in fields(buf):
        if not expect(f, wt, {(1, 2)}, "GeoSiteList", problems):
            continue
        code, doms = None, []
        for g, gwt, gv in fields(entry):
            if not expect(g, gwt, {(1, 2), (2, 2), (3, 2)}, "GeoSite", problems):
                continue
            if g == 1:
                code = gv.decode("utf-8")
            elif g == 2:
                t, v = 0, None
                for d, dwt, dv in fields(gv):
                    if not expect(d, dwt, {(1, 0), (2, 2), (3, 2)}, "Domain", problems):
                        continue
                    if d == 1:
                        t = dv
                    elif d == 2:
                        v = dv.decode("utf-8")
                doms.append((t, v))
        cats.append((code, doms))
    print(f"GeoSiteList: {len(cats)} entries")
    for code, doms in cats[:60]:
        print(f"  {code!r:28} domains={len(doms)}")
        for t, v in doms[:show]:
            print(f"      type={t} {v}")
    return problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=["geoip", "geosite"])
    ap.add_argument("file")
    ap.add_argument("--show", type=int, default=0)
    args = ap.parse_args()
    buf = open(args.file, "rb").read()
    print(f"{args.file}: {len(buf)} bytes, first bytes: {buf[:16].hex(' ')}")
    try:
        problems = (inspect_geoip if args.kind == "geoip" else inspect_geosite)(buf, args.show)
    except DecodeError as e:
        print(f"DECODE ERROR: {e}")
        sys.exit(2)
    print("problems: " + ("none" if not problems else ""))
    for p in problems[:20]:
        print("  " + p)
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
