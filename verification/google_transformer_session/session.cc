// Copyright 2026. SPDX-License-Identifier: Apache-2.0
#include "kernels.h"
#include "session_layout.h"
#include "session_state.h"
#include <cstring>
#include "ffn_core.h"
#include "attention_ops.h"
extern "C" {
volatile unsigned lv_session_round[3],lv_session_cycles[48],lv_session_lengths[48];
}
namespace {
constexpr unsigned kMagic=0x53535631u;
bool Valid(const session::State* s) {
  if(!s||s->magic!=kMagic||s->path>2||s->h<2||s->h>16||s->h%2||
     s->f<1||s->f>32||s->capacity<2||s->capacity>8||s->capacity*s->h>64||
     s->base>1000000||s->length>s->capacity)return false;
  if(session::Layout(s->capacity-1,s->h,s->f,1,s->base).total>1024)return false;
  for(int i=0;i<4;++i)if(s->before[i]!=kGuard||s->after[i]!=kGuard)return false;
  for(unsigned i=s->capacity*s->h;i<64;++i) {
    unsigned k,v;std::memcpy(&k,s->key+i,4);std::memcpy(&v,s->value+i,4);
    if(k!=kGuard||v!=kGuard)return false;
  }
  return true;
}
unsigned Tick() {
#ifdef TX_HOST
  return 0;
#else
  unsigned c;asm volatile("fence rw,rw\ncsrr %0,mcycle":"=r"(c)::"memory");return c;
#endif
}
int Process(session::State* s,int m,const float* x,const float* w,float* y) {
  const int row=s->length,h=s->h,cap=s->capacity,n=cap*h,path=s->path;
  const attention::Layout l(cap-1,h,s->base);
  float old_key[64],old_value[64];
  std::memcpy(old_key,s->key,row*h*4);std::memcpy(old_value,s->value,row*h*4);
  // x contains only this call's rows: historical token inputs are not read.
  Project(path,m,h,row,x,w,l,y);
  Copy(path,y+l.offset[KR]+row*h,m*h,s->key+row*h);
  Copy(path,y+l.offset[V]+row*h,m*h,s->value+row*h);Count(path,4);
  if(row==0){Copy(path,s->key,n,y+l.offset[PreK]);Copy(path,s->value,n,y+l.offset[PreV]);}
  Invoke(path,Stage(ATTENTION,1,m,cap,h,row),y+l.offset[QR]+row*h,
         s->key,s->value,y+l.offset[Context]+row*h);Count(path,3);
  Finish(path,m,h,row,x,w,l,y);
  layer_ffn_phase(path,cap,m,h,s->f,row,y+l.offset[Output],w+h+4*h*h+n,y+l.total+4);
  s->length+=m;
  Copy(path,s->key,n,y+l.offset[FinalK]);Copy(path,s->value,n,y+l.offset[FinalV]);
  const bool prefix=std::memcmp(old_key,s->key,row*h*4)==0&&std::memcmp(old_value,s->value,row*h*4)==0;
  const bool tail=std::memcmp(s->key+row*h,y+l.offset[KR]+row*h,m*h*4)==0&&
                  std::memcmp(s->value+row*h,y+l.offset[V]+row*h,m*h*4)==0;
  return prefix&&tail&&Valid(s)?1:0;
}
int Stream(int path,int p,int h,int f,int t,int base,const float* x,const float* w,float* y) {
  session::State state;
  if(!session_init(&state,path,h,f,p+t,base))return 0;
  const unsigned sample=lv_session_round[path]++;
  unsigned begin=Tick();
  if(!session_prefill(&state,p,x,w,y))return 0;
  if(sample<4){lv_session_cycles[path*16+sample*4]=Tick()-begin;lv_session_lengths[path*16+sample*4]=state.length;}
  for(int step=0;step<t;++step) {
    const int row=p+step;begin=Tick();
    if(!session_decode(&state,base+row,x+row*h,w,y))return 0;
    if(sample<4){lv_session_cycles[path*16+sample*4+step+1]=Tick()-begin;lv_session_lengths[path*16+sample*4+step+1]=state.length;}
  }
  return state.length==state.capacity&&Valid(&state)?1:0;
}
bool Rejected(session::State& state,int operation,int argument,
              const float* x,const float* w,float* y) {
  session::State before;float output_before[1024];
  std::memcpy(&before,&state,sizeof(state));
  std::memcpy(output_before,y,sizeof(output_before));
  const int result=operation?session_decode(&state,argument,x,w,y):session_prefill(&state,argument,x,w,y);
  return result==0&&std::memcmp(&before,&state,sizeof(state))==0&&
         std::memcmp(output_before,y,sizeof(output_before))==0;
}
}
extern "C" {
__attribute__((noinline)) int session_init(session::State* s,int path,int h,int f,int cap,int base) {
  if(!s||path<0||path>2||h<2||h>16||h%2||f<1||f>32||cap<2||cap>8||
     cap*h>64||base<0||base>1000000||session::Layout(cap-1,h,f,1,base).total>1024)return 0;
  std::memset(s,0,sizeof(*s));
  s->magic=kMagic;s->path=path;s->h=h;s->f=f;s->capacity=cap;s->base=base;
  for(int i=0;i<4;++i)s->before[i]=s->after[i]=kGuard;
  for(int i=0;i<64;++i) {
    std::memcpy(s->key+i,&kGuard,4);std::memcpy(s->value+i,&kGuard,4);
    if(i<cap*h){s->key[i]=attention::kKeyPoison;s->value[i]=attention::kValuePoison;}
  }
  return Valid(s)?1:0;
}
__attribute__((noinline)) int session_prefill(session::State* s,int m,const float* x,const float* w,float* y) {
  if(!Valid(s)||!x||!w||!y||s->length!=0||m<1||unsigned(m)>=s->capacity)return 0;
  return Process(s,m,x,w,y);
}
__attribute__((noinline)) int session_decode(session::State* s,int pos,const float* x,const float* w,float* y) {
  if(!Valid(s)||!x||!w||!y||s->length==0||s->length>=s->capacity||pos<0||unsigned(pos)!=s->base+s->length)return 0;
  return Process(s,1,x,w,y);
}
__attribute__((noinline)) int session_scalar(int p,int h,int f,int t,int b,const float* x,const float* w,float* y){return Stream(0,p,h,f,t,b,x,w,y);}
__attribute__((noinline)) int session_project(int p,int h,int f,int t,int b,const float* x,const float* w,float* y){return Stream(1,p,h,f,t,b,x,w,y);}
__attribute__((noinline)) int session_candidate(int p,int h,int f,int t,int b,const float* x,const float* w,float* y){return Stream(2,p,h,f,t,b,x,w,y);}
__attribute__((noinline)) int session_bulk(int p,int h,int f,int t,int base,const float* x,const float* w,float* y) {
  const int s=p+t;const attention::Layout a(s-1,h,base);
  if(attention_bulk(s-1,h,base,x,w,y)!=1)return 0;
  for(int i=p*h;i<s*h;++i){y[a.offset[PreK]+i]=attention::kKeyPoison;y[a.offset[PreV]+i]=attention::kValuePoison;}
  layer_ffn_phase(2,s,s,h,f,0,y+a.offset[Output],w+h+4*h*h+s*h,y+a.total+4);
  return 1;
}
// Untimed lifecycle/isolation control. Two caller-owned states, distinct inputs.
__attribute__((noinline)) unsigned session_contract(int p,int h,int f,int t,int base,const float* x,const float* w,float* ya,float* yb) {
  session::State a,b;float other[64];const int cap=p+t;
  for(int i=0;i<cap*h;++i)other[i]=-x[i];
  if(!session_init(&a,2,h,f,cap,base)||!session_init(&b,2,h,f,cap,base))return 0;
  unsigned mask=0;
  if(Rejected(a,1,base,x,w,ya))mask|=1;else return mask;
  if(!session_prefill(&a,p,x,w,ya))return mask;
  if(Rejected(a,0,p,x,w,ya))mask|=2;else return mask;
  if(Rejected(a,1,base+p+1,x+p*h,w,ya))mask|=4;else return mask;
  session::State broken;std::memcpy(&broken,&a,sizeof(a));broken.before[0]^=1;
  if(Rejected(broken,1,base+p,x+p*h,w,ya))mask|=8;else return mask;
  if(!session_prefill(&b,p,other,w,yb))return mask;
  for(int step=0;step<t;++step) {
    const int r=p+step;
    if(!session_decode(&a,base+r,x+r*h,w,ya)||!session_decode(&b,base+r,other+r*h,w,yb))return mask;
  }
  if(Rejected(a,1,base+cap,x,w,ya))mask|=16;else return mask;
  if(!session_init(&a,2,h,f,cap,base)||a.length!=0)return mask;
  for(int i=0;i<cap*h;++i)if(a.key[i]!=attention::kKeyPoison||a.value[i]!=attention::kValuePoison)return mask;
  if(!session_prefill(&a,p,x,w,ya))return mask;
  for(int step=0;step<t;++step)if(!session_decode(&a,base+p+step,x+(p+step)*h,w,ya))return mask;
  if(a.length==unsigned(cap)&&b.length==unsigned(cap)&&Valid(&a)&&Valid(&b))mask|=32;
  return mask;
}
}
