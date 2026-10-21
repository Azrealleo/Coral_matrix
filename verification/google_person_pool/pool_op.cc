// Copyright 2026. SPDX-License-Identifier: Apache-2.0
#include "pool_op.h"
#include "pool_core.h"
#include "tensorflow/lite/micro/kernels/pooling.h"
#include "tensorflow/lite/micro/micro_context.h"
#include <cstddef>
#include <cstring>
#ifndef PD_POOL_VALIDATE
#error "Explicitly choose the pooling validation/speed mode"
#endif
#ifndef PD_POOL_EMULATE
#include "pool_rvv.h"
#endif
extern "C" {
uint32_t pd_pool_calls,pd_pool_fallbacks,pd_pool_vector_blocks,pd_pool_emulated_blocks;
uint32_t pd_pool_validated,pd_pool_mismatches;
}
namespace person_pool { namespace {
struct State { tflite::OpDataPooling original; int scratch; };
static_assert(offsetof(State,original)==0,"Default pooling state must stay first");
void* Init(TfLiteContext* context,const char*,size_t) {
  auto* state=static_cast<State*>(context->AllocatePersistentBuffer(context,sizeof(State)));
  if(state){std::memset(state,0,sizeof(*state));state->scratch=-1;}return state;
}
TfLiteStatus Prepare(TfLiteContext* context,TfLiteNode* node) {
  TF_LITE_ENSURE(context,node->user_data!=nullptr);
  TF_LITE_ENSURE_STATUS(tflite::PoolingPrepare(context,node));
#if PD_POOL_VALIDATE
  auto* mc=tflite::GetMicroContext(context);
  auto* output=mc->AllocateTempOutputTensor(node,0);
  TF_LITE_ENSURE(context,output!=nullptr);
  const size_t bytes=output->bytes;mc->DeallocateTempTfLiteTensor(output);
  TF_LITE_ENSURE_STATUS(context->RequestScratchBufferInArena(context,bytes,
      &static_cast<State*>(node->user_data)->scratch));
#endif
  return kTfLiteOk;
}
TfLiteStatus Fallback(TfLiteContext* context,TfLiteNode* node) {
  ++pd_pool_fallbacks;return tflite::Register_AVERAGE_POOL_2D().invoke(context,node);
}
TfLiteStatus Eval(TfLiteContext* context,TfLiteNode* node) {
  const auto* input=tflite::micro::GetEvalInput(context,node,0);
  auto* output=tflite::micro::GetEvalOutput(context,node,0);
  TF_LITE_ENSURE(context,input && output && node->user_data && node->builtin_data);
  const auto& p=*static_cast<const TfLitePoolParams*>(node->builtin_data);
  const auto& data=static_cast<State*>(node->user_data)->original;
  if(input->type!=kTfLiteInt8 || output->type!=kTfLiteInt8 || input->dims->size!=4 || output->dims->size!=4 ||
     input->dims->data[0]!=output->dims->data[0] || input->dims->data[3]!=output->dims->data[3])
    return Fallback(context,node);
  const Geometry g={input->dims->data[0],input->dims->data[1],input->dims->data[2],input->dims->data[3],
      output->dims->data[1],output->dims->data[2],p.filter_height,p.filter_width,p.stride_height,p.stride_width,
      data.padding.height,data.padding.width,data.activation_min,data.activation_max};
  if(!Valid(g))return Fallback(context,node);
  const int8_t* x=tflite::micro::GetTensorData<int8_t>(input);
  int8_t* y=tflite::micro::GetTensorData<int8_t>(output);
#ifdef PD_POOL_EMULATE
  ScalarWindow backend;
#else
  RvvWindow backend;
#endif
  TF_LITE_ENSURE(context,AveragePool(g,x,y,backend));
  ++pd_pool_calls;
#ifdef PD_POOL_EMULATE
  pd_pool_emulated_blocks+=backend.blocks;
#else
  pd_pool_vector_blocks+=backend.blocks;
#endif
#if PD_POOL_VALIDATE
  const int bytes=g.batches*g.out_height*g.out_width*g.channels;
  auto* saved=static_cast<int8_t*>(context->GetScratchBuffer(context,static_cast<State*>(node->user_data)->scratch));
  TF_LITE_ENSURE(context,saved!=nullptr);std::memcpy(saved,y,bytes);
  TF_LITE_ENSURE_STATUS(tflite::Register_AVERAGE_POOL_2D().invoke(context,node));
  for(int i=0;i<bytes;++i)if(saved[i]!=y[i]){++pd_pool_mismatches;return kTfLiteError;}
  ++pd_pool_validated;
#endif
  return kTfLiteOk;
}
}  // namespace
TFLMRegistration RegisterAveragePool(){return tflite::micro::RegisterOp(Init,Prepare,Eval);}
}  // namespace person_pool
