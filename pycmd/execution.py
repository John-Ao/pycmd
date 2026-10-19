"""Drive suspended interpreter operations without recursive Python calls."""

def drive(operation,on_interrupt):
    stack=[operation];value=None;error=None
    try:
        while stack:
            try:
                child=stack[-1].throw(error) if error is not None else stack[-1].send(value)
            except StopIteration as done:
                stack.pop();value=done.value;error=None
            except BaseException as exc:
                stack.pop();value=None;error=exc
            else:
                stack.append(child);value=None;error=None
        if error is not None:raise error
        return value
    except KeyboardInterrupt as exc:
        # Also cover an interrupt arriving between generator steps.
        on_interrupt(exc)
        raise
    finally:
        # Unwind redirections, SETLOCAL and diagnostic frames if the driver
        # itself is interrupted outside a generator's exception handler.
        while stack:stack.pop().close()
