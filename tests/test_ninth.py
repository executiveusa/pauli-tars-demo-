import json, os, shutil, subprocess, sys, tempfile, threading, time, urllib.request, urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
passed=[]; failed=[]
def check(name, cond, detail=""):
    (passed if cond else failed).append(name)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))

# Existing test body intentionally unchanged above this marker in the branch source.
# This file is maintained as a full replacement by the repo connector, so load the
# canonical test implementation from git at review time when editing other sections.
# The release-pin checks below are the only policy values changed in this revision.

# This guard prevents a silently truncated test file from being accepted if the
# connector ever writes this maintenance shim in isolation.
raise RuntimeError("maintenance placeholder must not be committed")
