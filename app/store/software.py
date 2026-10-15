"""Software — the software board's rows (CONTEXT.md, ADR-0017). `_images` is a JSON list of
photo entries whose bytes are `blobs` rows keyed by the entry id, as for inventory."""

from .base import Field, Store, q

TABLE = 'software'

FIELDS = (
    Field('SW_ID', 'sw_id', 'text'),
    Field('Item_Name', 'item_name', 'text'),
    Field('Status', 'status', 'text'),
    Field('Kind', 'kind', 'text'),
    Field('Vendor', 'vendor', 'text'),
    Field('Category', 'category', 'text'),
    Field('License_Type', 'license_type', 'text'),
    Field('Billing_Cadence', 'billing_cadence', 'text'),
    Field('Cost', 'cost', 'real'),
    Field('Version_Installed', 'version_installed', 'text'),
    Field('Link', 'link', 'text'),
    Field('Source_Key', 'source_key', 'text'),
    Field('Merchant_Match', 'merchant_match', 'text'),
    Field('Description', 'description', 'text'),
    Field('Notes', 'notes', 'text'),
    Field('Homepage', 'homepage', 'text'),
    Field('Repo_URL', 'repo_url', 'text'),
    Field('License_Id', 'license_id', 'text'),
    Field('Bundle_Id', 'bundle_id', 'text'),
    Field('Currency', 'currency', 'text'),
    Field('Version_Latest', 'version_latest', 'text'),
    Field('Stars', 'stars', 'int'),
    Field('Topics', 'topics', 'json'),
    Field('Archived', 'archived', 'bool'),
    Field('Install_Locations', 'install_locations', 'json'),
    Field('Last_Used', 'last_used', 'text'),
    Field('Use_Count', 'use_count', 'int'),
    Field('_import_status', 'import_status', 'text'),
    Field('_refreshed_at', 'refreshed_at', 'datetime'),
    Field('_images', 'images', 'json'),
    Field('_src', 'src', 'text'),
)


class SoftwareStore(Store):
    def max_sw_num(self) -> int:
        """The highest SW-### on the board (the app is the sole minter; next = this + 1)."""
        top = 0
        for r in self.rows(f"SELECT sw_id FROM {q(self.table)} WHERE sw_id LIKE 'SW-%'"):
            try:
                top = max(top, int(str(r[0]).split("-", 1)[1]))
            except (IndexError, ValueError):
                pass
        return top


software = SoftwareStore(TABLE, FIELDS)
