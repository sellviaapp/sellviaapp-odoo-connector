# SellViaApp Connector — product audit

Audit date: 2026-10-17
Audited version: 17.0.1.10.0
Target: Odoo 17 Community/Enterprise

## Result

The connector covers the complete first operational loop: secure connection, catalogue publication, stock, customer access, reverse customer import and order import. Version 17.0.1.10.0 also provides the metadata, documentation, validation and anonymised visuals required for a professional public repository and Odoo Apps submission.

## Improvements included in 17.0.1.10.0

- Automatic creation of one ready-to-configure connector per Odoo company after installation.
- Automatic connector creation for companies added later.
- Guided setup progress and explicit first-connection message.
- Everyday actions grouped into catalogue, customers and orders instead of a crowded header.
- Useful counters for eligible products, linked customers and imported orders.
- Direct links to the relevant Odoo records and SellViaApp dashboard.
- Technical JSON results moved away from the primary workflow.
- Complete installation, upgrade, security and troubleshooting documentation.
- French interface catalogue added.
- Automatic deletion of synchronisation logs older than 90 days.
- Global authentication gate: no catalogue, customer, order, linked-record or protected-image operation is available before OAuth is established and unexpired.

## Functional coverage

### Complete

- OAuth 2.0 device authorisation and revocation.
- Multi-company isolation with one connector per company.
- Product/category/variant/price/VAT/unit/attribute/image/stock publication.
- Manual and scheduled catalogue updates.
- Safe removal/archive handling.
- Odoo customer creation in SellViaApp with invitation delivery.
- SellViaApp customer import with strict duplicate prevention.
- Confirmed order import as draft quotations with acknowledgements.
- Delivery, pickup point and payment metadata.
- Technical logs, bindings and readable action notifications.

### Recommended next extensions

These are useful options, not blockers for the current release:

1. Pricelist selection instead of always publishing the standard Odoo sales price.
2. An explicit “Publish in SellViaApp” checkbox for stores that do not want every saleable product published.
3. Scheduled order/customer retrieval with a configurable interval. It should remain opt-in because it creates Odoo records automatically.
4. Optional automatic quotation confirmation, delivery creation or invoice creation, each disabled by default.
5. Mapping between SellViaApp payment/delivery methods and Odoo journals/carriers.
6. Conflict policy selector for customer fields: Odoo wins, SellViaApp wins, or fill empty fields only.
7. Webhook-based near-real-time imports for larger catalogues and higher order volumes.
8. Additional automated test coverage against supported Odoo minor releases.

## Installation acceptance checklist

- Module installs without missing dependencies.
- A connector exists automatically for the active company.
- OAuth approval opens the SellViaApp dashboard and completes successfully.
- Connection test passes.
- Catalogue sync reports products and categories without failures.
- A test customer can be sent and retrieved without duplication.
- A confirmed test order is imported once as a quotation.
- Scheduled catalogue sync is active only for connected connectors.
- Odoo is restarted after every Python-code upgrade.
