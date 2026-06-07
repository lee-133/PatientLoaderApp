# Entry point
# Delegates to the CLI in cli.py. Kept tiny so the project has one obvious
# thing to run.


from healthex_runner.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
