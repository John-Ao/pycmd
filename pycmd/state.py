"""Session state: ordinary environment and CMD execution states are independent."""
from collections.abc import MutableMapping
from dataclasses import dataclass, field
from pathlib import Path

class Environment(MutableMapping):
    def __init__(self, values=None):
        self._data={}
        self.update(values or {})
    def __getitem__(self,key):return self._data[key.upper()][1]
    def __setitem__(self,key,value):self._data[key.upper()]=(key,str(value))
    def __delitem__(self,key):del self._data[key.upper()]
    def __iter__(self):return (k for k,v in self._data.values())
    def __len__(self):return len(self._data)
    def __contains__(self,key):return key.upper() in self._data
    def get(self,key,default=None):
        item=self._data.get(key.upper())
        return item[1] if item is not None else default
    def copy(self):
        result=Environment()
        # Entries are immutable (original spelling, string value) tuples.
        result._data=self._data.copy()
        return result

@dataclass
class State:
    env: Environment = field(default_factory=Environment)
    cwd: Path = field(default_factory=Path.cwd)
    extensions: bool = True
    delayed: bool = False
    errorlevel: int = 0
    command_result: int = 0
    process_code: int = 0
    external_code: int = 0
    echo: bool = True
    encoding: str = 'cp437'
    unicode_output: bool = False
    locals: list = field(default_factory=list)
    directories: list = field(default_factory=list)
    for_values: dict = field(default_factory=dict)
    args: list = field(default_factory=list)
    raw_args: str = ''
    unsupported: list = field(default_factory=list)

    def dynamic(self,name):
        # Ordinary variables shadow dynamic values, except special = names.
        if name in self.env:return self.env[name]
        if name.upper()=='=EXITCODE':return '%08X'%(self.external_code&0xffffffff)
        if name.upper()=='=EXITCODEASCII':return chr(self.external_code) if 32<=self.external_code<=126 else ''
        if self.extensions:
            if name.upper()=='ERRORLEVEL':return str(self.errorlevel)
            if name.upper()=='CD':return str(self.cwd)
            if name.upper()=='CMDEXTVERSION':return '2'
            if name.upper()=='CMDCMDLINE':return getattr(self,'command_line','cmd.exe')
            if name.upper()=='RANDOM':
                import random
                return str(random.randint(0,32767))
            if name.upper() in ('DATE','TIME'):
                from datetime import datetime
                now=getattr(self,'clock',None) or datetime.now()
                # CMD pads a single-digit hour with a space, not a zero.
                # Leading 08/09 would be invalid octal in SET /A consumers.
                return now.strftime('%a %m/%d/%Y') if name.upper()=='DATE' else f'{now.hour:2d}'+now.strftime(':%M:%S.%f')[:-4]
            if name.upper()=='HIGHESTNUMANODENUMBER':return '0'
        return ''
    def begin_local(self):self.locals.append((self.env.copy(),self.cwd,self.extensions,self.delayed))
    def end_local(self):
        if self.locals:self.env,self.cwd,self.extensions,self.delayed=self.locals.pop()

def signed32(value):return (int(value)+2**31)%2**32-2**31
