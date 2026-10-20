"""Restricted native Add Grid checkout with configurable, non-original revival pricing."""
from copy import deepcopy
import roi_skills

# Native decoder 0x1400fdc60: second digit 0, digits 7..9 = 002 identify an extra grid.
# Revival identifiers, not original server database IDs.
ITEM_ID = '1000000020000001'
STORE_ID = '1000000000001001'  # Native currency discriminator: LP, never Steam/IP.
NAME_QUOTE = '240118'


def cost(saved):
    return roi_skills.integer(saved.get('skillGridPriceLP', 1), 1, 100000000)


def item_master():
    return {'sv_itemId': ITEM_ID, 'sv_name': NAME_QUOTE, 'sv_desc': NAME_QUOTE,
            'sv_thumbnails': [], 'sv_additions': [], 'sv_sort': '1',
            'sv_createTime': '1388534400', 'sv_hold': '0'}


def store_master(saved):
    return {'_id': STORE_ID, 'sv_items': [{'sv_itemId': ITEM_ID, 'sv_itemCount': '1'}],
            'sv_price': str(cost(saved)), 'sv_basisPrice': str(cost(saved)), 'sv_sort': '1',
            'sv_beginTime': '1388534400', 'sv_thumbnail': 'NULL', 'sv_thumbnails': [],
            'sv_feature': '0', 'sv_storeItemDesc': NAME_QUOTE, 'sv_itemNameId': NAME_QUOTE}


def cart(saved):
    return deepcopy(saved.get('skillGridCart', []))


def reply(saved, rows=None):
    remaining = roi_skills.MAX_GRIDS - len(roi_skills.grids(saved))
    return {'sv_cartItems': cart(saved) if rows is None else rows,
            'sv_storeItems': [{'sv_storeItemId': STORE_ID, 'sv_buyableCount': str(remaining),
                               'sv_items': [{'sv_itemId': ITEM_ID}], 'sv_salesRank': '0'}],
            'sv_items': []}


def add(saved, data):
    if not roi_skills.enabled(saved) or not roi_skills.progression(saved):
        raise ValueError('Grid purchasing is unavailable')
    roi_skills.integer(data.get('sv_type'), 1, 1)
    items = data.get('sv_storeItems')
    if not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], dict):
        raise ValueError('Only one grid per checkout is supported')
    item = items[0]
    if str(item.get('sv_storeItemId')) != STORE_ID:
        raise ValueError('Unsupported shop item')
    roi_skills.integer(item.get('sv_storeItemCount'), 1, 1)
    if len(roi_skills.grids(saved)) >= roi_skills.MAX_GRIDS:
        raise ValueError('All loadouts are owned')
    # Retried addToCart replaces the single-item cart rather than duplicating it.
    rows = [{'sv_storeItemId': STORE_ID, 'sv_storeOrderId': '1', 'sv_resultCode': '0',
             'sv_storeItemDesc': NAME_QUOTE, 'sv_storeItemCount': '1',
             'sv_items': [{'sv_itemId': ITEM_ID}]}]
    return {'skillGridCart': rows}


def buy(saved, data):
    if not roi_skills.enabled(saved) or not roi_skills.progression(saved):
        raise ValueError('Grid purchasing is unavailable')
    roi_skills.integer(data.get('sv_type'), 1, 1)
    rows = cart(saved)
    if len(rows) != 1 or rows[0]['sv_storeItemId'] != STORE_ID:
        raise ValueError('No grid order to purchase')
    balance = roi_skills.integer(saved.get('gamePoint', 0), 0, 2147483647)
    price = cost(saved)
    if balance < price:
        raise ValueError('Insufficient LP')
    return {'skillGrids': roi_skills.add_grid(saved), 'gamePoint': balance - price,
            'skillGridCart': []}, rows
