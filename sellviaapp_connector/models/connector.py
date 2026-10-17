import hashlib
import hmac
import json
import logging
import secrets
import uuid
import base64
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.mail import email_normalize


_logger = logging.getLogger(__name__)


class SellViaAppConnector(models.Model):
    _name = "sellviaapp.connector"
    _description = "SellViaApp Connector"
    _order = "company_id, id"

    name = fields.Char(required=True, default="SellViaApp")
    singleton_key = fields.Integer(required=True, default=1, readonly=True, copy=False)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, ondelete="cascade"
    )
    api_url = fields.Char(required=True, default="https://api.sellviaapp.com/")
    public_base_url = fields.Char(
        help="Public HTTPS URL of this Odoo instance. SellViaApp uses it to retrieve product images."
    )
    state = fields.Selection(
        [
            ("disconnected", "Not connected"),
            ("authorizing", "Waiting for approval"),
            ("connected", "Connected"),
            ("error", "Attention required"),
        ],
        default="disconnected",
        required=True,
        readonly=True,
    )
    installation_id = fields.Char(required=True, readonly=True, copy=False, default=lambda self: str(uuid.uuid4()))
    device_code = fields.Char(copy=False, groups="base.group_system")
    user_code = fields.Char(copy=False, readonly=True)
    verification_uri = fields.Char(copy=False, readonly=True)
    authorization_expires_at = fields.Datetime(copy=False, readonly=True)
    access_token = fields.Char(copy=False, groups="base.group_system")
    api_key = fields.Char(copy=False, groups="base.group_system")
    token_expires_at = fields.Datetime(copy=False, readonly=True)
    supplier_name = fields.Char(copy=False, readonly=True)
    supplier_suffix = fields.Char(copy=False, readonly=True)
    supplier_currency = fields.Char(copy=False, readonly=True)
    auto_sync = fields.Boolean(default=True)
    stock_mode = fields.Selection(
        [("free", "Available stock"), ("on_hand", "On-hand stock")], default="free", required=True
    )
    image_secret = fields.Char(required=True, copy=False, default=lambda self: secrets.token_urlsafe(32))
    verify_ssl = fields.Boolean(default=True, help="Keep enabled outside an isolated development environment.")
    last_sync_at = fields.Datetime(readonly=True)
    last_sync_summary = fields.Text(readonly=True)
    last_inventory_sync_at = fields.Datetime(readonly=True)
    last_inventory_sync_summary = fields.Text(readonly=True)
    last_customer_sync_at = fields.Datetime(readonly=True)
    last_customer_sync_summary = fields.Text(readonly=True)
    last_error = fields.Text(readonly=True)
    binding_ids = fields.One2many("sellviaapp.binding", "connector_id", readonly=True)
    log_ids = fields.One2many("sellviaapp.sync.log", "connector_id", readonly=True)
    is_authenticated = fields.Boolean(
        compute="_compute_is_authenticated",
        compute_sudo=True,
        string="SellViaApp authentication established",
    )
    setup_progress = fields.Integer(compute="_compute_overview", compute_sudo=True)
    eligible_product_count = fields.Integer(compute="_compute_overview", compute_sudo=True)
    eligible_customer_count = fields.Integer(compute="_compute_overview", compute_sudo=True)
    linked_customer_count = fields.Integer(compute="_compute_overview", compute_sudo=True)
    imported_order_count = fields.Integer(compute="_compute_overview", compute_sudo=True)

    _sql_constraints = [
        ("sellviaapp_singleton_unique", "unique(singleton_key)", "Only one SellViaApp connection is allowed in this Odoo database."),
        ("sellviaapp_company_unique", "unique(company_id)", "Only one SellViaApp connector is allowed per company."),
        ("sellviaapp_installation_unique", "unique(installation_id)", "The installation identifier must be unique."),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        if len(vals_list) != 1 or self.sudo().search_count([]):
            raise ValidationError(_("Only one SellViaApp connection is allowed in this Odoo database."))
        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url", "")
        for vals in vals_list:
            vals.setdefault("public_base_url", base_url)
            vals["singleton_key"] = 1
        return super().create(vals_list)

    @api.model
    def action_open_singleton(self):
        """Open the only connector directly, creating its empty shell if needed."""
        connector = self._configure_legacy_action()
        return {
            "type": "ir.actions.act_window",
            "name": _("SellViaApp"),
            "res_model": "sellviaapp.connector",
            "view_mode": "form",
            "views": [(self.env.ref("sellviaapp_connector.view_sellviaapp_connector_form").id, "form")],
            "res_id": connector.id,
            "target": "current",
            "context": {"form_view_initial_mode": "edit"},
        }

    @api.model
    def _configure_legacy_action(self):
        """Keep old menus, bookmarks and open tabs bound to the singleton.

        Early connector versions exposed a plain form window action. Odoo opens
        such an action as a new record when it has no ``res_id``; pressing the
        connection button then attempts to create a second connector and is
        rejected by the singleton constraint. Keeping the legacy action bound
        makes those historical URLs safe while the main menu continues to use
        the dynamic server action.
        """
        connector = self.sudo().search([], order="id", limit=1)
        if not connector:
            connector = self.sudo().create(
                {
                    "name": "SellViaApp",
                    "company_id": self.env.company.id,
                }
            )
        legacy_action = self.env.ref(
            "sellviaapp_connector.action_sellviaapp_connector",
            raise_if_not_found=False,
        )
        if legacy_action and legacy_action.res_id != connector.id:
            legacy_action.sudo().write({"res_id": connector.id})
        return connector

    @api.depends("state", "access_token", "api_key", "token_expires_at")
    def _compute_is_authenticated(self):
        now = fields.Datetime.now()
        for connector in self:
            not_expired = not connector.token_expires_at or connector.token_expires_at > now
            connector.is_authenticated = bool(
                connector.state in ("connected", "error")
                and connector.access_token
                and connector.api_key
                and not_expired
            )

    def _ensure_authenticated(self):
        self.ensure_one()
        if not self.is_authenticated:
            if self.token_expires_at and self.token_expires_at <= fields.Datetime.now():
                message = _("The SellViaApp authorisation has expired. Reconnect this Odoo company.")
            else:
                message = _("Connect and authorise this Odoo company in SellViaApp before using this feature.")
            raise UserError(message)
        return True

    @api.depends(
        "state",
        "access_token",
        "api_key",
        "last_sync_at",
        "last_customer_sync_at",
        "last_customer_import_at",
        "last_order_import_at",
    )
    def _compute_overview(self):
        """Expose useful, non-technical indicators on the connector home screen."""
        Partner = self.env["res.partner"].sudo()
        SaleOrder = self.env["sale.order"].sudo()
        Product = self.env["product.product"].sudo()
        for connector in self:
            company_domain = [("company_id", "in", [False, connector.company_id.id])]
            connector.eligible_product_count = Product.with_company(connector.company_id).search_count(
                connector._product_domain()
            )
            connector.eligible_customer_count = Partner.with_company(connector.company_id).search_count(
                connector._customer_domain()
            )
            connector.linked_customer_count = Partner.with_company(connector.company_id).search_count(
                company_domain + [("sellviaapp_customer_key", "!=", False)]
            )
            connector.imported_order_count = SaleOrder.with_company(connector.company_id).search_count(
                [("company_id", "=", connector.company_id.id), ("sellviaapp_order_guid", "!=", False)]
            )
            progress = 10
            if connector.state in ("connected", "error") and connector.access_token and connector.api_key:
                progress += 35
            if connector.last_sync_at:
                progress += 25
            if connector.last_customer_sync_at or getattr(connector, "last_customer_import_at", False):
                progress += 15
            if getattr(connector, "last_order_import_at", False):
                progress += 15
            connector.setup_progress = min(progress, 100)

    def action_open_sellviaapp_dashboard(self):
        self.ensure_one()
        self._ensure_authenticated()
        return {
            "type": "ir.actions.act_url",
            "url": "https://sellviaapp.com/dashboard/",
            "target": "new",
        }

    def action_open_sellviaapp_tutorial(self):
        self.ensure_one()
        language = (self.env.context.get("lang") or "en").split("_")[0].lower()
        tutorial_slugs = {
            "fr": "tutoriel-connecteur-odoo-sellviaapp",
            "nl": "handleiding-odoo-sellviaapp-koppeling",
            "en": "odoo-sellviaapp-connector-tutorial",
            "es": "tutorial-conector-odoo-sellviaapp",
            "pt": "tutorial-conector-odoo-sellviaapp",
            "de": "anleitung-odoo-sellviaapp-integration",
            "it": "tutorial-connettore-odoo-sellviaapp",
        }
        if language not in tutorial_slugs:
            language = "en"
        return {
            "type": "ir.actions.act_url",
            "url": "https://sellviaapp.com/%s/%s" % (language, tutorial_slugs[language]),
            "target": "new",
        }

    def action_open_sellviaapp_support(self):
        self.ensure_one()
        self._ensure_authenticated()
        language = (self.env.context.get("lang") or "en").split("_")[0].lower()
        result = self._request("POST", "odoo/support/session", {"lang": language})
        support_url = (result.get("url") or "").strip()
        if not support_url:
            raise UserError(_("SellViaApp did not return a secure support link."))
        return {
            "type": "ir.actions.act_url",
            "url": support_url,
            "target": "new",
        }

    def action_open_products(self):
        self.ensure_one()
        self._ensure_authenticated()
        return {
            "type": "ir.actions.act_window",
            "name": _("Products published to SellViaApp"),
            "res_model": "product.product",
            "view_mode": "tree,form",
            "domain": self._product_domain(),
            "context": {"default_company_id": self.company_id.id},
        }

    def action_open_customers(self):
        self.ensure_one()
        self._ensure_authenticated()
        return {
            "type": "ir.actions.act_window",
            "name": _("SellViaApp customers"),
            "res_model": "res.partner",
            "view_mode": "tree,form",
            "domain": [
                ("company_id", "in", [False, self.company_id.id]),
                "|",
                ("customer_rank", ">", 0),
                ("sellviaapp_customer_key", "!=", False),
            ],
            "context": {"default_company_id": self.company_id.id},
        }

    def action_open_orders(self):
        self.ensure_one()
        self._ensure_authenticated()
        return {
            "type": "ir.actions.act_window",
            "name": _("SellViaApp orders"),
            "res_model": "sale.order",
            "view_mode": "tree,form",
            "domain": [("company_id", "=", self.company_id.id), ("sellviaapp_order_guid", "!=", False)],
            "context": {"default_company_id": self.company_id.id},
        }

    @api.constrains("api_url")
    def _check_api_url(self):
        for connector in self:
            value = (connector.api_url or "").strip().lower()
            if not value.startswith("https://") and not value.startswith("http://localhost") and not value.startswith("http://127.0.0.1"):
                raise ValidationError(_("The SellViaApp API URL must use HTTPS (HTTP is accepted only for localhost)."))

    def _endpoint(self, path):
        self.ensure_one()
        return urljoin((self.api_url or "").rstrip("/") + "/", path.lstrip("/"))

    def _request(self, method, path, payload=None, authenticated=True, timeout=45):
        self.ensure_one()
        headers = {"Accept": "application/json", "Content-Type": "application/json", "User-Agent": "Odoo-SellViaApp/1.0"}
        if authenticated:
            self._ensure_authenticated()
            headers["Authorization"] = "Bearer %s" % self.access_token
            headers["X-API-Key"] = self.api_key
        try:
            response = requests.request(
                method,
                self._endpoint(path),
                json=payload or {},
                headers=headers,
                timeout=timeout,
                verify=bool(self.verify_ssl),
            )
        except requests.RequestException as exc:
            raise UserError(_("SellViaApp cannot be reached: %s") % str(exc)) from exc
        try:
            body = response.json()
        except ValueError as exc:
            raise UserError(_("SellViaApp returned an unreadable response (HTTP %s).") % response.status_code) from exc
        if not response.ok or not body.get("success"):
            error = body.get("error") if isinstance(body.get("error"), dict) else {}
            code = error.get("code") or "HTTP_%s" % response.status_code
            message = error.get("message") or body.get("message") or _("Unknown SellViaApp error")
            raise UserError("%s — %s" % (code, message))
        data = body.get("data")
        return data if isinstance(data, dict) else {}

    def action_start_oauth(self):
        self.ensure_one()
        if self.is_authenticated:
            raise UserError(_("Disconnect the current SellViaApp account before starting a new connection."))
        # A missing or expired credential set must never trap administrators on
        # a technical error screen. Clear only unusable local OAuth data, then
        # start a fresh device-authorisation flow from the focused connection
        # card. Valid authenticated connections still require an explicit
        # disconnect above.
        if self.state in ("connected", "error") or self.access_token or self.api_key:
            self.write(
                {
                    "state": "disconnected",
                    "device_code": False,
                    "user_code": False,
                    "verification_uri": False,
                    "authorization_expires_at": False,
                    "access_token": False,
                    "api_key": False,
                    "token_expires_at": False,
                    "supplier_name": False,
                    "supplier_suffix": False,
                    "supplier_currency": False,
                    "last_error": False,
                }
            )
        instance_url = (self.public_base_url or self.env["ir.config_parameter"].sudo().get_param("web.base.url", "")).rstrip("/")
        result = self._request(
            "POST",
            "odoo/oauth/device/code",
            {
                "client_id": "sellviaapp_odoo",
                "installation_id": self.installation_id,
                "instance_url": instance_url,
            },
            authenticated=False,
        )
        expires_in = max(60, int(result.get("expires_in") or 900))
        self.write(
            {
                "state": "authorizing",
                "device_code": result.get("device_code"),
                "user_code": result.get("user_code"),
                "verification_uri": result.get("verification_uri_complete") or result.get("verification_uri"),
                "authorization_expires_at": fields.Datetime.now() + timedelta(seconds=expires_in),
                "last_error": False,
            }
        )
        return self.action_open_authorization()

    def action_open_authorization(self):
        self.ensure_one()
        if not self.verification_uri:
            raise UserError(_("Start the SellViaApp connection first."))
        return {"type": "ir.actions.act_url", "url": self.verification_uri, "target": "new"}

    def action_complete_oauth(self):
        self.ensure_one()
        if not self.device_code:
            raise UserError(_("Start the connection again to obtain a new authorisation code."))
        try:
            result = self._request(
                "POST",
                "odoo/oauth/device/token",
                {
                    "client_id": "sellviaapp_odoo",
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    "device_code": self.device_code,
                },
                authenticated=False,
            )
        except UserError as exc:
            self.write({"state": "authorizing", "last_error": str(exc)})
            raise
        account = result.get("account") if isinstance(result.get("account"), dict) else {}
        expiry = result.get("expires_at")
        expiry_datetime = False
        if expiry:
            try:
                expiry_datetime = datetime.fromisoformat(str(expiry).replace("Z", "+00:00"))
                if expiry_datetime.tzinfo:
                    expiry_datetime = expiry_datetime.astimezone(timezone.utc).replace(tzinfo=None)
            except ValueError:
                expiry_datetime = False
        self.write(
            {
                "state": "connected",
                "access_token": result.get("access_token"),
                "api_key": result.get("api_key"),
                "token_expires_at": expiry_datetime,
                "supplier_name": account.get("supplier_name"),
                "supplier_suffix": account.get("suffix"),
                "supplier_currency": account.get("currency"),
                "device_code": False,
                "authorization_expires_at": False,
                "last_error": False,
            }
        )
        self._log("connection", "success", _("Odoo is connected to %s.") % (self.supplier_name or "SellViaApp"))
        notification = self._notification(
            _("SellViaApp connected"),
            _("You can now synchronise the catalogue, prices, images and stock."),
        )
        notification["params"]["next"] = {"type": "ir.actions.client", "tag": "reload"}
        return notification

    def action_test_connection(self):
        self.ensure_one()
        account = self._request("GET", "odoo/account")
        self.write(
            {
                "state": "connected",
                "supplier_name": account.get("supplier_name"),
                "supplier_suffix": account.get("suffix"),
                "supplier_currency": account.get("currency"),
                "last_error": False,
            }
        )
        return self._notification(_("Connection verified"), _("SellViaApp recognised this Odoo company."))

    def action_disconnect(self):
        self.ensure_one()
        # An expired local token cannot call the remote revocation endpoint, but
        # administrators must still be able to clear it and start OAuth again.
        if self.access_token and self.api_key and self.is_authenticated:
            self._request("POST", "odoo/disconnect")
        self.write(
            {
                "state": "disconnected",
                "device_code": False,
                "user_code": False,
                "verification_uri": False,
                "authorization_expires_at": False,
                "access_token": False,
                "api_key": False,
                "token_expires_at": False,
                "supplier_name": False,
                "supplier_suffix": False,
                "supplier_currency": False,
                "image_secret": secrets.token_urlsafe(32),
                "last_error": False,
            }
        )
        self._log("connection", "info", _("SellViaApp access was revoked."))
        notification = self._notification(
            _("Disconnected"),
            _("This Odoo installation can no longer update SellViaApp."),
        )
        notification["params"]["next"] = {"type": "ir.actions.client", "tag": "reload"}
        return notification

    def _product_domain(self):
        return [("active", "=", True), ("sale_ok", "=", True), ("company_id", "in", [False, self.company_id.id])]

    def _catalogue_products(self):
        return self.env["product.product"].with_company(self.company_id).search(self._product_domain(), order="id")

    def _category_chain(self, category):
        chain = self.env["product.category"]
        current = category
        while current:
            chain = current + chain
            current = current.parent_id
        return chain

    def _catalogue_category_pair(self, category):
        """Return the useful SellViaApp FAM1/FAM2 pair for an Odoo category.

        Odoo's default root category (usually ``All``) is a technical
        container. Publishing it as FAM1 makes every mobile product appear
        below an unhelpful "All" menu. Keep the first category below that
        root as FAM1 and flatten the deepest category as FAM2.
        """
        chain = self._category_chain(category)
        if len(chain) > 1 and not chain[0].parent_id:
            chain = chain[1:]
        if not chain:
            return category, self.env["product.category"]
        primary = chain[0]
        secondary = chain[-1] if len(chain) > 1 else self.env["product.category"]
        return primary, secondary

    def _language_codes(self):
        languages = self.env["res.lang"].sudo().search([("active", "=", True)], order="id", limit=18)
        result = []
        seen = set()
        for language in languages:
            short = (language.code or "en").split("_")[0].split("-")[0].lower()
            if short not in seen:
                result.append((short, language.code))
                seen.add(short)
        return result

    def _category_payload(self, category, parent=False):
        translations = {}
        for short, language in self._language_codes():
            name = category.with_context(lang=language).name
            if name and name != category.name:
                translations[short] = {"name": name}
        return {
            "external_id": "product.category:%s" % category.id,
            "name": category.name,
            "parent_external_id": "product.category:%s" % parent.id if parent else "",
            "active": True,
            "sort_order": category.id,
            "translations": translations,
        }

    @staticmethod
    def _encoded_image(value):
        if not value:
            return False
        encoded = value.decode("ascii") if isinstance(value, bytes) else str(value)
        try:
            binary = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError):
            return False
        if not binary or len(binary) > 8 * 1024 * 1024:
            return False
        return {
            "data": encoded,
            "sha256": hashlib.sha256(binary).hexdigest(),
        }

    def _inline_images(self, product):
        images = []
        primary = self._encoded_image(product.image_1920)
        if primary:
            images.append(primary)
        if "product.image" in self.env.registry.models:
            image_model = self.env["product.image"]
            for image in image_model.sudo().search(
                [("product_tmpl_id", "=", product.product_tmpl_id.id)], order="sequence,id", limit=4
            ):
                encoded = self._encoded_image(image.image_1920)
                if encoded:
                    images.append(encoded)
                if len(images) == 5:
                    break
        return images

    def _image_urls(self, product):
        base = (self.public_base_url or "").strip().rstrip("/")
        if not base.lower().startswith("https://") or not product.image_1920:
            return []
        secondary_images = []
        if "product.image" in self.env.registry.models:
            secondary_images = self.env["product.image"].sudo().search(
                [("product_tmpl_id", "=", product.product_tmpl_id.id)], order="sequence,id", limit=4
            )
        count = 1 + len(secondary_images)
        write_dates = [value for value in [product.write_date] + [image.write_date for image in secondary_images] if value]
        version_date = max(write_dates) if write_dates else fields.Datetime.now()
        version = fields.Datetime.to_string(version_date).replace(" ", "T")
        urls = []
        for slot in range(1, min(5, count) + 1):
            message = "%s:%s:%s" % (self.id, product.id, slot)
            signature = hmac.new(self.image_secret.encode(), message.encode(), hashlib.sha256).hexdigest()
            urls.append("%s/sellviaapp/image/%s/%s/%s?signature=%s&v=%s" % (base, self.id, product.id, slot, signature, version))
        return urls

    def _product_payload(self, product):
        template = product.product_tmpl_id
        primary_category, secondary_category = self._catalogue_category_pair(template.categ_id)
        description = template.description_sale or template.description or ""
        product_name = product.with_context(display_default_code=False).display_name
        translations = {}
        for short, language in self._language_codes():
            translated = product.with_context(lang=language)
            translated_template = translated.product_tmpl_id
            name = translated.with_context(display_default_code=False).display_name
            translated_description = translated_template.description_sale or translated_template.description or ""
            if name != product_name or translated_description != description:
                translations[short] = {"name": name, "description": translated_description}
        taxes = template.taxes_id.filtered(lambda tax: not tax.company_id or tax.company_id == self.company_id)
        vat = taxes[:1].amount if taxes else 0.0
        stock = product.free_qty if self.stock_mode == "free" else product.qty_available
        attributes = [
            {"name": value.attribute_id.name, "option": value.name}
            for value in product.product_template_attribute_value_ids
        ]
        image_urls = self._image_urls(product)
        inline_images = [] if image_urls else self._inline_images(product)
        return {
            "external_id": "product.product:%s" % product.id,
            "parent_external_id": "product.template:%s" % template.id,
            "type": "variation" if template.product_variant_count > 1 else "simple",
            "sku": product.default_code or "ODOO-%s" % product.id,
            "barcode": product.barcode or "",
            "name": product_name,
            "description": description,
            "regular_price": float(product.lst_price),
            "vat_rate": float(vat),
            "stock_quantity": float(stock),
            "stock_status": "instock" if stock > 0 else "outofstock",
            "active": bool(product.active and template.active and template.sale_ok),
            "status": "publish" if product.active and template.active and template.sale_ok else "draft",
            "category_external_id": "product.category:%s" % primary_category.id if primary_category else "",
            "subcategory_external_id": "product.category:%s" % secondary_category.id if secondary_category else "",
            "images": image_urls,
            "images_inline": inline_images,
            "attributes": attributes,
            "translations": translations,
            "unit": template.uom_id.name or "pc",
            "unit_name": template.uom_id.name or _("Item"),
        }

    def _customer_domain(self):
        return [
            ("active", "=", True),
            ("type", "=", "contact"),
            ("email", "!=", False),
            ("company_id", "in", [False, self.company_id.id]),
            ("id", "!=", self.company_id.partner_id.id),
        ]

    def _customer_payload(self, partner):
        email = email_normalize(partner.email or "", strict=False) or ""
        language = (partner.lang or "en").split("_")[0].split("-")[0].lower()
        if len(language) != 2:
            language = "en"
        company_name = partner.name if partner.is_company else (partner.parent_id.name or "")
        first_name = "" if partner.is_company else partner.name
        street = "\n".join(value for value in [partner.street, partner.street2] if value)
        return {
            "external_id": "res.partner:%s" % partner.id,
            "username": email,
            "email": email,
            "display_name": partner.display_name,
            "first_name": first_name,
            "last_name": "",
            "company": company_name,
            "phone": partner.mobile or partner.phone or "",
            "vat_number": partner.vat or "",
            "type": "societe" if partner.is_company else "particulier",
            "language": language,
            "active": bool(partner.active),
            "send_invitation": True,
            "billing": {
                "address": street,
                "postcode": partner.zip or "",
                "city": partner.city or "",
                "country": partner.country_id.code or "",
                "phone": partner.phone or partner.mobile or "",
                "company": company_name,
                "first_name": first_name,
                "last_name": "",
            },
            "roles": ["customer"],
        }

    def _sync_customers(self, partners=None, force=False):
        """Synchronise contacts incrementally in bounded batches.

        A global run skips payloads already represented by a successful
        binding. A focused run can set ``force`` so the selected contact is
        refreshed without walking or resending the whole address book.
        """
        self.ensure_one()
        self.env.cr.execute(
            "SELECT pg_try_advisory_xact_lock(%s, %s)",
            (5457481, self.id),
        )
        if not self.env.cr.fetchone()[0]:
            raise UserError(
                _("A SellViaApp contact synchronisation is already in progress. Please wait for it to finish.")
            )
        self._ensure_authenticated()
        Partner = self.env["res.partner"].sudo().with_company(self.company_id)
        if partners is None:
            partners = Partner.search(self._customer_domain(), order="id")
        else:
            partners = partners.sudo().with_company(self.company_id).filtered(
                lambda partner: partner.active
                and partner.type == "contact"
                and partner.id != self.company_id.partner_id.id
                and (not partner.company_id or partner.company_id == self.company_id)
            )

        bindings = self._binding_map("res.partner", partners.ids)
        failures = []
        batch = []
        counts = {
            "processed": 0,
            "created": 0,
            "updated": 0,
            "skipped_unchanged": 0,
            "sent_to_sellviaapp": 0,
            "invitations_sent": 0,
            "invitations_queued": 0,
        }

        def flush(items):
            if not items:
                return
            payloads = [item[0] for item in items]
            partner_by_external = {item[0]["external_id"]: item[1] for item in items}
            source_by_external = {item["external_id"]: item for item in payloads}
            result = self._request("POST", "odoo/customers/sync", {"items": payloads}, timeout=120)
            returned = set()
            for item in result.get("items", []):
                external = str(item.get("external_id") or "")
                returned.add(external)
                partner = partner_by_external.get(external)
                if not partner:
                    continue
                if not item.get("success"):
                    error = str(item.get("error") or _("unknown error"))
                    failures.append("%s: %s" % (partner.display_name, error))
                    partner.write({
                        "sellviaapp_mobile_sync_state": "error",
                        "sellviaapp_mobile_sync_error": error,
                    })
                    continue
                action = str(item.get("action") or "updated")
                delivery = str(item.get("invitation_delivery") or "not_requested")
                customer_id = int(item.get("customer_id") or 0)
                counts["processed"] += 1
                if action in ("created", "updated"):
                    counts[action] += 1
                if delivery == "sent":
                    counts["invitations_sent"] += 1
                elif delivery == "queued":
                    counts["invitations_queued"] += 1
                values = {
                    "sellviaapp_mobile_customer_id": customer_id or False,
                    "sellviaapp_mobile_login": item.get("megawinapp_login") or item.get("login") or False,
                    "sellviaapp_mobile_sync_state": "synced",
                    "sellviaapp_mobile_invitation_status": delivery,
                    "sellviaapp_mobile_synced_at": fields.Datetime.now(),
                    "sellviaapp_mobile_sync_error": False,
                }
                if customer_id > 0 and not partner.sellviaapp_customer_key:
                    values["sellviaapp_customer_key"] = "%s:%s:%s" % (
                        (self.supplier_suffix or "supplier").lower(), self.id, customer_id
                    )
                partner.write(values)
                self._remember_binding(
                    "res.partner", partner.id, external, source_by_external[external], "customer"
                )
            for external, partner in partner_by_external.items():
                if external in returned:
                    continue
                error = _("SellViaApp did not return a result for this contact.")
                failures.append("%s: %s" % (partner.display_name, error))
                partner.write({
                    "sellviaapp_mobile_sync_state": "error",
                    "sellviaapp_mobile_sync_error": error,
                })
            counts["sent_to_sellviaapp"] += len(items)
            items.clear()

        for partner in partners:
            payload = self._customer_payload(partner)
            if not payload["email"]:
                error = _("%s: a valid email address is required to create the mobile access.") % partner.display_name
                failures.append(error)
                partner.write({
                    "sellviaapp_mobile_sync_state": "error",
                    "sellviaapp_mobile_sync_error": error,
                })
                continue
            if not force and not self._payload_needs_sync(bindings.get(partner.id), payload):
                counts["skipped_unchanged"] += 1
                continue
            batch.append((payload, partner))
            if len(batch) >= 250:
                flush(batch)
        flush(batch)

        summary = {
            "eligible_customers": len(partners),
            **counts,
            "failures": failures,
        }
        self.write({
            "last_customer_sync_at": fields.Datetime.now(),
            "last_customer_sync_summary": json.dumps(summary, ensure_ascii=False, indent=2),
            "last_error": "\n".join(failures) if failures else False,
            "state": "error" if failures else "connected",
        })
        self._log("customer_sync", "warning" if failures else "success", json.dumps(summary, ensure_ascii=False))
        return summary

    def action_sync_customers(self):
        self.ensure_one()
        summary = self._sync_customers(force=False)
        message = _("%s contact(s) synchronised; %s unchanged contact(s) skipped. %s invitation(s) sent, %s queued.") % (
            summary["processed"],
            summary["skipped_unchanged"],
            summary["invitations_sent"],
            summary["invitations_queued"],
        )
        if summary["failures"]:
            message += _(" %s warning(s).") % len(summary["failures"])
        return self._notification(
            _("SellViaApp customer synchronisation"),
            message,
            "warning" if summary["failures"] else "success",
        )

    @staticmethod
    def _chunks(items, size):
        for index in range(0, len(items), size):
            yield items[index : index + size]

    def _binding(self, model_name, res_id):
        return self.env["sellviaapp.binding"].search(
            [("connector_id", "=", self.id), ("model_name", "=", model_name), ("res_id", "=", res_id)], limit=1
        )

    @staticmethod
    def _payload_digest(payload):
        return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    @classmethod
    def _binding_payload_digest(cls, model_name, payload):
        """Keep catalogue and inventory fingerprints independent.

        Stock changes are handled by the lightweight inventory endpoint. They
        must not make the next catalogue run resend descriptions, translations
        and images for the same product.
        """
        if model_name != "product.product":
            return cls._payload_digest(payload)
        catalogue_payload = dict(payload)
        catalogue_payload.pop("stock_quantity", None)
        catalogue_payload.pop("stock_status", None)
        return cls._payload_digest(catalogue_payload)

    def _binding_map(self, model_name, res_ids):
        if not res_ids:
            return {}
        bindings = self.env["sellviaapp.binding"].sudo().search(
            [
                ("connector_id", "=", self.id),
                ("model_name", "=", model_name),
                ("res_id", "in", list(res_ids)),
            ]
        )
        return {binding.res_id: binding for binding in bindings}

    def _payload_needs_sync(self, binding, payload):
        model_name = binding.model_name if binding else ""
        digest = self._binding_payload_digest(model_name, payload) if model_name else self._payload_digest(payload)
        return not binding or binding.state != "synced" or binding.payload_hash != digest

    def _remember_binding(self, model_name, res_id, external_id, payload, remote_type):
        digest = self._binding_payload_digest(model_name, payload)
        binding = self._binding(model_name, res_id)
        now = fields.Datetime.now()
        values = {
            "connector_id": self.id,
            "model_name": model_name,
            "res_id": res_id,
            "external_id": external_id,
            "remote_type": remote_type,
            "payload_hash": digest,
            "state": "synced",
            "last_synced_at": now,
            "last_error": False,
        }
        if model_name == "product.product" and "stock_quantity" in payload:
            inventory_payload = {
                "external_id": external_id,
                "stock_quantity": float(payload.get("stock_quantity") or 0.0),
                "stock_status": payload.get("stock_status") or "outofstock",
            }
            values.update({
                "inventory_hash": self._payload_digest(inventory_payload),
                "inventory_synced_at": now,
            })
        if binding:
            binding.write(values)
        else:
            self.env["sellviaapp.binding"].create(values)

    def _consume_sync_result(self, path, payloads, model_name, id_by_external, remote_type):
        failures = []
        product_chunk_size = 5 if any(item.get("images_inline") for item in payloads) else 250
        for chunk in self._chunks(payloads, product_chunk_size if "products/sync" in path else 500):
            result = self._request("POST", path, {"items": chunk}, timeout=120)
            by_external = {item["external_id"]: item for item in chunk}
            for item in result.get("items", []):
                external = str(item.get("external_id") or "")
                if item.get("success"):
                    source = by_external.get(external)
                    if source and external in id_by_external:
                        item_type = item.get("type") if model_name == "product.category" else remote_type
                        self._remember_binding(model_name, id_by_external[external], external, source, item_type or remote_type)
                else:
                    failures.append("%s: %s" % (external, item.get("error") or _("unknown error")))
        return failures

    def _archive_stale(self, model_name, active_external_ids):
        bindings = self.env["sellviaapp.binding"].search(
            [("connector_id", "=", self.id), ("model_name", "=", model_name), ("state", "=", "synced")]
        )
        stale = bindings.filtered(lambda binding: binding.external_id not in active_external_ids)
        archived_count = 0
        failures = []
        for remote_type in set(stale.mapped("remote_type")):
            group = stale.filtered(lambda binding: binding.remote_type == remote_type)
            for chunk in self._chunks(group.mapped("external_id"), 500):
                if not chunk:
                    continue
                if remote_type == "category":
                    result = self._request("POST", "odoo/categories/archive", {"items": chunk}, timeout=120)
                else:
                    result = self._request(
                        "POST",
                        "odoo/products/archive",
                        {"entity_type": remote_type or "product", "items": chunk},
                        timeout=120,
                    )
                succeeded = {
                    str(item.get("external_id"))
                    for item in result.get("items", [])
                    if item.get("success")
                }
                archived = group.filtered(lambda binding: binding.external_id in succeeded)
                if archived:
                    archived.write({"state": "archived", "last_synced_at": fields.Datetime.now()})
                    archived_count += len(archived)
                failures += [
                    "%s: %s" % (item.get("external_id") or "?", item.get("error") or _("archive failed"))
                    for item in result.get("items", [])
                    if not item.get("success")
                ]
        return archived_count, failures

    def _catalogue_categories(self, products):
        category_pairs = {}
        for product in products:
            primary, secondary = self._catalogue_category_pair(product.categ_id)
            if primary:
                category_pairs[primary.id] = (primary, False)
            if secondary:
                category_pairs[secondary.id] = (secondary, primary)
        return [category_pairs[key] for key in sorted(category_pairs)]

    def _sync_category_payloads(self, categories):
        bindings = self._binding_map("product.category", [category.id for category, _parent in categories])
        payloads = []
        id_by_external = {}
        unchanged = 0
        for category, parent in categories:
            payload = self._category_payload(category, parent)
            if not self._payload_needs_sync(bindings.get(category.id), payload):
                unchanged += 1
                continue
            payloads.append(payload)
            id_by_external[payload["external_id"]] = category.id
        failures = self._consume_sync_result(
            "odoo/categories/sync", payloads, "product.category", id_by_external, "category"
        ) if payloads else []
        return len(payloads), unchanged, failures

    def _sync_product_payloads(self, products, force=False):
        """Send products in bounded batches so very large catalogues stay memory-safe."""
        bindings = self._binding_map("product.product", products.ids)
        plain_batch = []
        inline_batch = []
        failures = []
        sent = 0
        unchanged = 0
        active_external_ids = set()

        def flush(batch):
            nonlocal sent
            if not batch:
                return
            payloads = [item[0] for item in batch]
            id_by_external = {item[0]["external_id"]: item[1] for item in batch}
            failures.extend(
                self._consume_sync_result(
                    "odoo/products/sync", payloads, "product.product", id_by_external, "product"
                )
            )
            sent += len(batch)
            batch.clear()

        for product in products:
            payload = self._product_payload(product)
            active_external_ids.add(payload["external_id"])
            if not force and not self._payload_needs_sync(bindings.get(product.id), payload):
                unchanged += 1
                continue
            target = inline_batch if payload.get("images_inline") else plain_batch
            target.append((payload, product.id))
            if len(target) >= (5 if target is inline_batch else 250):
                flush(target)

        flush(inline_batch)
        flush(plain_batch)
        return sent, unchanged, active_external_ids, failures

    def _acquire_product_sync_lock(self):
        """Prevent catalogue and inventory jobs from racing each other."""
        self.ensure_one()
        self.env.cr.execute(
            "SELECT pg_try_advisory_xact_lock(%s, %s)",
            (5457482, self.id),
        )
        if not self.env.cr.fetchone()[0]:
            raise UserError(
                _("A SellViaApp product or stock synchronisation is already in progress. Please wait for it to finish.")
            )

    def _inventory_payload(self, product):
        stock = product.free_qty if self.stock_mode == "free" else product.qty_available
        return {
            "external_id": "product.product:%s" % product.id,
            "stock_quantity": float(stock),
            "stock_status": "instock" if stock > 0 else "outofstock",
        }

    def _sync_inventory(self, products=None, force=False, publish_missing=False):
        """Synchronise stock through the lightweight 500-item endpoint.

        Global runs are incremental and skip unpublished products until the
        catalogue job creates them. A focused user action can first publish
        missing selected products, then updates only the requested stock.
        """
        self.ensure_one()
        self._acquire_product_sync_lock()
        self._ensure_authenticated()
        Product = self.env["product.product"].sudo().with_company(self.company_id)
        if products is None:
            products = Product.search(self._product_domain(), order="id")
        else:
            products = products.sudo().with_company(self.company_id).filtered_domain(self._product_domain()).sorted("id")

        bindings = self._binding_map("product.product", products.ids)
        missing = products.filtered(lambda product: not bindings.get(product.id) or bindings[product.id].state != "synced")
        failures = []
        published_missing = 0
        if missing and publish_missing:
            catalogue_summary = self._synchronise_products(missing, force=True, archive_stale=False)
            failures.extend(catalogue_summary["failures"])
            bindings = self._binding_map("product.product", products.ids)
            published_missing = len(missing.filtered(lambda product: bindings.get(product.id) and bindings[product.id].state == "synced"))

        batch = []
        updated = 0
        unchanged = 0
        not_published = 0

        def flush(items):
            nonlocal updated
            if not items:
                return
            payloads = [item[0] for item in items]
            binding_by_external = {item[0]["external_id"]: item[1] for item in items}
            payload_by_external = {item[0]["external_id"]: item[0] for item in items}
            result = self._request("PATCH", "odoo/products/inventory", {"items": payloads}, timeout=120)
            returned = set()
            now = fields.Datetime.now()
            for item in result.get("items", []):
                external = str(item.get("external_id") or "")
                returned.add(external)
                binding = binding_by_external.get(external)
                if not binding:
                    continue
                if item.get("success"):
                    binding.write({
                        "inventory_hash": self._payload_digest(payload_by_external[external]),
                        "inventory_synced_at": now,
                        "state": "synced",
                        "last_error": False,
                    })
                    updated += 1
                else:
                    error = str(item.get("error") or _("unknown error"))
                    failures.append("%s: %s" % (external, error))
                    binding.write({"state": "error", "last_error": error})
            for external, binding in binding_by_external.items():
                if external in returned:
                    continue
                error = _("SellViaApp did not return a result for this stock update.")
                failures.append("%s: %s" % (external, error))
                binding.write({"state": "error", "last_error": error})
            items.clear()

        for product in products:
            binding = bindings.get(product.id)
            if not binding or binding.state != "synced":
                not_published += 1
                continue
            payload = self._inventory_payload(product)
            digest = self._payload_digest(payload)
            if not force and binding.inventory_hash == digest:
                unchanged += 1
                continue
            batch.append((payload, binding))
            if len(batch) >= 500:
                flush(batch)
        flush(batch)

        summary = {
            "eligible_products": len(products),
            "updated": updated,
            "unchanged": unchanged,
            "published_missing": published_missing,
            "not_published": not_published,
            "failures": failures,
        }
        self.write({
            "last_inventory_sync_at": fields.Datetime.now(),
            "last_inventory_sync_summary": json.dumps(summary, ensure_ascii=False, indent=2),
            "last_error": "\n".join(failures) if failures else False,
            "state": "error" if failures else "connected",
        })
        self._log("inventory_sync", "warning" if failures else "success", json.dumps(summary, ensure_ascii=False))
        return summary

    def _synchronise_products(self, products, force=False, archive_stale=False):
        self.ensure_one()
        self._acquire_product_sync_lock()
        self._ensure_authenticated()
        products = products.sudo().with_company(self.company_id).filtered_domain(self._product_domain()).sorted("id")
        categories = self._catalogue_categories(products)
        sent_categories, unchanged_categories, failures = self._sync_category_payloads(categories)
        sent_products, unchanged_products, active_product_ids, product_failures = self._sync_product_payloads(
            products, force=force
        )
        failures += product_failures

        archived_products = 0
        archived_categories = 0
        if archive_stale:
            active_category_ids = {"product.category:%s" % category.id for category, _parent in categories}
            archived_products, archive_product_failures = self._archive_stale(
                "product.product", active_product_ids
            )
            archived_categories, archive_category_failures = self._archive_stale(
                "product.category", active_category_ids
            )
            failures += archive_product_failures + archive_category_failures

        summary = {
            "eligible_products": len(products),
            "categories": sent_categories,
            "products": sent_products,
            "unchanged_categories": unchanged_categories,
            "unchanged_products": unchanged_products,
            "archived_products": archived_products,
            "archived_categories": archived_categories,
            "failures": failures,
        }
        values = {
            "last_sync_at": fields.Datetime.now(),
            "last_sync_summary": json.dumps(summary, ensure_ascii=False, indent=2),
            "last_error": "\n".join(failures) if failures else False,
            "state": "error" if failures else "connected",
        }
        self.write(values)
        self._log("catalogue_sync", "warning" if failures else "success", json.dumps(summary, ensure_ascii=False))
        return summary

    def _synchronise(self):
        """Incrementally synchronise the full catalogue and archive stale records."""
        self.ensure_one()
        return self._synchronise_products(self._catalogue_products(), force=False, archive_stale=True)

    def action_sync_products(self, products):
        """Force a focused update for products explicitly selected by an Odoo user."""
        self.ensure_one()
        summary = self._synchronise_products(products, force=True, archive_stale=False)
        if summary["failures"]:
            return self._notification(
                _("Synchronisation completed with warnings"),
                _("%s selected product(s) updated, %s warning(s).")
                % (summary["products"], len(summary["failures"])),
                "warning",
            )
        return self._notification(
            _("SellViaApp products updated"),
            _("%s selected product(s) were sent or updated without synchronising the whole catalogue.")
            % summary["products"],
        )

    def action_sync_inventory_products(self, products):
        """Force a stock refresh for only the explicitly selected products."""
        self.ensure_one()
        summary = self._sync_inventory(products, force=True, publish_missing=True)
        message = _("%s selected stock level(s) updated.") % summary["updated"]
        if summary["published_missing"]:
            message += _(" %s product(s) were first published to SellViaApp.") % summary["published_missing"]
        if summary["not_published"]:
            message += _(" %s product(s) could not be updated because they are not published.") % summary["not_published"]
        if summary["failures"]:
            message += _(" %s warning(s).") % len(summary["failures"])
        return self._notification(
            _("SellViaApp stock update"),
            message,
            "warning" if summary["failures"] or summary["not_published"] else "success",
        )

    def action_sync_inventory_all(self):
        """Incrementally update changed stock for the complete Odoo catalogue."""
        self.ensure_one()
        summary = self._sync_inventory(force=False, publish_missing=False)
        message = _("%s stock level(s) updated; %s unchanged.") % (summary["updated"], summary["unchanged"])
        if summary["not_published"]:
            message += _(" %s unpublished product(s) will be handled by the catalogue synchronisation.") % summary["not_published"]
        if summary["failures"]:
            message += _(" %s warning(s).") % len(summary["failures"])
        return self._notification(
            _("SellViaApp stock is up to date"),
            message,
            "warning" if summary["failures"] else "success",
        )

    def action_sync_all(self):
        self.ensure_one()
        summary = self._synchronise()
        if summary["failures"]:
            return self._notification(
                _("Synchronisation completed with warnings"),
                _("%s product(s) sent or updated, %s unchanged, %s warning(s).")
                % (summary["products"], summary["unchanged_products"], len(summary["failures"])),
                "warning",
            )
        return self._notification(
            _("SellViaApp is up to date"),
            _("%s product(s) sent or updated; %s already up to date.")
            % (summary["products"], summary["unchanged_products"]),
        )

    @api.model
    def _cron_sync(self):
        for connector in self.search([("auto_sync", "=", True), ("state", "in", ["connected", "error"])]):
            try:
                with self.env.cr.savepoint():
                    connector._synchronise()
            except Exception as exc:  # cron must continue with the next company
                _logger.exception("SellViaApp automatic synchronisation failed for connector %s", connector.id)
                connector.write({"state": "error", "last_error": str(exc)})
                connector._log("catalogue_sync", "error", str(exc))

    @api.model
    def _cron_sync_inventory(self):
        for connector in self.search([("auto_sync", "=", True), ("state", "in", ["connected", "error"])]):
            try:
                with self.env.cr.savepoint():
                    connector._sync_inventory(force=False, publish_missing=False)
            except Exception as exc:  # cron must continue with the next company
                _logger.exception("SellViaApp automatic stock synchronisation failed for connector %s", connector.id)
                connector.write({"state": "error", "last_error": str(exc)})
                connector._log("inventory_sync", "error", str(exc))

    @api.model
    def _cron_cleanup_logs(self):
        """Keep the technical log useful without letting it grow forever."""
        cutoff = fields.Datetime.now() - timedelta(days=90)
        self.env["sellviaapp.sync.log"].sudo().search([("create_date", "<", cutoff)]).unlink()

    def _log(self, operation, level, message):
        self.ensure_one()
        self.env["sellviaapp.sync.log"].sudo().create(
            {"connector_id": self.id, "operation": operation, "level": level, "message": message}
        )

    @staticmethod
    def _notification(title, message, notification_type="success"):
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {"title": title, "message": message, "type": notification_type, "sticky": False},
        }


