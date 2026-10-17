from . import models
from . import controllers


def post_init_hook(env):
    """Provide the database-wide connector immediately after installation."""
    Connector = env["sellviaapp.connector"].sudo()
    if not Connector.search([], limit=1):
        Connector.create({"name": "SellViaApp", "company_id": env.company.id})
