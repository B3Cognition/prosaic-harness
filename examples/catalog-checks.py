"""Host-owned admission against the fixed synthetic catalogue, not model claims."""
import json
from pathlib import Path

DATA = Path(__file__).with_name('catalog.json').read_bytes()
CATALOG = json.loads(DATA)
json.dumps(CATALOG, allow_nan=False)


def check_catalog(output, context):
    sku = context.request.get('sku') if isinstance(context.request, dict) else None
    item = CATALOG.get(sku) if isinstance(sku, str) else None
    expected = {'found': item is not None, 'item': item}
    if not isinstance(sku, str) or output != expected:
        return ['catalogue answer must exactly match the original requested SKU and fixed catalogue']
    return []


CHECKS = {'catalog': check_catalog}
