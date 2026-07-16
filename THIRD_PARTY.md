# Third-party software and media

The repository code is BSD-3-Clause. The following inputs retain their own
licenses:

- The 31-breed model is derived from
  [`Jaiking001/Dog_Breed_prediction`](https://huggingface.co/Jaiking001/Dog_Breed_prediction),
  revision `b51edc39bd75596cde50e7e888f5d20779aadf9c`, licensed MIT.
- The Gatekeeper's bundled photograph, derived MP4, and proof image use
  [Dachshund (Short).jpg](https://commons.wikimedia.org/wiki/File:%EB%8B%A5%EC%8A%A4%ED%9B%88%ED%8A%B8(%EB%8B%A8%EB%AA%A8%EC%A2%85)_(Dachshund_(Short)).jpg)
  by Katemil94 under CC BY-SA 4.0. That license applies to those media assets,
  not the surrounding source code.
- The recorded dog-breed proof embeds the same CC BY-SA 4.0 photograph and is
  distributed under that license.
- OmniCode's barcode localization model is derived from TI's official
  [`edgeai-gst-apps-barcode-reader`](https://github.com/TexasInstruments-Sandbox/edgeai-gst-apps-barcode-reader)
  source model. It retains TI's Text File License and is for use only with TI
  devices. The package installs the complete license text beside the model.
- OmniCode links to
  [`zxing-cpp` 2.2.1](https://github.com/zxing-cpp/zxing-cpp/tree/v2.2.1),
  licensed Apache-2.0. ZXing receives only crops localized by the accelerated
  detector; it is not used as a full-frame CPU detector.
- OmniCode's QR Code, Data Matrix, Code 128, and EAN-13 fixtures and derived
  sample video were generated specifically for this repository and are
  covered by the repository's BSD-3-Clause license.
- TI runtime, firmware, model-zoo, and Armbian kernel Debian packages carry the
  copyright and license files installed within each package.
