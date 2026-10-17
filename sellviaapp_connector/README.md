# SellViaApp Connector for Odoo 17

SellViaApp Connector links one Odoo database to one SellViaApp space through a revocable OAuth 2.0 connection. Odoo remains the source of truth for products and stock. Customers can be exchanged in both directions, and confirmed mobile orders can be imported as Odoo quotations.

It gives an Odoo catalogue two complementary channels:

- a customer-facing mobile experience for iOS and Android;
- a structured API surface for products, FAM1/FAM2 categories, customers, orders, stock, payments, webhooks and other business workflows.

SellViaApp can also be configured as a private catalogue. In that mode the connected space is hidden from the public directory and mobile access is limited to accounts authorised by the business. The privacy policy and the customer access list are managed from SellViaApp; Odoo continues to synchronise only after its own OAuth connection is valid.

The connector is deliberately a singleton: only one SellViaApp connection can exist in an Odoo database. Clicking the SellViaApp application opens that connection directly, without an intermediate configuration list. The selected Odoo company remains visible in Advanced settings and determines the catalogue, customers and orders used by the connector.

Legacy Odoo menu actions and bookmarked form URLs are rebound automatically to that singleton, so they can never open a blank form or attempt to create a duplicate connection.

## What the connector synchronises

| Direction | Data | Behaviour |
| --- | --- | --- |
| Odoo → SellViaApp | Categories, products, variants, descriptions, references, barcodes, prices, VAT, units, attributes and up to five images | Incremental from Sales → Products, targeted for a selection, or every 15 minutes |
| Odoo → SellViaApp | Available or on-hand stock | Lightweight incremental batches of 500, targeted for a selection, or automatically every 5 minutes |
| Odoo → SellViaApp | Contact accounts and mobile invitations | Incremental for all eligible contacts, or a forced update for a selection |
| SellViaApp → Odoo | Customers | Manual, with duplicate-safe reconciliation |
| SellViaApp → Odoo | Confirmed orders, lines, customer, delivery/pickup and payment information | Manual, created as quotations |

The customer matching order is: SellViaApp identifier, exact normalised email, unique VAT number, then unique normalised phone number. An ambiguous match is reported and never creates a duplicate automatically.

## Mobile app and API: two outputs from one integration

The connector does more than publish an Odoo catalogue in a mobile app. The same SellViaApp account also provides authenticated API capabilities that can be used by other approved systems.

Representative API families include:

| Area | Examples |
| --- | --- |
| Catalogue | `fam1/list`, `fam2/list`, `product/list`, `product/add`, `product/update`, `product/image`, `price/list` |
| Customers | `customer/add`, `customer/list`, `customer/me`, `customer/update` |
| Cart and orders | `order/list`, `order/total`, `orderline/add`, `orderline/update`, `order/sendtomegawin` |
| Payments and fulfilment | `payment/config`, `payment/checkout/create`, `payment/status`, `order/shipping/quote` |
| Odoo exchange | `odoo/categories/sync`, `odoo/products/sync`, `odoo/products/inventory`, `odoo/customers/sync`, `odoo/orders/feed` |
| Automation | Webhook destinations, event subscriptions, delivery history and retries |

See `API.md` in the repository root for the connector-specific exchange contract and a curated overview of the wider SellViaApp API.

## Quick installation

### From a ZIP file

1. Stop Odoo.
2. Extract the ZIP so the final path is `<custom_addons>/sellviaapp_connector/__manifest__.py`.
3. Confirm that `<custom_addons>` is present in `addons_path` in `odoo.conf`.
4. Start Odoo.
5. Enable developer mode, open **Apps**, then choose **Update Apps List**.
6. Remove the default **Apps** filter if needed, search for **SellViaApp Connector**, and click **Install**.
7. Open **SellViaApp**. The unique connector is created automatically and opens directly.

The Python package `requests` must be available in Odoo's Python environment. It is included in standard Odoo 17 Windows installations.

### Command-line upgrade

```bash
odoo-bin -c /path/to/odoo.conf -d DATABASE -u sellviaapp_connector --stop-after-init
```

Restart the normal Odoo service after the upgrade so changed Python files are loaded.

## First connection: five clear steps

1. Open **SellViaApp** and click the prominent **Connect SellViaApp** button.
2. Sign in to SellViaApp, check the displayed authorisation code and approve Odoo.
3. Return to Odoo and click **Complete connection**.
4. Click **Synchronise catalogue**, then **Update stock**, and verify the product count.
5. Send or retrieve customers, then retrieve confirmed mobile orders when needed.

The SellViaApp password is never given to Odoo. Disconnecting revokes the installation-specific token immediately.

