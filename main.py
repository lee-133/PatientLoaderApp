# Entry point: `python main.py`
#
# Delegates to the CLI in cli.py. Kept tiny on purpose
# the package holds all the real logic and
# this is just the one obvious thing to run


from healthex_runner.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
