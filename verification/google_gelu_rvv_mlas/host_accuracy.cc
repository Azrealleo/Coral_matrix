// Independent double tanh-form GELU reference. Host mirror, NEVER RTL.
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <vector>
extern "C" void candidate_gelu_f32(const float*,const float*,float*,size_t);
int main() {
  unsigned long checked=0;double maximum=0,scaled=0;
  for(const float up : {-2.f,-1.f,0.f,1.f,2.f}) {
    std::vector<float> x,w;
    for(int i=-8192;i<=8192;++i){x.push_back(i/1024.f);w.push_back(up);}
    std::vector<float> y(x.size());candidate_gelu_f32(x.data(),w.data(),y.data(),x.size());
    for(size_t i=0;i<x.size();++i) {
      const double v=x[i],z=std::sqrt(2.0/3.14159265358979323846)*(v+0.044715*v*v*v);
      const float gold=float(0.5*v*(1.0+std::tanh(z))*double(up));
      const double error=std::fabs(double(y[i])-gold),limit=2e-5+2e-4*std::fabs(gold);
      if(!std::isfinite(y[i])||error>limit){std::printf("FAIL x=%g up=%g actual=%.9g gold=%.9g error=%g\n",v,double(up),double(y[i]),double(gold),error);return 1;}
      maximum=std::max(maximum,error);scaled=std::max(scaled,error/limit);++checked;
    }
  }
  // Canary and tail wiring on the scalar host mirror only. RTL tail coverage
  // still requires the independent real RVV safety/performance tests.
  for(size_t n : {0,1,15,16,17,31,32,33,37,63,64,65,256}) {
    std::vector<float> x(n,1.f),w(n,2.f),y(n+2,-777.f);
    candidate_gelu_f32(x.data(),w.data(),y.data()+1,n);
    if(y.front()!=-777.f||y.back()!=-777.f)return 2;
    for(size_t i=1;i<=n;++i)if(!std::isfinite(y[i])||y[i]==-777.f)return 3;
  }
  std::printf("[GELU_MLAS_HOST_NUMERICS_PASS] checked=%lu max_abs_error=%.9g max_tolerance_multiple=%.9g hardware=NOT_RUN\n",checked,maximum,scaled);
}
