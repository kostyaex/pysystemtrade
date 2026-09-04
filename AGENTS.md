# AGENTS.md

## Quick start

```bash
python -m pip install --editable '.[dev]'
pytest
```

## Commands

- **run all tests**: `pytest`
- **run single file**: `pytest sysdata/tests/test_config.py`
- **skip a module**: `pytest --ignore=sysinit/futures/tests/test_sysinit_futures.py`
- **run slow tests**: `pytest --runslow` (marked with `@pytest.mark.slow`)
- **format**: `black .` (exclude venv: `black . --exclude '/.venv\/.+/'`)
- **required black version**: `23.11.0` (enforced in `pyproject.toml [tool.black]`)

## Project layout

| Directory | Purpose |
|---|---|
| `systems/` | Backtesting system stages: rawdata, forecast, positionsizing, portfolio, accounts |
| `sysdata/` | Data layer: CSV, MongoDB, Parquet, Arctic stores |
| `syscore/` | Core utilities: pandas helpers, date utils, file utils, math |
| `sysquant/` | Quantitative estimators and optimisation |
| `sysobjects/` | Data objects: futures contracts, prices, rolls, instruments |
| `sysbrokers/` | Broker integration (Interactive Brokers via `ib_async`) |
| `sysproduction/` | Production automation: price updates, backups, strategy runners |
| `sysexecution/` | Order execution: algos, order stacks, strategy orders |
| `sysinit/` | Data initialization scripts (futures, FX, transfers) |
| `syscontrol/` | Production control configuration (YAML) |
| `data/` | CSV price/config data files |
| `private/` | Private config (gitignored) |

Entry point: `systems.basesystem.System` composes stages with a `simData` object and optional `Config`.

## Test configuration

- Doctests run on all modules (`--doctest-modules` in `pyproject.toml`)
- Test paths are explicit in `pyproject.toml [tool.pytest.ini_options] testpaths`
- `examples/` is excluded from test collection (`norecursedirs`)
- `systems/provided/moretradingrules/temp.py` is explicitly ignored

## Conventions

- **Default sentinel**: Use `arg_not_supplied` (`from syscore.constants import arg_not_supplied`) instead of `None` for optional params.
- **Class naming**: mixedCase, not CamelCase. Single-word classes are CamelCase.
- **Error handling**: Production code should not throw unless unrecoverable; use `log.critical()` for critical errors.
- **Docstrings on class methods**: Avoid verbose docstrings for params (use type hints instead). Doctests in class methods are discouraged; prefer standalone functions.
- **Data naming**: Objects forming the data hierarchy follow a specific naming convention (see `docs/data.md` Part 2). Breaking this breaks `DataBlob` auto-abstraction.

## Dependencies

Pinned exact versions in `pyproject.toml` matter. Key pins:
- `pandas==2.1.3`, `pymongo==3.11.3`, `statsmodels==0.14.0`, `PyYAML==6.0.1`
- `ib_async>=2,<3` (Interactive Brokers)
- `pyarrow>=16,<20`

## Gotchas

- `tox.ini` and `.travis.yml` are **stale/outdated** - ignore them. Use `pytest` directly.
- `setup.py` is deprecated. Use `pyproject.toml` for all config.
- The `private/` directory is gitignored and contains sensitive config. Do not read or modify unless explicitly asked.
- `CONTRIBUTING.md` has strict AI policy: review all AI-generated changes before submitting.
