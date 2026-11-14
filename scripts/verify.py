#!/usr/bin/env python3
"""Independent 231-gate verification — runs WITHOUT NEAR.

Verifies the core cryptographic primitive that the contract implements:
- SUM, LINEAR, PROD checksums mod 231
- Deterministic (same input → same output)
- Tamper detection (single-char change breaks checksums)
- Gates in valid ranges
- Edge cases: empty string, unicode/multibyte, single char, long input
"""
MOD = 231
LINEAR_MULT = 22

import json, os, subprocess, sys, datetime


def derive_gates(action_data: str):
    """Fold ALL bytes of the input into 5 gate values so every byte matters."""
    bytes_ = action_data.encode()
    gates = [0] * 5
    for i, b in enumerate(bytes_):
        gates[i % 5] = (gates[i % 5] + b) % (22 if i % 5 < 2 else MOD)
    return gates


def compute_checksums(action_data: str):
    g = derive_gates(action_data)
    s = (g[0] + g[1] + g[2] + g[3] + g[4]) % MOD
    l = (g[0] * LINEAR_MULT + g[1]) % MOD
    p = (((g[0] * g[1]) % MOD) * (((g[2] * g[3]) % MOD) * g[4] % MOD)) % MOD
    return {"sum": s, "linear": l, "prod": p}


def main():
    failures = []

    def check(name, cond):
        if cond:
            print(f"PASS {name}")
        else:
            print(f"FAIL {name}")
            failures.append(name)

    # 1. Deterministic
    c1 = compute_checksums("hello world")
    c2 = compute_checksums("hello world")
    check("deterministic checksums", c1 == c2)

    # 2. Tamper detection — single char change must break at least one checksum
    c_tampered = compute_checksums("hello world!")
    changed = c1["sum"] != c_tampered["sum"] or c1["linear"] != c_tampered["linear"] or c1["prod"] != c_tampered["prod"]
    check("tamper detected on single-char change", changed)

    # 3. Gates in range
    g = derive_gates("test data")
    check("g1/g2 < 22", g[0] < 22 and g[1] < 22)
    check("g3/g4/g5 < 231", all(x < MOD for x in g[2:5]))

    # 4. Checksums in [0, 230]
    check("checksums in [0,230]", all(0 <= v < MOD for v in c1.values()))

    # 5. Different inputs produce different checksums
    c_a = compute_checksums("transfer 5 NEAR to alice")
    c_b = compute_checksums("transfer 5 NEAR to bob")
    check("different inputs → different checksums", c_a != c_b)

    # 6. Empty string edge case
    c_empty = compute_checksums("")
    check("empty string gates in range", all(0 <= x < MOD for x in c_empty.values()))

    # 7. Unicode / multibyte UTF-8
    c_uni = compute_checksums("café résumé 🚀")
    c_uni2 = compute_checksums("café résumé 🚀")
    check("unicode deterministic", c_uni == c_uni2)
    c_uni_tampered = compute_checksums("café résumé 🚀!")
    check("unicode tamper detected", c_uni != c_uni_tampered)

    # 8. Single character
    c_single = compute_checksums("A")
    check("single char gates in range", all(0 <= x < MOD for x in c_single.values()))

    # 9. Very long input
    long_input = "x" * 100000
    c_long = compute_checksums(long_input)
    check("long input gates in range", all(0 <= x < MOD for x in c_long.values()))

    # 10. Collision resistance spot check — many inputs should not all collide
    samples = [f"entry-{i}" for i in range(50)]
    checksums = [compute_checksums(s) for s in samples]
    unique = len({(c["sum"], c["linear"], c["prod"]) for c in checksums})
    check(f"collision resistance ({unique}/50 unique)", unique > 1)

    print()
    if failures:
        print(f"{len(failures)} CHECK(S) FAILED: {failures}")
        sys.exit(1)
    print("ALL 231-GATE CHECKS PASSED")


if __name__ == "__main__":
    main()
