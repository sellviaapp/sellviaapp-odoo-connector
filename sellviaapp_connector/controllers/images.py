import base64
import hashlib
import hmac

from odoo import http
from odoo.http import request


class SellViaAppImages(http.Controller):
    @http.route(
        "/sellviaapp/image/<int:connector_id>/<int:product_id>/<int:slot>",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
        sitemap=False,
    )
    def product_image(self, connector_id, product_id, slot, signature="", **kwargs):
        if slot < 1 or slot > 5:
            return request.not_found()
        connector = request.env["sellviaapp.connector"].sudo().browse(connector_id).exists()
        product = request.env["product.product"].sudo().browse(product_id).exists()
        if not connector or not product or not connector.is_authenticated:
            return request.not_found()
        if product.company_id and product.company_id != connector.company_id:
            return request.not_found()
        message = "%s:%s:%s" % (connector.id, product.id, slot)
        expected = hmac.new(connector.image_secret.encode(), message.encode(), hashlib.sha256).hexdigest()
        if not signature or not hmac.compare_digest(signature, expected):
            return request.not_found()

        encoded = product.image_1920 if slot == 1 else False
        if slot > 1:
            images = request.env["product.image"].sudo().search(
                [("product_tmpl_id", "=", product.product_tmpl_id.id)], order="sequence,id", limit=4
            )
            index = slot - 2
            if index < len(images):
                encoded = images[index].image_1920
        if not encoded:
            return request.not_found()
        try:
            content = base64.b64decode(encoded)
        except (ValueError, TypeError):
            return request.not_found()
        if content.startswith(b"\x89PNG"):
            content_type = "image/png"
        elif content.startswith((b"GIF87a", b"GIF89a")):
            content_type = "image/gif"
        elif content.startswith(b"RIFF") and content[8:12] == b"WEBP":
            content_type = "image/webp"
        else:
            content_type = "image/jpeg"
        etag = hashlib.sha256(content).hexdigest()
        if request.httprequest.headers.get("If-None-Match", "").strip('"') == etag:
            return request.make_response("", status=304, headers=[("ETag", '"%s"' % etag)])
        return request.make_response(
            content,
            headers=[
                ("Content-Type", content_type),
                ("Content-Length", str(len(content))),
                ("Cache-Control", "public, max-age=86400, stale-while-revalidate=604800"),
                ("ETag", '"%s"' % etag),
                ("X-Content-Type-Options", "nosniff"),
            ],
        )
