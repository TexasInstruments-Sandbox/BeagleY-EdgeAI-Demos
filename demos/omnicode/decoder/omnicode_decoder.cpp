#include "omnicode_decoder.h"

#include <ZXing/BarcodeFormat.h>
#include <ZXing/Content.h>
#include <ZXing/ImageView.h>
#include <ZXing/ReadBarcode.h>
#include <ZXing/ReaderOptions.h>
#include <ZXing/Result.h>
#include <ZXing/ZXVersion.h>

#include <algorithm>
#include <cstring>
#include <exception>
#include <iomanip>
#include <sstream>
#include <string>

namespace {

std::string json_escape(const std::string& value)
{
    std::ostringstream out;
    for (unsigned char byte : value) {
        switch (byte) {
        case '"': out << "\\\""; break;
        case '\\': out << "\\\\"; break;
        case '\b': out << "\\b"; break;
        case '\f': out << "\\f"; break;
        case '\n': out << "\\n"; break;
        case '\r': out << "\\r"; break;
        case '\t': out << "\\t"; break;
        default:
            if (byte < 0x20) {
                out << "\\u" << std::hex << std::setw(4) << std::setfill('0')
                    << static_cast<unsigned int>(byte) << std::dec;
            } else {
                out << static_cast<char>(byte);
            }
        }
    }
    return out.str();
}

} // namespace

extern "C" int omnicode_decode_luma(const uint8_t* pixels, int width, int height,
                                      int stride, const char* formats, char* output,
                                      size_t output_capacity)
{
    if (!pixels || !output || width <= 0 || height <= 0 || stride < width || output_capacity < 3)
        return -1;

    try {
        ZXing::ReaderOptions options;
        options.setTryHarder(true)
            .setTryRotate(true)
            .setTryInvert(true)
            .setTryDownscale(true)
            .setReturnErrors(false)
            .setMaxNumberOfSymbols(32)
            .setTextMode(ZXing::TextMode::HRI)
            .setEanAddOnSymbol(ZXing::EanAddOnSymbol::Read);
        if (formats && *formats)
            options.setFormats(ZXing::BarcodeFormatsFromString(formats));

        ZXing::ImageView image(pixels, width, height, ZXing::ImageFormat::Lum, stride);
        const auto results = ZXing::ReadBarcodes(image, options);
        std::ostringstream json;
        json << '[';
        int count = 0;
        for (const auto& result : results) {
            if (!result.isValid())
                continue;
            if (count++)
                json << ',';
            const auto& position = result.position();
            json << "{\"format\":\"" << json_escape(ZXing::ToString(result.format()))
                 << "\",\"text\":\"" << json_escape(result.text())
                 << "\",\"content_type\":\"" << json_escape(ZXing::ToString(result.contentType()))
                 << "\",\"symbology_identifier\":\"" << json_escape(result.symbologyIdentifier())
                 << "\",\"orientation\":" << result.orientation()
                 << ",\"position\":[";
            for (int index = 0; index < 4; ++index) {
                if (index)
                    json << ',';
                json << "[" << position[index].x << ',' << position[index].y << "]";
            }
            json << "]}";
        }
        json << ']';
        const std::string serialized = json.str();
        if (serialized.size() + 1 > output_capacity)
            return -3;
        std::memcpy(output, serialized.c_str(), serialized.size() + 1);
        return count;
    } catch (const std::invalid_argument&) {
        return -2;
    } catch (const std::exception&) {
        return -1;
    }
}

extern "C" const char* omnicode_decoder_version(void)
{
    return ZXing::ZXING_VERSION_STR;
}
