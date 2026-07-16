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
        ZXing::ImageView image(pixels, width, height, ZXing::ImageFormat::Lum, stride);
        const auto make_options = [formats](bool robust) {
            ZXing::ReaderOptions options;
            options.setTryHarder(robust)
                .setTryRotate(true)
                .setTryInvert(robust)
                .setTryDownscale(robust)
                .setReturnErrors(false)
                // TIDL supplies one localized symbol per crop. Keep a little
                // headroom for overlapping labels without asking ZXing to
                // search for 32 symbols in every ROI.
                .setMaxNumberOfSymbols(4)
                .setTextMode(ZXing::TextMode::HRI)
                .setEanAddOnSymbol(ZXing::EanAddOnSymbol::Read);
            if (formats && *formats)
                options.setFormats(ZXing::BarcodeFormatsFromString(formats));
            return options;
        };

        // Clear, upright detector crops take the inexpensive path. Preserve
        // the previous maximum-compatibility behavior as an exact fallback
        // for inverted, low-contrast, small, or otherwise difficult codes.
        auto results = ZXing::ReadBarcodes(image, make_options(false));
        const auto valid_count = std::count_if(
            results.begin(), results.end(), [](const auto& result) { return result.isValid(); });
        // A TIDL-localized crop normally contains exactly one symbol. Empty
        // and multi-symbol diagnostic inputs take the compatibility path so
        // the optimization never narrows the wrapper's original behavior.
        if (valid_count != 1) {
            results = ZXing::ReadBarcodes(image, make_options(true));
        }
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
