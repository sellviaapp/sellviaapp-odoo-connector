import json
import re
from datetime import datetime, timezone

from odoo import Command, _, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools.mail import email_normalize


class ResPartner(models.Model):
    _inherit = "res.partner"

    sellviaapp_customer_key = fields.Char(copy=False, index=True, readonly=True)
    sellviaapp_mobile_customer_id = fields.Integer(copy=False, index=True, readonly=True)
    sellviaapp_mobile_login = fields.Char(copy=False, index=True, readonly=True)
    sellviaapp_mobile_sync_state = fields.Selection(
        [("synced", "Synchronised"), ("error", "Error")], copy=False, readonly=True
    )
    sellviaapp_mobile_invitation_status = fields.Char(copy=False, readonly=True)
    sellviaapp_mobile_synced_at = fields.Datetime(copy=False, readonly=True)
    sellviaapp_mobile_sync_error = fields.Text(copy=False, readonly=True)

    _sql_constraints = [
        (
            "sellviaapp_customer_key_unique",
            "unique(sellviaapp_customer_key)",
            "This SellViaApp customer is already linked to another Odoo contact.",
        ),
    ]

    def _sellviaapp_customer_connector(self):
        if not self.env.user.has_group("sales_team.group_sale_manager"):
            raise AccessError(_("Only Sales managers can synchronise contacts with SellViaApp."))
        company = self.env.company
        connector = self.env["sellviaapp.connector"].sudo().search(
            [("company_id", "=", company.id)], limit=1
        )
        if not connector:
            raise UserError(_("Connect this Odoo company to SellViaApp before synchronising customers."))
        connector._ensure_authenticated()
        return connector.with_company(company)

    def _sellviaapp_customer_sync_notification(self, connector, summary):
        message = _("%s contact(s) synchronised; %s unchanged contact(s) skipped. %s invitation(s) sent, %s queued.") % (
            summary["processed"],
            summary["skipped_unchanged"],
            summary["invitations_sent"],
            summary["invitations_queued"],
        )
        if summary["failures"]:
            message += _(" %s warning(s).") % len(summary["failures"])
        return connector._notification(
            _("SellViaApp customer synchronisation"),
            message,
            "warning" if summary["failures"] else "success",
        )

    def action_sellviaapp_sync_all_customers(self):
        connector = self._sellviaapp_customer_connector()
        summary = connector._sync_customers(partners=None, force=False)
        return self._sellviaapp_customer_sync_notification(connector, summary)

    def action_sellviaapp_sync_selected_customers(self):
        if not self:
            raise UserError(_("Select at least one contact to update in SellViaApp."))
        connector = self._sellviaapp_customer_connector()
        eligible = self.filtered(
            lambda partner: partner.active
            and partner.type == "contact"
            and partner.id != connector.company_id.partner_id.id
            and (not partner.company_id or partner.company_id == connector.company_id)
        )
        if not eligible:
            raise UserError(_("The selected records do not contain an eligible contact."))
        summary = connector._sync_customers(partners=eligible, force=True)
        return self._sellviaapp_customer_sync_notification(connector, summary)

    def action_sellviaapp_sync_customers(self):
        """Compatibility action used by the existing contact form button."""
        if self:
            return self.action_sellviaapp_sync_selected_customers()
        return self.action_sellviaapp_sync_all_customers()

    def action_sellviaapp_fetch_customers(self):
        if not self.env.user.has_group("sales_team.group_sale_manager"):
            raise AccessError(_("Only Sales managers can retrieve contacts from SellViaApp."))
        company = self.env.company
        connector = self.env["sellviaapp.connector"].sudo().search(
            [("company_id", "=", company.id)], limit=1
        )
        if not connector:
            raise UserError(_("Connect this Odoo company to SellViaApp before importing customers."))
        connector._ensure_authenticated()
        return connector.with_company(company).action_import_customers()


