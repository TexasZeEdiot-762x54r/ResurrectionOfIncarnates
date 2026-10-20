"""Bounded revival Circle records; native response shapes, not original server policy."""
from contextlib import contextmanager
from contextlib import closing
import base64
import binascii
import sqlite3
import struct
import time

import commendations

# Revival safety limits, NOT recovered original membership limits or prices.
MEMBER_LIMIT = 20
MEMBER_EXPANSION_STEP = 5
MEMBER_EXPANSION_LP = 10000
MAX_MEMBERS = 100  # Bounded revival policy, not a recovered original maximum.
SUBLEADER_EXPANSION_STEP = 1
SUBLEADER_EXPANSION_LP = 10000
MAX_SUBLEADERS = 10  # Revival safety bound; the historical maximum is unknown.
MAX_CAPACITY_RECEIPTS = 16384
CAPACITY_POLICIES = {
    'members': dict(action='incMaxNumOfMembers', initial=MEMBER_LIMIT,
        step=MEMBER_EXPANSION_STEP, price=MEMBER_EXPANSION_LP, maximum=MAX_MEMBERS,
        table='circle_capacity', receipts='circle_capacity_receipts',
        info_field='sv_maxMembers', response_field='sv_maxMembers',
        pending='circleCapacityPending', receipt='circleCapacityReceipt'),
    'subleaders': dict(action='incMaxNumOfSubLeaders', initial=0,
        step=SUBLEADER_EXPANSION_STEP, price=SUBLEADER_EXPANSION_LP, maximum=MAX_SUBLEADERS,
        table='circle_subleader_capacity', receipts='circle_subleader_capacity_receipts',
        info_field='sv_subLeaderMax', response_field='sv_subLeaderNum',
        pending='circleSubLeaderCapacityPending', receipt='circleSubLeaderCapacityReceipt'),
}
CIRCLE_LIMIT = 1024
PAGE_SIZE = 20
MAX_ICON_CHARS = 96 * 1024
MAX_REQUEST_BYTES = 128 * 1024
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
# Native wire positions map to internal UI roles 1/2/3 as leader/subleader/member.
LEADER_POSITION = '2'
MEMBER_POSITION = '0'
SUPPORTED = {'setupCircle', 'getCircleInfo', 'getCircleMemberList', 'findCircle',
             'getCircleName', 'leaveCircle', 'breakUpCircle', 'changeComment',
             'changeCircleIcon', 'changeEntryQualifications', 'changeCircleArea',
             'incMaxNumOfMembers', 'incMaxNumOfSubLeaders'}
UNSUPPORTED = {'joinCircle', 'replyToJoinCircle', 'inviteCircle', 'replyToInviteCircle',
               'kickCircleMember',
               'assignLeader', 'changeSubLeader'}


def integer(value, low=0, high=2**31-1):
    if type(value) not in (int, str) or isinstance(value, str) and (
            not value or not value.isascii() or not value.isdecimal() or len(value) > 20):
        raise ValueError('Invalid integer')
    value = int(value)
    if not low <= value <= high:
        raise ValueError('Integer out of range')
    return value


def text(value, limit, empty=False):
    if (not isinstance(value, str) or len(value.encode('utf-8')) > limit
            or any(ord(c) < 32 for c in value) or not empty and not value.strip()):
        raise ValueError('Invalid text')
    return value


def icon(value):
    value = text(value, MAX_ICON_CHARS, empty=True)
    # The native client sends ==== before an emblem is selected, otherwise a
    # base64 PNG (observed 512x512, roughly 74 KB encoded). Never fetch a URL.
    if value in ('', '===='):
        return value
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValueError('Invalid Circle emblem encoding') from error
    if (len(raw) < 33 or raw[:16] != b'\x89PNG\r\n\x1a\n\x00\x00\x00\x0dIHDR'
            or not all(0 < size <= 512 for size in struct.unpack_from('>II', raw, 16))):
        raise ValueError('Circle emblem must be a bounded PNG')
    return value


