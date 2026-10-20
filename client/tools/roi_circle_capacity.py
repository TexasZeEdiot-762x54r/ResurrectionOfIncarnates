"""Reserve local revival LP and reconcile an idempotent shared capacity purchase."""
import secrets
import time

import circles
import profile_store
import roi_circles

RETRY_WINDOW = 2


def expand(path, url, token, uid, name, kind='members'):
    uid = str(circles.integer(uid, 1, 2**64-1))
    if kind not in circles.CAPACITY_POLICIES:
        raise ValueError('Unknown capacity purchase kind')
    policy = circles.CAPACITY_POLICIES[kind]
    response_field = policy['response_field']

    def request(action, data):
        return roi_circles.request(url, token, uid, name, action, data)

    with profile_store.LOCK:
        saved = profile_store.read(path)
        pending = saved.get(policy['pending'])
        if pending is None:
            last = saved.get(policy['receipt'])
            if (isinstance(last, dict) and last.get('uid') == uid
                    and 0 <= time.time() - last.get('time', 0) < RETRY_WINDOW):
                return {response_field: str(last['maximum']),
                        'sv_gamePoint': str(saved.get('gamePoint', 0))}
            result = request('getCircleInfo', {})
            circle = result['data']['sv_circle']
            if circle.get('sv_leaderUid') != uid:
                raise ValueError('Only the Circle leader can buy capacity')
            cid = circles.integer(circle.get('sv_circleId'), 1, 2**63-1)
            previous = circles.integer(circle.get(policy['info_field']), policy['initial'], policy['maximum'])
            if previous + policy['step'] > policy['maximum']:
                raise ValueError('Circle capacity limit reached')
            balance = circles.integer(saved.get('gamePoint', 0), 0, 2**31-1)
            if balance < policy['price']:
                raise ValueError('Insufficient LP')
            pending = dict(operation=secrets.token_hex(16), uid=uid, circle_id=cid,
                           previous=previous, price=policy['price'], kind=kind)
            # Reserve before sending. A timeout keeps the operation durable;
            # retrying it cannot debit again or expand twice on the backend.
            profile_store.update(path, {'gamePoint': balance - pending['price'],
                                        policy['pending']: pending})
        if not isinstance(pending, dict) or pending.get('uid') != uid:
            raise ValueError('Pending purchase belongs to another identity')
        if pending.get('price') != policy['price'] or pending.get('kind', 'members') != kind:
            raise ValueError('Unrecognized pending purchase price')
        result = request(policy['action'], {'_purchase': pending})
        receipt = result['data'].get('_purchase')
        if (not isinstance(receipt, dict) or receipt.get('kind', 'members') != kind
                or any(receipt.get(k) != pending[k] for k in
                ('operation', 'uid', 'circle_id', 'previous', 'price'))):
            raise ValueError('Mismatched purchase receipt; reservation retained')
        maximum = circles.integer(receipt.get('maximum'), policy['initial'], policy['maximum'])
        current = profile_store.read(path)
        balance = circles.integer(current.get('gamePoint', 0), 0, 2**31-1)
        if receipt.get('status') == 'rejected':
            if receipt.get('reason') not in ('not_leader', 'capacity_changed', 'capacity_limit'):
                raise ValueError('Unknown rejection; reservation retained')
            if balance + pending['price'] > 2**31-1:
                raise ValueError('Refund exceeds native balance range')
            profile_store.update(path, {'gamePoint': balance + pending['price'], policy['pending']: None})
            raise ValueError('Purchase rejected and LP refunded: ' + receipt['reason'])
        if (receipt.get('status') != 'accepted' or receipt.get('reason') != ''
                or maximum != pending['previous'] + policy['step']
                or result['data'].get(response_field) != str(maximum)):
            raise ValueError('Unconfirmed capacity purchase; reservation retained')
        profile_store.update(path, {policy['pending']: None,
            policy['receipt']: dict(pending, maximum=maximum, time=time.time())})
        return {response_field: str(maximum), 'sv_gamePoint': str(balance)}
