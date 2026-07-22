# Armbian Noble GNOME image for BeagleY-AI

The release GNOME image is a normal Armbian image, not a separately maintained
root filesystem. It is built from the `main` history of
[`Grippy98/build`](https://github.com/Grippy98/build) with the BeagleY-AI
J722S 4 GB EdgeAI memory map, IMX219 CSI0 composition, and required kernel
interfaces carried as ordinary kernel/DT patches. It does not run an image
customization script, install the EdgeAI release during image creation, add a
second compositor, or disable UHS.

The validated source is branch
[`agent/beagley-edgeai-gnome-noble`](https://github.com/Grippy98/build/tree/agent/beagley-edgeai-gnome-noble),
commit `90e6a1c23636a40ed48915cf5b53d774ecbe0819`, based directly on fork `main`
commit `3fb3329393a15ff496eb92e90d198bc45b6bbeba`.

## Reproduce the base image

On an arm64 Linux workstation, or with Armbian's Docker build support:

```bash
git clone https://github.com/Grippy98/build.git armbian-build
cd armbian-build
git switch agent/beagley-edgeai-gnome-noble

DOCKER_ARMBIAN_HOST_ARCH=arm64 ./compile.sh build \
  BOARD=beagley-ai BRANCH=vendor RELEASE=noble \
  BUILD_MINIMAL=no BUILD_DESKTOP=yes \
  DESKTOP_ENVIRONMENT=gnome DESKTOP_TIER=mid \
  EXPERT=no KERNEL_CONFIGURE=no \
  COMPRESS_OUTPUTIMAGE=img,sha SHARE_LOG=yes
```

`DOCKER_ARMBIAN_HOST_ARCH=arm64` selects Armbian's arm64 build container when
the host is Apple Silicon. It does not alter the produced root filesystem.
The EdgeAI/PowerVR packages remain the same independently versioned release
archive used by stock and existing Armbian installations.

## Graphics path

J722S uses the `tidss` display driver and an Imagination PowerVR BXS-4-64 GPU.
TI documents Wayland and GBM EGL platforms, OpenGL ES 3.2, Vulkan 1.3, and
DMA-BUF modifiers for this GPU stack. GNOME 46 runs its normal Mutter Wayland
compositor on top of DRM/KMS and EGL; GDM remains the standard display manager.

The package installer provides the exact TI Noble graphics set used for this
release:

- PowerVR Mesa shim `24.0.1+git20250304+82e6a9293c-2`;
- Rogue firmware, tools, and userspace
  `25.3.6908880+git20260217+2ecc98c61aed-2`;
- Rogue DKMS driver
  `25.3.6908880+git20260225+d241b0d5df40-1`;
- headers for `6.12.49-vendor-k3-beagle`.

After installing and rebooting, `eglinfo -B` and `vulkaninfo --summary` must
identify PowerVR BXS. An `llvmpipe` or `lavapipe` result is a failed graphics
validation, even if the desktop happens to render.

TI reference documentation:

- [J722S Rogue graphics overview](https://software-dl.ti.com/jacinto7/esd/processor-sdk-linux-j722s/latest/exports/docs/linux/Foundational_Components/Graphics/Rogue/Overview.html)
- [J722S Rogue build guide](https://software-dl.ti.com/jacinto7/esd/processor-sdk-linux-j722s/latest/exports/docs/linux/Foundational_Components/Graphics/Rogue/Build_Guide.html)

## Other Armbian desktop choices

Current Noble/arm64 Armbian profiles include GNOME, KDE Plasma, Cinnamon,
MATE, XFCE, and i3. Budgie, Deepin, and Enlightenment are community profiles.
GNOME is the release target because its native Wayland path best matches TI's
documented EGL/Wayland stack and requires no additional session policy.

KDE Plasma can also run a native Wayland session, but it is not validated by
this release. Cinnamon, MATE, XFCE, and i3 are predominantly X11 profiles;
TI's Mesa shim supplies GLX, but those sessions add an Xorg path that needs its
own end-to-end validation before claiming GPU acceleration. The lighter memory
footprint of XFCE or i3 may be attractive on the 4 GB board, while GNOME gives
the clearest supported graphics path.

## Performance considerations

For the release image, use GNOME's default Wayland session and confirm it is
actually on PowerVR. Keep display resolution and browser tab count reasonable:
the 4 GB EdgeAI DTB reserves memory for remote processors and accelerator
heaps, leaving less memory to Linux than a stock desktop DTB. Swap or zram can
improve responsiveness under bursty memory pressure but does not replace
physical accelerator memory.

For kiosk or dedicated inference products, a single fullscreen native Wayland
client can use fewer resources than a general desktop. That is an application
deployment choice, not a second compositor embedded in this image. The image
itself deliberately stays on standard GNOME/GDM so it remains close to the
Armbian profile users already receive.