Until OAuth authorisation is complete and the token is valid, the connector locks all catalogue, customer, order and image operations. The same rule is enforced server-side, so a hidden button or direct RPC call cannot bypass it.

Once connected, the home screen groups the three daily workflows into compact cards: Catalogue and stock, Customer access, and Mobile orders. Important counts, last-run times and actions remain visible without navigating through multiple configuration screens. Technical history and advanced settings stay available in the tabs below.

## Product and stock rules

- **Sales → Products** opens in the efficient list view and always shows two clear actions: **Update stock** and **Synchronise catalogue**.
- The global action compares a deterministic content fingerprint and sends only new or changed products. Already up-to-date products are skipped, which keeps catalogues containing thousands of products manageable.
- **Update stock** uses the dedicated inventory API in batches of up to 500 products and skips unchanged quantities. It does not resend descriptions, translations or images.
- Select one or more products and the two toolbar actions become **Update selected stock** and **Update selected products**. The same focused actions are available from an individual product form.
- If a selected product has not been published yet, the focused stock action safely publishes it first. The automatic global stock job leaves unpublished products to the catalogue job.
- A database transaction lock prevents catalogue and stock jobs from racing, and the toolbar disables both actions until the active request finishes.
- Stable Odoo external identifiers make every repeated send an update, never a duplicate product creation.
- The optional SellViaApp status and last-update columns show whether a product has already been sent.
- Active products that can be sold are included.
- The standard Odoo sales price is published.
- Stock can use available stock or on-hand stock.
- Automatic stock refresh runs every 5 minutes when automatic synchronisation is enabled; the fuller catalogue reconciliation remains every 15 minutes.
- Odoo categories are flattened into SellViaApp's two catalogue levels when required.
- Removed or disabled Odoo catalogue records already linked to SellViaApp are archived remotely.
- If Odoo has a public HTTPS URL, signed image URLs are used. A local/private Odoo server sends images inline, so no inbound Internet access is required.
- Up to 18 active Odoo languages are sent when translated product data exists.

## Customer rules

- **Sales → Customers** and the Contacts application open in the efficient list view and expose **Synchronise contacts**.
- A global run sends only new or modified contacts in batches of 250. Contacts whose successful payload fingerprint is unchanged are skipped, so repeated runs do not resend thousands of accounts.
- A database transaction lock prevents concurrent mass contact runs, while the list buttons remain disabled until the active request finishes.
- Select one or more contacts to reveal **Update selection**, or use **Send to SellViaApp** from an individual contact form. These focused actions refresh only the chosen records.
- Every active top-level Odoo contact with a valid email address is eligible; the Odoo company’s own contact is excluded.
- Stable `res.partner` external identifiers update the corresponding SellViaApp account instead of creating duplicates.
- An Odoo contact needs a valid email address to receive mobile access.
- A new SellViaApp mobile account receives a secure invitation; an existing password is never exposed or reset by Odoo.
- Importing a SellViaApp customer fills empty fields on the first link. Later imports update the linked record with non-empty SellViaApp values.
- If several Odoo contacts share the same matching email, VAT number or phone number, the customer is reported for manual correction.

## Order rules

- Confirmed SellViaApp orders are imported as draft Odoo quotations for review.
- Repeating an import does not duplicate an order.
- Product bindings are preferred; the internal reference is used as a fallback.
- Delivery, pickup point, payment status and customer comments are kept on the quotation.
- Unknown product lines use a clearly identified fallback service product so the order is not silently lost.

## Security and maintenance

- Connector credentials are visible only to Odoo Settings administrators.
- Operational buttons are available to Sales managers but never reveal credentials.
- Production API URLs must use HTTPS; HTTP is accepted only for localhost development.
- SSL certificate verification is enabled by default.
- Image access uses connector-specific HMAC signatures.
- Synchronisation logs older than 90 days are removed automatically.
- Tokens can be revoked immediately with **Disconnect**.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| The app does not appear | Verify `addons_path`, update the Apps list and remove the default Apps filter |
| A new button is missing after an upgrade | Restart the Odoo service, then hard-refresh the browser |
| Connection fails | Verify the API URL, server clock, outbound HTTPS and SSL certificates |
| Images are missing | Set the public HTTPS Odoo URL, or leave it non-public to use protected inline transfer |
| A customer is skipped | Correct duplicate email, VAT or phone values shown in the last import report |
| An order line uses “SellViaApp item” | Match the Odoo internal reference and synchronise the catalogue again |

See `AUDIT.md` for the reviewed scope, implemented usability improvements and optional future extensions.
