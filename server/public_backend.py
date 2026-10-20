"""Anonymous revival backend, reachable ONLY through the container-local TLS gateway."""
from network_defaults import LOOPBACK
import os
import sys


def main():
    if os.environ.get('ROI_PUBLIC_ACCESS')!='1' or os.environ.get('ROI_AUTH_FILE'):
        raise ValueError('Public backend requires explicit anonymous opt-in and no private credential file')
    import nrt_security
    # Gateway already bounds real source IPs; all backend peers are loopback.
    nrt_security.MAX_PER_ADDRESS=nrt_security.MAX_CONNECTIONS
    import nrt_server
    sys.argv=[sys.argv[0],'--host',LOOPBACK,'--port','52711']
    nrt_server.main()


if __name__=='__main__':
    main()
