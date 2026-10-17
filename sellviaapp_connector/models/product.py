from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError


def _ensure_sync_access(recordset):
    if not recordset.env.user.has_group("sales_team.group_sale_manager"):
        raise AccessError(_("Only Sales managers can synchronise products with SellViaApp."))


def _connected_connector(recordset):
    _ensure_sync_access(recordset)
    connector = recordset.env["sellviaapp.connector"].sudo().search([], order="id", limit=1)
    if not connector:
        raise UserError(_("Open SellViaApp and establish the connection before synchronising products."))
    connector._ensure_authenticated()
    return connector


def _binding_values(recordset, product_ids):
    if not product_ids:
        return {}
    connector = recordset.env["sellviaapp.connector"].sudo().search([], order="id", limit=1)
    if not connector:
        return {}
    bindings = recordset.env["sellviaapp.binding"].sudo().search(
        [
            ("connector_id", "=", connector.id),
            ("model_name", "=", "product.product"),
            ("res_id", "in", list(product_ids)),
        ]
    )
    return {binding.res_id: binding for binding in bindings}


class ProductTemplate(models.Model):
    _inherit = "product.template"

    sellviaapp_sync_state = fields.Selection(
        [
            ("not_synced", "Not sent"),
            ("synced", "Up to date"),
            ("partial", "Partially sent"),
            ("error", "Attention required"),
            ("archived", "Archived"),
        ],
        compute="_compute_sellviaapp_sync_status",
        string="SellViaApp",
    )
    sellviaapp_last_synced_at = fields.Datetime(
        compute="_compute_sellviaapp_sync_status",
        string="Last SellViaApp update",
    )
    sellviaapp_stock_synced_at = fields.Datetime(
        compute="_compute_sellviaapp_sync_status",
        string="Last stock update",
    )

    @api.depends("product_variant_ids.write_date", "sale_ok", "active")
    def _compute_sellviaapp_sync_status(self):
        templates = self.with_context(active_test=False)
        variants_by_template = {
            template.id: template.product_variant_ids.ids
            for template in templates
        }
        all_variant_ids = {variant_id for variant_ids in variants_by_template.values() for variant_id in variant_ids}
        bindings = _binding_values(self, all_variant_ids)
        for template in self:
            template_bindings = [
                bindings[variant_id]
                for variant_id in variants_by_template.get(template.id, [])
                if variant_id in bindings
            ]
            if not template_bindings:
                state = "not_synced"
                last_sync = False
                stock_sync = False
            else:
                states = {binding.state for binding in template_bindings}
                expected_count = len(variants_by_template.get(template.id, []))
                if "error" in states:
                    state = "error"
                elif states == {"archived"}:
                    state = "archived"
                elif states == {"synced"} and len(template_bindings) == expected_count:
                    state = "synced"
                else:
                    state = "partial"
                dates = [binding.last_synced_at for binding in template_bindings if binding.last_synced_at]
                last_sync = max(dates) if dates else False
                stock_dates = [binding.inventory_synced_at for binding in template_bindings if binding.inventory_synced_at]
                stock_sync = max(stock_dates) if stock_dates else False
            template.sellviaapp_sync_state = state
            template.sellviaapp_last_synced_at = last_sync
            template.sellviaapp_stock_synced_at = stock_sync

    def action_sellviaapp_sync_all_products(self):
        connector = _connected_connector(self)
        return connector.action_sync_all()

    def action_sellviaapp_sync_selected_products(self):
        if not self:
            raise UserError(_("Select at least one product to update in SellViaApp."))
        connector = _connected_connector(self)
        variants = self.with_context(active_test=False).mapped("product_variant_ids")
        eligible = variants.filtered_domain(connector._product_domain())
        if not eligible:
            raise UserError(_("The selected products must be active and available for sale."))
        return connector.action_sync_products(eligible)

    def action_sellviaapp_sync_all_inventory(self):
        connector = _connected_connector(self)
        return connector.action_sync_inventory_all()

    def action_sellviaapp_sync_selected_inventory(self):
        if not self:
            raise UserError(_("Select at least one product whose stock must be updated."))
        connector = _connected_connector(self)
        variants = self.with_context(active_test=False).mapped("product_variant_ids")
        eligible = variants.filtered_domain(connector._product_domain())
        if not eligible:
            raise UserError(_("The selected products must be active and available for sale."))
        return connector.action_sync_inventory_products(eligible)


class ProductProduct(models.Model):
    _inherit = "product.product"

    sellviaapp_sync_state = fields.Selection(
        [
            ("not_synced", "Not sent"),
            ("synced", "Up to date"),
            ("error", "Attention required"),
            ("archived", "Archived"),
        ],
        compute="_compute_sellviaapp_sync_status",
        string="SellViaApp",
    )
    sellviaapp_last_synced_at = fields.Datetime(
        compute="_compute_sellviaapp_sync_status",
        string="Last SellViaApp update",
    )
    sellviaapp_stock_synced_at = fields.Datetime(
        compute="_compute_sellviaapp_sync_status",
        string="Last stock update",
    )

    @api.depends("write_date", "sale_ok", "active")
    def _compute_sellviaapp_sync_status(self):
        bindings = _binding_values(self, self.ids)
        for product in self:
            binding = bindings.get(product.id)
            product.sellviaapp_sync_state = binding.state if binding else "not_synced"
            product.sellviaapp_last_synced_at = binding.last_synced_at if binding else False
            product.sellviaapp_stock_synced_at = binding.inventory_synced_at if binding else False

    def action_sellviaapp_sync_all_products(self):
        connector = _connected_connector(self)
        return connector.action_sync_all()

    def action_sellviaapp_sync_selected_products(self):
        if not self:
            raise UserError(_("Select at least one product to update in SellViaApp."))
        connector = _connected_connector(self)
        eligible = self.with_context(active_test=False).filtered_domain(connector._product_domain())
        if not eligible:
            raise UserError(_("The selected products must be active and available for sale."))
        return connector.action_sync_products(eligible)

    def action_sellviaapp_sync_all_inventory(self):
        connector = _connected_connector(self)
        return connector.action_sync_inventory_all()

    def action_sellviaapp_sync_selected_inventory(self):
        if not self:
            raise UserError(_("Select at least one product whose stock must be updated."))
        connector = _connected_connector(self)
        eligible = self.with_context(active_test=False).filtered_domain(connector._product_domain())
        if not eligible:
            raise UserError(_("The selected products must be active and available for sale."))
        return connector.action_sync_inventory_products(eligible)