class ResCompany(models.Model):
    _inherit = "res.company"

    @api.model_create_multi
    def create(self, vals_list):
        companies = super().create(vals_list)
        Connector = self.env["sellviaapp.connector"].sudo()
        if not Connector.search_count([]) and companies:
            Connector.create({"name": "SellViaApp", "company_id": companies[0].id})
        return companies


class SellViaAppBinding(models.Model):
    _name = "sellviaapp.binding"
    _description = "SellViaApp External Binding"
    _order = "last_synced_at desc, id desc"

    connector_id = fields.Many2one("sellviaapp.connector", required=True, ondelete="cascade", index=True)
    model_name = fields.Char(required=True, index=True)
    res_id = fields.Integer(required=True, index=True)
    external_id = fields.Char(required=True, index=True)
    remote_type = fields.Selection(
        [("product", "Product"), ("category", "Category"), ("subcategory", "Subcategory"), ("customer", "Customer")], required=True
    )
    payload_hash = fields.Char()
    inventory_hash = fields.Char(copy=False, index=True)
    state = fields.Selection([("synced", "Synced"), ("archived", "Archived"), ("error", "Error")], default="synced")
    last_synced_at = fields.Datetime()
    inventory_synced_at = fields.Datetime(copy=False)
    last_error = fields.Text()

    _sql_constraints = [
        (
            "sellviaapp_binding_record_unique",
            "unique(connector_id, model_name, res_id)",
            "This Odoo record is already linked to SellViaApp.",
        ),
        (
            "sellviaapp_binding_external_unique",
            "unique(connector_id, remote_type, external_id)",
            "This SellViaApp identifier is already linked.",
        ),
    ]


class SellViaAppSyncLog(models.Model):
    _name = "sellviaapp.sync.log"
    _description = "SellViaApp Synchronisation Log"
    _order = "create_date desc, id desc"

    connector_id = fields.Many2one("sellviaapp.connector", required=True, ondelete="cascade", index=True)
    operation = fields.Char(required=True)
    level = fields.Selection(
        [("info", "Information"), ("success", "Success"), ("warning", "Warning"), ("error", "Error")],
        required=True,
        default="info",
    )
    message = fields.Text(required=True)
