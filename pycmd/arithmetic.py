"""SET /A's signed 32-bit expression evaluator; no Python eval or recursive env evaluation."""
import re
from dataclasses import dataclass
from .state import signed32

ERRORS={0:('Unbalanced parenthesis.',1073750988),1:('Missing operand.',1073750989),
        2:('Missing operator.',1073750990),3:('Invalid number.  Numeric constants are either decimal (17),\r\nhexadecimal (0x11), or octal (021).',1073750991),
        4:('Invalid number.  Numbers are limited to 32-bits of precision.',1073750992),
        5:('Divide by zero error.',1073750993)}
class ArithmeticError(Exception):
    def __init__(self,kind):self.message,self.code=ERRORS[kind];super().__init__(self.message)
@dataclass
class Operand:
    value:int
    name:str|None=None

def number(token,environment=False):
    sign=1
    if environment:
        token=token.lstrip()
        if token.startswith(('-','+')):
            if token[0]=='-':sign=-1
            token=token[1:]
    base=16 if token.lower().startswith('0x') else 8 if token.startswith('0') else 10
    pattern=r'0[xX]([0-9a-fA-F]+)' if base==16 else r'([0-9]+)'
    m=re.match(pattern,token)
    if not m:
        if environment:return 0
        raise ArithmeticError(3)
    digits=m[1]
    try:n=int(digits,base)
    except ValueError:
        if environment:return 0
        raise ArithmeticError(3)
    if not environment:
        if m.end()!=len(token):raise ArithmeticError(3)
        if n>(0x7fffffff if base==10 else 0xffffffff):raise ArithmeticError(4)
    return signed32(sign*n)

OPS=['==','<<=','>>=','+=','-=','*=','/=','%=','&=','^=','|=','<<','>>']
PRECEDENCE={',':1,'=':2,'+=':2,'-=':2,'*=':2,'/=':2,'%=':2,'&=':2,'^=':2,'|=':2,'<<=':2,'>>=':2,
            '|':3,'^':4,'&':5,'<<':6,'>>':6,'+':7,'-':7,'*':8,'/':8,'%':8}
def tokens(text):
    i=0
    while i<len(text):
        ch=text[i]
        if ch.isspace():i+=1;continue
        op=next((x for x in OPS if text.startswith(x,i)),None)
        if op:yield op;i+=len(op);continue
        if ch in '(),=+-*/%&^|!~?:':yield ch;i+=1;continue
        # A decimal point ends a numeric literal. Completed assignments commit
        # before the trailing token raises Missing operator (e.g. N=1.5/0.5).
        if ch.isdigit():
            m=re.match(r'[0-9][^\s.(),=+\-*/%&^|!~<>?:]*',text[i:])
            yield m[0];i+=len(m[0]);continue
        m=re.match(r'[^\s(),=+\-*/%&^|!~<>?:]+',text[i:])
        if not m:raise ArithmeticError(2)
        yield m[0];i+=len(m[0])

def calculate(text,env):
    parser=Evaluator(list(tokens(text.replace('"',''))),env)
    result=parser.expr(1).value
    if parser.pos!=len(parser.items):raise ArithmeticError(2)
    return result
class Evaluator:
    def __init__(self,items,env):self.items=items;self.pos=0;self.env=env
    def peek(self):return self.items[self.pos] if self.pos<len(self.items) else ''
    def take(self):
        token=self.peek();self.pos+=1;return token
    def atom(self):
        token=self.take()
        if token in ('+','-','!','~'):
            value=self.atom().value
            return Operand(signed32({'+':lambda:value,'-':lambda:-value,'!':lambda:int(not value),'~':lambda:~value}[token]()))
        if token=='(':
            result=self.expr(1)
            if self.take()!=')':raise ArithmeticError(0)
            return result
        if not token or token in PRECEDENCE or token==')':raise ArithmeticError(1)
        if token[0].isdigit():return Operand(number(token))
        return Operand(number(self.env.get(token,''),True),token)
    def expr(self,minimum):
        left=self.atom()
        while self.peek() in PRECEDENCE and PRECEDENCE[self.peek()]>=minimum:
            op=self.take();level=PRECEDENCE[op];assignment=level==2
            if assignment and left.name is None:raise ArithmeticError(2)
            right=self.expr(level if assignment else level+1)
            if op==',':left=right;continue
            operation=op[:-1] if assignment and op!='=' else op
            a,b=left.value,right.value
            if operation=='=':value=b
            elif operation=='+':value=a+b
            elif operation=='-':value=a-b
            elif operation=='*':value=a*b
            elif operation in ('/','%'):
                if not b:raise ArithmeticError(5)
                if a==-2147483648 and b==-1:raise ArithmeticError(4)
                q=(abs(a)//abs(b))*(-1 if (a<0)!=(b<0) else 1)
                value=q if operation=='/' else a-q*b
            elif operation=='&':value=a&b
            elif operation=='|':value=a|b
            elif operation=='^':value=a^b
            elif operation=='<<':value=a<<b if 0<=b<32 else 0
            elif operation=='>>':value=a>>b if 0<=b<32 else (-1 if a<0 else 0)
            else:raise ArithmeticError(2)
            value=signed32(value)
            if assignment:self.env[left.name]=str(value)
            left=Operand(value)
        return left
