# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability, please report it privately by emailing the maintainer or using [GitHub's private vulnerability reporting](https://github.com/dohyung1/x402-fpl-api/security/advisories/new).

Please do **not** open a public issue for security vulnerabilities.

## Scope

This project connects to the public FPL API and runs locally. The main security surfaces are:

- **x402 payment verification** — on-chain USDC payment validation
- **SQLite replay protection** — transaction hash deduplication
- **Input validation** — team IDs, gameweek numbers, player names

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.3.x   | Yes       |
| < 0.3   | No        |
