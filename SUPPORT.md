# Support

## Before requesting assistance

Please collect:

- Odoo version and edition;
- connector version from `__manifest__.py`;
- operating system and deployment method;
- the failing action and approximate timestamp;
- the connector status and the non-sensitive part of the latest summary;
- relevant Odoo server traceback with tokens, passwords, email addresses and customer data removed.

Never publish an API key, access token, device code, database dump or customer record in a public issue.

## Common checks

| Symptom | Check |
| --- | --- |
| App is missing | Confirm `addons_path`, update the Apps list and remove the default Apps filter |
| Button is missing after upgrade | Restart Odoo, upgrade the module and hard-refresh the browser |
| Connection does not complete | Check server time, outbound HTTPS, the approval code and SSL certificates |
| Operations remain locked | Complete OAuth authorisation and use **Check connection** |
| Images are missing | Configure a public HTTPS Odoo URL or allow protected inline image transfer |
| Customer is skipped | Resolve ambiguous duplicate email, VAT or phone values |
| Unknown order item | Match the Odoo internal reference and synchronise the catalogue again |

## Contact

For account or service support, use the secure support button in the connected Odoo workspace or email `info@sellviaapp.com`.

For a reproducible connector defect, open a GitHub issue with sanitised diagnostic information.
