"""Use the qualified short-probe ELF geometry audit, with Pool scope only."""
import probe_audit
from portable_pool import SCOPE


def inspect(data):
    report=probe_audit.inspect(data)
    report["scope"]=SCOPE
    return report