@contextmanager
def database():
    # Reuse the existing bounded, durable volume and its SQLite transaction rules.
    with commendations.database() as db:
        db.row_factory = sqlite3.Row
        db.execute('CREATE TABLE IF NOT EXISTS circles ('
                   'id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, '
                   'name_key TEXT NOT NULL UNIQUE, icon TEXT NOT NULL, comment TEXT NOT NULL, '
                   'area INTEGER NOT NULL, invite_only INTEGER NOT NULL, min_rank INTEGER NOT NULL, '
                   'created INTEGER NOT NULL, leader TEXT NOT NULL UNIQUE)')
        db.execute('CREATE TABLE IF NOT EXISTS circle_members ('
                   'uid TEXT PRIMARY KEY, circle_id INTEGER NOT NULL, name TEXT NOT NULL, '
                   'joined INTEGER NOT NULL, rank INTEGER NOT NULL)')
        db.execute('CREATE INDEX IF NOT EXISTS circle_member_parent ON circle_members(circle_id)')
        for policy in CAPACITY_POLICIES.values():
            # Identifiers come only from the fixed policy table, never a request.
            db.execute('CREATE TABLE IF NOT EXISTS '+policy['table']+' ('
                       'circle_id INTEGER PRIMARY KEY, maximum INTEGER NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS '+policy['receipts']+' ('
                       'operation TEXT PRIMARY KEY, uid TEXT NOT NULL, circle_id INTEGER NOT NULL, '
                       'previous INTEGER NOT NULL, maximum INTEGER NOT NULL, price INTEGER NOT NULL, '
                       'status TEXT NOT NULL, reason TEXT NOT NULL)')
        yield db


def membership(db, uid):
    return db.execute('SELECT circles.* FROM circles JOIN circle_members '
                      'ON circles.id=circle_members.circle_id WHERE circle_members.uid=?',
                      (str(uid),)).fetchone()


def circle_id(uid):
    path = commendations.database_path()
    if not path.exists():
        return '0'
    # A profile read must not create tables or a database on its own.
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=3)) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='circle_members'").fetchone():
            return '0'
        row = db.execute('SELECT circle_id FROM circle_members WHERE uid=?', (str(uid),)).fetchone()
        return str(row[0]) if row else '0'


def snapshot(db, row):
    if row is None:
        return dict(sv_circleId='0', sv_createTime='0', sv_circleName='', sv_circleIcon='',
                    sv_comment='', sv_circleAreaId='0', sv_inviteOnly='0', sv_minRank='0',
                    sv_maxMembers='0', sv_memberCount='0', sv_status='0', sv_gamePoint='0',
                    sv_leaderUid='0', sv_leaderName='', sv_subLeaderMax='0',
                    sv_subLeaderCount='0', sv_subLeaderUids=[], sv_members=[], sv_invitings=[])
    members = db.execute('SELECT * FROM circle_members WHERE circle_id=? ORDER BY joined,uid',
                         (row['id'],)).fetchall()
    people = [dict(sv_uid=m['uid'], sv_onlineId=m['uid'], sv_userName=m['name'],
                   sv_rankId=str(m['rank']), sv_joinTime=str(m['joined']), sv_joinMethod='0',
                   sv_loginTime='0', sv_position=LEADER_POSITION if m['uid'] == row['leader'] else MEMBER_POSITION)
              for m in members]
    leader = next((m['name'] for m in members if m['uid'] == row['leader']), '')
    capacity = db.execute('SELECT maximum FROM circle_capacity WHERE circle_id=?', (row['id'],)).fetchone()
    subleaders = db.execute('SELECT maximum FROM circle_subleader_capacity WHERE circle_id=?', (row['id'],)).fetchone()
    return dict(sv_circleId=str(row['id']), sv_createTime=str(row['created']),
                sv_circleName=row['name'], sv_circleIcon=row['icon'], sv_comment=row['comment'],
                sv_circleAreaId=str(row['area']), sv_inviteOnly=str(row['invite_only']),
                sv_minRank=str(row['min_rank']), sv_maxMembers=str(capacity[0] if capacity else MEMBER_LIMIT),
                sv_memberCount=str(len(people)), sv_status='1', sv_gamePoint='0',
                sv_leaderUid=row['leader'], sv_leaderName=leader,
                sv_subLeaderMax=str(subleaders[0] if subleaders else 0),
                sv_subLeaderCount='0', sv_subLeaderUids=[], sv_members=people, sv_invitings=[])


