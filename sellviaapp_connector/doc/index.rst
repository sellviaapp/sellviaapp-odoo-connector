SellViaApp Connector for Odoo 17
================================

The connector links one Odoo database to one SellViaApp space through a
revocable OAuth 2.0 device-authorisation flow. Odoo remains the source of truth
for products and stock. Customers can be exchanged in both directions, and
confirmed mobile orders can be retrieved as draft Odoo quotations.

Main capabilities
-----------------

* Synchronise FAM1/FAM2 categories, products, variants, descriptions,
  references, barcodes, prices, VAT, attributes, images and stock.
* Send eligible Odoo contacts to the mobile service and issue invitations.
* Retrieve SellViaApp customers with duplicate-safe matching.
* Retrieve confirmed mobile orders without importing the same order twice.
* Run incremental jobs suitable for catalogues and contact lists containing
  thousands of records.
* Update selected products, stock records or contacts without sending the full
  dataset again.

Mobile and API
--------------

The integration provides both a customer-facing mobile experience and access
to authenticated API families for catalogue, FAM1/FAM2 categories, customers,
orders, fulfilment, payments and webhooks. Representative resources include
``product/list``, ``fam1/list``, ``fam2/list``, ``customer/list`` and
``order/list``.

Private catalogue
-----------------

SellViaApp can be configured so the connected catalogue is absent from the
public directory and accessible only to authorised accounts. Private access is
managed in SellViaApp while the Odoo module continues to enforce its own OAuth
authentication gate.

Installation
------------

1. Place ``sellviaapp_connector`` in a configured Odoo add-ons directory.
2. Restart Odoo and update the Apps list.
3. Install **SellViaApp Connector**.
4. Open **SellViaApp**, approve the displayed code and select
   **Complete connection**.
5. Synchronise the catalogue and stock, then choose the required customer and
   order operations.

The module requires the standard Odoo ``base``, ``product``, ``stock`` and
``sale_management`` modules and the Python ``requests`` package.

Security
--------

The SellViaApp password is never given to Odoo. Credentials are restricted to
Odoo Settings administrators, production traffic requires HTTPS, tokens can be
revoked, and image access uses connector-specific signatures.
