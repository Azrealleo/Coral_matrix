"""Independent six-stage FP64 reference with FP32 storage boundaries."""
import hashlib
import math
import random
import struct

CASES=(('ffn_decode','GEGLU',(1,8,16,0,0)),
       ('ffn_tail','GEGLU',(3,7,13,0,0)),
       ('ffn_prefill','GEGLU',(4,8,32,0,0)))
PROBE_CASE=('ffn_zero_safety','GEGLU',(1,1,1,0,0))
GUARD=struct.unpack('<f',struct.pack('<I',0x55aa7711))[0]
def f32(x):return struct.unpack('<f',struct.pack('<f',x))[0]
def packed(v):return struct.pack('<'+'f'*len(v),*v)

def layout(shape):
    m,h,f,*_=shape
    if any(type(v) is not int or v<=0 for v in (m,h,f)):raise ValueError('Invalid FFN shape')
    out=[];at=0
    for name,n in zip(('norm','gate','up','activation','down','output'),(m*h,m*f,m*f,m*f,m*h,m*h)):
        out.append((name,at,n));at+=n+4
    return out

def golden(shape,x,w):
    m,h,f,*_=shape
    layout(shape)
    if len(x)!=m*h or len(w)!=h+3*h*f:raise ValueError('Wrong FFN input geometry')
    gamma=w[:h];wg=w[h:h+h*f];wu=w[h+h*f:h+2*h*f];wd=w[h+2*h*f:]
    norm=[]
    for r in range(m):
        row=x[r*h:(r+1)*h];scale=1/math.sqrt(math.fsum(v*v for v in row)/h+1e-5)
        norm.extend(f32(v*scale*(1+gamma[c])) for c,v in enumerate(row))
    def matmul(a,b,k,n):
        return [f32(math.fsum(a[r*k+i]*b[i*n+c] for i in range(k))) for r in range(m) for c in range(n)]
    gate=matmul(norm,wg,h,f);up=matmul(norm,wu,h,f)
    activation=[f32(.5*g*(1+math.tanh(math.sqrt(2/math.pi)*(g+.044715*g**3)))*u) for g,u in zip(gate,up)]
    down=matmul(activation,wd,f,h);output=[f32(a+b) for a,b in zip(down,x)]
    values=(norm,gate,up,activation,down,output);y=[]
    for i,v in enumerate(values):
        y.extend(v)
        if i<5:y.extend([GUARD]*4)
    return y

def fixture(index):
    if type(index) is not int or not 0<=index<=len(CASES):raise ValueError('Wrong case index')
    name,kind,shape=PROBE_CASE if index==len(CASES) else CASES[index]
    m,h,f,*_=shape;rng=random.Random(20261026+index)
    x=[f32(rng.uniform(-1,1)) for _ in range(m*h)]
    w=[f32(rng.uniform(-.2,.2)) for _ in range(h)]
    for k,n in ((h,f),(h,f),(f,h)):
        w.extend(f32(rng.uniform(-.5,.5)/math.sqrt(k)) for _ in range(k*n))
    if index==len(CASES):x=[0.];w=[0.,1.,1.,1.]
    y=golden(shape,x,w)
    if max(len(x),len(w),len(y))>1024:raise ValueError('FFN static capacity exceeded')
    return dict(id=index,name=name,kind=kind,shape=shape,x=x,w=w,v=[],y=y,algorithm=y[:],
                vector_sha256=hashlib.sha256(packed(x)+packed(w)).hexdigest(),
                algorithm_sha256=hashlib.sha256(packed(y)).hexdigest())
