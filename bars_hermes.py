#!/usr/bin/env python3
"""Run the existing BARS sovereign server with Hermes as its capability kernel.

The import order is intentional: server.py owns auth, memory, receipts, mission
contracts, verification, HTTP routes, and shutdown semantics.  We replace only
its model-call function, then invoke the unchanged server main().
"""
import os

os.environ.setdefault("BARS_NO_BROWSER", "1")
os.environ.setdefault("BARS_HERMES_ENABLED", "1")

import server  # noqa: E402
from hermes_kernel import install_into_bars  # noqa: E402


def main():
    kernel = install_into_bars(server)
    kernel.validate()
    print(
        "[bars] Hermes kernel active: "
        f"profile={kernel.profile} provider={kernel.provider} toolsets={kernel.toolsets}"
    )
    server.main()


if __name__ == "__main__":
    main()
