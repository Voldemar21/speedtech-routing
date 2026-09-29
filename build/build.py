#!/usr/bin/env python3
"""Build geosite.dat, geoip.dat, profile.json and deeplink.txt for the SpeedTech Happ routing profile.

Usage: python build/build.py --out dist [--prev prev-meta.json] [--repo owner/name] [--force]

Release policy (written to $GITHUB_OUTPUT as release=true|false):
  * first build, or lists/*.txt / profile template changed  -> release now (new LastUpdated);
  * only upstream data changed -> release if the previous release is older than
    data_release_min_interval_days (Happ refreshes geo files at most weekly anyway);
  * nothing changed -> no release.
"""
import argparse
import base64
import hashlib
import ipaddress
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import geodat  # noqa: E402

PRIVATE_CIDRS = [
    "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8", "169.254.0.0/16", "172.16.0.0/12",
    "192.0.0.0/24", "192.0.2.0/24", "192.88.99.0/24", "192.168.0.0/16", "198.18.0.0/15",
    "198.51.100.0/24", "203.0.113.0/24", "224.0.0.0/4", "240.0.0.0/4", "255.255.255.255/32",
    "::/128", "::1/128", "fc00::/7", "fe80::/10", "ff00::/8",
]
LIST_NAMES = ("proxy", "direct", "block", "block-allow")


def log(msg):
    print(msg, flush=True)


