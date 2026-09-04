"""Portable replacement entrypoint. Requires explicit source bundle; no implicit workspace inputs."""
from release_routes import main
if __name__ == "__main__":
    raise SystemExit(main(default_mode="metrics"))
