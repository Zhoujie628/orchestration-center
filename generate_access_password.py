#!/usr/bin/env python3
"""Generate SHA-256 hash for access_password config.

Usage:
    python generate_access_password.py

Then copy the output hash to etc/conf/server.conf:
    access_password=<hash>
"""

import hashlib
import sys


def main():
    if len(sys.argv) > 1:
        print(f"Error: unexpected argument(s): {' '.join(sys.argv[1:])}")
        print("This tool only generates the access password hash interactively; it takes no arguments.")
        print("For TLS certificates use: python -m generate_selfsign_cert <cert_dir> serverAuth "
              "[--dns HOST] [--ip ADDRESS] [--plain-key]")
        sys.exit(1)
    print("Access Password Generator")
    print("=" * 40)
    password = input("Enter password: ").strip()
    if not password:
        print("Error: password cannot be empty")
        return
    hash_value = hashlib.sha256(password.encode()).hexdigest()
    print()
    print(f"SHA-256 hash: {hash_value}")
    print()
    print("Add this to etc/conf/server.conf:")
    print(f"  access_password={hash_value}")


if __name__ == "__main__":
    main()
