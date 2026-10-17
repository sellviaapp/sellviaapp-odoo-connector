# Odoo Apps release checklist

- [ ] Branch name matches the Odoo series: `17.0`.
- [ ] `__manifest__.py` contains a unique version and complete metadata.
- [ ] `static/description/icon.png` is square and at least 128 px.
- [ ] English marketplace copy contains no unsupported scripts or promotional links.
- [ ] Screenshots are English, anonymised and accurately reflect available features.
- [ ] `python tools/validate_module.py` passes.
- [ ] The generated ZIP installs in a clean Odoo 17 database.
- [ ] Upgrade from the previous connector version succeeds.
- [ ] OAuth connect, check and disconnect flows are tested.
- [ ] Catalogue, stock, customer and order actions are tested.
- [ ] No API key, token, password, database dump or customer data is present.
- [ ] Support address and documentation are current.
- [ ] `python tools/package_release.py` produces a ZIP below 50 MiB.
