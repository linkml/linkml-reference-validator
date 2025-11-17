# CLAUDE.md for linkml-reference-validator

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Validation of supporting text from references and publications

The project uses `uv` for dependency management and `just` as the command runner.

## IMPORTANT INSTRUCTIONS

- we use test driven development, write tests first before implementing a feature
- do not try and 'cheat' by making mock tests (unless asked)
- if functionality does not work, keep trying, do not relax the test just to get poor code in
- always run tests
- use docstrings

We make heavy use of doctests, these serve as both docs and tests. `just test` will include these,
or do `just doctest` just to write doctests

In general AVOID try/except blocks, except when these are truly called for, for example
when interfacing with external systems. For wrapping deterministic code,  these are ALMOST
NEVER required, if you think you need them, it's likely a bad smell that your logic is wrong.

## Essential Commands


### Testing and Quality
- `just test` - Run all tests, type checking, and formatting checks
- `just pytest` - Run Python tests only
- `just mypy` - Run type checking
- `just format` - Run ruff linting/formatting checks
- `uv run pytest tests/test_simple.py::test_simple` - Run a specific test

### Running the CLI
- `uv run linkml-reference-validator --help` - Run the CLI tool with options

### Documentation
- `just _serve` - Run local documentation server with mkdocs

## Project Architecture

### Core Structure
- **src/my_awesome_tool/** - Main package containing the CLI and application logic
  - `cli.py` - Typer-based CLI interface, entry point for the application
- **tests/** - Test suite using pytest with parametrized tests
- **docs/** - MkDocs-managed documentation with Material theme

### Technology Stack
- **Python 3.10+** with `uv` for dependency management
- **LinkML** for data modeling (linkml-runtime)
- **Typer** for CLI interface
- **pytest** for testing
- **mypy** for type checking
- **ruff** for linting and formatting
- **MkDocs Material** for documentation

### Key Configuration Files
- `pyproject.toml` - Python project configuration, dependencies, and tool settings
- `justfile` - Command runner recipes for common development tasks
- `mkdocs.yml` - Documentation configuration
- `uv.lock` - Locked dependency versions

## Development Workflow

1. Dependencies are managed via `uv` - use `uv add` for new dependencies
2. All commands are run through `just` or `uv run`
3. The project uses dynamic versioning from git tags
4. Documentation is auto-deployed to GitHub Pages at https://monarch-initiative.github.io/my-awesome-tool
