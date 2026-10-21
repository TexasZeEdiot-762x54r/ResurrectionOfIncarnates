import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'client' / 'tools'))

import circles
import network_defaults as network
import profile_store
import roi_circle_capacity
import roi_circles


class CircleCapacityPurchaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = patch.dict('os.environ', ROI_COMMENDATION_DB=str(self.root / 'state.sqlite3'))
        self.env.start()
        self.addCleanup(self.env.stop)
        self.uid = 42424242
        self.name = 'Synthetic Leader'
        self.profile = self.root / 'profile.json'
        self.original = {
            'gamePoint': 25000,
            'playerLevel': 12,
            'customizes': {'5': {'costume': '7'}},
            'skillGrids': {'5': {'active': 1}},
        }
        self.profile.write_text(json.dumps(self.original), encoding='utf-8')
        circles.perform(self.uid, self.name, 'setupCircle', {
            'sv_name': 'Synthetic Test Circle',
            'sv_circleIcon': '====',
            'sv_circleAreaId': 1,
            'sv_inviteOnly': 0,
            'sv_minRank': 0,
        })

    def request_local_circle(self, url, token, uid, name, action, data):
        return circles.perform(uid, name, action, data)

    def test_member_capacity_costs_10000_lp_for_five_slots(self):
        with patch.object(roi_circles, 'request', side_effect=self.request_local_circle):
            result = roi_circle_capacity.expand(
                self.profile,
                f'http://{network.LOOPBACK}/circle/{self.uid}',
                '',
                self.uid,
                self.name,
            )

        self.assertEqual(result, {'sv_maxMembers': '25', 'sv_gamePoint': '15000'})
        info = circles.perform(self.uid, self.name, 'getCircleInfo', {})
        self.assertEqual(info['data']['sv_circle']['sv_maxMembers'], '25')
        saved = profile_store.read(self.profile)
        self.assertEqual(saved['gamePoint'], 15000)
        self.assertIsNone(saved.get('circleCapacityPending'))
        self.assertEqual(saved['circleCapacityReceipt']['maximum'], 25)
        for key in ('playerLevel', 'customizes', 'skillGrids'):
            self.assertEqual(saved[key], self.original[key])

    def test_later_intentional_purchase_adds_five_more_slots(self):
        with patch.object(roi_circle_capacity.time, 'time', side_effect=(100, 103, 103)), \
                patch.object(roi_circles, 'request', side_effect=self.request_local_circle):
            first = roi_circle_capacity.expand(
                self.profile, f'http://{network.LOOPBACK}/circle/{self.uid}', '', self.uid, self.name)
            second = roi_circle_capacity.expand(
                self.profile, f'http://{network.LOOPBACK}/circle/{self.uid}', '', self.uid, self.name)

        self.assertEqual(first, {'sv_maxMembers': '25', 'sv_gamePoint': '15000'})
        self.assertEqual(second, {'sv_maxMembers': '30', 'sv_gamePoint': '5000'})
        info = circles.perform(self.uid, self.name, 'getCircleInfo', {})
        self.assertEqual(info['data']['sv_circle']['sv_maxMembers'], '30')
        self.assertEqual(profile_store.read(self.profile)['gamePoint'], 5000)

    def test_lost_reply_after_commit_retries_without_double_debit(self):
        operations = []

        def commit_then_drop_reply(url, token, uid, name, action, data):
            if action == 'incMaxNumOfMembers':
                operations.append(data['_purchase']['operation'])
            result = self.request_local_circle(url, token, uid, name, action, data)
            if action == 'incMaxNumOfMembers':
                raise TimeoutError('Synthetic lost reply after commit')
            return result

        with patch.object(roi_circles, 'request', side_effect=commit_then_drop_reply):
            with self.assertRaisesRegex(TimeoutError, 'lost reply'):
                roi_circle_capacity.expand(
                    self.profile, f'http://{network.LOOPBACK}/circle/{self.uid}', '', self.uid, self.name)

        reserved = profile_store.read(self.profile)
        self.assertEqual(reserved['gamePoint'], 15000)
        self.assertIsNotNone(reserved.get('circleCapacityPending'))

        def retry_same_operation(url, token, uid, name, action, data):
            if action == 'incMaxNumOfMembers':
                operations.append(data['_purchase']['operation'])
            return self.request_local_circle(url, token, uid, name, action, data)

        with patch.object(roi_circles, 'request', side_effect=retry_same_operation):
            result = roi_circle_capacity.expand(
                self.profile, f'http://{network.LOOPBACK}/circle/{self.uid}', '', self.uid, self.name)

        self.assertEqual(operations[0], operations[1])
        self.assertEqual(result, {'sv_maxMembers': '25', 'sv_gamePoint': '15000'})
        self.assertEqual(profile_store.read(self.profile)['gamePoint'], 15000)
        self.assertIsNone(profile_store.read(self.profile).get('circleCapacityPending'))
        info = circles.perform(self.uid, self.name, 'getCircleInfo', {})
        self.assertEqual(info['data']['sv_circle']['sv_maxMembers'], '25')

    def test_immediate_duplicate_click_is_coalesced(self):
        with patch.object(roi_circle_capacity.time, 'time', return_value=100), \
                patch.object(roi_circles, 'request', side_effect=self.request_local_circle) as request:
            first = roi_circle_capacity.expand(
                self.profile, f'http://{network.LOOPBACK}/circle/{self.uid}', '', self.uid, self.name)
            second = roi_circle_capacity.expand(
                self.profile, f'http://{network.LOOPBACK}/circle/{self.uid}', '', self.uid, self.name)

        self.assertEqual(first, second)
        self.assertEqual(first, {'sv_maxMembers': '25', 'sv_gamePoint': '15000'})
        self.assertEqual(request.call_count, 2)
        self.assertEqual(profile_store.read(self.profile)['gamePoint'], 15000)
        info = circles.perform(self.uid, self.name, 'getCircleInfo', {})
        self.assertEqual(info['data']['sv_circle']['sv_maxMembers'], '25')

    def test_insufficient_lp_does_not_reserve_or_expand_capacity(self):
        profile_store.update(self.profile, {'gamePoint': 9999})

        with patch.object(roi_circles, 'request', side_effect=self.request_local_circle):
            with self.assertRaisesRegex(ValueError, 'Insufficient LP'):
                roi_circle_capacity.expand(
                    self.profile, f'http://{network.LOOPBACK}/circle/{self.uid}', '', self.uid, self.name)

        saved = profile_store.read(self.profile)
        self.assertEqual(saved['gamePoint'], 9999)
        self.assertIsNone(saved.get('circleCapacityPending'))
        self.assertIsNone(saved.get('circleCapacityReceipt'))
        info = circles.perform(self.uid, self.name, 'getCircleInfo', {})
        self.assertEqual(info['data']['sv_circle']['sv_maxMembers'], '20')

    def test_server_capacity_rejection_refunds_reserved_lp_once(self):
        local_request = self.request_local_circle
        competed = False

        def compete_before_purchase(url, token, uid, name, action, data):
            nonlocal competed
            if action == 'incMaxNumOfMembers' and not competed:
                competed = True
                circles.perform(uid, name, action, {'_purchase': {
                    'operation': 'a' * 32,
                    'uid': str(uid),
                    'circle_id': '1',
                    'previous': 20,
                    'price': 10000,
                    'kind': 'members',
                }})
            return local_request(url, token, uid, name, action, data)

        with patch.object(roi_circles, 'request', side_effect=compete_before_purchase):
            with self.assertRaisesRegex(ValueError, 'Purchase rejected and LP refunded: capacity_changed'):
                roi_circle_capacity.expand(
                    self.profile, f'http://{network.LOOPBACK}/circle/{self.uid}', '', self.uid, self.name)

        saved = profile_store.read(self.profile)
        self.assertEqual(saved['gamePoint'], 25000)
        self.assertIsNone(saved.get('circleCapacityPending'))
        self.assertIsNone(saved.get('circleCapacityReceipt'))
        info = circles.perform(self.uid, self.name, 'getCircleInfo', {})
        self.assertEqual(info['data']['sv_circle']['sv_maxMembers'], '25')

    def test_subleader_purchase_uses_native_field_and_only_adds_allowance(self):
        with patch.object(roi_circles, 'request', side_effect=self.request_local_circle):
            result = roi_circle_capacity.expand(
                self.profile,
                f'http://{network.LOOPBACK}/circle/{self.uid}',
                '',
                self.uid,
                self.name,
                kind='subleaders',
            )

        self.assertEqual(result, {'sv_subLeaderNum': '1', 'sv_gamePoint': '15000'})
        info = circles.perform(self.uid, self.name, 'getCircleInfo', {})
        circle = info['data']['sv_circle']
        self.assertEqual(circle['sv_subLeaderMax'], '1')
        self.assertEqual(circle['sv_subLeaderCount'], '0')
        self.assertEqual(circle['sv_subLeaderUids'], [])
        self.assertEqual(circle['sv_maxMembers'], '20')
        self.assertEqual(circle['sv_members'][0]['sv_uid'], str(self.uid))
        self.assertEqual(profile_store.read(self.profile)['gamePoint'], 15000)

    def test_mismatched_committed_receipt_keeps_reservation_for_reconciliation(self):
        def mismatch_receipt(url, token, uid, name, action, data):
            result = self.request_local_circle(url, token, uid, name, action, data)
            if action == 'incMaxNumOfMembers':
                result['data']['_purchase']['uid'] = str(int(uid) + 1)
            return result

        with patch.object(roi_circles, 'request', side_effect=mismatch_receipt):
            with self.assertRaisesRegex(ValueError, 'Mismatched purchase receipt'):
                roi_circle_capacity.expand(
                    self.profile, f'http://{network.LOOPBACK}/circle/{self.uid}', '', self.uid, self.name)

        pending = profile_store.read(self.profile).get('circleCapacityPending')
        self.assertIsNotNone(pending)
        self.assertEqual(profile_store.read(self.profile)['gamePoint'], 15000)
        self.assertEqual(circles.perform(self.uid, self.name, 'getCircleInfo', {})[
            'data']['sv_circle']['sv_maxMembers'], '25')

        with patch.object(roi_circles, 'request', side_effect=self.request_local_circle):
            result = roi_circle_capacity.expand(
                self.profile, f'http://{network.LOOPBACK}/circle/{self.uid}', '', self.uid, self.name)

        self.assertEqual(result, {'sv_maxMembers': '25', 'sv_gamePoint': '15000'})
        self.assertEqual(profile_store.read(self.profile)['gamePoint'], 15000)
        self.assertIsNone(profile_store.read(self.profile).get('circleCapacityPending'))


if __name__ == '__main__':
    unittest.main()
