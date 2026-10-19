"""Concurrent pipe stages with isolated CMD sessions and OS byte pipes."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import os
from .syntax import Unsupported,unescape,crt_split,SyntaxFailure
from .io import extract,HandleCopyError

def block_text(node):
    """Reconstruct block commands for the pipe child's second parse."""
    if node.kind in ('command','quiet'):
        command,redirs=extract(node.text)
        if redirs:
            suffix=' '.join(str(r.target)+('>&' if r.mode=='copy' else r.mode)+r.source for r in redirs)
            return command+' '+suffix
    return node.text

def pipe_text(parent,part):
    from .pipe_conditions import rebuild
    # Rewrite the parsed parent condition before the child's fresh expansion.
    # An IF introduced only in that child therefore bypasses this bug.
    rebuilt,condition_error=rebuild(part.source or part.text)
    if rebuilt!=(part.source or part.text):
        from .syntax import parse
        if condition_error:return rebuilt,condition_error
        part=parse(rebuilt)
    if part.kind=='block':
        text=('('+block_text(part.children[0]).rstrip('\n')+' )'+part.text).replace('\n',' & ')
    else:
        text=unescape(parent.expand_execution(part.text))
        # Redirections at the end acquire a separating blank when CMD
        # reconstructs the child command (even without spaces at |).
        if part.kind=='command' and text and not text[-1].isspace():
            command,redirs=extract(text)
            if redirs and text.endswith(redirs[-1].source):
                suffix=' '.join(str(r.target)+('>&' if r.mode=='copy' else r.mode)+r.source for r in redirs)
                text=command+' '+suffix
    return text,None

def run(parent,node):
    links=[]
    for _ in range(len(node.children)-1):
        read,write=os.pipe()
        links.append((os.fdopen(read,'rb',buffering=0),os.fdopen(write,'wb',buffering=0)))
    children=[]
    def launch(index,part,pool):
        source=parent.streams.table[0] if index==0 else links[index-1][0]
        sink=parent.streams.table[1] if index==len(node.children)-1 else links[index][1]
        child=parent.fork(stdin=source,stdout=sink,stderr=parent.streams.table[2]);child.state.delayed=False
        children.append(child)
        text,condition_error=pipe_text(parent,part);prepared=ExitStack();failure=False
        if condition_error:
            child.write(condition_error+'\r\n',2)
            failure=True
        # BAT/CMD launches open their outer redirections before the next stage
        # is launched. The BAT body itself must still run concurrently.
        try:
            clean,redirs=extract(text)
            argv=crt_split(clean)
            from .runtime import BUILTINS
            builtin=argv and argv[0].lower() in BUILTINS|{'choice','xcopy','timeout','if','for'}
            target=child.lookup(argv[0]) if argv and redirs and not failure and not builtin and '%' not in text else None
            if target is not None and target.suffix.lower() in ('.bat','.cmd'):
                prepared.enter_context(child.streams.redirected(redirs,child))
                text=clean
        except HandleCopyError as exc:
            child.write('The handle could not be duplicated\r\nduring redirection of handle '+str(exc.target)+'.\r\n',2);failure=True
        except OSError:
            child.write(child.redirection_error(redirs)+'\r\n',2);failure=True
        except SyntaxFailure:
            pass  # Let the ordinary command entry report the original syntax.
        return pool.submit(stage,index,child,text,prepared,failure,source,sink)
    def stage(index,child,text,prepared,failure,source,sink):
        try:
            return child.result(1,1) if failure else child.command(text)
        except BrokenPipeError:return 1
        finally:
            prepared.close()
            child.streams.close_owned()
            if index:source.close()
            if index<len(node.children)-1:sink.close()
    try:
        with ThreadPoolExecutor(max_workers=len(node.children),thread_name_prefix='pycmd-pipe') as pool:
            jobs=[launch(i,p,pool) for i,p in enumerate(node.children)]
            codes=[job.result() for job in jobs]
    finally:
        for read,write in links:read.close();write.close()
        for child in children:parent.state.unsupported.extend(child.state.unsupported)
    return parent.result(codes[-1],codes[-1])
