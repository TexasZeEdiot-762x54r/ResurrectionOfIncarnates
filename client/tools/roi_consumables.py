"""Inventory catalogue recovered from text, using explicit revival item IDs.

Original names/descriptions: common_text 460484..460514. Original server
database IDs and activation behavior remain unrecovered. Merely owning these
items never changes award policy, currency, XP, or expansion rights.
"""
from copy import deepcopy

DAYS = (1, 3, 7, 14, 30)
CATALOGUE = tuple(
    {'id': f'1400{kind:02d}{days:03d}0200{index+1:03d}',
     'name': f'{label} Boost ({days} '+('day)' if days == 1 else 'days)'),
     'name_quote': 460484 + kind*5 + index,
     'description_quote': 460501 + kind*5 + index,
     'thumbnail': f'Other/Store_Thumbnail_Other_{("LP", "Exp")[kind]}_{index+1:03d}',
     'kind': label.lower(), 'days': days}
    for kind, label in enumerate(('LP', 'EXP')) for index, days in enumerate(DAYS)
) + (
    {'id':'1000030010000001','name':'Tournament Ticket','name_quote':460494,
     'description_quote':460511,'kind':'tournament_ticket',
     'thumbnail':'Other/Store_Thumbnail_Other_Tournament_001'},
    {'id':'1000030020000001','name':'Team Name Ticket','name_quote':460496,
     'description_quote':460513,'kind':'team_name_ticket',
     'thumbnail':'Other/Store_Thumbnail_Other_Teamname_001'},
)
IDS = {row['id'] for row in CATALOGUE}


def master_rows():
    return [{'sv_itemId': row['id'], 'sv_name': str(row['name_quote']),
             'sv_desc': str(row['description_quote']), 'sv_thumbnails': [row['thumbnail']],
             'sv_additions': [], 'sv_sort': str(index+100),
             'sv_createTime':'1388534400', 'sv_hold':'1'}
            for index, row in enumerate(CATALOGUE)]


def owned(snapshot):
    rows = snapshot.get('consumableItems', [])
    if not isinstance(rows, list) or len(rows) > 9999:
        raise ValueError('Invalid consumable inventory')
    result, holds = [], set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('Invalid consumable row')
        item, hold, count = (str(row.get(key, '')) for key in ('sv_itemId','sv_itemHoldId','sv_itemNum'))
        if (not item.isascii() or not item.isdigit() or not 0 < int(item) < 2**64
                or not hold.isascii() or not hold.isdigit() or not 0 < int(hold) < 2**64
                or not count.isascii() or not count.isdigit() or not 0 <= int(count) <= 2147483647
                or hold in holds):
            raise ValueError('Invalid consumable identity or quantity')
        holds.add(hold)
        result.append({'sv_itemId':item,'sv_itemHoldId':hold,'sv_itemNum':count})
    return result


def grant_one_each(snapshot, receipt):
    receipts = deepcopy(snapshot.get('consumableGrants', {}))
    if receipt in receipts:
        return {}
    rows = owned(snapshot)
    holds = {row['sv_itemHoldId'] for row in rows}
    next_hold = max([97000000000] + [int(value) for value in holds]) + 1
    for item in CATALOGUE:
        existing = next((row for row in rows if row['sv_itemId'] == item['id']), None)
        if existing:
            if int(existing['sv_itemNum']) == 2147483647:
                raise ValueError('Inventory quantity overflow')
            existing['sv_itemNum'] = str(int(existing['sv_itemNum'])+1)
        else:
            rows.append({'sv_itemHoldId':str(next_hold),'sv_itemId':item['id'],'sv_itemNum':'1'})
            next_hold += 1
    owned({'consumableItems':rows})
    receipts[receipt] = [item['id'] for item in CATALOGUE]
    return {'consumableItems':rows,'consumableGrants':receipts}