class SaleOrder(models.Model):
    _inherit = "sale.order"

    sellviaapp_order_guid = fields.Char(copy=False, index=True, readonly=True)
    sellviaapp_order_id = fields.Integer(copy=False, index=True, readonly=True)
    sellviaapp_number = fields.Char(copy=False, readonly=True)
    sellviaapp_status = fields.Char(copy=False, readonly=True)
    sellviaapp_delivery_mode = fields.Char(copy=False, readonly=True)
    sellviaapp_pickup_point = fields.Char(copy=False, readonly=True)
    sellviaapp_payment_method = fields.Char(copy=False, readonly=True)
    sellviaapp_payment_status = fields.Char(copy=False, readonly=True)
    sellviaapp_payment_reference = fields.Char(copy=False, readonly=True)

    _sql_constraints = [
        (
            "sellviaapp_order_company_guid_unique",
            "unique(company_id,sellviaapp_order_guid)",
            "This SellViaApp order has already been imported for this company.",
        ),
    ]

    def action_sellviaapp_fetch_orders(self):
        company = self.env.company
        connector = self.env["sellviaapp.connector"].sudo().search(
            [("company_id", "=", company.id)],
            limit=1,
        )
        if not connector:
            raise UserError(_("Connect this Odoo company to SellViaApp before importing orders."))
        connector._ensure_authenticated()
        return connector.with_company(company).action_import_orders()


