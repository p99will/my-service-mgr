from __future__ import annotations


def main(argv: list[str] | None = None) -> int:
    # Basic "hello world" entrypoint. `argv` is reserved for future CLI args.
    _ = argv
    print("hello world")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
