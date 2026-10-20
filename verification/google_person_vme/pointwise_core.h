// Copyright 2026. SPDX-License-Identifier: Apache-2.0
// Portable packing/scheduling shared by the host emulator and real VME path.
#pragma once
#include <cstdint>
#include <climits>

namespace person_vme {
constexpr int kTile = 16;
constexpr int kMaxK = 256;
struct Workspace {
  alignas(16) int8_t weights[kMaxK * kTile];
  alignas(16) uint8_t inputs[kMaxK * kTile];
  alignas(16) int32_t accum[kTile * kTile];
  alignas(16) int32_t initial[kTile];
};

// VME's integer opcode uses signed A, UNSIGNED B. For signed input x and
// TFLM zero point z, use u=x+128 and bias' = bias-(128+z)*sum(weights).
// Thus sum(w*(x-z))+bias == sum(w*u)+bias'. Never reinterpret signed B
// as uint8 without this correction (in particular for x<0 and z=-128).
inline bool InitialBias(const int8_t* weights, const int32_t* bias,
                        int outputs, int depth, int zero_point) {
  if (!weights || outputs < 1 || depth < 1 || depth > kMaxK ||
      zero_point < -128 || zero_point > 127) return false;
  for (int o = 0; o < outputs; ++o) {
    int64_t sum = 0, bound = 0;
    for (int k = 0; k < depth; ++k) {
      const int w = weights[o * depth + k];
      sum += w;
      bound += (w < 0 ? -w : w) * 255;
    }
    const int64_t base = (bias ? bias[o] : 0) - (128 + zero_point) * sum;
    // Conservative guard: avoid signed-overflow in both the real accumulator
    // and the host emulator even for a non-model input/bias combination.
    if (base - bound < INT32_MIN || base + bound > INT32_MAX) return false;
  }
  return true;
}

// Input/output NHWC flattened spatial positions; filter OHWI with H=W=1.
// Backend must implement Run(packed_A, packed_unsigned_B, bias, M,N,K,out).
// Quantize implements the PINNED TFLM per-channel integer requantization.
// No implicit fallback: caller must explicitly choose/reference-count it.
template <typename Backend, typename Quantize>
bool Pointwise(const int8_t* input, const int8_t* weights, const int32_t* bias,
               int8_t* output, int positions, int depth, int outputs,
               int zero_point, Workspace& work, Backend& backend, Quantize quantize) {
  if (!input || !weights || !output || positions < 1 || outputs < 1 ||
      !InitialBias(weights, bias, outputs, depth, zero_point)) return false;
  const int padded_k = (depth + 3) & ~3;
  for (int first_o = 0; first_o < outputs; first_o += kTile) {
    const int m = outputs - first_o < kTile ? outputs - first_o : kTile;
    for (int r = 0; r < kTile; ++r) {
      int sum = 0;
      for (int k = 0; k < padded_k; ++k) {
        const int8_t w = (r < m && k < depth) ? weights[(first_o + r) * depth + k] : 0;
        work.weights[k * kTile + r] = w;
        sum += w;
      }
      work.initial[r] = r < m ?
          static_cast<int32_t>(static_cast<int64_t>(bias ? bias[first_o + r] : 0) -
                               static_cast<int64_t>(128 + zero_point) * sum) : 0;
    }
    // Reuse the Kx16 packed weight block over all spatial tiles.
    for (int first_p = 0; first_p < positions; first_p += kTile) {
      const int n = positions - first_p < kTile ? positions - first_p : kTile;
      for (int k = 0; k < padded_k; ++k)
        for (int lane = 0; lane < kTile; ++lane)
          work.inputs[k * kTile + lane] = (k < depth && lane < n) ?
              static_cast<uint8_t>(static_cast<int>(input[(first_p + lane) * depth + k]) + 128) : 0;
      backend.Run(work.weights, work.inputs, work.initial, m, n, padded_k, work.accum);
      for (int r = 0; r < m; ++r)
        for (int lane = 0; lane < n; ++lane)
          output[(first_p + lane) * outputs + first_o + r] =
              quantize(work.accum[r * kTile + lane], first_o + r);
    }
  }
  return true;
}

// Host arithmetic emulation ONLY. This is not VME execution or a speed test.
struct EmulatedTile {
  void Run(const int8_t* a, const uint8_t* b, const int32_t* bias,
           int m, int n, int k, int32_t* out) {
    for (int r = 0; r < kTile; ++r)
      for (int c = 0; c < kTile; ++c) {
        int32_t sum = (r < m && c < n) ? bias[r] : 0;
        if (r < m && c < n)
          for (int d = 0; d < k; ++d) sum += a[d * kTile + r] * b[d * kTile + c];
        out[r * kTile + c] = sum;
      }
  }
};
}  // namespace person_vme
