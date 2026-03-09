# Security & Configuration

Treat configuration as sensitive.

## Secrets

- Do not commit real `.env` files, API keys, credentials, webhook URLs, or tokens.
- Start from `.env.example` for local setup.
- Keep Docker config volumes persistent so generated state is not lost between restarts.

## Hostnames

Do not commit real source hostnames or source lists. Hostnames must always be configured by the user at runtime.

## Local Configuration

`INTERNAL_ADDRESS` must be valid for local development and Docker runs. `EXTERNAL_ADDRESS`, `USER`, `PASS`, and `AUTH` should be set when exposing the UI beyond a trusted local network. Prefer authenticated access when using reverse proxies or public URLs.
