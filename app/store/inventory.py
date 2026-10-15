"""Inventory — Items (CONTEXT.md). `_images` is a JSON list of photo entries whose bytes
are `blobs` rows keyed by the entry id (ADR-0020)."""

from .base import Field, Store

TABLE = 'inventory'

FIELDS = (
    Field('Item_ID', 'item_id', 'text'),
    Field('Item_Name', 'item_name', 'text'),
    Field('Category', 'category', 'text'),
    Field('Subcategory', 'subcategory', 'text'),
    Field('Item_Type', 'item_type', 'text'),
    Field('Brand', 'brand', 'text'),
    Field('Model', 'model', 'text'),
    Field('Color', 'color', 'text'),
    Field('Size', 'size', 'text'),
    Field('Dimensions', 'dimensions', 'text'),
    Field('Link', 'link', 'text'),
    Field('Qty', 'qty', 'real'),
    Field('Unit_Cost', 'unit_cost', 'real'),
    Field('Salvage_Value', 'salvage_value', 'real'),
    Field('Useful_Life_Years', 'useful_life_years', 'real'),
    Field('Classification', 'classification', 'text'),
    Field('Source', 'source', 'text'),
    Field('Date_Moved', 'date_moved', 'text'),
    Field('Notes', 'notes', 'text'),
    Field('Email_ID', 'email_id', 'text'),
    Field('_images', 'images', 'json'),
)



class InventoryStore(Store):
    pass


inventory = InventoryStore(TABLE, FIELDS)
