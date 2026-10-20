// Copyright 2026. SPDX-License-Identifier: Apache-2.0
#include "conv_vme.h"
#include "pointwise_core.h"
#include "tensorflow/lite/micro/kernels/conv.h"
#include "tensorflow/lite/micro/kernels/kernel_util.h"
#include "tensorflow/lite/kernels/internal/common.h"
#include "tensorflow/lite/micro/micro_context.h"
#include <cstring>
#include <cstddef>
#ifndef PD_VME_VALIDATE
#error "Choose PD_VME_VALIDATE explicitly: validation and speed firmware differ"
#endif
#ifndef PD_VME_EMULATE
#include "vme_tile.h"
#endif
#ifdef USE_TFLM_COMPRESSION
#error "Compressed tensors require a separate audited adapter"
#endif

extern "C" {
uint32_t pd_vme_conv_calls, pd_vme_fallback_calls, pd_vme_commands;
uint32_t pd_vme_emulated_tiles, pd_vme_validated_layers, pd_vme_mismatches;
uint32_t pd_vme_first_bad_index = UINT32_MAX;
}
namespace person_vme {
namespace {
// Single-interpreter/single-NPU experiment, explicitly non-reentrant.
Workspace workspace;
struct State {
  tflite::OpDataConv reference;  // Must be first: standard ConvPrepare uses it.
  int validation_scratch;
};
static_assert(offsetof(State, reference) == 0, "Reference state must remain first");
void* Init(TfLiteContext* context, const char*, size_t) {
  auto* state = static_cast<State*>(context->AllocatePersistentBuffer(context, sizeof(State)));
  if (state) { std::memset(state, 0, sizeof(*state)); state->validation_scratch = -1; }
  return state;
}
TfLiteStatus Prepare(TfLiteContext* context, TfLiteNode* node) {
  TF_LITE_ENSURE(context, node->user_data != nullptr);
  TF_LITE_ENSURE_STATUS(tflite::ConvPrepare(context, node));
#if PD_VME_VALIDATE
  // Arena scratch is reused between nodes, not another full static feature map.
  auto* mc = tflite::GetMicroContext(context);
  auto* output = mc->AllocateTempOutputTensor(node, 0);
  TF_LITE_ENSURE(context, output != nullptr);
  const size_t bytes = output->bytes;
  mc->DeallocateTempTfLiteTensor(output);
  auto* state = static_cast<State*>(node->user_data);
  TF_LITE_ENSURE_STATUS(context->RequestScratchBufferInArena(context, bytes, &state->validation_scratch));
#endif
  return kTfLiteOk;
}
TfLiteStatus Fallback(TfLiteContext* context, TfLiteNode* node) {
  ++pd_vme_fallback_calls;
  return tflite::Register_CONV_2D().invoke(context, node);
}
TfLiteStatus Eval(TfLiteContext* context, TfLiteNode* node) {
  const auto* input = tflite::micro::GetEvalInput(context, node, 0);
  const auto* filter = tflite::micro::GetEvalInput(context, node, 1);
  const auto* bias = node->inputs->size == 3 ? tflite::micro::GetEvalInput(context, node, 2) : nullptr;
  auto* output = tflite::micro::GetEvalOutput(context, node, 0);
  TF_LITE_ENSURE(context, input && filter && output && node->builtin_data && node->user_data);
  const auto& p = *static_cast<const TfLiteConvParams*>(node->builtin_data);
  const auto& data = static_cast<State*>(node->user_data)->reference;
  if (input->type != kTfLiteInt8 || filter->type != kTfLiteInt8 || output->type != kTfLiteInt8 ||
      (bias && bias->type != kTfLiteInt32) || input->dims->size != 4 ||
      filter->dims->size != 4 || output->dims->size != 4 ||
      input->dims->data[0] != 1 || output->dims->data[0] != 1 ||
      filter->dims->data[1] != 1 || filter->dims->data[2] != 1 ||
      p.stride_height != 1 || p.stride_width != 1 || p.dilation_height_factor != 1 ||
      p.dilation_width_factor != 1 || data.padding.height || data.padding.width ||
      data.filter_zero_point != 0 || input->dims->data[1] != output->dims->data[1] ||
      input->dims->data[2] != output->dims->data[2]) return Fallback(context, node);
  const int depth = input->dims->data[3], channels = output->dims->data[3];
  if (depth < 1 || depth > kMaxK || channels < 1 || filter->dims->data[3] != depth ||
      filter->dims->data[0] != channels) return Fallback(context, node);
  const int positions = output->dims->data[1] * output->dims->data[2];
  const int8_t* x = tflite::micro::GetTensorData<int8_t>(input);
  const int8_t* w = tflite::micro::GetTensorData<int8_t>(filter);
  const int32_t* b = tflite::micro::GetOptionalTensorData<int32_t>(bias);
  int8_t* y = tflite::micro::GetTensorData<int8_t>(output);
  if (!InitialBias(w, b, channels, depth, data.input_zero_point)) return Fallback(context, node);
  auto quantize = [&data](int32_t value, int channel) -> int8_t {
    value = tflite::MultiplyByQuantizedMultiplier(value,
        data.per_channel_output_multiplier[channel], data.per_channel_output_shift[channel]);
    // Match the exact pinned TFLM integer helper, not the team's shift-only rule.
    value += data.output_zero_point;
    if (value < data.output_activation_min) value = data.output_activation_min;
    if (value > data.output_activation_max) value = data.output_activation_max;
    return static_cast<int8_t>(value);
  };
#ifdef PD_VME_EMULATE
  struct CountedEmulator : EmulatedTile {
    void Run(const int8_t* a, const uint8_t* bb, const int32_t* bias_data,
             int m, int n, int k, int32_t* out) {
      ++pd_vme_emulated_tiles;
      EmulatedTile::Run(a, bb, bias_data, m, n, k, out);
    }
  } backend;
#else
  HardwareTile backend(&pd_vme_commands);
#endif
  TF_LITE_ENSURE(context, Pointwise(x, w, b, y, positions, depth, channels,
                                  data.input_zero_point, workspace, backend, quantize));
  ++pd_vme_conv_calls;
#if PD_VME_VALIDATE
  auto* state = static_cast<State*>(node->user_data);
  auto* saved = static_cast<int8_t*>(context->GetScratchBuffer(context, state->validation_scratch));
  TF_LITE_ENSURE(context, saved != nullptr);
  const int bytes = positions * channels;
  std::memcpy(saved, y, bytes);
  TF_LITE_ENSURE_STATUS(tflite::Register_CONV_2D().invoke(context, node));
  for (int i = 0; i < bytes; ++i) {
    if (saved[i] != y[i]) {
      ++pd_vme_mismatches;
      if (pd_vme_first_bad_index == UINT32_MAX) pd_vme_first_bad_index = i;
      return kTfLiteError;
    }
  }
  ++pd_vme_validated_layers;
#endif
  return kTfLiteOk;
}
}  // namespace
TFLMRegistration RegisterPointwise() {
  return tflite::micro::RegisterOp(Init, Prepare, Eval);
}
}  // namespace person_vme