def expand_capacity(db, own, uid, data, kind):
    policy = CAPACITY_POLICIES[kind]
    purchase = data.get('_purchase')
    if not isinstance(purchase, dict):
        raise ValueError('Missing purchase reservation')
    if purchase.get('kind', 'members') != kind:
        raise ValueError('Purchase kind does not match operation')
    operation = purchase.get('operation')
    if (not isinstance(operation, str) or len(operation) != 32
            or any(c not in '0123456789abcdef' for c in operation)):
        raise ValueError('Invalid purchase operation')
    cid = integer(purchase.get('circle_id'), 1, 2**63-1)
    previous = integer(purchase.get('previous'), policy['initial'], policy['maximum'])
    price = integer(purchase.get('price'), policy['price'], policy['price'])
    if (previous - policy['initial']) % policy['step']:
        raise ValueError('Invalid capacity reservation')
    for other in CAPACITY_POLICIES.values():
        if other is not policy and db.execute('SELECT 1 FROM '+other['receipts']+' WHERE operation=?', (operation,)).fetchone():
            raise ValueError('Purchase operation already used for another capacity kind')
    receipt = db.execute('SELECT * FROM '+policy['receipts']+' WHERE operation=?', (operation,)).fetchone()
    if receipt:
        if (receipt['uid'], receipt['circle_id'], receipt['previous'], receipt['price']) != (uid, cid, previous, price):
            raise ValueError('Purchase operation reused for a different request')
    else:
        count = sum(db.execute('SELECT COUNT(*) FROM '+p['receipts']).fetchone()[0]
                    for p in CAPACITY_POLICIES.values())
        if count >= MAX_CAPACITY_RECEIPTS:
            raise ValueError('Purchase receipt storage full')
        maximum = previous
        reason = ''
        if own is None or own['id'] != cid or own['leader'] != uid:
            reason = 'not_leader'
        else:
            current = snapshot(db, own)
            maximum = int(current[policy['info_field']])
            if maximum != previous:
                reason = 'capacity_changed'
            elif maximum + policy['step'] > policy['maximum']:
                reason = 'capacity_limit'
            else:
                maximum += policy['step']
                db.execute('INSERT OR REPLACE INTO '+policy['table']+' VALUES (?,?)', (cid, maximum))
        status = 'rejected' if reason else 'accepted'
        db.execute('INSERT INTO '+policy['receipts']+' VALUES (?,?,?,?,?,?,?,?)',
                   (operation, uid, cid, previous, maximum, price, status, reason))
        receipt = db.execute('SELECT * FROM '+policy['receipts']+' WHERE operation=?', (operation,)).fetchone()
    return {policy['response_field']: str(receipt['maximum']), '_purchase': dict(receipt, kind=kind)}


