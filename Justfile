# django-tui's development tasks: `just` lists them. Everything runs through uv.

set shell := ["bash", "-euo", "pipefail", "-c"]
set positional-arguments

paths := "src tests scripts docs"

# List the recipes
[private]
default:
    @just --list --unsorted

# Install Python and the dev dependencies
sync:
    uv sync

# Run the tests; arguments go to pytest (`just test tests/test_tui.py -x`)
[group("test")]
test *args:
    uv run pytest "$@"

# Run the tests on another Python and Django (`just test-on 3.11 5.2`)
[group("test")]
test-on python django="" *args:
    uv run --isolated --python "{{ python }}" {{ if django != "" { "--with 'django~=" + django + ".0'" } else { "" } }} pytest "${@:3}"

# Run the tests on every Python and Django combination CI tests
[group("test")]
test-all:
    #!/usr/bin/env bash
    set -euo pipefail
    for py in 3.11 3.12 3.13 3.14 3.15; do
        for django in 5.2 6.0 6.1; do
            # Django 6.0+ requires Python 3.12+
            [[ $py == 3.11 && $django != 5.2 ]] && continue
            echo "── Python $py, Django $django"
            just test-on "$py" "$django" -q
        done
    done

# Lint and format check, as CI does
[group("check")]
lint:
    uv run ruff check {{ paths }}
    uv run ruff format --check {{ paths }}

# Format the code and apply ruff's safe fixes
[group("check")]
fmt:
    uv run ruff format {{ paths }}
    uv run ruff check --fix {{ paths }}

# Audit the GitHub workflows (zizmor, actionlint)
[group("check")]
lint-actions:
    uvx zizmor .github/workflows
    uvx --from actionlint-py actionlint

# Everything before a push: lint, then the tests
[group("check")]
check: lint test

# Run the TUI in the test project (`just tui --shell`)
[group("run")]
tui *args:
    cd tests && uv run python manage.py tui "$@"

# Take the README's screenshots for the next version (needs Chrome)
[group("docs")]
screenshots:
    uv run python docs/screenshots.py

# Record the README's demo for the next version (needs VHS: https://github.com/charmbracelet/vhs)
[group("docs")]
demo:
    #!/usr/bin/env bash
    set -euo pipefail
    directory=$(uv run python docs/screenshots.py --version-dir)
    mkdir -p "$directory"
    vhs docs/demo.tape --output "$directory/demo.gif"
    uv run python docs/screenshots.py --readme demo.gif

# Preview the next release; `just release --no-dry-run` commits and pushes it, then waits for it
[group("release")]
release *args:
    #!/usr/bin/env bash
    set -euo pipefail
    commit=false
    rest=()
    for arg in "$@"; do
        if [[ $arg == --no-dry-run ]]; then commit=true; else rest+=("$arg"); fi
    done
    if $commit; then
        uv run scripts/release.py prepare ${rest[@]+"${rest[@]}"}
    else
        uv run scripts/release.py prepare --dry-run ${rest[@]+"${rest[@]}"}
        echo
        echo "That was a dry run. To release it: just release --no-dry-run"
        echo "(commits it, pushes it to main and waits until CI passes and it's published)"
    fi

# Remove build, coverage and cache output
clean:
    rm -rf dist htmlcov .coverage .coverage.* .pytest_cache .ruff_cache
