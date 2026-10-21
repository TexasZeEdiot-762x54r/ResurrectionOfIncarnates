import copy
import asyncio
import importlib.util
from ipaddress import IPv4Address
import json
import os
import ssl
from pathlib import Path
import shutil
import subprocess
import sys
import struct
import tempfile
import unittest
from unittest.mock import patch
from io import BytesIO
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
_ORIGINAL_WAIT_FOR=asyncio.wait_for


class FastAsyncio:
    def __getattr__(self,name):return getattr(asyncio,name)
    async def wait_for(self,awaitable,timeout):
        return await _ORIGINAL_WAIT_FOR(awaitable,min(timeout,.02))


sys.path.insert(0,str(ROOT/'client/tools'))
sys.path.insert(0,str(ROOT/'server'))
import deployment_config as config
import configure
import firewall_guard
import network_defaults as network
import tls_transport
import public_tunnel
import provision_players
import nrt_logic as realtime_logic
import nrt_security as realtime_security
sys.path.insert(0,str(ROOT))
import audit_public


def example():
    value=json.loads((ROOT/'deployment.example.json').read_text(encoding='utf-8'))
    value['policy']['progression_mode']='faithful'
    return value


def configured():
    value=example()
    value['client'].update(internet_host='gateway.example.invalid',lan_host='lan.example.invalid',
        certificate_sha256='a'*64,vpn_lobby_host='vpn.example.invalid')
    value['server'].update(public_bind_host=str(IPv4Address(0xC000020A)),
        vpn_bind_host=str(IPv4Address(0xC000020B)),vpn_network=str(IPv4Address(0xC0000200))+'/24',
        vpn_interface='wg-test',python_base='python:3-slim@sha256:'+'b'*64)
    return value


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name)
        self.path=self.folder/'deployment.local.json'
        self.env=patch.dict(os.environ,{'ROI_DEPLOYMENT_FILE':str(self.path)})
        self.env.start();self.addCleanup(self.env.stop)

    def save(self,value):
        self.path.write_text(json.dumps(value),encoding='utf-8')

    def test_missing_explicit_config_never_falls_back(self):
        with self.assertRaises(ValueError):config.load(required=False)

    def test_example_has_no_operator_endpoints_or_pin(self):
        value=example()
        for key in ('internet_host','lan_host','certificate_sha256','vpn_lobby_host'):
            self.assertEqual(value['client'][key],'')
        self.save(value)
        with self.assertRaises(ValueError):config.public_settings()
        with self.assertRaises(ValueError):config.vpn_endpoint()
        with self.assertRaises(ValueError):configure.environment(value,'public')

    def test_load_rejects_unknown_keys_and_duplicate_keys(self):
        for section in ('client','server'):
            value=example();value[section]['typo']='x';self.save(value)
            with self.assertRaises(ValueError):config.load()
        self.path.write_text('{"version":1,"version":1,"client":{}}')
        with self.assertRaises(ValueError):config.load()

    def test_version_one_config_remains_compatible_without_policy(self):
        value=example();value['version']=1;value.pop('policy')
        self.save(value)
        loaded=config.load()
        self.assertEqual(loaded['version'],1)
        self.assertNotIn('policy',loaded)

    def test_version_two_policy_requires_explicit_supported_choice(self):
        template=json.loads((ROOT/'deployment.example.json').read_text(encoding='utf-8'))
        self.save(template)
        with self.assertRaisesRegex(ValueError,'progression_mode'):
            config.load()
        for mode in ('faithful','fully_unlocked','match_xp'):
            value=example();value['policy']['progression_mode']=mode;self.save(value)
            self.assertEqual(config.load()['policy']['progression_mode'],mode)
        value=example();value['policy']['extra']='x';self.save(value)
        with self.assertRaises(ValueError):config.load()

    def test_policy_selection_does_not_rewrite_existing_profile(self):
        profile=self.folder/'profile.json'
        before=b'{"gamePoint":321,"consumableItems":[{"sv_itemId":"7","sv_itemHoldId":"8","sv_itemNum":"2"}],"skillGrids":[{"sv_sgridId":"0"}]}'
        profile.write_bytes(before)
        for mode in ('faithful','fully_unlocked','match_xp'):
            value=example();value['policy']['progression_mode']=mode;self.save(value)
            config.load()
            self.assertEqual(profile.read_bytes(),before)

    def test_version_two_policy_rejects_non_string_modes_in_both_copies(self):
        for number, path in enumerate((ROOT/'client/tools/deployment_config.py',
                                       ROOT/'server/deployment_config.py')):
            spec=importlib.util.spec_from_file_location('policy_validation_'+str(number),path)
            module=importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            for mode in (None,True,1,[],{},['faithful'],{'mode':'faithful'}):
                with self.subTest(source=number,mode=mode):
                    value=example();value['policy']['progression_mode']=mode;self.save(value)
                    with self.assertRaisesRegex(ValueError,'progression_mode'):
                        module.load(self.path)

    def test_rejects_invalid_ports_types_and_control_characters(self):
        for bad in (0,65536,True,'52714',52714.5):
            value=example();value['client']['port']=bad;self.save(value)
            with self.assertRaises(ValueError):config.load()
        value=example();value['client']['internet_host']='host\nBAD=x';self.save(value)
        with self.assertRaises(ValueError):config.load()

    def test_bom_config_and_vpn_endpoint(self):
        self.path.write_text(json.dumps(configured()),encoding='utf-8-sig')
        self.assertEqual(config.vpn_endpoint(),'vpn.example.invalid:52711')

    def test_file_bound_and_version(self):
        self.path.write_bytes(b' '*32769)
        with self.assertRaises(ValueError):config.load()
        self.save({'version':2})
        with self.assertRaises(ValueError):config.load()

    def test_public_environment_uses_configured_host_and_port(self):
        value=configured();value['server']['public_port']=53999
        env=configure.environment(value,'public')
        self.assertEqual(env['ROI_PUBLIC_PORT'],'53999')
        self.assertEqual(env['ROI_PUBLIC_BIND_HOST'],value['server']['public_bind_host'])
        value['server']['public_bind_host']='any'
        self.assertEqual(configure.environment(value,'public')['ROI_PUBLIC_BIND_HOST'],network.ANY_IPV4)

    def test_vpn_configuration_rejects_mismatched_or_overbroad_network(self):
        value=configured()
        self.assertEqual(configure.vpn_settings(value)[2],'wg-test')
        value['server']['vpn_bind_host']=str(IPv4Address(0xCB007101))
        with self.assertRaises(ValueError):configure.vpn_settings(value)
        value=configured();value['server']['vpn_network']=network.ANY_IPV4+'/0'
        with self.assertRaises(ValueError):configure.vpn_settings(value)
        value=configured();value['server']['vpn_interface']='wg0;bad'
        with self.assertRaises(ValueError):configure.vpn_settings(value)

    def test_image_reference_must_be_pinned_official_python(self):
        for bad in ('python:latest','unknown/image@sha256:'+'a'*64,'python:3@sha256:short'):
            value=configured();value['server']['python_base']=bad
            with self.assertRaises(ValueError):configure.environment(value,'public')

    def test_env_writer_backs_up_existing_settings(self):
        target=self.folder/'.env'
        configure.write_env({'VALUE':'first'},target)
        configure.write_env({'VALUE':'second'},target)
        backups=list(self.folder.glob('.env.backup-*'))
        self.assertEqual(len(backups),1)
        self.assertEqual(backups[0].read_text(),'VALUE=first\n')
        self.assertEqual(target.read_text(),'VALUE=second\n')

    def test_public_tunnel_only_accepts_selected_private_configuration(self):
        value=configured();self.save(value)
        runtime=self.folder/'config.json'
        runtime.write_text(json.dumps({'lobby_transport':'tls-public','public_lobby_host':'gateway.example.invalid'}))
        with patch.object(public_tunnel,'HERE',self.folder):
            self.assertEqual(public_tunnel.settings(),('gateway.example.invalid',52714,'a'*64))
            runtime.write_text(json.dumps({'lobby_transport':'tls-public','public_lobby_host':'other.example.invalid'}))
            with self.assertRaises(ValueError):public_tunnel.settings()

    def test_guard_scopes_match_and_rich_rule_to_private_settings(self):
        self.save(configured());firewall_guard.configuration.cache_clear()
        self.addCleanup(firewall_guard.configuration.cache_clear)
        rule=firewall_guard.match(52711)
        self.assertEqual(rule[rule.index('--ctorigdst')+1],configured()['server']['vpn_bind_host'])
        self.assertIn(configured()['server']['vpn_bind_host'],firewall_guard.rich_rule(52711))

    def test_standard_loopback_wire_values_are_preserved(self):
        address=IPv4Address(network.LOOPBACK)
        self.assertTrue(address.is_loopback)
        self.assertEqual(address.packed,bytes((127,0,0,1)))
        self.assertTrue(IPv4Address(network.ANY_IPV4).is_unspecified)
        self.assertEqual(network.listen_address('loopback'),network.LOOPBACK)
        self.assertEqual(network.listen_address('any'),network.ANY_IPV4)

    def test_isolated_client_entrypoints_import_without_starting_services(self):
        for name in ('server.py','public_tunnel.py'):
            result=subprocess.run([sys.executable,'-I',str(ROOT/'client/tools'/name),'--help'],capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)

    def test_all_python_and_json_sources_parse(self):
        for path in ROOT.rglob('*'):
            if path.suffix=='.py':compile(path.read_bytes(),path.name,'exec')
            if path.suffix=='.json':json.loads(path.read_text(encoding='utf-8-sig'))

    @unittest.skipUnless(os.name=='nt','PowerShell parser available on Windows')
    def test_all_powershell_files_parse_without_executing_scripts(self):
        command="$bad=0; Get-ChildItem -LiteralPath $env:ROI_TEST_ROOT -Recurse -Filter *.ps1 | ForEach-Object { $tokens=$null; $errors=$null; [void][System.Management.Automation.Language.Parser]::ParseFile($_.FullName,[ref]$tokens,[ref]$errors); $bad += $errors.Count }; Write-Output $bad; exit ([int]($bad -gt 0))"
        result=subprocess.run(['powershell.exe','-NoProfile','-Command',command],env=dict(os.environ,ROI_TEST_ROOT=str(ROOT)),capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_public_scan_detects_synthetic_address_and_metadata(self):
        findings=audit_public.scan({'example.txt':str(IPv4Address(0xC0000201)).encode()})
        self.assertEqual(findings,[('example.txt','literal-ip-address')])
        self.assertTrue(audit_public.jpeg_metadata(bytes((255,216,255,225,0,2,255,217))))
        self.assertEqual(audit_public.scan({'slice.py':b'value[::-1]'}),[])

    def test_component_settings_take_precedence_over_repository_file(self):
        tools=self.folder/'client/tools';tools.mkdir(parents=True)
        self.save(configured())
        local=configured();local['client']['internet_host']='component.example.invalid'
        (tools.parent/'deployment.local.json').write_text(json.dumps(local))
        with patch.dict(os.environ,{'ROI_DEPLOYMENT_FILE':''}),patch.object(config,'__file__',str(tools/'deployment_config.py')):
            self.assertEqual(config.load()['client']['internet_host'],'component.example.invalid')

    def test_invitation_uses_configured_endpoint_and_keeps_existing_token(self):
        self.save(configured())
        private=self.folder/'private'
        provision_players.provision(private,[],invite=True)
        first=json.loads((private/'lobby-invitation.json').read_text())
        provision_players.provision(private,[],invite=True)
        second=json.loads((private/'lobby-invitation.json').read_text())
        self.assertEqual(first,second)
        self.assertEqual(first['lobby_server'],'vpn.example.invalid:52711')

    def test_unconfigured_invitation_does_not_create_credentials(self):
        self.save(example())
        private=self.folder/'private'
        with self.assertRaises(ValueError):provision_players.provision(private,[],invite=True)
        self.assertFalse(private.exists())

    @unittest.skipUnless(shutil.which('docker'),'Docker Compose CLI unavailable')
    def test_both_compose_variants_validate_and_missing_config_fails(self):
        env={k:v for k,v in os.environ.items() if k not in
             ('PYTHON_BASE','ROI_PUBLIC_BIND_HOST','ROI_PUBLIC_PORT','ROI_VPN_BIND_HOST')}
        docker_config=self.folder/'docker-config';docker_config.mkdir()
        env['DOCKER_CONFIG']=str(docker_config)
        for mode,name in (('public','compose.public.yaml'),('vpn','compose.yaml')):
            command=['docker','compose','-f',str(ROOT/'server'/name),'config','--quiet']
            empty=subprocess.run(command,env=env,capture_output=True,text=True,timeout=20)
            self.assertNotEqual(empty.returncode,0)
            populated=subprocess.run(command,env=dict(env,**configure.environment(configured(),mode)),capture_output=True,text=True,timeout=20)
            self.assertEqual(populated.returncode,0,populated.stderr)

    def test_native_library_patches_keep_original_allocations_and_loopback(self):
        spec=importlib.util.spec_from_file_location('native_library_test',ROOT/'client/tools/sessions/library_pages.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        replacements=list(module.replacements())
        self.assertEqual(len(replacements),4)
        for _,old,new in replacements:
            self.assertEqual(len(old),len(new))
            self.assertTrue(new.startswith(('http://'+network.LOOPBACK+':52710/library/%s/').encode()))

    def test_transport_admission_limits_unchanged(self):
        limits=tls_transport.Limits(maximum=2,per_ip=1)
        self.assertTrue(limits.enter('peer-a',0))
        self.assertFalse(limits.enter('peer-a',0))
        self.assertTrue(limits.enter('peer-b',0))
        self.assertFalse(limits.enter('peer-c',0))
        limits.leave('peer-a')
        self.assertTrue(limits.enter('peer-c',0))

    def test_shared_protocol_sources_are_identical(self):
        for name in ('network_defaults.py','deployment_config.py','paths.py','tls_transport.py',
                     'nrt_server.py','nrt_security.py','nrt_logic.py','nrt_rooms.py'):
            self.assertEqual((ROOT/'server'/name).read_bytes(),(ROOT/'client/tools'/name).read_bytes(),name)

    def test_no_settings_can_silently_select_an_unconfigured_public_host(self):
        value=configured();value['client']['internet_host']=''
        self.save(value)
        runtime=self.folder/'config.json'
        runtime.write_text(json.dumps({'lobby_transport':'tls-public','public_lobby_host':''}))
        with patch.object(public_tunnel,'HERE',self.folder):
            with self.assertRaises(ValueError):public_tunnel.settings()


class LocalRequestFailureTests(unittest.TestCase):
    def setUp(self):
        import server
        self.service = server

    def test_oversized_length_is_rejected_before_read(self):
        handler = SimpleNamespace(headers={'Content-Length': str(self.service.MAX_BODY + 1)}, rfile=None)
        with self.assertRaises(self.service.RequestTooLarge):
            self.service.Handler._body(handler)

    def test_short_body_and_invalid_lengths_are_rejected(self):
        for length, body in (('5', b'x'), ('-1', b''), ('invalid', b'')):
            handler = SimpleNamespace(headers={'Content-Length': length}, rfile=BytesIO(body))
            with self.subTest(length=length), self.assertRaises(ValueError):
                self.service.Handler._body(handler)

    def test_zero_length_body_is_accepted(self):
        handler = SimpleNamespace(headers={}, rfile=None)
        self.assertEqual(self.service.Handler._body(handler), b'')

    def test_body_failures_return_bounded_errors_and_close_connection(self):
        for error, expected in ((self.service.RequestTooLarge(), 413),
                                (TimeoutError(), 408), (ValueError('sensitive value'), 400)):
            handler = SimpleNamespace(command='POST', path='/Dragon/game', close_connection=False)
            def fail(error=error):
                raise error
            handler._body = fail
            handler._reply = lambda status, headers, body, quiet=False: (status, body, quiet)
            fake_library = SimpleNamespace(respond=lambda *args: None)
            with self.subTest(status=expected), patch.dict(sys.modules, {'library_pages': fake_library}):
                status, body, quiet = self.service.Handler._handle(handler)
            self.assertEqual(status, expected)
            self.assertLess(len(body), 80)
            self.assertNotIn(b'sensitive', body)
            self.assertTrue(quiet and handler.close_connection)


class TransportFailureTests(unittest.IsolatedAsyncioTestCase):
    class Writer:
        def __init__(self, ssl_object=None, block_drain=False):
            self.data=bytearray()
            self.closed=False
            self.ssl_object=ssl_object
            self.block_drain=block_drain
            self.transport=self
        def write(self,data):self.data.extend(data)
        def set_write_buffer_limits(self,**_kwargs):pass
        def get_extra_info(self,name):return self.ssl_object if name=='ssl_object' else None
        async def drain(self):
            if self.block_drain:await asyncio.Event().wait()
        def close(self):self.closed=True
        async def wait_closed(self):pass

    async def test_bridge_preserves_partial_reads_in_order(self):
        left,right=asyncio.StreamReader(),asyncio.StreamReader()
        left.feed_data(b'first-')
        left.feed_data(b'second')
        left.feed_eof()
        inbound,outbound=self.Writer(),self.Writer()
        result=await tls_transport.bridge(left,inbound,right,outbound)
        self.assertEqual(outbound.data,b'first-second')
        self.assertEqual(result['left_to_right_bytes'],12)
        self.assertEqual(result['reason'],'left-eof')
        self.assertTrue(outbound.closed and inbound.closed)

    async def test_peer_disconnect_closes_both_sides_promptly(self):
        left,right=asyncio.StreamReader(),asyncio.StreamReader()
        left.feed_eof()
        outbound,inbound=self.Writer(),self.Writer()
        result=await asyncio.wait_for(tls_transport.bridge(left,outbound,right,inbound),.5)
        self.assertEqual(result['reason'],'left-eof')
        self.assertTrue(outbound.closed and inbound.closed)

    async def test_blocked_drain_times_out_and_closes_both_sides(self):
        left,right=asyncio.StreamReader(),asyncio.StreamReader()
        left.feed_data(b'bounded')
        inbound,outbound=self.Writer(),self.Writer(block_drain=True)
        with patch.object(tls_transport,'asyncio',FastAsyncio()):
            result=await tls_transport.bridge(left,inbound,right,outbound)
        self.assertEqual(result['reason'],'left-TimeoutError')
        self.assertTrue(outbound.closed and inbound.closed)

    async def test_gateway_connect_timeout_is_bounded_without_network_access(self):
        async def never_connect(*_args,**_kwargs):await asyncio.Event().wait()
        fake_asyncio=FastAsyncio()
        fake_asyncio.open_connection=never_connect
        with patch.object(tls_transport,'asyncio',fake_asyncio):
            with self.assertRaises(asyncio.TimeoutError):
                await tls_transport.pinned_connection('gateway.example.invalid',52714,'a'*64)

    async def test_certificate_mismatch_closes_writer_before_forwarding(self):
        class SSLPeer:
            def getpeercert(self,binary_form=False):return b'synthetic-untrusted-certificate'
        writer=self.Writer(SSLPeer())
        calls=[]
        async def synthetic_connection(*_args,**_kwargs):
            calls.append(1)
            return asyncio.StreamReader(),writer
        with patch.object(tls_transport.asyncio,'open_connection',synthetic_connection):
            with self.assertRaises(ssl.SSLError):
                await tls_transport.pinned_connection('gateway.example.invalid',52714,'a'*64)
        self.assertEqual(len(calls),1)
        self.assertTrue(writer.closed)
        self.assertEqual(writer.data,b'')

    async def test_failed_gateway_health_check_does_not_retry(self):
        reader=asyncio.StreamReader()
        reader.feed_data(b'NOT-HEALTHY\n')
        writer=self.Writer()
        calls=[]
        async def synthetic_connection(*_args):
            calls.append(1)
            return reader,writer
        with patch.object(public_tunnel,'pinned_connection',synthetic_connection):
            with self.assertRaises(ValueError):
                await public_tunnel.check(('gateway.example.invalid',52714,'a'*64))
        self.assertEqual(len(calls),1)
        self.assertTrue(writer.closed)
        self.assertEqual(writer.data,tls_transport.CHANNELS['health'])


class RealtimeFrameTests(unittest.TestCase):
    @staticmethod
    def client_packet(seq=7, session=3, uid=0x123456789ABCDEF0, payload=b'\xa5\x5a'):
        body=struct.pack('<QHHQ',seq,session,0xE609,uid)+payload
        return struct.pack('<HH',len(body)+4,len(body))+body+b'\x00\x00'

    def test_complete_e609_frame_preserves_fields_and_opaque_payload(self):
        raw=self.client_packet()
        messages,rest=realtime_logic.parse(raw)
        self.assertEqual(rest,b'')
        self.assertEqual(messages,[(7,3,0xE609,0x123456789ABCDEF0,b'\xa5\x5a')])

    def test_every_fragment_boundary_is_retained_until_complete(self):
        raw=self.client_packet()
        for end in range(1,len(raw)):
            with self.subTest(end=end):
                messages,rest=realtime_logic.parse(raw[:end])
                self.assertEqual(messages,[])
                self.assertEqual(rest,raw[:end])
        messages,rest=realtime_logic.parse(raw)
        self.assertEqual(len(messages),1)
        self.assertEqual(rest,b'')

    def test_coalesced_frames_are_split_without_socket_io(self):
        first=self.client_packet(seq=1,payload=b'')
        second=self.client_packet(seq=2,session=4,payload=b'opaque')
        messages,rest=realtime_logic.parse(first+second)
        self.assertEqual([entry[0] for entry in messages],[1,2])
        self.assertEqual(rest,b'')

    def test_truncated_body_waits_for_remaining_bytes(self):
        raw=self.client_packet()
        messages,rest=realtime_logic.parse(raw[:-1])
        self.assertEqual(messages,[])
        self.assertEqual(rest,raw[:-1])

    def test_invalid_and_oversized_outer_lengths_are_rejected(self):
        for length in (0,1,23,realtime_security.MAX_FRAME-1,0xFFFF):
            with self.subTest(length=length):
                with self.assertRaises(realtime_security.ProtocolError):
                    realtime_logic.parse(struct.pack('<H',length))

    def test_inconsistent_body_length_is_rejected(self):
        raw=bytearray(self.client_packet())
        struct.pack_into('<H',raw,2,19)
        with self.assertRaises(realtime_security.ProtocolError):
            realtime_logic.parse(raw)


if __name__=='__main__':unittest.main()
