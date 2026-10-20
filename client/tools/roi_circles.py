"""Native Circle requests forwarded to the same shared backend as lobby profiles."""
import json
import urllib.request

import circles


def request(url, token, uid, name, action, data):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    body = json.dumps({'call': action, 'data': data, 'name': name},
                      separators=(',', ':')).encode()
    if len(body) > circles.MAX_REQUEST_BYTES:
        raise ValueError('Circle request too large')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(url, data=body, headers=headers, method='POST')
    with opener.open(req, timeout=3) as response:
        raw = response.read(circles.MAX_RESPONSE_BYTES + 1)
        if len(raw) > circles.MAX_RESPONSE_BYTES:
            raise ValueError('Circle response too large')
        result = json.loads(raw)
    if (not isinstance(result, dict) or not isinstance(result.get('data'), dict)
            or not isinstance(result.get('circle_id'), str)):
        raise ValueError('Invalid Circle response')
    circles.integer(result['circle_id'], 0, 2**63-1)
    # Native type 57/60 dereferences this object even on an empty success reply.
    if action in ('setupCircle', 'getCircleInfo'):
        value = result['data'].get('sv_circle')
        if (not isinstance(value, dict) or not isinstance(value.get('sv_circleId'), str)
                or value['sv_circleId'] != result['circle_id']
                or not isinstance(value.get('sv_members'), list)):
            raise ValueError('Incomplete Circle response')
    if action == 'getCircleInfo' and not isinstance(result['data'].get('sv_invitings'), list):
        raise ValueError('Missing root Circle invitations')
    return result