def fetch(url, timeout=180):
    req = urllib.request.Request(url, headers={"User-Agent": "speedtech-routing-build"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    log(f"  fetched {url} ({len(data)} bytes)")
    return data


def read_list(name):
    """lists/<name>.txt -> sorted list of (type, value); '#' comments allowed."""
    path = ROOT / "lists" / f"{name}.txt"
    rules = set()
    for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        try:
            rules.add(geodat.parse_rule(line))
        except ValueError as e:
            sys.exit(f"{path.name}:{n}: {e}")
    return sorted(rules)


def rule_str(rule):
    return f"{rule[0]}:{rule[1]}"


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def build_geosite(cfg, lists):
    v2fly = geodat.V2flyData(fetch(cfg["v2fly_tarball"]))
    rf_cache = {}
    cats = {}
    for code, spec in cfg["geosite"].items():
        rules = set()
        for name in spec.get("v2fly", []):
            rules |= {(t, v) for t, v, _ in v2fly.entries(name)}
        for name in spec.get("runetfreedom", []):
            if name not in rf_cache:
                text = fetch(cfg["runetfreedom_base"] + name + ".txt").decode("utf-8")
                rf_cache[name] = {geodat.parse_rule(l.strip()) for l in text.splitlines() if l.strip() and not l.startswith("#")}
            rules |= rf_cache[name]
        if spec.get("exclude_list"):
            bases = [v for t, v in lists[spec["exclude_list"]] if t in ("domain", "full")]
            before = len(rules)
            rules = {r for r in rules if not geodat.is_covered(r[0], r[1], bases)}
            log(f"  {code}: excluded {before - len(rules)} rules via lists/{spec['exclude_list']}.txt")
        cats[code] = rules
    if cfg.get("subtract_direct_from_proxy"):
        bases = [v for t, v in lists["direct"] if t in ("domain", "full")]
        before = len(cats["st-proxy"])
        cats["st-proxy"] = {r for r in cats["st-proxy"] if not geodat.is_covered(r[0], r[1], bases)}
        log(f"  st-proxy: subtracted {before - len(cats['st-proxy'])} rules covered by lists/direct.txt")
        for t, v in cats["st-proxy"]:
            if t == "domain" and any(b.endswith("." + v) for b in bases):
                log(f"  WARNING: st-proxy keeps parent rule domain:{v} that covers a direct.txt exception")
    return cats


def build_geoip(cfg):
    """Fallback for local runs without Go: our own encoder."""
    return {
        "st-telegram": geodat.parse_cidrs(fetch(cfg["telegram_cidr"]).decode("utf-8")),
        "private": [ipaddress.ip_network(c) for c in PRIVATE_CIDRS],
    }


def prepare_geoip(cfg, src_dir):
    """Write text sources + config.json for the official v2fly/geoip tool (CI uses this)."""
    src = Path(src_dir)
    src.mkdir(parents=True, exist_ok=True)
    nets = geodat.parse_cidrs(fetch(cfg["telegram_cidr"]).decode("utf-8"))
    (src / "st-telegram.txt").write_text("".join(f"{n}\n" for n in nets), encoding="utf-8")
    config = {
        "input": [
            {"type": "text", "action": "add", "args": {"name": "st-telegram", "uri": "./st-telegram.txt"}},
            {"type": "private", "action": "add"},
        ],
        "output": [
            {"type": "v2rayGeoIPDat", "action": "output",
             "args": {"outputDir": "./output", "outputName": "geoip.dat", "wantedList": ["st-telegram", "private"]}},
        ],
    }
    (src / "config.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    log(f"prepared {src}/st-telegram.txt ({len(nets)} CIDRs) and {src}/config.json")


def check_counts(cfg, geosite, geoip_counts):
    counts = {code: len(r) for code, r in geosite.items()}
    counts.update({f"geoip:{code}": n for code, n in geoip_counts.items()})
    for key, minimum in cfg["min_counts"].items():
        if counts.get(key, 0) < minimum:
            sys.exit(f"sanity check failed: {key} has {counts.get(key, 0)} entries, expected >= {minimum}")
    return counts


def make_profile(lists, subtract_direct):
    profile = json.loads((HERE / "profile.template.json").read_text(encoding="utf-8"))
    proxy = lists["proxy"]
    if subtract_direct:
        bases = [v for t, v in lists["direct"] if t in ("domain", "full")]
        proxy = [r for r in proxy if not geodat.is_covered(r[0], r[1], bases)]
    profile["ProxySites"] += [rule_str(r) for r in proxy]
    profile["DirectSites"] += [rule_str(r) for r in lists["direct"]]
    profile["BlockSites"] += [rule_str(r) for r in lists["block"]]
    return profile


def compact(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def decide(prev, core_sha, geosite_sha, geoip_sha, now, cfg, force):
    if force:
        return True, "forced"
    if not prev:
        return True, "first release"
    if prev.get("profile_core_sha256") != core_sha:
        return True, "lists/template changed"
    if prev.get("geosite_sha256") != geosite_sha or prev.get("geoip_sha256") != geoip_sha:
        age_days = (now - int(prev.get("last_updated", 0))) / 86400
        if age_days >= cfg["data_release_min_interval_days"]:
            return True, f"upstream data changed, previous release {age_days:.1f} days old"
        return False, f"upstream data changed, but previous release only {age_days:.1f} days old"
    return False, "nothing changed"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="dist")
    ap.add_argument("--prev", help="meta.json of the previous release (missing/empty = first release)")
    ap.add_argument("--repo", default="Voldemar21/speedtech-routing")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--prepare-geoip", metavar="DIR", help="only write v2fly/geoip sources + config to DIR and exit")
    ap.add_argument("--geoip-dat", metavar="FILE", help="use geoip.dat built by v2fly/geoip instead of the built-in encoder")
    args = ap.parse_args()

    cfg = json.loads((HERE / "sources.json").read_text(encoding="utf-8"))
    if args.prepare_geoip:
        prepare_geoip(cfg, args.prepare_geoip)
        return
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    prev = {}
    if args.prev and Path(args.prev).is_file() and Path(args.prev).stat().st_size:
        prev = json.loads(Path(args.prev).read_text(encoding="utf-8"))

    lists = {name: read_list(name) for name in LIST_NAMES}
    log("lists: " + ", ".join(f"{k}={len(v)}" for k, v in lists.items()))

    log("building geosite...")
    geosite = build_geosite(cfg, lists)
    if args.geoip_dat:
        log(f"using geoip from {args.geoip_dat}")
        geoip_dat = Path(args.geoip_dat).read_bytes()
    elif cfg.get("geoip_copy_url"):
        # Happ rejects tiny geoip.dat files (500 B hand-encoded and 414 B from v2fly/geoip both
        # failed its validation), so we ship a copy of a ready-made ~165 KB file instead.
        log("copying ready-made geoip.dat...")
        geoip_dat = fetch(cfg["geoip_copy_url"])
    else:
        log("building geoip with the built-in encoder...")
        geoip_dat = geodat.encode_geoip(build_geoip(cfg))
    try:
        geoip_counts = geodat.decode_geoip_counts(geoip_dat)
    except ValueError as e:
        sys.exit(f"geoip.dat failed strict decoding: {e}")
    counts = check_counts(cfg, geosite, geoip_counts)
    log("counts: " + json.dumps(counts))

    geosite_dat = geodat.encode_geosite(geosite)
    (out / "geosite.dat").write_bytes(geosite_dat)
    (out / "geoip.dat").write_bytes(geoip_dat)
    for name, data in (("geosite.dat", geosite_dat), ("geoip.dat", geoip_dat)):
        (out / f"{name}.sha256").write_text(f"{sha256(data)}  {name}\n", encoding="utf-8")
    log(f"geosite.dat {len(geosite_dat)} bytes, geoip.dat {len(geoip_dat)} bytes")

    profile = make_profile(lists, cfg.get("subtract_direct_from_proxy", False))
    core_sha = sha256(compact(profile).encode())  # URLs/LastUpdated are still empty here
    now = int(time.time())
    release, reason = decide(prev, core_sha, sha256(geosite_dat), sha256(geoip_dat), now, cfg, args.force)

    if release:
        tag = "r" + time.strftime("%Y%m%d%H%M", time.gmtime(now))
        last_updated = now
    else:
        tag = prev.get("tag", "unreleased")
        last_updated = int(prev.get("last_updated", now))
    base = cfg["file_base_url"].format(repo=args.repo, tag=tag)
    profile["Geositeurl"] = base + "geosite.dat"
    profile["Geoipurl"] = base + "geoip.dat"
    profile["LastUpdated"] = str(last_updated)

    profile_compact = compact(profile)
    deeplink = "happ://routing/onadd/" + base64.b64encode(profile_compact.encode()).decode()
    if len(deeplink) > cfg["max_deeplink_bytes"]:
        sys.exit(f"deeplink is {len(deeplink)} bytes, limit {cfg['max_deeplink_bytes']} - move entries to geosite")
    (out / "profile.json").write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "deeplink.txt").write_text(deeplink + "\n", encoding="utf-8")

    meta = {
        "tag": tag,
        "last_updated": last_updated,
        "built_at": now,
        "reason": reason,
        "geosite_sha256": sha256(geosite_dat),
        "geoip_sha256": sha256(geoip_dat),
        "profile_core_sha256": core_sha,
        "counts": counts,
        "sizes": {"geosite.dat": len(geosite_dat), "geoip.dat": len(geoip_dat),
                  "profile.json": len(profile_compact), "deeplink.txt": len(deeplink)},
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    log(f"release={str(release).lower()} tag={tag} reason: {reason}")
    log(f"profile {len(profile_compact)} bytes, deeplink {len(deeplink)} bytes")

    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a", encoding="utf-8") as f:
            f.write(f"release={str(release).lower()}\ntag={tag}\nreason={reason}\n")


if __name__ == "__main__":
    main()
