#pragma once

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/*
 * Decode one grayscale crop and serialize all valid symbols as a JSON array.
 * formats may be null/empty for every ZXing format or a comma-separated list.
 * Returns the result count, -1 for invalid arguments, -2 for a bad format list,
 * or -3 when output_capacity cannot hold the complete JSON document.
 */
int omnicode_decode_luma(const uint8_t* pixels, int width, int height, int stride,
                         const char* formats, char* output, size_t output_capacity);

const char* omnicode_decoder_version(void);

#ifdef __cplusplus
}
#endif
