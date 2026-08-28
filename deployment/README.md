# Deployment

Three ways to run EduMatcher, pick one:

- [`curl/`](curl/) — **the quickest**: one command, prebuilt images, the whole
  system (exchange + all four web GUIs). Needs only Podman or Docker. See
  [curl/README.md](curl/README.md).
- [`docker/`](docker/) — the same system, built from this checkout. What you
  want when you are changing the code. See [docker/README.md](docker/README.md).
- [`vm/`](vm/) — a Multipass VM with the runtime installed, no containers. See
  [vm/README.md](vm/README.md).
