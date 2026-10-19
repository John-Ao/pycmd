"""Opt-in BAT source diagnostics, independent of CMD execution state."""
from contextlib import contextmanager

class Diagnostics:
    def __init__(self, runtime, enabled=False):
        self.runtime=runtime;self.enabled=enabled
        self.parents=[];self.nodes=[];self.counter=[0];self.local_counter=0;self.reporting=False;self.pending=None

    def stack(self):
        # Resolve source positions only when a diagnostic or child context needs
        # them. Active nodes hold references, not eagerly copied frame locations.
        locations={};parent=None;location=None
        rt=self.runtime
        for item in self.nodes:
            node,frame=item['node'],item['frame']
            source=node.source or node.text
            unit=frame.get('trace_unit','') if frame else rt.trace_command
            if parent and parent['frame'] is frame and any(c is node for c in parent['node'].children):
                offset=parent['offset']+node.source_offset
            elif parent and parent['frame'] is frame and source in parent['source']:
                offset=parent['offset']+parent['source'].find(source)
            else:offset=max(0,unit.find(source))
            line_offset=unit.count('\n',0,offset)
            if frame:
                location=self.frame_location(frame)
                raw_lines=frame.get('trace_lines',[])
                mapping=frame.get('trace_expanded_lines')
                if mapping is None and 'trace_raw' in frame:
                    mapping=self.map_unit(frame['trace_raw'],unit)
                    frame['trace_expanded_lines']=mapping
                raw_index=mapping[min(line_offset,len(mapping)-1)] if mapping else line_offset
                physical=frame.get('trace_offsets',[])
                if physical:
                    end=physical[min(raw_index,len(physical)-1)]-frame.get('trace_start',0)
                    location['line']+=b''.join(frame.get('trace_chunks',())).count(b'\n',0,end)
                location['source']=raw_lines[min(raw_index,len(raw_lines)-1)] if raw_lines else source.split('\n')[0]
                locations[id(frame)]=location
            else:location={'file':'<command>','name':'command','line':1+line_offset,'source':source.split('\n')[0]}
            parent=dict(node=node,frame=frame,source=source,offset=offset)
        frames=self.parents+[locations[id(f)] if id(f) in locations else self.frame_location(f) for f in rt.batch_frames if 'trace' in f]
        if not rt.batch_frames and location:frames.append(location)
        if not frames:
            frames.append({'file':'<command>','line':1,'name':'command','source':rt.trace_command.split('\n')[0]})
        return frames

    @staticmethod
    def frame_location(frame):
        location=dict(frame['trace'])
        if 'trace_prefix' in frame:location['line']=frame['trace_prefix'].count(b'\n')+1
        return location

    def emit(self, message, *, force=False, kind="CmdError"):
        if not self.enabled or self.reporting:return
        if not force and self.nodes and self.nodes[-1]['serial']!=self.local_counter:return
        self.counter[0]+=1;self.local_counter+=1
        lines=['Traceback (most recent call last):']
        frames=self.pending or self.stack();self.pending=None
        for frame in frames:
            lines.append(f'  File "{frame["file"]}", line {frame["line"]}, in {frame["name"]}')
            if frame.get('source'):lines.append('    '+frame['source'].strip())
        lines.append(kind+(': ' if message else '')+message.strip().replace('\r\n','\n').replace('\n',' | '))
        self.reporting=True
        try:self.runtime.write('\r\n'.join(lines)+'\r\n',2)
        finally:self.reporting=False

    def interrupted(self,exc):
        # Capture before CALL/BAT finally blocks remove the active frames.
        if not self.enabled or getattr(exc,'_pycmd_traced',False):return
        self.pending=None
        self.emit('',force=True,kind='KeyboardInterrupt')
        exc._pycmd_traced=True

    def prepare_unit(self,frame,raw,expanded):
        frame['trace_raw']=raw
        frame['trace_expanded_lines']=None

    @staticmethod
    def map_unit(raw,expanded):
        if '\n' not in raw:return [0]*(expanded.count('\n')+1)
        if raw==expanded:return list(range(raw.count('\n')+1))
        from difflib import SequenceMatcher
        opcodes=SequenceMatcher(None,raw,expanded,autojunk=False).get_opcodes()
        mapping=[];position=0
        for line in expanded.split('\n'):
            origin=0
            for tag,a,b,c,d in opcodes:
                if c<=position<d or position==len(expanded) and d==position:
                    origin=a+position-c if tag=='equal' else a
                    break
            mapping.append(raw[:origin].count('\n'))
            position+=len(line)+1
        return mapping

    @contextmanager
    def executing(self,node):
        if not self.enabled:
            yield;return
        rt=self.runtime
        frame=rt.batch_frames[-1] if rt.batch_frames else None
        item={'node':node,'frame':frame,'serial':self.local_counter}
        self.nodes.append(item)
        try:yield
        except KeyboardInterrupt as exc:
            self.interrupted(exc)
            raise
        except Exception as exc:
            # GOTO and EXIT are control flow, not failures.
            from .runtime import ExitFlow,GotoFlow
            from .syntax import SyntaxFailure,Unsupported
            if isinstance(exc,(SyntaxFailure,Unsupported,OSError)):
                if self.pending is None:self.pending=self.stack()
            elif not isinstance(exc,(ExitFlow,GotoFlow)) and not getattr(exc,'_pycmd_traced',False):
                self.emit(type(exc).__name__+': '+str(exc));exc._pycmd_traced=True
            raise
        finally:
            self.nodes.pop()
