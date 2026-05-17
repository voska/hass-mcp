"""Entry point for `python -m app`. Delegates to app.run.main so both this
and the `hass-mcp` console script (`[project.scripts]`) take the same CLI."""

from app.run import main


if __name__ == "__main__":
    main()
