# Security policy

## Supported version

Security fixes are applied to the latest published release for Odoo 17.

## Report a vulnerability

Do not open a public issue for a suspected vulnerability. Email `info@sellviaapp.com` with:

- the affected connector version;
- a concise impact description;
- reproducible steps or a minimal proof of concept;
- suggested remediation, if available.

Remove passwords, access tokens, API keys, customer data and database dumps from the report unless a secure transfer method has been agreed.

## Security design

- OAuth device authorisation avoids giving the SellViaApp password to Odoo.
- Tokens are installation-specific and revocable.
- Synchronisation actions are blocked until authentication is valid.
- Credential fields are restricted to Odoo Settings administrators.
- Production API URLs require HTTPS and SSL verification is enabled by default.
- Remote image access uses connector-specific HMAC signatures.
- Stable external identifiers and acknowledgements reduce duplicate processing.
- Synchronisation logs are retained for a limited period.
