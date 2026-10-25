"""Independent FP64 stage reference, with explicit FP32 tensor boundaries."""
import hashlib
import math
import random
import struct

CASES=(('chain_decode32','GEGLU',(1,32,0,0,0)),
       ('chain_tail37','GEGLU',(1,37,0,0,0)),
       ('chain_prefill4x64','GEGLU',(4,64,0,0,0)))
PROBE_CASE=('chain_zero_safety','GEGLU',(1,1,0,0,0))
GUARD=struct.unpack('<f',struct.pack('<I',0x55aa7711))[0]

def f32(value):return struct.unpack('<f',struct.pack('<f',value))[0]
def packed(values):return struct.pack('<'+'f'*len(values),*values)

def golden(rows,cols,x,w):
    n=rows*cols
    if not (rows>0 and cols>0 and len(x)==n and len(w)==cols+2*n):
        raise ValueError('Wrong chain input geometry')
    norm=[]
    for r in range(rows):
        row=x[r*cols:(r+1)*cols]
        scale=1/math.sqrt(math.fsum(v*v for v in row)/cols+1e-5)
        norm.extend(f32(v*scale*(1+w[c])) for c,v in enumerate(row))
    activation=[f32(.5*v*(1+math.tanh(math.sqrt(2/math.pi)*(v+.044715*v**3)))*up)
                for v,up in zip(norm,w[cols:cols+n])]
    output=[f32(v+skip) for v,skip in zip(activation,w[cols+n:])]
    return norm+[GUARD]*4+activation+[GUARD]*4+output

def fixture(index):
    if type(index) is not int or not 0<=index<=len(CASES):raise ValueError('Wrong case index')
    name,kind,shape=PROBE_CASE if index==len(CASES) else CASES[index]
    rows,cols,*_=shape;n=rows*cols
    rng=random.Random(20261025+index)
    x=[f32(rng.uniform(-2,2)) for _ in range(n)]
    gamma=[f32(rng.uniform(-.25,.25)) for _ in range(cols)]
    up=[f32(rng.uniform(-2,2)) for _ in range(n)]
    residual=[f32(rng.uniform(-1,1)) for _ in range(n)]
    if index==len(CASES):x=[0.];gamma=[0.];up=[2.];residual=[0.]
    w=gamma+up+residual;y=golden(rows,cols,x,w)
    if max(len(x),len(w),len(y))>1024:raise ValueError('Chain exceeds static capacity')
    return dict(id=index,name=name,kind=kind,shape=shape,x=x,w=w,v=[],y=y,algorithm=y[:],
                vector_sha256=hashlib.sha256(packed(x)+packed(w)).hexdigest(),
                algorithm_sha256=hashlib.sha256(packed(y)).hexdigest())
