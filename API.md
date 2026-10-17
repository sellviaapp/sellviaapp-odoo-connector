# SellViaApp API capabilities

The Odoo connector uses a dedicated authenticated exchange surface. The same SellViaApp account can also expose a broader API for approved integrations. Exact availability depends on the account configuration and assigned credentials.

## Odoo connector endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `odoo/oauth/device/code` | Start OAuth device authorisation |
| `POST` | `odoo/oauth/device/token` | Complete the approved connection |
| `GET` | `odoo/account` | Verify account and connection metadata |
| `POST` | `odoo/disconnect` | Revoke the installation connection |
| `POST` | `odoo/categories/sync` | Create or update categories in batches |
| `POST` | `odoo/categories/archive` | Hide categories removed from Odoo |
| `POST` | `odoo/products/sync` | Create or update products and variants |
| `PATCH` | `odoo/products/inventory` | Update price, stock and visibility in lightweight batches |
| `POST` | `odoo/products/archive` | Hide products removed or disabled in Odoo |
| `POST` | `odoo/customers/sync` | Create or update mobile customer access |
| `POST` | `odoo/customers/feed` | Retrieve SellViaApp customers with cursor pagination |
| `POST` | `odoo/orders/feed` | Retrieve confirmed mobile orders with cursor pagination |
| `POST` | `odoo/orders/acknowledge` | Record the Odoo import result and reference |
| `POST` | `odoo/support/session` | Open a short-lived authenticated support session |

The connector sends stable Odoo external identifiers. Repeating a successful transfer updates the existing record instead of creating another one.

## Catalogue API

Representative endpoints include:

- `GET fam1/list`, `POST fam1/add`, `PATCH fam1/update`, `DELETE fam1/delete`
- `GET fam2/list`, `POST fam2/add`, `PATCH fam2/update`, `DELETE fam2/delete`
- `GET product/list`, `POST product/add`, `PATCH product/update`, `DELETE product/delete`
- `GET product/image`
- `GET price/list`, `GET mark/list`, `GET size/list`, `GET libweb/list`

These resources cover the two-level catalogue structure, product discovery, signed media, prices, brands, sizes and reference labels.

## Customer API

- `POST customer/add`
- `GET customer/list`
- `GET customer/me`
- `PATCH customer/update`
- `DELETE customer/deleteaccount`

Customer endpoints can create mobile access, list authorised records and manage the currently authenticated profile.

## Orders, fulfilment and payments

- `GET order/list`, `GET order/total`, `DELETE order/delete`
- `POST orderline/add`, `GET orderline/list`, `PATCH orderline/update`, `DELETE orderline/delete`
- `POST order/shipping/quote`
- `POST order/sendtomegawin`
- `GET payment/config`, `POST payment/checkout/create`, `POST payment/pay-later`, `GET payment/status`

This surface supports cart management, delivery or pickup calculations, order confirmation and server-verified payment state.

## Automation and additional domains

SellViaApp also provides authenticated capabilities for webhook subscriptions and deliveries, appointments, documents, case tracking and related workflows when enabled for the account. Use only the scopes and endpoints required by the integration.

## Authentication and safety

- Never commit API keys, OAuth tokens or customer credentials.
- Keep credentials in Odoo protected fields or a dedicated secret manager.
- Use HTTPS for every production request.
- Validate webhook signatures before processing events.
- Treat pagination cursors as opaque values.
- Implement retry with backoff for transient failures and preserve idempotent external identifiers.
- Do not log passwords, full bearer tokens or sensitive customer payloads.

The exact schemas and credential types are available in the authenticated SellViaApp API documentation for the connected account.
