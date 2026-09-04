"""Audit this assembled package, not the original workspace."""
from audit_release_package import main
if __name__ == "__main__":
    raise SystemExit(main())
