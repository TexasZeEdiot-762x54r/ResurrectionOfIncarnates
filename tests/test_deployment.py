import copy
import importlib.util
from ipaddress import IPv4Address
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'client/tools'))
sys.path.insert(0,str(ROOT/'server'))
import deployment_config as config
import configure
import firewall_guard
import network_defaults as network
import tls_transport
import public_tunnel
import provision_players
sys.path.insert(0,str(ROOT))
import audit_public


def example():
    return json.loads((ROOT/'deployment.example.json').read_text(encoding='utf-8'))


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


if __name__=='__main__':unittest.main()