class SellViaAppConnectorOrderImport(models.Model):
    _inherit = "sellviaapp.connector"

    last_order_import_at = fields.Datetime(readonly=True)
    last_order_import_summary = fields.Text(readonly=True)
    last_customer_import_at = fields.Datetime(readonly=True)
    last_customer_import_summary = fields.Text(readonly=True)

    @staticmethod
    def _remote_datetime(value):
        value = str(value or "").strip()
        if not value:
            return False
        parsed = None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
                try:
                    parsed = datetime.strptime(value, pattern)
                    break
                except ValueError:
                    continue
        if not parsed:
            return False
        if parsed.tzinfo:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return fields.Datetime.to_string(parsed)

    def _partner_language(self, code):
        short = str(code or "").strip().lower().replace("-", "_")
        if not short:
            return False
        languages = self.env["res.lang"].sudo().search([("active", "=", True)])
        exact = languages.filtered(lambda language: (language.code or "").lower() == short)
        if exact:
            return exact[0].code
        prefix = short.split("_")[0]
        matching = languages.filtered(lambda language: (language.code or "").lower().split("_")[0] == prefix)
        return matching[0].code if matching else False

    def _partner_country(self, value):
        value = str(value or "").strip()
        if not value:
            return self.env["res.country"]
        country = self.env["res.country"].sudo().search([("code", "=ilike", value)], limit=1)
        if not country:
            country = self.env["res.country"].sudo().search([("name", "=ilike", value)], limit=1)
        return country

    @staticmethod
    def _normalised_phone(value):
        digits = re.sub(r"\D+", "", str(value or ""))
        if digits.startswith("00"):
            digits = digits[2:]
        return digits[-9:] if len(digits) >= 9 else digits

    def _sellviaapp_customer_key(self, remote_id):
        self.ensure_one()
        return "%s:%s:%s" % (
            (self.supplier_suffix or "supplier").lower(),
            self.id,
            int(remote_id),
        )

    def _customer_partner_match(self, customer):
        self.ensure_one()
        customer = customer if isinstance(customer, dict) else {}
        remote_id = int(customer.get("id") or 0)
        Partner = self.env["res.partner"].sudo().with_company(self.company_id)
        company_domain = [("company_id", "in", [False, self.company_id.id])]

        if remote_id > 0:
            customer_key = self._sellviaapp_customer_key(remote_id)
            matches = Partner.search(
                company_domain
                + [
                    "|",
                    ("sellviaapp_customer_key", "=", customer_key),
                    "&",
                    ("sellviaapp_mobile_customer_id", "=", remote_id),
                    ("sellviaapp_customer_key", "=", False),
                ],
                limit=3,
            )
            if len(matches) > 1:
                raise UserError(
                    _("SellViaApp customer #%s is linked to several Odoo contacts. Resolve the duplicate before continuing.")
                    % remote_id
                )
            if matches:
                return matches, "sellviaapp_id"

        email = email_normalize(str(customer.get("email") or ""), strict=False) or ""
        if email:
            email_candidates = Partner.search(company_domain + [("email", "ilike", email)], limit=20)
            matches = email_candidates.filtered(
                lambda partner: (email_normalize(partner.email or "", strict=False) or "") == email
            )
            if len(matches) > 1:
                raise UserError(
                    _("Several Odoo contacts use %s. Merge or correct them before importing this SellViaApp customer.")
                    % email
                )
            if matches:
                if matches.sellviaapp_customer_key and matches.sellviaapp_customer_key != self._sellviaapp_customer_key(remote_id):
                    raise UserError(
                        _("The Odoo contact using %s is already linked to another SellViaApp customer.") % email
                    )
                return matches, "email"

        vat = str(customer.get("vat_number") or "").strip()
        if vat:
            matches = Partner.search(company_domain + [("vat", "=ilike", vat)], limit=3)
            if len(matches) > 1:
                raise UserError(
                    _("Several Odoo contacts use VAT number %s. Resolve the duplicate before continuing.") % vat
                )
            if matches:
                if matches.sellviaapp_customer_key and matches.sellviaapp_customer_key != self._sellviaapp_customer_key(remote_id):
                    raise UserError(
                        _("The Odoo contact using VAT number %s is already linked to another SellViaApp customer.") % vat
                    )
                return matches, "vat"

        phones = {
            self._normalised_phone(customer.get("phone")),
            self._normalised_phone(customer.get("cellphone")),
        }
        phones.discard("")
        for phone in phones:
            tail = phone[-6:]
            candidates = Partner.search(
                company_domain + ["|", ("phone", "ilike", tail), ("mobile", "ilike", tail)],
                limit=20,
            )
            matches = candidates.filtered(
                lambda partner: phone
                in {self._normalised_phone(partner.phone), self._normalised_phone(partner.mobile)}
            )
            if len(matches) > 1:
                raise UserError(
                    _("Several Odoo contacts use the same phone number. Resolve the duplicate before continuing.")
                )
            if matches:
                if matches.sellviaapp_customer_key and matches.sellviaapp_customer_key != self._sellviaapp_customer_key(remote_id):
                    raise UserError(
                        _("The Odoo contact using this phone number is already linked to another SellViaApp customer.")
                    )
                return matches, "phone"
        return Partner, "new"

    def _remote_customer_values(self, customer):
        self.ensure_one()
        customer = customer if isinstance(customer, dict) else {}
        first_name = str(customer.get("first_name") or "").strip()
        last_name = str(customer.get("last_name") or "").strip()
        company_name = str(customer.get("company") or "").strip()
        email = email_normalize(str(customer.get("email") or ""), strict=False) or ""
        login = str(customer.get("mobile_login") or customer.get("login") or "").strip()
        full_name = " ".join(value for value in [first_name, last_name] if value)
        name = company_name or full_name or str(customer.get("display_name") or "").strip() or email or login
        if not name:
            name = _("SellViaApp customer")
        values = {
            "name": name,
            "email": email or False,
            "street": str(customer.get("address") or "").strip() or False,
            "zip": str(customer.get("zipcode") or "").strip() or False,
            "city": str(customer.get("city") or "").strip() or False,
            "phone": str(customer.get("phone") or "").strip() or False,
            "mobile": str(customer.get("cellphone") or "").strip() or False,
            "vat": str(customer.get("vat_number") or "").strip() or False,
            "company_type": "company" if customer.get("account_type") == "company" else "person",
            "company_id": self.company_id.id,
        }
        country = self._partner_country(customer.get("country"))
        if country:
            values["country_id"] = country.id
        language = self._partner_language(customer.get("language"))
        if language:
            values["lang"] = language
        return values

    def _import_remote_customer(self, customer):
        self.ensure_one()
        customer = customer if isinstance(customer, dict) else {}
        remote_id = int(customer.get("id") or 0)
        if remote_id < 1:
            raise UserError(_("The SellViaApp customer identifier is missing."))
        partner, match_source = self._customer_partner_match(customer)
        values = self._remote_customer_values(customer)
        customer_key = self._sellviaapp_customer_key(remote_id)
        remote_values = {
            "sellviaapp_customer_key": customer_key,
            "sellviaapp_mobile_customer_id": remote_id,
            "sellviaapp_mobile_login": customer.get("mobile_login") or customer.get("login") or False,
            "sellviaapp_mobile_sync_state": "synced",
            "sellviaapp_mobile_invitation_status": "imported",
            "sellviaapp_mobile_synced_at": fields.Datetime.now(),
            "sellviaapp_mobile_sync_error": False,
        }
        if partner:
            already_linked = bool(
                partner.sellviaapp_customer_key or partner.sellviaapp_mobile_customer_id
            )
            if already_linked:
                updates = {key: value for key, value in values.items() if value not in (False, "")}
                updates["active"] = bool(customer.get("active", True))
                action = "updated"
            else:
                updates = {
                    key: value
                    for key, value in values.items()
                    if value not in (False, "") and not partner[key]
                }
                action = "linked"
            updates.update(remote_values)
            partner.write(updates)
            return partner, action, match_source

        values["active"] = bool(customer.get("active", True))
        values.update(remote_values)
        partner = self.env["res.partner"].sudo().with_company(self.company_id).create(values)
        return partner, "created", "new"

    def _order_partner(self, customer, order_guid):
        self.ensure_one()
        customer = customer if isinstance(customer, dict) else {}
        if int(customer.get("id") or 0) > 0:
            partner, _action, _match_source = self._import_remote_customer(customer)
            return partner
        partner, _match_source = self._customer_partner_match(customer)
        values = self._remote_customer_values(customer)
        if partner:
            partner.write(
                {key: value for key, value in values.items() if value not in (False, "") and not partner[key]}
            )
        else:
            partner = self.env["res.partner"].sudo().with_company(self.company_id).create(values)
        return partner

    def _import_customers(self):
        self.ensure_one()
        self._ensure_authenticated()
        summary = {
            "created": 0,
            "linked": 0,
            "updated": 0,
            "failed": 0,
            "matches": {"sellviaapp_id": 0, "email": 0, "vat": 0, "phone": 0, "new": 0},
            "failures": [],
        }
        cursor = ""
        seen_cursors = set()
        for _page in range(100):
            result = self._request(
                "POST",
                "odoo/customers/feed",
                {"limit": 100, "cursor": cursor},
                timeout=120,
            )
            remote_customers = result.get("items") if isinstance(result.get("items"), list) else []
            for remote in remote_customers:
                if not isinstance(remote, dict):
                    continue
                remote_id = int(remote.get("id") or 0)
                try:
                    with self.env.cr.savepoint():
                        _partner, action, match_source = self._import_remote_customer(remote)
                    summary[action] += 1
                    summary["matches"][match_source] += 1
                except Exception as exc:
                    summary["failed"] += 1
                    summary["failures"].append("SellViaApp #%s: %s" % (remote_id or "?", str(exc)))
            cursor_data = result.get("cursor") if isinstance(result.get("cursor"), dict) else {}
            next_cursor = str(cursor_data.get("next") or "").strip()
            if not cursor_data.get("has_more") or not next_cursor or next_cursor in seen_cursors:
                break
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        self.write(
            {
                "last_customer_import_at": fields.Datetime.now(),
                "last_customer_import_summary": json.dumps(summary, ensure_ascii=False, indent=2),
                "last_error": "\n".join(summary["failures"]) if summary["failures"] else False,
                "state": "error" if summary["failures"] else "connected",
            }
        )
        self._log(
            "customer_import",
            "warning" if summary["failures"] else "success",
            json.dumps(summary, ensure_ascii=False),
        )
        return summary

    def action_import_customers(self):
        self.ensure_one()
        summary = self._import_customers()
        message = _("%s new customer(s), %s linked to existing Odoo contacts, %s updated.") % (
            summary["created"],
            summary["linked"],
            summary["updated"],
        )
        if summary["failures"]:
            message += " " + _("%s duplicate or invalid customer(s) require attention.") % summary["failed"]
        notification = self._notification(
            _("SellViaApp customers retrieved"),
            message,
            "warning" if summary["failures"] else "success",
        )
        notification["params"]["next"] = {"type": "ir.actions.client", "tag": "reload"}
        return notification

    def _product_from_remote_line(self, line):
        self.ensure_one()
        Product = self.env["product.product"].sudo().with_company(self.company_id)
        external_id = str(line.get("provider_external_id") or "").strip()
        if external_id:
            binding = self.env["sellviaapp.binding"].sudo().search(
                [
                    ("connector_id", "=", self.id),
                    ("model_name", "=", "product.product"),
                    ("external_id", "=", external_id),
                    ("state", "=", "synced"),
                ],
                limit=1,
            )
            product = Product.browse(binding.res_id).exists() if binding else Product
            if product:
                return product
        code = str(line.get("product_code") or "").strip()
        if code:
            product = Product.search(
                [
                    ("default_code", "=", code),
                    ("product_tmpl_id.company_id", "in", [False, self.company_id.id]),
                ],
                limit=1,
            )
            if product:
                return product
        return self._service_product("SELLVIAAPP-UNMATCHED", _("SellViaApp item"))

    def _service_product(self, code, name):
        Product = self.env["product.product"].sudo().with_company(self.company_id)
        product = Product.search(
            [
                ("default_code", "=", code),
                ("product_tmpl_id.company_id", "in", [False, self.company_id.id]),
            ],
            limit=1,
        )
        if product:
            return product
        template = self.env["product.template"].sudo().with_company(self.company_id).create(
            {
                "name": name,
                "default_code": code,
                "detailed_type": "service",
                "sale_ok": True,
                "purchase_ok": False,
                "company_id": self.company_id.id,
            }
        )
        return template.product_variant_id

    def _sale_tax(self, rate):
        rate = float(rate or 0.0)
        if rate < 0 or rate > 100:
            raise UserError(_("The SellViaApp VAT rate must be between 0 and 100."))
        Tax = self.env["account.tax"].sudo().with_company(self.company_id)
        tax = Tax.search(
            [
                ("company_id", "=", self.company_id.id),
                ("type_tax_use", "=", "sale"),
                ("amount_type", "=", "percent"),
                ("amount", "=", rate),
                ("active", "=", True),
            ],
            limit=1,
        )
        if tax:
            return tax
        return Tax.create(
            {
                "name": _("SellViaApp VAT %s%%") % ("%g" % rate),
                "description": _("SellViaApp VAT %s%%") % ("%g" % rate),
                "amount_type": "percent",
                "amount": rate,
                "type_tax_use": "sale",
                "company_id": self.company_id.id,
                "active": True,
            }
        )

    def _order_note(self, remote):
        pickup = remote.get("pickup_point") if isinstance(remote.get("pickup_point"), dict) else {}
        labels = [
            (_("Delivery mode"), remote.get("delivery_mode")),
            (_("Delivery address"), remote.get("delivery_address")),
            (_("Pickup point"), pickup.get("name")),
            (_("Pickup address"), pickup.get("address")),
            (_("Requested delivery date"), remote.get("delivery_date")),
            (_("Customer comment"), remote.get("delivery_comment")),
            (_("Payment method"), remote.get("payment_method")),
            (_("Payment status"), remote.get("payment_status")),
            (_("Payment reference"), remote.get("payment_reference")),
        ]
        return "\n".join("%s: %s" % (label, value) for label, value in labels if str(value or "").strip())

    def _order_line_commands(self, remote):
        commands = []
        for line in remote.get("items") or []:
            if not isinstance(line, dict):
                continue
            product = self._product_from_remote_line(line)
            quantity = max(0.0, float(line.get("quantity") or 0.0))
            if quantity <= 0:
                continue
            tax = self._sale_tax(line.get("vat_rate"))
            description = str(line.get("description") or line.get("product_code") or product.display_name).strip()
            commands.append(
                Command.create(
                    {
                        "product_id": product.id,
                        "name": description or product.display_name,
                        "product_uom_qty": quantity,
                        "product_uom": product.uom_id.id,
                        "price_unit": float(line.get("unit_price") or 0.0),
                        "tax_id": [Command.set(tax.ids)],
                    }
                )
            )
        shipping_fee = max(0.0, float(remote.get("shipping_fee") or 0.0))
        if shipping_fee > 0:
            shipping = self._service_product("SELLVIAAPP-SHIPPING", _("SellViaApp delivery"))
            commands.append(
                Command.create(
                    {
                        "product_id": shipping.id,
                        "name": _("Delivery costs — SellViaApp"),
                        "product_uom_qty": 1.0,
                        "product_uom": shipping.uom_id.id,
                        "price_unit": shipping_fee,
                        "tax_id": [Command.set([])],
                    }
                )
            )
        if not commands:
            raise UserError(_("The SellViaApp order does not contain any usable lines."))
        return commands

    def _apply_remote_taxes(self, order, remote):
        remote_items = [
            line
            for line in (remote.get("items") or [])
            if isinstance(line, dict) and float(line.get("quantity") or 0.0) > 0
        ]
        order_lines = order.order_line.filtered(lambda line: not line.display_type)
        for order_line, remote_line in zip(order_lines, remote_items):
            tax = self._sale_tax(remote_line.get("vat_rate"))
            order_line.write({"tax_id": [Command.set(tax.ids)]})
        if max(0.0, float(remote.get("shipping_fee") or 0.0)) > 0 and len(order_lines) > len(remote_items):
            order_lines[len(remote_items)].write({"tax_id": [Command.set([])]})

    def _import_remote_order(self, remote):
        self.ensure_one()
        guid = str(remote.get("guid") or "").strip()
        if not guid:
            raise UserError(_("The SellViaApp order identifier is missing."))
        SaleOrder = self.env["sale.order"].sudo().with_company(self.company_id)
        order = SaleOrder.search(
            [("company_id", "=", self.company_id.id), ("sellviaapp_order_guid", "=", guid)],
            limit=1,
        )
        if order and order.state not in ("draft", "sent"):
            return order, "existing"
        partner = self._order_partner(remote.get("customer"), guid)
        line_commands = self._order_line_commands(remote)
        pickup = remote.get("pickup_point") if isinstance(remote.get("pickup_point"), dict) else {}
        number = str(remote.get("number") or "").strip()
        values = {
            "company_id": self.company_id.id,
            "partner_id": partner.id,
            "client_order_ref": number or guid,
            "origin": "SellViaApp %s" % (number or guid),
            "note": self._order_note(remote),
            "sellviaapp_order_guid": guid,
            "sellviaapp_order_id": int(remote.get("id") or 0),
            "sellviaapp_number": number or False,
            "sellviaapp_status": str(remote.get("status") or "pending"),
            "sellviaapp_delivery_mode": str(remote.get("delivery_mode") or "") or False,
            "sellviaapp_pickup_point": str(pickup.get("name") or "") or False,
            "sellviaapp_payment_method": str(remote.get("payment_method") or "") or False,
            "sellviaapp_payment_status": str(remote.get("payment_status") or "") or False,
            "sellviaapp_payment_reference": str(remote.get("payment_reference") or "") or False,
            "order_line": [Command.clear(), *line_commands] if order else line_commands,
        }
        date_order = self._remote_datetime(remote.get("confirmed_at") or remote.get("created_at"))
        if date_order:
            values["date_order"] = date_order
        action = "updated" if order else "created"
        if order:
            order.write(values)
        else:
            order = SaleOrder.create(values)
        self._apply_remote_taxes(order, remote)
        return order, action

    def _import_orders(self):
        self.ensure_one()
        self._ensure_authenticated()
        summary = {"created": 0, "updated": 0, "existing": 0, "failed": 0, "failures": []}
        cursor = ""
        seen_cursors = set()
        for _page in range(20):
            payload = {"limit": 100, "cursor": cursor, "unacknowledged_only": True}
            result = self._request("POST", "odoo/orders/feed", payload, timeout=120)
            remote_orders = result.get("items") if isinstance(result.get("items"), list) else []
            acknowledgements = []
            for remote in remote_orders:
                if not isinstance(remote, dict):
                    continue
                guid = str(remote.get("guid") or "").strip()
                try:
                    with self.env.cr.savepoint():
                        order, action = self._import_remote_order(remote)
                    summary[action] += 1
                    acknowledgements.append(
                        {
                            "order_guid": guid,
                            "order_id": int(remote.get("id") or 0),
                            "external_order_id": order.name,
                            "status": "imported",
                        }
                    )
                except Exception as exc:
                    summary["failed"] += 1
                    message = "%s: %s" % (guid or "?", str(exc))
                    summary["failures"].append(message)
                    acknowledgements.append({"order_guid": guid, "status": "failed", "error": str(exc)})
            valid_acknowledgements = [item for item in acknowledgements if item.get("order_guid")]
            if valid_acknowledgements:
                self._request(
                    "POST",
                    "odoo/orders/acknowledge",
                    {"items": valid_acknowledgements},
                    timeout=120,
                )
            cursor_data = result.get("cursor") if isinstance(result.get("cursor"), dict) else {}
            next_cursor = str(cursor_data.get("next") or "").strip()
            if not cursor_data.get("has_more") or not next_cursor or next_cursor in seen_cursors:
                break
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        self.write(
            {
                "last_order_import_at": fields.Datetime.now(),
                "last_order_import_summary": json.dumps(summary, ensure_ascii=False, indent=2),
                "last_error": "\n".join(summary["failures"]) if summary["failures"] else False,
                "state": "error" if summary["failures"] else "connected",
            }
        )
        self._log("order_import", "warning" if summary["failures"] else "success", json.dumps(summary, ensure_ascii=False))
        return summary

    def action_import_orders(self):
        self.ensure_one()
        summary = self._import_orders()
        message = _("%s new order(s), %s updated, %s already imported.") % (
            summary["created"],
            summary["updated"],
            summary["existing"],
        )
        if summary["failures"]:
            message += " " + _("%s error(s) require attention.") % summary["failed"]
        notification = self._notification(
            _("SellViaApp orders retrieved"),
            message,
            "warning" if summary["failures"] else "success",
        )
        notification["params"]["next"] = {"type": "ir.actions.client", "tag": "reload"}
        return notification