def perform(uid, name, action, data):
    uid = str(integer(uid, 1, 2**64-1))
    name = text(name, 255)
    if action not in SUPPORTED or not isinstance(data, dict):
        raise ValueError('Circle operation not implemented')
    with database() as db, db:
        db.execute('BEGIN IMMEDIATE')
        own = membership(db, uid)
        db.execute('UPDATE circle_members SET name=? WHERE uid=?', (name, uid))
        result = {}
        if action in ('incMaxNumOfMembers', 'incMaxNumOfSubLeaders'):
            kind = 'members' if action == 'incMaxNumOfMembers' else 'subleaders'
            result = expand_capacity(db, own, uid, data, kind)
        elif action == 'setupCircle':
            title = text(data.get('sv_name'), 64).strip()
            emblem = icon(data.get('sv_circleIcon', ''))
            area = integer(data.get('sv_circleAreaId'), 0, 255)
            invite = integer(data.get('sv_inviteOnly'), 0, 1)
            rank = integer(data.get('sv_minRank'), 0, 255)
            settings = (title, emblem, area, invite, rank)
            if own:
                if uid != own['leader'] or settings != tuple(own[k] for k in
                        ('name', 'icon', 'area', 'invite_only', 'min_rank')):
                    raise ValueError('Already belongs to a Circle')
            else:
                if db.execute('SELECT COUNT(*) FROM circles').fetchone()[0] >= CIRCLE_LIMIT:
                    raise ValueError('Circle storage full')
                now = int(time.time())
                cursor = db.execute('INSERT INTO circles '
                    '(name,name_key,icon,comment,area,invite_only,min_rank,created,leader) '
                    'VALUES (?,?,?,?,?,?,?,?,?)',
                    (title, title.casefold(), emblem, '', area, invite, rank, now, uid))
                db.execute('INSERT INTO circle_members VALUES (?,?,?,?,?)',
                           (uid, cursor.lastrowid, name, now, 1))
                own = membership(db, uid)
            result = {'sv_circle': snapshot(db, own)}
        elif action == 'getCircleInfo':
            value = snapshot(db, own)
            # Native type 60 reads invitations from data, not from sv_circle.
            result = {'sv_circle': value, 'sv_leaderName': value['sv_leaderName'],
                      'sv_invitings': []}
        elif action == 'getCircleMemberList':
            result = {'sv_members': snapshot(db, own)['sv_members'], 'sv_tagNames': []}
        elif action in ('findCircle', 'getCircleName'):
            clauses, params = [], []
            if 'sv_circleIds' in data:
                ids = data['sv_circleIds']
                if not isinstance(ids, list) or len(ids) > 100:
                    raise ValueError('Invalid Circle IDs')
                ids = [integer(v, 1, 2**63-1) for v in ids]
                clauses.append('id IN (' + ','.join('?' for _ in ids) + ')')
                params.extend(ids)
            elif action == 'getCircleName':
                raise ValueError('Missing Circle IDs')
            else:
                query = text(data.get('sv_name', ''), 64, empty=True)
                if query:
                    clauses.append('instr(name_key,?)>0')
                    params.append(query.casefold())
                for key, column in (('sv_inviteOnly', 'invite_only'), ('sv_minRank', 'min_rank'),
                                    ('sv_circleAreaId', 'area')):
                    if key in data:
                        val = integer(data[key], 0, 255)
                        # Area 0 is the revival all-areas search. Rank 0 imposes no filter.
                        if val or key == 'sv_inviteOnly':
                            clauses.append(column + '=?')
                            params.append(val)
            where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
            if action == 'getCircleName':
                rows = db.execute('SELECT id,name FROM circles' + where + ' ORDER BY id', params)
                result = {'sv_circleNames': [dict(sv_circleId=str(r['id']), sv_circleName=r['name'])
                                             for r in rows]}
            else:
                # The native first page is 1. Retain 0 only as a first-page alias
                # for older diagnostic callers; it must not advance pagination.
                page = integer(data.get('sv_page', 1), 0, 1000)
                count = db.execute('SELECT COUNT(*) FROM circles' + where, params).fetchone()[0]
                rows = db.execute('SELECT * FROM circles' + where + ' ORDER BY id LIMIT ? OFFSET ?',
                                  params + [PAGE_SIZE, max(0, page - 1) * PAGE_SIZE]).fetchall()
                summaries = [snapshot(db, r) for r in rows]
                for summary in summaries:
                    # Search consumes summaries, not every member's profile.
                    # Keep a full 20-emblem page within the response bound.
                    for key in ('sv_members', 'sv_invitings', 'sv_subLeaderUids'):
                        summary.pop(key)
                result = {'sv_totalPage': str((count + PAGE_SIZE-1)//PAGE_SIZE),
                          'sv_circles': summaries}
        elif action in ('leaveCircle', 'breakUpCircle'):
            if own:
                if action == 'breakUpCircle':
                    if own['leader'] != uid:
                        raise ValueError('Only the leader can disband')
                    db.execute('DELETE FROM circle_members WHERE circle_id=?', (own['id'],))
                    db.execute('DELETE FROM circle_capacity WHERE circle_id=?', (own['id'],))
                    db.execute('DELETE FROM circle_subleader_capacity WHERE circle_id=?', (own['id'],))
                    db.execute('DELETE FROM circles WHERE id=?', (own['id'],))
                else:
                    if own['leader'] == uid:
                        raise ValueError('Leader must disband instead of leaving')
                    db.execute('DELETE FROM circle_members WHERE uid=?', (uid,))
                own = None
        else:
            if own is None or own['leader'] != uid:
                raise ValueError('Only the leader can change Circle settings')
            if action == 'changeComment':
                value = text(data.get('sv_comment'), 255, empty=True)
                db.execute('UPDATE circles SET comment=? WHERE id=?', (value, own['id']))
                result = {'sv_comment': value}
            elif action == 'changeCircleIcon':
                value = icon(data.get('sv_circleIcon'))
                db.execute('UPDATE circles SET icon=? WHERE id=?', (value, own['id']))
            elif action == 'changeCircleArea':
                value = integer(data.get('sv_circleAreaId'), 0, 255)
                db.execute('UPDATE circles SET area=? WHERE id=?', (value, own['id']))
            elif action == 'changeEntryQualifications':
                invite = integer(data.get('sv_inviteOnly'), 0, 1)
                rank = integer(data.get('sv_minRank'), 0, 255)
                db.execute('UPDATE circles SET invite_only=?,min_rank=? WHERE id=?',
                           (invite, rank, own['id']))
        return {'data': result, 'circle_id': str(own['id']) if own else '0'}
