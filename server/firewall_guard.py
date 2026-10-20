"""Root-owned, port-specific guard. Never changes WireGuard zones or other services."""
import subprocess
import sys
from functools import lru_cache
from configure import vpn_settings
from deployment_config import load

IPTABLES = "/usr/sbin/iptables"
CHAIN = "ROI-LOBBY"
PORTS = (52711, 52713)


@lru_cache(maxsize=1)
def configuration():
    return vpn_settings(load())


def match(port):
    address,_,_=configuration()
    return ["-p", "tcp", "-m", "conntrack", "--ctdir", "ORIGINAL",
            "--ctorigdst", address, "--ctorigdstport", str(port),
            "-m", "comment", "--comment", "roi-lobby-only", "-j", CHAIN]
DROP = ["-j", "DROP"]
def rich_rule(port):
    address,_,_=configuration()
    return f'rule family="ipv4" destination address="{address}" port port="{port}" protocol="tcp" reject'


def iptables(*args, check=True):
    return subprocess.run([IPTABLES, "-w", "5", *args], check=check,
                          capture_output=True, text=True, timeout=10)


def main():
    _,network,interface=configuration()
    allow=["-i",interface,"-s",network,"-j","RETURN"]
    action = sys.argv[1] if len(sys.argv) > 1 else "start"
    if action == "start":
        if iptables("-S", CHAIN, check=False).returncode:
            iptables("-N", CHAIN)
        existing = iptables("-S", CHAIN).stdout.splitlines()
        expected = {"-N " + CHAIN,
                    f"-A ROI-LOBBY -s {network} -i {interface} -j RETURN",
                    "-A ROI-LOBBY -j DROP"}
        if any(line not in expected for line in existing):
            raise RuntimeError("Existing ROI-LOBBY chain has unexpected rules; refusing to change it")
        for rule in (allow, DROP):
            if iptables("-C", CHAIN, *rule, check=False).returncode:
                iptables("-A", CHAIN, *rule)
        for port in PORTS:
            if iptables("-C", "DOCKER-USER", *match(port), check=False).returncode:
                iptables("-I", "DOCKER-USER", "1", *match(port))
            for permanence in ([], ["--permanent"]):
                subprocess.run(["/usr/bin/firewall-cmd", *permanence, "--zone=public",
                                "--add-rich-rule", rich_rule(port)], check=True, timeout=10)
    elif action == "stop":
        for port in PORTS:
            if not iptables("-C", "DOCKER-USER", *match(port), check=False).returncode:
                iptables("-D", "DOCKER-USER", *match(port))
        for rule in (allow, DROP):
            if not iptables("-C", CHAIN, *rule, check=False).returncode:
                iptables("-D", CHAIN, *rule)
        iptables("-X", CHAIN, check=False)
        for port in PORTS:
            for permanence in ([], ["--permanent"]):
                subprocess.run(["/usr/bin/firewall-cmd", *permanence, "--zone=public",
                                "--remove-rich-rule", rich_rule(port)], check=True, timeout=10)
    else:
        raise ValueError("Expected start or stop")


if __name__ == "__main__":
    main()
