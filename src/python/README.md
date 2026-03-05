# phenix-apps

Apps written in Python to work with latest version of phenix.

* Accept stage as single argument.
* Accept experiment JSON over STDIN.
* Return updated experiment JSON over STDOUT.
* Write JSON logs to the file specified by the `PHENIX_LOG_FILE` environment variable.

## Development

This directory contains a `Makefile` to standardize development tasks.

```bash
make all          # Run format and lint
make install      # Install package in editable mode
make install-dev  # Install package with dev dependencies
make test         # Run unit tests
make clean        # Clean build artifacts
```