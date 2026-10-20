"""Observe results-ready, mail parsing and 9008 without changing state."""
HOOKS = {
    'ready_entry': (0x140103620, bytes.fromhex('40534883ec20')),
    'collect_entry': (0x140107EF0, bytes.fromhex('48895c2408')),
    'mails_entry': (0x1400CF370, bytes.fromhex('48894c2408')),
    'mails_complete': (0x1400D0DAC, bytes.fromhex('83e904')),
    'mails_exit': (0x1400D11D1, bytes.fromhex('4881c4e0150000')),
    'mail_entry': (0x1400DBD90, bytes.fromhex('48894c2408')),
    'mail_ok': (0x1400DC2B2, bytes.fromhex('b901000000')),
    'mail_exit': (0x1400DD750, bytes.fromhex('4881c418060000')),
    'controller_error': (0x140100DE0, bytes.fromhex('48895c2408')),
    'central_error': (0x140014300, bytes.fromhex('48895c24104889742418')),
}


def snapshot(d):
    game=d.q(0x141b87450)
    api=d.q(game+0x170) if game else 0
    nrt=d.q(game+0x150) if game else 0
    return dict(api_state=d.d32(api+0x128) if api else None,
                api_mode=d.d32(api+0x12c) if api else None,
                nrt_state=d.d32(nrt+0x3fd0) if nrt else None,
                nrt_wait=d.d32(nrt+0x40c8) if nrt else None)


def setup(d):
    budget=[30]
    legacy_budget=[6]
    active_mail=[False]

    def log(message, legacy=False):
        remaining=legacy_budget if legacy else budget
        if remaining[0]>0:
            remaining[0]-=1
            d.log('RESULT_FLOW '+message)

    def ready_entry(h):
        log(f'validated results-ready event received state={snapshot(d)}')

    def collect_entry(h):
        log(f'collecting getItemMail queued state={snapshot(d)}')

    def mail_entry(h):
        log(f'mail callback entered request={h.rcx:x} status={h.rdx & 0xffffffff} state={snapshot(d)}',legacy=True)

    def mails_entry(h):
        kind=h.rdx & 0xffffffff
        active_mail[0]=kind in (17,18)
        if active_mail[0]:
            log(f'getItemMail native variant={kind} callback entered state={snapshot(d)}')

    def mails_complete(h):
        if active_mail[0]:
            log(f'getItemMail collecting variant marked complete state={snapshot(d)}')

    def mails_exit(h):
        if active_mail[0]:
            log(f'getItemMail native callback exited state={snapshot(d)}')
            active_mail[0]=False

    def mail_ok(h):
        log('mail JSON result accepted as OK',legacy=True)

    def mail_exit(h):
        request=d.q(h.rbp+0x560)
        status=d.d32(request+0x40) if request else None
        log(f'mail callback completed request={request:x} status={status} state={snapshot(d)}',legacy=True)

    def controller_error(h):
        if h.rdx & 0xffffffff != 9008:
            return
        fields={hex(off):d.d32(h.rcx+off) for off in (0x284,0x288,0x28c,0x290,0x2a0)}
        log(f'controller raised 9008 fields={fields} state={snapshot(d)}')
        for offset,call,op in d.call_chain(h.rsp,0x1000)[:12]:
            log(f'controller caller stack+{offset:x} at {call:x} -> {op}')

    def central_error(h):
        if h.r8 & 0xffffffff != 9008:
            return
        log(f'central 9008 category={h.rdx & 0xffffffff} state={snapshot(d)}')
        for offset,call,op in d.call_chain(h.rsp,0x1000)[:12]:
            log(f'error caller stack+{offset:x} at {call:x} -> {op}')

    handlers=locals()

    def arm(debugger):
        for name,(address,expected) in HOOKS.items():
            if debugger.read(address,len(expected))!=expected:
                raise RuntimeError('Unexpected results-flow code: '+name)
        for name,(address,_) in HOOKS.items():
            debugger.bp(address,handlers[name])
        debugger.log('RESULT_FLOW observational completion/error tracing armed')

    d.on_start(arm)
